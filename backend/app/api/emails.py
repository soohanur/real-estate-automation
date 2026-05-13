"""
Emails API — outbound emails to property agencies.

Dual storage per user spec: every email is recorded in the `email_messages`
DB table AND mirrored to an "Emails" tab in the same Google Sheet the
scraper writes to. The DB is the source of truth; the Sheet is a paper
trail for human review.

Actual Google Workspace sending is stubbed in Phase 4 — the row lands as
status="queued" and a background worker (to come) will flip it to
sent / failed. The frontend already shows status correctly.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..db.models import EmailMessage, Property
from ..services import email_sheet

router = APIRouter(prefix="/emails", tags=["Emails"])


# ── Schemas ────────────────────────────────────────────────────

class EmailCreate(BaseModel):
    to_email: EmailStr
    cc_emails: Optional[str] = None
    subject: str
    body: Optional[str] = None
    attachment_path: Optional[str] = None
    property_id: Optional[int] = None
    property_url: Optional[str] = None


class EmailOut(BaseModel):
    id: int
    property_id: Optional[int] = None
    property_url: Optional[str] = None
    to_email: str
    cc_emails: Optional[str] = None
    subject: str
    body: Optional[str] = None
    attachment_path: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EmailList(BaseModel):
    items: List[EmailOut]
    total: int
    limit: int
    offset: int


class EmailStats(BaseModel):
    total: int
    queued: int
    sent: int
    failed: int
    sent_today: int
    sent_this_week: int


# ── Endpoints ──────────────────────────────────────────────────

@router.post("", response_model=EmailOut, status_code=201)
async def create_email(payload: EmailCreate, db: AsyncSession = Depends(get_db)):
    """
    Queue an email. Writes to DB (source of truth) and best-effort mirrors
    into the 'Emails' tab in Google Sheets. Real send is wired in a later
    phase via the Google Workspace API.
    """
    # Resolve property if given by id or url.
    prop_url = payload.property_url
    prop_id = payload.property_id
    if prop_id and not prop_url:
        prop = await db.get(Property, prop_id)
        if prop is not None:
            prop_url = prop.url
    elif prop_url and not prop_id:
        r = await db.execute(select(Property).where(Property.url == prop_url))
        prop = r.scalar_one_or_none()
        if prop is not None:
            prop_id = prop.id

    obj = EmailMessage(
        property_id=prop_id,
        property_url=prop_url,
        to_email=str(payload.to_email),
        cc_emails=payload.cc_emails,
        subject=payload.subject,
        body=payload.body,
        attachment_path=payload.attachment_path,
        status="queued",
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)

    # Mirror to Sheet (best-effort).
    email_sheet.append_email_row(
        to_email=obj.to_email,
        cc_emails=obj.cc_emails,
        subject=obj.subject,
        body=obj.body,
        attachment_path=obj.attachment_path,
        property_url=obj.property_url,
        status=obj.status,
        error=None,
        sent_at=obj.created_at,
    )

    # If the email is tied to a property, bump its status.
    if prop_id:
        prop = await db.get(Property, prop_id)
        if prop is not None and (prop.email_status or "not_sent") in ("not_sent", "failed"):
            prop.email_status = "queued"
            await db.commit()

    return obj


@router.get("", response_model=EmailList)
async def list_emails(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    stmt = select(EmailMessage)
    count_stmt = select(func.count(EmailMessage.id))
    if status:
        stmt = stmt.where(EmailMessage.status == status)
        count_stmt = count_stmt.where(EmailMessage.status == status)
    if property_id is not None:
        stmt = stmt.where(EmailMessage.property_id == property_id)
        count_stmt = count_stmt.where(EmailMessage.property_id == property_id)
    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(EmailMessage.created_at.desc()).offset(offset).limit(limit)
    r = await db.execute(stmt)
    items = r.scalars().all()
    return EmailList(items=items, total=int(total), limit=limit, offset=offset)


@router.get("/stats", response_model=EmailStats)
async def get_stats(db: AsyncSession = Depends(get_db)) -> EmailStats:
    async def cnt(stmt):
        return int((await db.execute(stmt)).scalar_one())

    total = await cnt(select(func.count(EmailMessage.id)))
    queued = await cnt(select(func.count(EmailMessage.id)).where(EmailMessage.status == "queued"))
    sent = await cnt(select(func.count(EmailMessage.id)).where(EmailMessage.status == "sent"))
    failed = await cnt(select(func.count(EmailMessage.id)).where(EmailMessage.status == "failed"))

    now = datetime.utcnow()
    day_cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_cutoff = day_cutoff - timedelta(days=7)
    sent_today = await cnt(
        select(func.count(EmailMessage.id)).where(
            EmailMessage.status == "sent", EmailMessage.sent_at >= day_cutoff
        )
    )
    sent_this_week = await cnt(
        select(func.count(EmailMessage.id)).where(
            EmailMessage.status == "sent", EmailMessage.sent_at >= week_cutoff
        )
    )
    return EmailStats(
        total=total,
        queued=queued,
        sent=sent,
        failed=failed,
        sent_today=sent_today,
        sent_this_week=sent_this_week,
    )


@router.get("/{email_id}", response_model=EmailOut)
async def get_email(email_id: int, db: AsyncSession = Depends(get_db)):
    obj = await db.get(EmailMessage, email_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return obj
