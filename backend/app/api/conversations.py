"""
Conversations API — the chat-inbox backend. A conversation = a Gmail thread
(`gmail_thread_id`); messages are the inbound/outbound EmailMessage rows in it.

  GET  /conversations                      list (newest activity first)
  GET  /conversations/unread-count         total unread (nav badge)
  GET  /conversations/{thread}/messages    full thread, chronological
  POST /conversations/{thread}/read        mark inbound read
  POST /conversations/{thread}/reply       send a reply in-thread (multipart)
  GET  /conversations/attachments/{id}     download an attachment
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.serializers import UtcDateTime
from ..db.database import get_db
from ..db.models import EmailAttachment, EmailMessage, Property
from ..services.email_service import deliver, require_gmail

router = APIRouter(prefix="/conversations", tags=["Conversations"])

_EFF = func.coalesce(EmailMessage.sent_at, EmailMessage.created_at)


# ── Schemas ────────────────────────────────────────────────────

class AttachmentOut(BaseModel):
    id: int
    filename: str
    mime_type: Optional[str] = None
    size: Optional[int] = None


class ConversationOut(BaseModel):
    thread_id: str
    property_id: Optional[int] = None
    property_url: Optional[str] = None
    agency_name: Optional[str] = None
    address: Optional[str] = None
    last_message_preview: str
    last_message_at: Optional[UtcDateTime] = None
    last_direction: str
    unread_count: int
    total_messages: int


class ConversationList(BaseModel):
    items: List[ConversationOut]
    total: int


class MessageOut(BaseModel):
    id: int
    property_id: Optional[int] = None
    direction: str
    from_email: Optional[str] = None
    to_email: str
    subject: str
    body: Optional[str] = None
    body_html: Optional[str] = None
    is_read: bool
    attachments: List[AttachmentOut] = []
    sent_at: Optional[UtcDateTime] = None
    created_at: Optional[UtcDateTime] = None


# ── Helpers ────────────────────────────────────────────────────

def _text_to_html(text: str) -> str:
    """Wrap a plain-text reply in a clean, email-client-safe HTML body so the
    recipient sees formatted text (not a broken/blank message). Escapes the
    text, converts newlines to <br>, links bare URLs."""
    import html as _html
    import re as _re

    safe = _html.escape(text or "")
    safe = _re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" style="color:#1a56db;">\1</a>',
        safe,
    )
    safe = safe.replace("\n", "<br>")
    return (
        '<div style="font-family:Helvetica,Arial,sans-serif;font-size:14px;'
        'line-height:1.6;color:#0a0a0a;">' + safe + "</div>"
    )


def _preview(msg: EmailMessage) -> str:
    txt = (msg.body or "").strip()
    if not txt and msg.body_html:
        import re
        txt = re.sub(r"<[^>]+>", " ", msg.body_html)
    txt = " ".join(txt.split())
    return txt[:140]


# ── Endpoints ──────────────────────────────────────────────────

@router.get("", response_model=ConversationList)
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    unread_expr = func.sum(
        case((and_(EmailMessage.direction == "inbound", EmailMessage.is_read.is_(False)), 1), else_=0)
    )
    base = (
        select(
            EmailMessage.gmail_thread_id.label("tid"),
            func.max(_EFF).label("last_at"),
            func.count().label("total"),
            unread_expr.label("unread"),
        )
        .where(EmailMessage.gmail_thread_id.is_not(None))
        .group_by(EmailMessage.gmail_thread_id)
    )

    if q:
        like = f"%{q}%"
        match_threads = (
            select(EmailMessage.gmail_thread_id)
            .outerjoin(Property, Property.id == EmailMessage.property_id)
            .where(
                EmailMessage.gmail_thread_id.is_not(None),
                or_(
                    EmailMessage.subject.ilike(like),
                    EmailMessage.from_email.ilike(like),
                    EmailMessage.to_email.ilike(like),
                    Property.agency_name.ilike(like),
                    Property.address.ilike(like),
                ),
            )
        )
        base = base.where(EmailMessage.gmail_thread_id.in_(match_threads))

    agg_rows = (await db.execute(base.order_by(func.max(_EFF).desc()).offset(offset).limit(limit))).all()
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    if not agg_rows:
        return ConversationList(items=[], total=int(total))

    tids = [r.tid for r in agg_rows]
    agg = {r.tid: r for r in agg_rows}

    # Latest message per thread (Postgres DISTINCT ON).
    latest_rows = (await db.execute(
        select(EmailMessage)
        .where(EmailMessage.gmail_thread_id.in_(tids))
        .order_by(EmailMessage.gmail_thread_id, _EFF.desc())
        .distinct(EmailMessage.gmail_thread_id)
    )).scalars().all()
    latest = {m.gmail_thread_id: m for m in latest_rows}

    prop_ids = {m.property_id for m in latest_rows if m.property_id}
    props = {}
    if prop_ids:
        pr = (await db.execute(select(Property).where(Property.id.in_(prop_ids)))).scalars().all()
        props = {p.id: p for p in pr}

    items = []
    for tid in tids:  # preserve order from agg (newest first)
        m = latest.get(tid)
        if m is None:
            continue
        p = props.get(m.property_id) if m.property_id else None
        items.append(ConversationOut(
            thread_id=tid,
            property_id=m.property_id,
            property_url=m.property_url,
            agency_name=p.agency_name if p else None,
            address=p.address if p else None,
            last_message_preview=_preview(m),
            last_message_at=agg[tid].last_at,
            last_direction=m.direction or "outbound",
            unread_count=int(agg[tid].unread or 0),
            total_messages=int(agg[tid].total or 0),
        ))
    return ConversationList(items=items, total=int(total))


@router.get("/unread-count")
async def unread_count(db: AsyncSession = Depends(get_db)):
    n = (await db.execute(
        select(func.count()).where(
            EmailMessage.direction == "inbound", EmailMessage.is_read.is_(False)
        )
    )).scalar_one()
    return {"unread": int(n)}


@router.get("/{thread_id}/messages")
async def thread_messages(thread_id: str, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(EmailMessage)
        .where(EmailMessage.gmail_thread_id == thread_id)
        .order_by(_EFF.asc())
    )).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Conversation not found")
    ids = [m.id for m in rows]
    atts = (await db.execute(
        select(EmailAttachment).where(EmailAttachment.email_id.in_(ids))
    )).scalars().all()
    by_email: dict = {}
    for a in atts:
        by_email.setdefault(a.email_id, []).append(
            AttachmentOut(id=a.id, filename=a.filename, mime_type=a.mime_type, size=a.size)
        )
    return {"items": [
        MessageOut(
            id=m.id, property_id=m.property_id, direction=m.direction or "outbound",
            from_email=m.from_email, to_email=m.to_email, subject=m.subject, body=m.body,
            body_html=m.body_html, is_read=bool(m.is_read), attachments=by_email.get(m.id, []),
            sent_at=m.sent_at, created_at=m.created_at,
        ) for m in rows
    ]}


@router.post("/{thread_id}/read")
async def mark_read(thread_id: str, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(EmailMessage).where(
            EmailMessage.gmail_thread_id == thread_id,
            EmailMessage.direction == "inbound",
            EmailMessage.is_read.is_(False),
        )
    )).scalars().all()
    for m in rows:
        m.is_read = True
    await db.commit()
    return {"updated": len(rows)}


@router.post("/{thread_id}/reply", response_model=MessageOut)
async def reply(
    thread_id: str,
    body: str = Form(...),
    body_html: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
):
    await require_gmail(db)
    latest = (await db.execute(
        select(EmailMessage)
        .where(EmailMessage.gmail_thread_id == thread_id)
        .order_by(_EFF.desc()).limit(1)
    )).scalars().first()
    if latest is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Reply target: write to whoever the agency address is.
    to = latest.from_email if latest.direction == "inbound" else latest.to_email
    subject = latest.subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    # Always send an HTML part so the reply renders cleanly on the agency side
    # (plain-text-only replies looked broken next to the branded original).
    html_body = body_html or _text_to_html(body)

    obj = EmailMessage(
        property_id=latest.property_id,
        property_url=latest.property_url,
        to_email=to,
        subject=subject,
        body=body,
        body_html=html_body,
        status="queued",
        direction="outbound",
        gmail_thread_id=thread_id,
        in_reply_to=latest.rfc_message_id,
    )
    db.add(obj)
    await db.flush()

    # Save uploaded files.
    max_bytes = settings.MAX_ATTACHMENT_MB * 1024 * 1024
    for f in files or []:
        data = await f.read()
        if not data:
            continue
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail=f"{f.filename} exceeds {settings.MAX_ATTACHMENT_MB}MB")
        folder = os.path.join(settings.ATTACHMENTS_DIR, str(obj.id))
        os.makedirs(folder, exist_ok=True)
        import re as _re
        safe = _re.sub(r"[^A-Za-z0-9._-]+", "_", (f.filename or "file"))[:120] or "file"
        path = os.path.join(folder, safe)
        with open(path, "wb") as out:
            out.write(data)
        db.add(EmailAttachment(
            email_id=obj.id, filename=f.filename or safe, mime_type=f.content_type,
            size=len(data), storage_path=path, direction="outbound",
        ))
    await db.commit()

    await deliver(db, obj)  # sends in-thread; sets status + gmail ids
    await db.refresh(obj)

    atts = (await db.execute(
        select(EmailAttachment).where(EmailAttachment.email_id == obj.id)
    )).scalars().all()
    return MessageOut(
        id=obj.id, property_id=obj.property_id, direction="outbound",
        from_email=obj.from_email, to_email=obj.to_email,
        subject=obj.subject, body=obj.body, body_html=obj.body_html, is_read=True,
        attachments=[AttachmentOut(id=a.id, filename=a.filename, mime_type=a.mime_type, size=a.size) for a in atts],
        sent_at=obj.sent_at, created_at=obj.created_at,
    )


@router.get("/attachments/{attachment_id}")
async def download_attachment(attachment_id: int, db: AsyncSession = Depends(get_db)):
    a = await db.get(EmailAttachment, attachment_id)
    if a is None or not a.storage_path or not os.path.exists(a.storage_path):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(a.storage_path, media_type=a.mime_type or "application/octet-stream",
                        filename=a.filename)
