"""
Dashboard aggregate API.

GET /api/v1/dashboard/stats — single roll-up call so the dashboard renders
without 5 separate round-trips. Pulls from the properties + email_messages
tables exclusively (Sheet is mirrored into the DB already).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..db.models import EmailMessage, Property
# Reuse the canonical PropertyOut so dashboard's latest_scrapes carries
# every column the Global Data table renders — no field drift.
from .properties import PropertyOut

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class DashboardStats(BaseModel):
    total_scraped: int
    scraped_today: int
    total_emails: int
    emails_sent: int
    emails_sent_today: int
    emails_queued: int
    emails_failed: int
    not_emailed: int
    latest_scrapes: List[PropertyOut]


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    latest_limit: int = 10,
) -> DashboardStats:
    now = datetime.utcnow()
    day_cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async def cnt(stmt):
        return int((await db.execute(stmt)).scalar_one())

    total_scraped = await cnt(select(func.count(Property.id)))
    scraped_today = await cnt(
        select(func.count(Property.id)).where(Property.created_at >= day_cutoff)
    )
    not_emailed = await cnt(
        select(func.count(Property.id)).where(
            (Property.email_status == "not_sent") | (Property.email_status.is_(None))
        )
    )

    total_emails = await cnt(select(func.count(EmailMessage.id)))
    emails_sent = await cnt(
        select(func.count(EmailMessage.id)).where(EmailMessage.status == "sent")
    )
    emails_queued = await cnt(
        select(func.count(EmailMessage.id)).where(EmailMessage.status == "queued")
    )
    emails_failed = await cnt(
        select(func.count(EmailMessage.id)).where(EmailMessage.status == "failed")
    )
    emails_sent_today = await cnt(
        select(func.count(EmailMessage.id)).where(
            EmailMessage.status == "sent",
            EmailMessage.sent_at >= day_cutoff,
        )
    )

    latest_q = await db.execute(
        select(Property).order_by(Property.created_at.desc()).limit(latest_limit)
    )
    latest = latest_q.scalars().all()

    return DashboardStats(
        total_scraped=total_scraped,
        scraped_today=scraped_today,
        total_emails=total_emails,
        emails_sent=emails_sent,
        emails_sent_today=emails_sent_today,
        emails_queued=emails_queued,
        emails_failed=emails_failed,
        not_emailed=not_emailed,
        latest_scrapes=[PropertyOut.model_validate(p) for p in latest],
    )
