"""
Properties API — scraped property records (DB-backed, Sheet-mirrored).

GET    /properties              → list, paginate, filter, sort
GET    /properties/{property_id}→ single record
POST   /properties/sync         → on-demand sheet → DB sync
PATCH  /properties/{property_id}→ update notes / email_status
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
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
    sheet_tab: Optional[str] = None
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
    bidding_filled: int = 0


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
    "listed_since",
}


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGITS_RE = re.compile(r"\d+")


def _dynamic_dom(listed_since: Optional[str], fallback: Optional[str]) -> Optional[str]:
    """Return days-on-market as a fresh integer string derived from
    listed_since (always YYYY-MM-DD in the sheet). Falls back to the
    stored static days_on_market when the date isn't parseable.

    Computed every read so the value grows by 1 every midnight without
    rewriting any rows.
    """
    if listed_since and _ISO_DATE_RE.match(listed_since):
        try:
            d = datetime.strptime(listed_since, "%Y-%m-%d").date()
            delta = (date.today() - d).days
            if delta < 0:
                # listed in the future — sanity guard
                return fallback
            return str(delta)
        except ValueError:
            pass
    return fallback


def _bidding_multiplier(asking_int: int) -> float:
    """Tiered keep-fraction by asking band (1 - discount%)."""
    if asking_int >= 500000:
        return 0.84  # 16% off
    if asking_int >= 400000:
        return 0.83  # 17% off
    if asking_int >= 300000:
        return 0.82  # 18% off
    return 0.80      # 20% off


def _default_bidding(asking_price: Optional[str], current: Optional[str]) -> Optional[str]:
    """If the user hasn't entered a bidding price, default to asking minus a
    tiered discount by asking band:
        < €300k  → 20% off  (×0.80)
        €300k+   → 18% off  (×0.82)
        €400k+   → 17% off  (×0.83)
        €500k+   → 16% off  (×0.84)
    AND the discount is capped at €76,000 (bidding never below asking-76000).
    User-entered values always win.
    """
    if current and current.strip():
        return current
    if not asking_price:
        return current
    digits = _DIGITS_RE.findall(asking_price)
    if not digits:
        return current
    try:
        asking_int = int(''.join(digits))
    except ValueError:
        return current
    if asking_int <= 0:
        return current
    tiered = round(asking_int * _bidding_multiplier(asking_int))
    # Cap: discount never exceeds €76,000 (bidding never < asking - 76000).
    return str(int(max(tiered, asking_int - 76000)))


def _enrich_for_response(items: List["PropertyOut"]) -> None:
    """In-place mutation of PropertyOut copies — never the ORM objects."""
    for p in items:
        p.days_on_market = _dynamic_dom(p.listed_since, p.days_on_market)
        p.bidding_price = _default_bidding(p.asking_price, p.bidding_price)


def _apply_filters(stmt, *, q: Optional[str], email_status: Optional[str],
                   property_type: Optional[str], energy_label: Optional[str],
                   agency_name: Optional[str], days_back: Optional[int],
                   sheet_tab: Optional[str],
                   dom_min: Optional[int] = None,
                   dom_max: Optional[int] = None):
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
    if sheet_tab:
        stmt = stmt.where(Property.sheet_tab == sheet_tab)
    # DOM filter — listed_since is stored as YYYY-MM-DD so string
    # compare gives the same ordering as date compare and uses the
    # existing index. dom_min/dom_max are "days ago" bounds:
    #   dom_min=5 → listed >= today - dom_max days  AND  listed <= today - 5 days
    if dom_min is not None and dom_min >= 0:
        cutoff_old = (date.today() - timedelta(days=dom_min)).isoformat()
        stmt = stmt.where(Property.listed_since <= cutoff_old)
        stmt = stmt.where(Property.listed_since != "")
        stmt = stmt.where(Property.listed_since.is_not(None))
    if dom_max is not None and dom_max >= 0:
        cutoff_new = (date.today() - timedelta(days=dom_max)).isoformat()
        stmt = stmt.where(Property.listed_since >= cutoff_new)
        stmt = stmt.where(Property.listed_since != "")
        stmt = stmt.where(Property.listed_since.is_not(None))
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
    sheet_tab: Optional[str] = Query(None),
    dom_min: Optional[int] = Query(None, ge=0, le=3650, description="min days-on-market (inclusive)"),
    dom_max: Optional[int] = Query(None, ge=0, le=3650, description="max days-on-market (inclusive)"),
    sort: str = Query("created_at"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    # Cap raised so the dashboard table can render every row in one
    # virtualized list. 100k is well above any realistic NL listing total
    # (~55k), still bounded so a typo can't ask for the whole world.
    limit: int = Query(100, ge=1, le=100000),
    offset: int = Query(0, ge=0),
    # When true (default for the table view) drops the heaviest fields
    # — description (~2KB/row) and notes — and trims images to first
    # URL only. Cuts the response from ~10KB/row to ~1.5KB/row, so 3000
    # properties go 30MB → 4-5MB and the API responds in <5s instead of
    # ~50s. Profile detail endpoint always returns the full record.
    compact: bool = Query(True),
):
    """List properties (DB-backed). Use POST /properties/sync to refresh from Sheet."""
    if sort not in _SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Invalid sort field. Allowed: {sorted(_SORT_FIELDS)}")

    base = _apply_filters(
        select(Property),
        q=q, email_status=email_status, property_type=property_type,
        energy_label=energy_label, agency_name=agency_name, days_back=days_back,
        sheet_tab=sheet_tab, dom_min=dom_min, dom_max=dom_max,
    )

    # Count.
    count_stmt = _apply_filters(
        select(func.count(Property.id)),
        q=q, email_status=email_status, property_type=property_type,
        energy_label=energy_label, agency_name=agency_name, days_back=days_back,
        sheet_tab=sheet_tab, dom_min=dom_min, dom_max=dom_max,
    )
    total = (await db.execute(count_stmt)).scalar_one()

    # Page.
    col = getattr(Property, sort)
    base = base.order_by(col.asc() if order == "asc" else col.desc())
    base = base.offset(offset).limit(limit)
    res = await db.execute(base)
    items = res.scalars().all()

    # Build response models — copy out of ORM so we never mutate session
    # state. In compact mode we then blank the heaviest fields on the
    # Pydantic copies before serialization.
    out_items = [PropertyOut.model_validate(p) for p in items]
    # Derived fields applied on every read so dashboards stay fresh
    # without rewriting any rows: DOM grows automatically, bidding
    # defaults to asking × 0.80 when user hasn't set one.
    _enrich_for_response(out_items)
    if compact:
        for p in out_items:
            p.description = None
            p.notes = None
            if p.images:
                # Keep only the first thumbnail URL — full carousel is
                # fetched on demand from /properties/{id}.
                first = p.images.split(',')[0].strip()
                p.images = first or None

    return PropertyList(items=out_items, total=int(total), limit=limit, offset=offset)


@router.get("/filters")
async def get_filter_options(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Distinct values for the dashboard's filter dropdowns.

    Cache for 5 minutes — distinct sets shift only when new property
    types / agencies appear, which happens rarely. Browser + any
    intermediate proxy can serve the cached payload in microseconds.
    """
    response.headers["Cache-Control"] = "public, max-age=300"

    async def distinct(col):
        r = await db.execute(select(col).distinct().where(col.is_not(None)))
        return sorted({(v or "").strip() for (v,) in r.all() if v and v.strip()})

    return {
        "property_type": await distinct(Property.property_type),
        "energy_label": await distinct(Property.energy_label),
        "agency_name": await distinct(Property.agency_name),
        "email_status": await distinct(Property.email_status),
        "sheet_tab": await distinct(Property.sheet_tab),
    }


