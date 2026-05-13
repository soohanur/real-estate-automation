"""
Properties API — scraped property records (DB-backed, Sheet-mirrored).

GET    /properties              → list, paginate, filter, sort
GET    /properties/{property_id}→ single record
POST   /properties/sync         → on-demand sheet → DB sync
PATCH  /properties/{property_id}→ update notes / email_status
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..db.models import Property
from ..services import sheet_sync

router = APIRouter(prefix="/properties", tags=["Properties"])


# ── Schemas ────────────────────────────────────────────────────

class PropertyOut(BaseModel):
    id: int
    url: str
    scrape_date: Optional[str] = None
    address: Optional[str] = None
    listed_since: Optional[str] = None
    days_on_market: Optional[str] = None
    asking_price: Optional[str] = None
    woz_value: Optional[str] = None
    suggested_bid: Optional[str] = None
    bidding_price: Optional[str] = None
    price_per_m2: Optional[str] = None
    living_area: Optional[str] = None
    plot_area: Optional[str] = None
    rooms: Optional[str] = None
    bedrooms: Optional[str] = None
    construction_year: Optional[str] = None
    property_type: Optional[str] = None
    energy_label: Optional[str] = None
    heating: Optional[str] = None
    insulation: Optional[str] = None
    maintenance_inside: Optional[str] = None
    maintenance_outside: Optional[str] = None
    garden: Optional[str] = None
    garden_orientation: Optional[str] = None
    parking: Optional[str] = None
    vve: Optional[str] = None
    erfpacht: Optional[str] = None
    acceptance: Optional[str] = None
    description: Optional[str] = None
    images: Optional[str] = None
    agency_name: Optional[str] = None
    agency_phone: Optional[str] = None
    agency_email: Optional[str] = None
    agency_website: Optional[str] = None
    email_status: Optional[str] = "not_sent"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PropertyList(BaseModel):
    items: List[PropertyOut]
    total: int
    limit: int
    offset: int


class PropertyPatch(BaseModel):
    notes: Optional[str] = None
    email_status: Optional[str] = None
    bidding_price: Optional[str] = None


class SyncResponse(BaseModel):
    inserted: int
    updated: int
    total_rows: int


# ── Helpers ────────────────────────────────────────────────────

_SORT_FIELDS = {
    "created_at",
    "updated_at",
    "scrape_date",
    "address",
    "asking_price",
    "woz_value",
    "suggested_bid",
    "days_on_market",
    "energy_label",
    "property_type",
    "agency_name",
    "email_status",
}


def _apply_filters(stmt, *, q: Optional[str], email_status: Optional[str],
                   property_type: Optional[str], energy_label: Optional[str],
                   agency_name: Optional[str], days_back: Optional[int]):
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Property.address.ilike(like),
                Property.url.ilike(like),
                Property.agency_name.ilike(like),
                Property.agency_email.ilike(like),
                Property.description.ilike(like),
            )
        )
    if email_status:
        stmt = stmt.where(Property.email_status == email_status)
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if energy_label:
        stmt = stmt.where(Property.energy_label == energy_label)
    if agency_name:
        stmt = stmt.where(Property.agency_name == agency_name)
    if days_back is not None and days_back > 0:
        cutoff = datetime.utcnow() - timedelta(days=days_back)
        stmt = stmt.where(Property.created_at >= cutoff)
    return stmt


# ── Endpoints ──────────────────────────────────────────────────

@router.get("", response_model=PropertyList)
async def list_properties(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None, description="search across address/url/agency/description"),
    email_status: Optional[str] = Query(None),
    property_type: Optional[str] = Query(None),
    energy_label: Optional[str] = Query(None),
    agency_name: Optional[str] = Query(None),
    days_back: Optional[int] = Query(None, ge=1, le=3650),
    sort: str = Query("created_at"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List properties (DB-backed). Use POST /properties/sync to refresh from Sheet."""
    if sort not in _SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Invalid sort field. Allowed: {sorted(_SORT_FIELDS)}")

    base = _apply_filters(
        select(Property),
        q=q, email_status=email_status, property_type=property_type,
        energy_label=energy_label, agency_name=agency_name, days_back=days_back,
    )

    # Count.
    count_stmt = _apply_filters(
        select(func.count(Property.id)),
        q=q, email_status=email_status, property_type=property_type,
        energy_label=energy_label, agency_name=agency_name, days_back=days_back,
    )
    total = (await db.execute(count_stmt)).scalar_one()

    # Page.
    col = getattr(Property, sort)
    base = base.order_by(col.asc() if order == "asc" else col.desc())
    base = base.offset(offset).limit(limit)
    res = await db.execute(base)
    items = res.scalars().all()

    return PropertyList(items=items, total=int(total), limit=limit, offset=offset)


@router.get("/filters")
async def get_filter_options(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Distinct values for the dashboard's filter dropdowns."""
    async def distinct(col):
        r = await db.execute(select(col).distinct().where(col.is_not(None)))
        return sorted({(v or "").strip() for (v,) in r.all() if v and v.strip()})

    return {
        "property_type": await distinct(Property.property_type),
        "energy_label": await distinct(Property.energy_label),
        "agency_name": await distinct(Property.agency_name),
        "email_status": await distinct(Property.email_status),
    }


@router.get("/{property_id}", response_model=PropertyOut)
async def get_property(property_id: int, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Property, property_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return obj


def _mirror_bidding_to_sheet(url: str, bidding_price: str) -> None:
    """Best-effort write of the human-entered bidding price to the Google
    Sheet (column I). Runs in BackgroundTasks so the HTTP response doesn't
    wait on Google. Failures are logged but never raised — the DB row is the
    source of truth."""
    try:
        import sys
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[3]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from funda.src.modules import SheetsWriter
        writer = SheetsWriter()
        writer.update_bidding_price(url, bidding_price)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Bidding sheet mirror failed: {e}")


@router.patch("/{property_id}", response_model=PropertyOut)
async def update_property(
    property_id: int,
    patch: PropertyPatch,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(Property, property_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Property not found")
    if patch.notes is not None:
        obj.notes = patch.notes
    if patch.email_status is not None:
        obj.email_status = patch.email_status
    bidding_changed = False
    if patch.bidding_price is not None:
        bidding_changed = (obj.bidding_price or "") != (patch.bidding_price or "")
        obj.bidding_price = patch.bidding_price
    await db.commit()
    await db.refresh(obj)
    if bidding_changed and obj.url:
        background_tasks.add_task(_mirror_bidding_to_sheet, obj.url, obj.bidding_price or "")
    return obj


@router.post("/sync", response_model=SyncResponse)
async def sync_from_sheet(db: AsyncSession = Depends(get_db)):
    """Pull every row from the Google Sheet into the DB. Idempotent on URL."""
    try:
        out = await sheet_sync.sync_properties(db)
        return SyncResponse(**out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")
