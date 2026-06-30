"""
Gmail send service. Reads OAuth credentials from gmail_credentials,
auto-refreshes the access token when expired, and sends a MIME message
via the Gmail API.

Synchronous (gmail API client is sync). Always called via
asyncio.to_thread from the async caller so a hung Google request can
never freeze the event loop.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from email.message import EmailMessage as _MimeMessage
from typing import Optional

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..db.models import GmailCredential

logger = logging.getLogger(__name__)


class GmailSendError(Exception):
    pass


def _credentials_from_row(row: GmailCredential) -> Credentials:
    """Build a google-auth Credentials object from a stored row."""
    return Credentials(
        token=row.access_token,
        refresh_token=row.refresh_token,
        token_uri=row.token_uri or "https://oauth2.googleapis.com/token",
        client_id=row.client_id,
        client_secret=row.client_secret,
        scopes=(row.scopes or "").split(),
    )


def _refresh_if_needed(creds: Credentials) -> bool:
    """Refresh the access token if expired. Returns True if refreshed."""
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        return True
    return False


def _attach_file(msg: "_MimeMessage", path: str) -> None:
    import mimetypes
    import os
    try:
        with open(path, "rb") as f:
            data = f.read()
        mtype, _ = mimetypes.guess_type(path)
        maintype, subtype = (mtype or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            data, maintype=maintype, subtype=subtype,
            filename=os.path.basename(path),
        )
    except Exception as e:
        logger.warning(f"Attachment skipped ({path}): {e}")


def send_via_gmail(
    *,
    row: GmailCredential,
    to: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    cc: Optional[str] = None,
    attachment_path: Optional[str] = None,
    attachments: Optional[list] = None,
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> dict:
    """Send a single message via Gmail API.

    Returns {'id', 'threadId', 'rfc_message_id'} on success; raises
    GmailSendError on any failure.

    Threading: pass `thread_id` to keep a reply in the same Gmail
    conversation, and `in_reply_to` / `references` (RFC822 Message-IDs) so
    mail clients thread it. `attachments` is a list of file paths (the
    legacy single `attachment_path` still works).

    Caller must invoke this in a thread (asyncio.to_thread) — googleapiclient
    is synchronous.
    """
    creds = _credentials_from_row(row)
    refreshed = False
    try:
        refreshed = _refresh_if_needed(creds)
    except Exception as e:
        raise GmailSendError(f"refresh failed: {e}") from e

    # Build MIME message.
    msg = _MimeMessage()
    msg["From"] = row.email_address
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    if body_html:
        msg.set_content(body_text or "")
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text or "")

    for path in ([attachment_path] if attachment_path else []) + list(attachments or []):
        if path:
            _attach_file(msg, path)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    send_body = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    try:
        resp = service.users().messages().send(userId="me", body=send_body).execute()
    except Exception as e:
        raise GmailSendError(f"Gmail API send failed: {e}") from e

    # Read back the RFC822 Message-ID Gmail assigned (needed to thread future
    # replies). Requires gmail.readonly — null gracefully if not granted yet.
    rfc_message_id = None
    try:
        meta = service.users().messages().get(
            userId="me", id=resp["id"], format="metadata",
            metadataHeaders=["Message-ID"],
        ).execute()
        for h in meta.get("payload", {}).get("headers", []):
            if h.get("name", "").lower() == "message-id":
                rfc_message_id = h.get("value")
                break
    except Exception as e:
        logger.debug(f"Message-ID readback unavailable (need readonly?): {e}")

    # Persist refreshed token + new expiry back to caller's row.
    if refreshed:
        row.access_token = creds.token
        row.token_expiry = creds.expiry

    return {"id": resp.get("id"), "threadId": resp.get("threadId"),
            "rfc_message_id": rfc_message_id}


__all__ = ["send_via_gmail", "GmailSendError", "_credentials_from_row", "_refresh_if_needed"]
