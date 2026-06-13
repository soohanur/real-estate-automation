"""
Sheet → DB sync.

Pulls every row from every tab of the canonical Google Sheet and upserts it
into the `properties` table. Idempotent on URL. Scraper code is NOT touched —
it keeps writing to Sheets exactly as before; this is a one-way read mirror.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Make funda package importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# These come from the scraper's own config so we always read the same sheet.
from funda.src.config import config  # noqa: E402
from funda.src.modules.sheets_writer import HEADERS  # noqa: E402

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Map sheet header → Property column. Trailing whitespace / unicode handled
# by .strip() at lookup time. Kept explicit to survive future header renames.
_HEADER_TO_COL: Dict[str, str] = {
    "Scrape Date": "scrape_date",
    "Property URL": "url",
    "Address": "address",
    "Listed Since": "listed_since",
    "Days on Market": "days_on_market",
    "Asking Price (€)": "asking_price",
    "WOZ Value (€)": "woz_value",
    "Suggested Bid (€)": "suggested_bid",
    "Bidding Price": "bidding_price",
    "Price / m² (€)": "price_per_m2",
    "Living Area (m²)": "living_area",
    "Plot Area (m²)": "plot_area",
    "Rooms": "rooms",
    "Bedrooms": "bedrooms",
    "Construction Year": "construction_year",
    "Property Type": "property_type",
    "Energy Label": "energy_label",
    "Heating": "heating",
    "Insulation": "insulation",
    "Maintenance Inside": "maintenance_inside",
    "Maintenance Outside": "maintenance_outside",
    "Garden": "garden",
    "Garden Orientation": "garden_orientation",
    "Parking": "parking",
    "VVE (€/month)": "vve",
    "Erfpacht": "erfpacht",
    "Acceptance": "acceptance",
    "Description": "description",
    "Images": "images",
    "Agency Name": "agency_name",
    "Agency Phone": "agency_phone",
    "Agency Email": "agency_email",
    "Agency Website": "agency_website",
}


def _open_spreadsheet() -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CREDENTIALS, scopes=_SCOPES
    )
    return gspread.authorize(creds).open_by_key(config.GOOGLE_SHEETS_SPREADSHEET_ID)


# Only these worksheets hold scraped property rows. Everything else
# (Emails mirror tab, scratch tabs) is ignored by the sync.
_PROPERTY_TABS = {
    "3-7 Days Ago",
    "8-12 Days Ago",
    "13-17 Days Ago",
    "25-30 Days Ago",
    "30+ Days Ago",
}


def fetch_sheet_rows() -> List[Dict[str, Any]]:
    """Pull every data row from every worksheet and return as dicts.

    Each row dict carries '_sheet' (worksheet title) AND '_row_index'
    (1-based row number on that sheet, where header is row 1). The
    row index lets sync_properties batch-write formulas to col I
    without a second find_row_by_url roundtrip.
    """
    ss = _open_spreadsheet()
    out: List[Dict[str, Any]] = []
    for ws in ss.worksheets():
        # Only the property tabs hold property rows. Other tabs (e.g.
        # "Emails", which carries property URLs in its own columns) must NOT
        # be imported as properties — doing so caused the URL to collide with
        # the real property row and the whole sync 500'd on a UniqueViolation.
        if ws.title not in _PROPERTY_TABS:
            continue
        try:
            values: List[List[str]] = ws.get_all_values()
        except Exception as e:
            logger.warning("Failed to read worksheet %s: %s", ws.title, e)
            continue
        if not values:
            continue
        header_row = [h.strip() for h in values[0]]
        for r_idx, raw in enumerate(values[1:], start=2):
            if not any(c.strip() for c in raw):
                continue  # blank
            row = {
                _HEADER_TO_COL.get(header_row[i], None): (raw[i].strip() if i < len(raw) else "")
                for i in range(len(header_row))
            }
            row.pop(None, None)
            url = row.get("url") or ""
            if not url:
                continue
            row["_sheet"] = ws.title
            row["_row_index"] = r_idx
            out.append(row)
    return out


_DIGITS_RE = re.compile(r"\d+")


def _default_bidding_from_asking(asking_price: Optional[str]) -> Optional[str]:
    """Compute the 20%-off default bidding price from an asking-price
    string. Returns None when asking can't be parsed to a positive int.
    Mirrors the read-time enrichment in properties.py so the value
    persisted in DB matches what the dashboard already displays."""
    if not asking_price:
        return None
    digits = _DIGITS_RE.findall(asking_price)
    if not digits:
        return None
    try:
        asking_int = int("".join(digits))
    except ValueError:
        return None
    if asking_int <= 0:
        return None
    # Tiered: <300k 20% | 300k+ 18% | 400k+ 17% | 500k+ 16%.
    if asking_int >= 500000:
        mult = 0.84
    elif asking_int >= 400000:
        mult = 0.83
    elif asking_int >= 300000:
        mult = 0.82
    else:
        mult = 0.80
    tiered = round(asking_int * mult)
    # Cap: discount never exceeds €76,000.
    return str(int(max(tiered, asking_int - 76000)))


def _batch_write_formulas_safe(
    tab_to_updates: Dict[str, List[Tuple[int, str]]],
) -> None:
    """Write Bidding Price formulas to Sheet col I in batches — ONE
    API call per worksheet — so a long backfill never blows the
    60 writes/min quota.

    Input: {tab_name: [(row_index, formula), ...], ...}

    Runs in a background thread so the sync's HTTP response isn't
    blocked on Google. Failures are logged and swallowed; DB is the
    source of truth.
    """
    if not tab_to_updates:
        return
    try:
        from funda.src.modules import SheetsWriter
        writer = SheetsWriter()
        writer._connect()
        for tab_name, items in tab_to_updates.items():
            if not items:
                continue
            try:
                ws = writer._spreadsheet.worksheet(tab_name)
            except Exception as e:
                logger.warning(f"sheet-batch: worksheet {tab_name} missing: {e}")
                continue
            # Chunk to keep payloads under the 100-cell rule of thumb
            # and avoid 429 on a single huge call.
            CHUNK = 100
            for start in range(0, len(items), CHUNK):
                slice_ = items[start:start + CHUNK]
                requests = [
                    {"range": f"I{row_idx}", "values": [[formula]]}
                    for row_idx, formula in slice_
                ]
                ok = writer._batch_update_with_backoff(
                    ws,
                    requests,
                    label=f"Bidding-formula batch [{tab_name}] {len(requests)}",
                )
                if ok:
                    logger.info(
                        f"  ✓ Bidding formula batch [{tab_name}]: {len(requests)} cells"
                    )
    except Exception as e:
        logger.warning(f"sheet-batch formula write failed: {e}")


async def sync_properties(db: AsyncSession) -> Dict[str, int]:  # noqa: D401
    import asyncio as _aio
    """
    Read all sheet rows and upsert into `properties` table. Returns counts.

    Side effect: for any property where the Sheet's Bidding Price column
    is empty but Asking Price is valid, computes the 20%-off default,
    persists it to DB, AND schedules a background write back to Sheet
    col I so the spreadsheet view also shows the default. Existing
    user-entered values are never overwritten.
    """
    from ..db.models import Property  # local import to dodge circulars

    # Run the blocking gspread reads in a worker thread so a slow / hung
    # Google API call cannot freeze the asyncio event loop (and with it
    # every HTTP endpoint). Without this wrapper, fetch_sheet_rows is a
    # sync function that calls ws.get_all_values() without timeout —
    # a Google read that never returns blocks the entire backend.
    rows = await _aio.to_thread(fetch_sheet_rows)
    inserted = 0
    updated = 0
    bidding_filled = 0
    now = datetime.utcnow()

    # Bulk lookup: get all existing URLs.
    existing_q = await db.execute(select(Property.id, Property.url))
    existing = {url: pid for pid, url in existing_q.all()}

    # Per-tab list of (row_index, formula) cells to write back to Sheet
    # col I. We already have the row index from fetch_sheet_rows so a
    # single batch_update per tab fills every blank cell — no
    # find_row_by_url roundtrips, ~3 API calls per sync iteration
    # instead of hundreds.
    pending_formula_writes: Dict[str, List[Tuple[int, str]]] = {}

    # Asking column letter for the formula. F = 6th column = Asking
    # Price (€). Keep this aligned with the COLUMNS constant in
    # funda/src/modules/sheets_writer.py.
    _ASK_COL = "F"

    for row in rows:
        url = row["url"]
        sheet_tab = row.get("_sheet")
        row_index = row.get("_row_index")
        payload = {
            k: v
            for k, v in row.items()
            if k not in ("_sheet", "_row_index", "url") and v != ""
        }
        payload["last_synced_at"] = now
        if sheet_tab:
            payload["sheet_tab"] = sheet_tab

        # The Sheet now holds the 20%-off math as a per-row formula
        # (tiered 20/18/17/16% by asking band). Whenever the Sheet cell
        # is blank — which happens on freshly-scraped rows that haven't
        # been formula-written yet — we enqueue a one-cell formula
        # write. DB just receives whatever value the Sheet evaluates
        # the formula to (already in payload when the formula is in
        # place). User PATCH still overrides with a static value.
        sheet_bidding_blank = "bidding_price" not in payload
        asking_present = bool(payload.get("asking_price"))

        def _queue_formula_write():
            if not (sheet_tab and row_index and asking_present and sheet_bidding_blank):
                return
            formula = (
                f'=IF({_ASK_COL}{row_index}="","",MAX(ROUND({_ASK_COL}{row_index}*IF({_ASK_COL}{row_index}>=500000,0.84,IF({_ASK_COL}{row_index}>=400000,0.83,IF({_ASK_COL}{row_index}>=300000,0.82,0.80)))),{_ASK_COL}{row_index}-76000))'
            )
            pending_formula_writes.setdefault(sheet_tab, []).append((row_index, formula))

        if url in existing:
            pid = existing[url]
            obj = await db.get(Property, pid)
            if obj is None:
                continue
            for k, v in payload.items():
                setattr(obj, k, v)
            if sheet_bidding_blank and asking_present:
                _queue_formula_write()
                bidding_filled += 1
            updated += 1
        else:
            obj = Property(url=url, **payload)
            db.add(obj)
            if sheet_bidding_blank and asking_present:
                _queue_formula_write()
                bidding_filled += 1
            inserted += 1

    await db.commit()

    # Batch write all formulas in ONE thread (per-tab batch_update).
    # No find_row_by_url reads — we already know each row's index from
    # the sheet iter above. Typical sync iteration = up to 6 API
    # writes total (one batch per tab), well under the 60/min cap.
    if pending_formula_writes:
        import threading
        threading.Thread(
            target=_batch_write_formulas_safe,
            args=(pending_formula_writes,),
            daemon=True,
            name="bid-formula-batch",
        ).start()

    return {
        "inserted": inserted,
        "updated": updated,
        "bidding_filled": bidding_filled,
        "total_rows": len(rows),
    }


__all__ = ["fetch_sheet_rows", "sync_properties", "HEADERS"]
