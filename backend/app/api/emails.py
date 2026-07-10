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

from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..core.serializers import UtcDateTime
from ..db.models import EmailMessage, Property
from ..services import email_sheet
from ..services.email_service import deliver, require_gmail

router = APIRouter(prefix="/emails", tags=["Emails"])


# ── Schemas ────────────────────────────────────────────────────

class EmailCreate(BaseModel):
    to_email: EmailStr
    cc_emails: Optional[str] = None
    subject: str
    body: Optional[str] = None
    body_html: Optional[str] = None
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
    body_html: Optional[str] = None
    attachment_path: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    sent_at: Optional[UtcDateTime] = None
    created_at: Optional[UtcDateTime] = None

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


# Send logic lives in services.email_service (deliver / require_gmail).


# ── Endpoints ──────────────────────────────────────────────────

@router.post("", response_model=EmailOut, status_code=201)
async def create_email(payload: EmailCreate, db: AsyncSession = Depends(get_db)):
    """
    Create and immediately send an email. Writes to DB (source of truth),
    mirrors into the 'Emails' Google Sheet tab, then sends via Gmail right
    away if credentials are connected. Falls back to status='queued' when
    Gmail isn't connected, so it can be flushed later via /send-queued.
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
        body_html=payload.body_html,
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

    # If the email is tied to a property, bump its status to queued first.
    if prop_id:
        prop = await db.get(Property, prop_id)
        if prop is not None and (prop.email_status or "not_sent") in ("not_sent", "failed"):
            prop.email_status = "queued"
            await db.commit()

    # Send right away (no-op if Gmail not connected → stays queued).
    await deliver(db, obj)
    return obj


@router.get("", response_model=EmailList)
async def list_emails(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    from_date: Optional[date] = Query(None, description="Inclusive start (UTC date)"),
    to_date: Optional[date] = Query(None, description="Inclusive end (UTC date)"),
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
    # Date filter on when the email happened: sent_at if present, else
    # created_at — matches the dashboard graph's bucketing so the list and
    # the graph stay in sync for the same range.
    if from_date is not None or to_date is not None:
        eff = func.coalesce(EmailMessage.sent_at, EmailMessage.created_at)
        if from_date is not None:
            lo = datetime.combine(from_date, datetime.min.time())
            stmt = stmt.where(eff >= lo)
            count_stmt = count_stmt.where(eff >= lo)
        if to_date is not None:
            hi = datetime.combine(to_date + timedelta(days=1), datetime.min.time())
            stmt = stmt.where(eff < hi)
            count_stmt = count_stmt.where(eff < hi)
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


@router.post("/{email_id}/send", response_model=EmailOut)
async def send_email_now(email_id: int, db: AsyncSession = Depends(get_db)):
    """Send a single queued/failed email via Gmail now."""
    obj = await db.get(EmailMessage, email_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Email not found")
    if obj.status == "sent":
        return obj  # idempotent
    await require_gmail(db)
    return await deliver(db, obj)


class SendQueuedResult(BaseModel):
    attempted: int
    sent: int
    failed: int


@router.post("/send-queued", response_model=SendQueuedResult)
async def send_all_queued(db: AsyncSession = Depends(get_db)) -> SendQueuedResult:
    """Flush the backlog: send every queued (and previously failed) email.
    Sent sequentially so one Gmail rate-limit doesn't stampede the API."""
    await require_gmail(db)
    r = await db.execute(
        select(EmailMessage)
        .where(EmailMessage.status.in_(["queued", "failed"]))
        .order_by(EmailMessage.created_at.asc())
    )
    pending = r.scalars().all()
    sent = failed = 0
    for obj in pending:
        await deliver(db, obj)
        if obj.status == "sent":
            sent += 1
        else:
            failed += 1
    return SendQueuedResult(attempted=len(pending), sent=sent, failed=failed)
