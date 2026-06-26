"""
Dashboard aggregate API.

GET /api/v1/dashboard/stats — single roll-up call so the dashboard renders
without 5 separate round-trips. Pulls from the properties + email_messages
tables exclusively (Sheet is mirrored into the DB already).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..db.models import EmailMessage, Property
# Shared PropertyOut so dashboard's latest_scrapes carries every column the
# Global Data table renders — no field drift, and no router→router import.
from ..schemas.properties import PropertyOut

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class EmailReportBucket(BaseModel):
    bucket: str       # ISO date / month / year label, e.g. '2026-05-16'
    sent: int = 0
    queued: int = 0
    failed: int = 0
    total: int = 0


class EmailReport(BaseModel):
    granularity: Literal["day", "month", "year"]
    from_date: date
    to_date: date
    buckets: List[EmailReportBucket]
    totals: EmailReportBucket  # status totals across the range


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
    latest_limit: int = 50,
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


_RANGE_DEFAULTS = {
    "day":   ("day",   1),     # last 24h, grouped by hour... we group by day (single bucket)
    "week":  ("day",   7),     # last 7 days, grouped by day
    "month": ("day",   30),    # last 30 days, grouped by day
    "year":  ("month", 365),   # last 365 days, grouped by month
    "all":   ("month", 3650),  # last 10y, grouped by month
}


@router.get("/email-report", response_model=EmailReport)
async def email_report(
    period: Literal["day", "week", "month", "year", "all", "custom"] = Query(
        "month",
        description="Preset window. Use 'custom' to pass from_date + to_date.",
    ),
    from_date: Optional[date] = Query(None, description="Inclusive start (UTC date) — used when period=custom"),
    to_date: Optional[date] = Query(None, description="Inclusive end (UTC date) — used when period=custom"),
    group_by: Optional[Literal["day", "month", "year"]] = Query(
        None,
        description="Override bucket granularity. Defaults sensibly from `period`.",
    ),
    db: AsyncSession = Depends(get_db),
) -> EmailReport:
    """Time-bucketed counts of email_messages by status (sent / queued /
    failed) for the dashboard report graph. Backed by the existing
    `email_messages.sent_at` (sent rows) and `email_messages.created_at`
    (queued/failed rows) — sent_at falls back to created_at when null.

    Default presets:
      day   → last 1 day,   grouped by day
      week  → last 7 days,  grouped by day
      month → last 30 days, grouped by day (default)
      year  → last 365 days, grouped by month
      all   → last 10 years, grouped by month
      custom→ caller provides from_date + to_date
    """
    today = date.today()
    if period == "custom":
        if from_date is None or to_date is None:
            raise HTTPException(
                status_code=400,
                detail="period=custom requires both from_date and to_date",
            )
        if to_date < from_date:
            raise HTTPException(status_code=400, detail="to_date must be on or after from_date")
        default_group = "day" if (to_date - from_date).days <= 90 else "month"
    else:
        default_group, lookback_days = _RANGE_DEFAULTS[period]
        from_date = today - timedelta(days=lookback_days - 1)
        to_date = today

    granularity = group_by or default_group

    # date_trunc returns timestamp at start of the bucket. We render the
    # bucket label as YYYY-MM-DD (day), YYYY-MM (month), YYYY (year).
    # COALESCE so queued/failed rows (no sent_at) still appear in their
    # creation bucket — otherwise the graph would only show sent rows.
    effective_ts = func.coalesce(EmailMessage.sent_at, EmailMessage.created_at)
    bucket = func.date_trunc(granularity, effective_ts).label("bucket")

    stmt = (
        select(bucket, EmailMessage.status, func.count(EmailMessage.id))
        .where(effective_ts >= datetime.combine(from_date, datetime.min.time()))
        .where(effective_ts < datetime.combine(to_date + timedelta(days=1), datetime.min.time()))
        .group_by(bucket, EmailMessage.status)
        .order_by(bucket)
    )
    rows = (await db.execute(stmt)).all()

    fmt_map = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
    fmt = fmt_map[granularity]

    by_bucket: dict[str, EmailReportBucket] = {}
    totals = EmailReportBucket(bucket="totals")

    # Pre-seed every bucket in range so the graph X-axis shows empty days
    # too (cleaner UX than a gap-toothed chart).
    cursor = from_date
    step = {"day": timedelta(days=1), "month": None, "year": None}[granularity]
    if granularity == "day":
        while cursor <= to_date:
            label = cursor.strftime(fmt)
            by_bucket[label] = EmailReportBucket(bucket=label)
            cursor = cursor + step
    elif granularity == "month":
        c = cursor.replace(day=1)
        while c <= to_date:
            label = c.strftime(fmt)
            by_bucket[label] = EmailReportBucket(bucket=label)
            # advance one month
            if c.month == 12:
                c = c.replace(year=c.year + 1, month=1)
            else:
                c = c.replace(month=c.month + 1)
    else:  # year
        for y in range(from_date.year, to_date.year + 1):
            label = f"{y}"
            by_bucket[label] = EmailReportBucket(bucket=label)

    for bucket_ts, status, count in rows:
        if bucket_ts is None:
            continue
        label = bucket_ts.strftime(fmt)
        b = by_bucket.setdefault(label, EmailReportBucket(bucket=label))
        n = int(count or 0)
        if status == "sent":
            b.sent += n
            totals.sent += n
        elif status == "queued":
            b.queued += n
            totals.queued += n
        elif status == "failed":
            b.failed += n
            totals.failed += n
        b.total += n
        totals.total += n

    ordered = sorted(by_bucket.values(), key=lambda b: b.bucket)
    return EmailReport(
        granularity=granularity,
        from_date=from_date,
        to_date=to_date,
        buckets=ordered,
        totals=totals,
    )
