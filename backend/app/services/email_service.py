"""
Email delivery service — the actual "send this email via Gmail" logic,
kept out of the API router so the router stays thin.

  • deliver(db, email)   — try to send one EmailMessage via Gmail; update its
                           status (sent | failed) + mirror to the Property.
                           Never raises on a send failure (records it instead).
  • require_gmail(db)     — raise an HTTP error if Gmail isn't connected, used
                           by the manual "send now" / "send all" actions.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.models import EmailAttachment, EmailMessage, GmailCredential, Property
from .gmail_sender import GmailSendError, send_via_gmail


async def deliver(db: AsyncSession, obj: EmailMessage) -> EmailMessage:
    """Attempt to send `obj` via Gmail. Mutates status in-place
    (sent | failed), stamps sent_at, mirrors to the linked Property, and
    commits. If no Gmail credentials are stored the message is left as-is
    (queued) so it can be sent later. Never raises on a send failure — records
    it on the row instead so a bulk flush keeps going."""
    sender = settings.GMAIL_SENDER
    if not sender:
        return obj  # not configured → leave queued

    res = await db.execute(
        select(GmailCredential).where(GmailCredential.email_address == sender)
    )
    cred = res.scalar_one_or_none()
    if cred is None:
        return obj  # not connected yet → leave queued

    # Gather any attachment file paths queued on this message (query, not the
    # lazy relationship — lazy loads aren't allowed in async context).
    att_rows = await db.execute(
        select(EmailAttachment.storage_path).where(EmailAttachment.email_id == obj.id)
    )
    att_paths = [p for p in att_rows.scalars().all() if p]

    try:
        # Gmail client is sync — to_thread keeps the event loop free even if
        # Google hangs (per the post-outage hardening rules). Thread-aware:
        # when this is a reply, obj.gmail_thread_id / obj.in_reply_to are set.
        resp = await asyncio.to_thread(
            send_via_gmail,
            row=cred,
            to=obj.to_email,
            subject=obj.subject,
            body_text=obj.body or "",
            body_html=obj.body_html or None,
            cc=obj.cc_emails,
            attachment_path=obj.attachment_path,
            attachments=att_paths,
            thread_id=obj.gmail_thread_id,
            in_reply_to=obj.in_reply_to,
        )
        obj.status = "sent"
        obj.error_message = None
        obj.sent_at = datetime.utcnow()
        obj.direction = "outbound"
        obj.from_email = cred.email_address
        obj.is_read = True
        obj.gmail_message_id = resp.get("id")
        obj.gmail_thread_id = resp.get("threadId") or obj.gmail_thread_id
        obj.rfc_message_id = resp.get("rfc_message_id")
    except GmailSendError as e:
        obj.status = "failed"
        obj.error_message = str(e)[:1000]

    await db.commit()
    await db.refresh(obj)

    # Mirror status back to the parent Property row.
    if obj.property_id:
        prop = await db.get(Property, obj.property_id)
        if prop is not None:
            prop.email_status = obj.status
            await db.commit()

    return obj


async def require_gmail(db: AsyncSession) -> None:
    """Raise a clear error if Gmail isn't connected, so manual send actions
    get an explanatory message rather than a silent no-op."""
    sender = settings.GMAIL_SENDER
    if not sender:
        raise HTTPException(status_code=500, detail="GMAIL_SENDER not configured")
    res = await db.execute(
        select(GmailCredential).where(GmailCredential.email_address == sender)
    )
    if res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No Gmail credentials stored for {sender}. "
                "Click Connect Gmail and complete the OAuth flow first."
            ),
        )