@router.get("/{property_id}", response_model=PropertyOut)
async def get_property(property_id: int, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Property, property_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Property not found")
    out = PropertyOut.model_validate(obj)
    _enrich_for_response([out])
    return out


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


@router.delete("/{property_id}")
async def delete_property(property_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a property from BOTH the Google Sheet and the DB. Sheet row is
    removed first (best-effort); the DB row + its emails (cascade) follow.
    Returns what was removed."""
    obj = await db.get(Property, property_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Property not found")
    url = obj.url
    address = obj.address

    # Remove the sheet row + purge the KVK id (sync — runs in a thread so a
    # slow Sheets call can't block the event loop; bounded by socket timeout).
    # Purging KVK means a deleted property is never re-collected in future
    # scrapes (user no longer wants it).
    sheet_deleted = False
    kvk_removed = False
    if url:
        import asyncio

        def _del_sheet_and_kvk():
            import re as _re
            import sys
            from pathlib import Path
            root = Path(__file__).resolve().parents[3]
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from funda.src.modules import SheetsWriter
            from funda.src.modules.kvk_storage import get_kvk_storage
            sd = SheetsWriter().delete_row_by_url(url)
            # Funda object id = the 7-10 digit segment in the detail URL.
            kr = False
            m = _re.search(r"/(\d{7,10})/?(?:\?|$)", url)
            fid = m.group(1) if m else None
            if not fid:
                for seg in reversed(url.rstrip("/").split("/")):
                    if seg.isdigit() and 7 <= len(seg) <= 10:
                        fid = seg
                        break
            if fid:
                kr = get_kvk_storage().remove(fid)
            return sd, kr

        try:
            sheet_deleted, kvk_removed = await asyncio.wait_for(
                asyncio.to_thread(_del_sheet_and_kvk), timeout=90
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Sheet/KVK delete failed for {url}: {e}")

    await db.delete(obj)
    await db.commit()
    return {"deleted": True, "id": property_id, "address": address,
            "sheet_deleted": sheet_deleted, "kvk_removed": kvk_removed}


@router.post("/sync", response_model=SyncResponse)
async def sync_from_sheet(db: AsyncSession = Depends(get_db)):
    """Pull every row from the Google Sheet into the DB. Idempotent on URL."""
    try:
        out = await sheet_sync.sync_properties(db)
        return SyncResponse(**out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")
