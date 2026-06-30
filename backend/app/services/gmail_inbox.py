"""
Gmail inbox poller — fetches agency replies and stores them as inbound
EmailMessage rows (+ EmailAttachment), threaded by Gmail threadId.

Polling (not Pub/Sub): we keep a `last_history_id` watermark on the
GmailCredential and ask Gmail for the delta each tick (cheap). First run
seeds from `messages.list(q="in:inbox newer_than:7d")`.

All blocking Gmail calls run via asyncio.to_thread (the client is sync).
Inbound HTML is sanitized server-side before storage (untrusted senders).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.models import EmailAttachment, EmailMessage, GmailCredential, Property
from .gmail_sender import _credentials_from_row, _refresh_if_needed

logger = logging.getLogger(__name__)

# ── HTML sanitization (prefer bleach; fall back to a basic strip) ──
# Tags whose *inner text* must also be dropped — bleach strip=True keeps the
# text content of stripped tags, so a bare <style> dumps raw CSS into the chat
# bubble (the "renders as bold… body { width:100% }" leak). Kill these blocks
# wholesale before bleach runs.
_DROP_BLOCKS = re.compile(r"(?is)<(style|script|head|title)\b[^>]*>.*?</\1\s*>")
_DROP_ORPHAN = re.compile(r"(?is)</?(style|script|head|title)\b[^>]*>")


def _pre_strip(html: str) -> str:
    html = html or ""
    html = _DROP_BLOCKS.sub("", html)
    html = _DROP_ORPHAN.sub("", html)
    return html


try:
    import bleach

    _ALLOWED_TAGS = list(getattr(bleach.sanitizer, "ALLOWED_TAGS", []))
    for _t in ("p", "br", "div", "span", "strong", "b", "em", "i", "u", "ul",
               "ol", "li", "a", "blockquote", "pre", "code", "h1", "h2", "h3",
               "h4", "table", "thead", "tbody", "tr", "td", "th", "img"):
        if _t not in _ALLOWED_TAGS:
            _ALLOWED_TAGS.append(_t)
    _ALLOWED_ATTRS = {"a": ["href", "title"], "img": ["src", "alt"], "*": ["style"]}

    def sanitize_html(html: str) -> str:
        return bleach.clean(_pre_strip(html), tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS,
                            protocols=["http", "https", "mailto", "cid", "data"], strip=True)
except Exception:  # bleach not installed → conservative strip
    def sanitize_html(html: str) -> str:
        html = _pre_strip(html)
        html = re.sub(r'(?i)\son\w+\s*=\s*"[^"]*"', "", html)
        html = re.sub(r"(?i)\son\w+\s*=\s*'[^']*'", "", html)
        html = re.sub(r"(?i)javascript:", "", html)
        return html


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _build_service(row: GmailCredential):
    creds = _credentials_from_row(row)
    refreshed = _refresh_if_needed(creds)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return service, creds, refreshed


def list_new_message_ids(service, start_history_id):
    """Return (message_ids, latest_history_id)."""
    if start_history_id:
        ids, latest = [], start_history_id
        page = None
        try:
            while True:
                resp = service.users().history().list(
                    userId="me", startHistoryId=start_history_id,
                    historyTypes=["messageAdded"], pageToken=page,
                ).execute()
                for h in resp.get("history", []):
                    latest = h.get("id", latest)
                    for m in h.get("messagesAdded", []):
                        mid = m.get("message", {}).get("id")
                        if mid:
                            ids.append(mid)
                page = resp.get("nextPageToken")
                if not page:
                    break
            return list(dict.fromkeys(ids)), latest
        except Exception as e:
            # historyId too old / expired → fall through to a fresh seed
            logger.warning(f"history.list failed ({e}); reseeding from recent inbox")
    # Seed: recent inbox + current mailbox historyId
    resp = service.users().messages().list(userId="me", q="in:inbox newer_than:7d").execute()
    ids = [m["id"] for m in resp.get("messages", [])]
    prof = service.users().getProfile(userId="me").execute()
    return ids, str(prof.get("historyId"))


def _walk_payload(payload):
    """Return (text, html, attachments[]) from a Gmail message payload."""
    text, html, attachments = "", "", []

    def walk(part):
        nonlocal text, html
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        filename = part.get("filename") or ""
        if filename and body.get("attachmentId"):
            attachments.append({
                "filename": filename,
                "mime": mime or "application/octet-stream",
                "size": body.get("size"),
                "attachmentId": body["attachmentId"],
            })
        elif mime == "text/plain" and body.get("data"):
            text += _b64url(body["data"]).decode("utf-8", "replace")
        elif mime == "text/html" and body.get("data"):
            html += _b64url(body["data"]).decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload or {})
    return text, html, attachments


def fetch_message(service, msg_id) -> dict:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    text, html, attachments = _walk_payload(payload)
    try:
        dt = parsedate_to_datetime(headers.get("date")) if headers.get("date") else None
        if dt is not None:
            # Normalize to UTC before going naive, so inbound timestamps sort
            # correctly against our outbound utcnow() values (the email Date
            # header carries the sender's TZ; stripping tzinfo without
            # converting left a multi-hour skew → replies "jumped" up).
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            dt = dt.replace(tzinfo=None)
    except Exception:
        dt = None
    return {
        "gmail_message_id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "label_ids": msg.get("labelIds", []) or [],
        "from_email": parseaddr(headers.get("from", ""))[1] or headers.get("from", ""),
        "subject": headers.get("subject", "(no subject)"),
        "rfc_message_id": headers.get("message-id"),
        "in_reply_to": headers.get("in-reply-to"),
        "body_text": text or None,
        "body_html": sanitize_html(html) if html else None,
        "date": dt,
        "attachments": attachments,
    }


def download_attachment(service, msg_id, attachment_id) -> bytes:
    a = service.users().messages().attachments().get(
        userId="me", messageId=msg_id, id=attachment_id,
    ).execute()
    return _b64url(a.get("data", ""))


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    name = _SAFE_NAME.sub("_", (name or "file").strip()) or "file"
    return name[:120]


async def poll_inbox(db: AsyncSession) -> dict:
    """Fetch new inbound messages → store as inbound EmailMessage (+ attachments).
    Returns {'fetched', 'inserted'}."""
    sender = settings.GMAIL_SENDER
    if not sender:
        return {"fetched": 0, "inserted": 0}
    res = await db.execute(select(GmailCredential).where(GmailCredential.email_address == sender))
    cred = res.scalar_one_or_none()
    if cred is None or not (cred.scopes and "gmail.readonly" in cred.scopes):
        return {"fetched": 0, "inserted": 0}  # not connected with read access yet

    service, creds, refreshed = await asyncio.to_thread(_build_service, cred)
    if refreshed:
        cred.access_token = creds.token
        cred.token_expiry = creds.expiry

    ids, latest_history_id = await asyncio.to_thread(
        list_new_message_ids, service, cred.last_history_id
    )

    inserted = 0
    max_bytes = settings.MAX_ATTACHMENT_MB * 1024 * 1024
    for mid in ids:
        # Already stored?
        exists = await db.execute(
            select(EmailMessage.id).where(EmailMessage.gmail_message_id == mid)
        )
        if exists.scalar_one_or_none() is not None:
            continue
        try:
            m = await asyncio.to_thread(fetch_message, service, mid)
        except Exception as e:
            logger.warning(f"fetch_message {mid} failed: {e}")
            continue
        if "SENT" in m["label_ids"]:
            continue  # our own outbound echoed into the thread

        # Inherit property from the newest existing row in this thread.
        prop_id, prop_url = None, None
        if m["thread_id"]:
            r = await db.execute(
                select(EmailMessage.property_id, EmailMessage.property_url)
                .where(EmailMessage.gmail_thread_id == m["thread_id"])
                .order_by(EmailMessage.created_at.desc())
                .limit(1)
            )
            row = r.first()
            if row:
                prop_id, prop_url = row[0], row[1]
        if prop_id is None and m["from_email"]:
            r = await db.execute(
                select(Property.id, Property.url)
                .where(Property.agency_email == m["from_email"]).limit(1)
            )
            row = r.first()
            if row:
                prop_id, prop_url = row[0], row[1]

        obj = EmailMessage(
            property_id=prop_id,
            property_url=prop_url,
            to_email=sender,
            from_email=m["from_email"],
            subject=m["subject"],
            body=m["body_text"],
            body_html=m["body_html"],
            status="received",
            direction="inbound",
            is_read=False,
            gmail_message_id=m["gmail_message_id"],
            gmail_thread_id=m["thread_id"],
            rfc_message_id=m["rfc_message_id"],
            in_reply_to=m["in_reply_to"],
            sent_at=m["date"],
            created_at=m["date"] or datetime.utcnow(),
        )
        db.add(obj)
        await db.flush()  # get obj.id for attachment paths

        for att in m["attachments"]:
            try:
                data = await asyncio.to_thread(
                    download_attachment, service, mid, att["attachmentId"]
                )
                if len(data) > max_bytes:
                    logger.warning(f"attachment {att['filename']} > cap, skipped")
                    continue
                folder = os.path.join(settings.ATTACHMENTS_DIR, str(obj.id))
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, _safe_filename(att["filename"]))
                with open(path, "wb") as f:
                    f.write(data)
                db.add(EmailAttachment(
                    email_id=obj.id, filename=att["filename"], mime_type=att["mime"],
                    size=len(data), storage_path=path,
                    gmail_attachment_id=att["attachmentId"], direction="inbound",
                ))
            except Exception as e:
                logger.warning(f"attachment download failed ({att['filename']}): {e}")

        inserted += 1

    cred.last_history_id = latest_history_id
    await db.commit()
    return {"fetched": len(ids), "inserted": inserted}


__all__ = ["poll_inbox"]
