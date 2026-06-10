"""
Google Sheets Writer Module

Writes scraped Funda property data directly to Google Sheets,
one row per property, instantly after scraping.

Sheet tabs correspond to the publication_date filter:
  3-7 Days Ago | 8-12 Days Ago | 13-17 Days Ago | 25-30 Days Ago | 30+ Days Ago

Uses gspread + google-auth with a service account.
"""
import re
import socket
import gspread
from datetime import date
from google.oauth2.service_account import Credentials
from typing import Optional, List, Set

# Hard cap on every TCP socket read this process ever opens — including
# the gspread / requests / urllib3 stack underneath. Without this a
# hung Google Sheets read on a quiet TCP connection waits forever and
# can block the asyncio event loop in the FastAPI backend. 60 s is well
# above any healthy Sheets response time + long enough to ride out a
# transient blip; quota/backoff loops handle anything legitimately slow.
socket.setdefaulttimeout(60)

from ..config import config
from ..utils.logger import setup_logger

logger = setup_logger('funda.sheets')

# Google Sheets API scopes
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# Column definitions: (header, pixel_width)
# Valuation columns (Walter / Suggested Bid / Confidence / Reasoning) sit
# directly after Asking Price so the bid decision is readable next to asking.
COLUMNS = [
    ('Scrape Date',                   95),
    ('Property URL',                 180),
    ('Address',                      220),
    ('Listed Since',                  95),
    ('Days on Market',                95),
    ('Asking Price (\u20ac)',        120),
    ('WOZ Value (\u20ac)',           120),
    ('Suggested Bid (\u20ac)',       130),
    ('Bidding Price',                 130),
    ('Price / m\u00b2 (\u20ac)',    100),
    ('Living Area (m\u00b2)',        110),
    ('Plot Area (m\u00b2)',          100),
    ('Rooms',                         65),
    ('Bedrooms',                      75),
    ('Construction Year',            130),
    ('Property Type',                150),
    ('Energy Label',                  90),
    ('Heating',                      160),
    ('Insulation',                   200),
    ('Maintenance Inside',           130),
    ('Maintenance Outside',          130),
    ('Garden',                       100),
    ('Garden Orientation',           130),
    ('Parking',                      150),
    ('VVE (\u20ac/month)',          100),
    ('Erfpacht',                      80),
    ('Acceptance',                   110),
    ('Description',                  280),
    ('Images',                       200),
    ('Agency Name',                  150),
    ('Agency Phone',                 120),
    ('Agency Email',                 160),
    ('Agency Website',               160),
]

HEADERS = [col[0] for col in COLUMNS]

# Header theme: dark navy blue
_HEADER_BG   = {'red': 0.145, 'green': 0.247, 'blue': 0.455}
_HEADER_TEXT = {'red': 1.0,   'green': 1.0,   'blue': 1.0}
# Alternating row colours: white / very light blue
_ROW_ODD     = {'red': 1.0,   'green': 1.0,   'blue': 1.0}
_ROW_EVEN    = {'red': 0.929, 'green': 0.941, 'blue': 0.969}


class SheetsWriter:
    """Writes property data to Google Sheets in real-time."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
    ):
        self.credentials_path = credentials_path or config.GOOGLE_SHEETS_CREDENTIALS
        self.spreadsheet_id   = spreadsheet_id   or config.GOOGLE_SHEETS_SPREADSHEET_ID
        self._client: Optional[gspread.Client]       = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None
        # Guards _connect against concurrent reconnect attempts (writer thread,
        # valuation thread, bidding-mirror BackgroundTask, dashboard sync).
        import threading
        self._connect_lock = threading.Lock()
        self._formatted_sheets: Set[str] = set()   # track formatted tabs this session
        # In-memory URL set per tab, seeded from the sheet on first use and
        # updated after every append. Prevents writing a property twice — both
        # within a session AND across sessions (e.g. when a prior run's write
        # reported failure due to Google API eventual consistency but actually
        # landed, so the property never got added to KVK and gets re-scraped).
        self._tab_urls: dict = {}   # tab_name -> set(url)
        # Cache: property URL → (tab_name, row_number). Lets back-write paths
        # (update_valuation_row / update_bidding_price / update_bidding_formula)
        # skip the 6-tab col_values(2) scan that find_row_by_url does.
        # Seeded from col B on first touch of each tab, kept fresh by
        # write_property after every successful append. Guarded by a lock
        # because the three scraper workers append concurrently.
        self._url_to_row: dict = {}   # url -> (tab_name, row_num)
        self._url_to_row_lock = threading.Lock()

    # ── Connection ────────────────────────────────────────────

    def _connect(self) -> None:
        # Both must be live — earlier code only checked _client, which broke
        # if a prior open_by_key failure left _spreadsheet=None or a thread
        # raced past the guard before the spreadsheet handle was assigned.
        if self._client is not None and self._spreadsheet is not None:
            return
        with self._connect_lock:
            if self._client is not None and self._spreadsheet is not None:
                return
            try:
                creds = Credentials.from_service_account_file(
                    self.credentials_path, scopes=SCOPES,
                )
                client = gspread.authorize(creds)
                spreadsheet = client.open_by_key(self.spreadsheet_id)
            except Exception:
                # Reset both so the next call retries cleanly instead of
                # entering the half-connected state that caused
                # 'NoneType has no attribute worksheet'.
                self._client = None
                self._spreadsheet = None
                raise
            self._client = client
            self._spreadsheet = spreadsheet
            logger.info(f"Connected to Google Sheets: {self._spreadsheet.title}")

    def _force_reconnect(self) -> None:
        """Drop cached client + spreadsheet so the next op rebuilds them."""
        with self._connect_lock:
            self._client = None
            self._spreadsheet = None
            self._formatted_sheets.clear()
            self._tab_urls.clear()

    # ── Worksheet setup ───────────────────────────────────────

    def _get_or_create_worksheet(self, tab_name: str) -> gspread.Worksheet:
        """Get existing worksheet or create it, then ensure headers + formatting."""
        self._connect()
        # Belt-and-braces: if a prior op left _spreadsheet None despite _client
        # being set, force a clean reconnect now instead of crashing with
        # 'NoneType has no attribute worksheet'.
        if self._spreadsheet is None:
            self._force_reconnect()
            self._connect()

        try:
            ws = self._spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=tab_name, rows=2000, cols=len(HEADERS),
            )
            logger.info(f"Created new sheet tab: {tab_name}")

        # Update headers if missing or outdated
        existing = ws.row_values(1)
        if not existing or existing != HEADERS:
            ws.update(values=[HEADERS], range_name='A1')
            logger.info(f"Headers updated on tab: {tab_name}")

        # Apply formatting once per session per tab
        if tab_name not in self._formatted_sheets:
            self._apply_sheet_formatting(ws)
            self._formatted_sheets.add(tab_name)

        # Seed the in-memory URL set + URL→row cache from the sheet's
        # Property URL column (B) the first time we touch this tab.
        # Same single col_values(2) call powers both — append-time dedup
        # (set) and back-write lookups (cache). Cache lets
        # update_valuation_row / update_bidding_price /
        # update_bidding_formula skip the 6-tab scan in find_row_by_url.
        if tab_name not in self._tab_urls:
            try:
                col_b = ws.col_values(2)   # includes header
                urls_set: Set[str] = set()
                # col_b[0] is the header. col_b[1] is row 2 (first data
                # row), col_b[2] is row 3, etc. enumerate(start=2) keeps
                # the 1-based sheet row in lock-step with the iteration.
                local_url_to_row: dict = {}
                for idx, v in enumerate(col_b[1:], start=2):
                    u = (v or "").strip()
                    if not u:
                        continue
                    urls_set.add(u)
                    local_url_to_row[u] = (tab_name, idx)
                self._tab_urls[tab_name] = urls_set
                with self._url_to_row_lock:
                    self._url_to_row.update(local_url_to_row)
                logger.info(
                    f"  Seeded {len(urls_set)} known URLs for tab: {tab_name}"
                )
            except Exception as e:
                logger.warning(f"  Could not seed URL set for {tab_name}: {e}")
                self._tab_urls[tab_name] = set()

        return ws

    # ── Cached row lookup ────────────────────────────────────────

    _UPDATED_RANGE_RE = re.compile(r"!([A-Z]+)(\d+):")  # parses 'Tab!A51:AG51' → row 51

    def _lookup_row(self, url: str) -> Optional[tuple]:
        """Return (worksheet, row_number) for `url` from the cache when
        possible; fall back to find_row_by_url's 6-tab scan only on a
        cache miss. The worksheet handle comes from self._spreadsheet's
        cached worksheet metadata — no API call when the tab is known.
        """
        cached = self._url_to_row.get(url)
        if cached:
            tab_name, row_num = cached
            try:
                self._connect()
                if self._spreadsheet is None:
                    raise RuntimeError("spreadsheet handle missing after _connect")
                ws = self._spreadsheet.worksheet(tab_name)
                return ws, row_num
            except Exception as e:
                logger.debug(f"  cached-row lookup [{tab_name}]: {e} — falling back")
        return self.find_row_by_url(url)

    # ── Formatting ────────────────────────────────────────────

    def _apply_sheet_formatting(self, ws: gspread.Worksheet) -> None:
        """
        Apply professional formatting to a worksheet:
        - Dark navy header with white bold text, 40 px tall, frozen
        - Data rows: 21 px fixed height, text CLIPPED (never expands row)
        - Alternating row banding (white / light blue)
        - Per-column pixel widths
        """
        try:
            sid      = ws.id
            num_cols = len(HEADERS)
            # Grow-only: never resize below current row count or prior data is lost.
            # 2000 is the minimum baseline so brand-new tabs get a sensible buffer.
            current_rows = ws.row_count or 0
            max_rows = max(2000, current_rows)

            # Only call resize when we actually need to grow — sending a resize
            # equal to the current size still costs an API call, and a smaller
            # value would truncate existing data.
            if current_rows < max_rows or (ws.col_count or 0) < num_cols:
                ws.resize(rows=max_rows, cols=num_cols)

            requests = [
                # ── 1. Header row style ───────────────────────
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 0, "endRowIndex": 1,
                            "startColumnIndex": 0, "endColumnIndex": num_cols,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _HEADER_BG,
                                "textFormat": {
                                    "foregroundColor": _HEADER_TEXT,
                                    "bold": True,
                                    "fontSize": 9,
                                    "fontFamily": "Arial",
                                },
                                "wrapStrategy": "WRAP",
                                "verticalAlignment": "MIDDLE",
                                "horizontalAlignment": "CENTER",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,"
                                  "wrapStrategy,verticalAlignment,horizontalAlignment)",
                    }
                },
                # ── 2. Header row height: 40 px ───────────────
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "ROWS",
                            "startIndex": 0, "endIndex": 1,
                        },
                        "properties": {"pixelSize": 40},
                        "fields": "pixelSize",
                    }
                },
                # ── 3. Data rows fixed height: 21 px ─────────
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "ROWS",
                            "startIndex": 1, "endIndex": max_rows,
                        },
                        "properties": {"pixelSize": 21},
                        "fields": "pixelSize",
                    }
                },
                # ── 4. All data cells: CLIP wrap ──────────────
                #    This is the key fix — text never expands row height
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 1, "endRowIndex": max_rows,
                            "startColumnIndex": 0, "endColumnIndex": num_cols,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "wrapStrategy": "CLIP",
                                "verticalAlignment": "MIDDLE",
                                "textFormat": {
                                    "fontSize": 9,
                                    "fontFamily": "Arial",
                                },
                            }
                        },
                        "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,textFormat)",
                    }
                },
                # ── 5. Freeze header row ──────────────────────
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sid,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
            ]

            # ── 6. Alternating row banding ────────────────────
            # Remove existing banding first to avoid duplicates
            try:
                sheet_info = self._spreadsheet.fetch_sheet_metadata()
                for s in sheet_info.get('sheets', []):
                    if s['properties']['sheetId'] == sid:
                        for br in s.get('bandedRanges', []):
                            requests.insert(0, {
                                "deleteBanding": {"bandedRangeId": br['bandedRangeId']}
                            })
            except Exception:
                pass

            requests.append({
                "addBanding": {
                    "bandedRange": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 1,
                            "endRowIndex": max_rows,
                            "startColumnIndex": 0,
                            "endColumnIndex": num_cols,
                        },
                        "rowProperties": {
                            "firstBandColor":  _ROW_ODD,
                            "secondBandColor": _ROW_EVEN,
                        },
                    }
                }
            })

            # ── 7. Column widths ──────────────────────────────
            for col_idx, (_, px_width) in enumerate(COLUMNS):
                requests.append({
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "COLUMNS",
                            "startIndex": col_idx,
                            "endIndex": col_idx + 1,
                        },
                        "properties": {"pixelSize": px_width},
                        "fields": "pixelSize",
                    }
                })

            self._spreadsheet.batch_update({"requests": requests})
            logger.info(f"  Formatting applied to tab: {ws.title}")

        except Exception as e:
            logger.warning(f"  Sheet formatting failed (non-critical): {e}")

    # ── Public API ────────────────────────────────────────────

    def _get_tab_name(self, publication_date: int) -> str:
        return config.PUBLICATION_DATE_TABS.get(publication_date, f'{publication_date} Days')

    def write_property(self, prop: dict, publication_date: int) -> bool:
        """Write a single property row to the correct sheet tab.

        Dedup guard: if the property URL is already present in the tab (seeded
        from the sheet on first use + tracked across this session), skip the
        append and return True. Returning True is intentional — it makes the
        controller treat the property as 'written' so it gets added to KVK
        storage, closing the loop that previously could leave a stale dup.

        Retry policy:
          - Google API quota errors (429 / RESOURCE_EXHAUSTED): up to 4
            attempts with exponential backoff (5s, 15s, 45s) so long runs
            survive the 60-write/min/project cap.
          - Other transient errors (token expiry, network blip,
            half-connected client): force_reconnect + retry once.
        """
        import time as _time
        attempts = 4
        backoff = [0, 5, 15, 45]  # seconds before attempts 1..4

        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            if backoff[attempt - 1] > 0:
                _time.sleep(backoff[attempt - 1])
            try:
                return self._write_property_once(prop, publication_date)
            except Exception as e:
                last_exc = e
                msg = str(e).lower()
                is_quota = (
                    '429' in msg
                    or 'quota' in msg
                    or 'rate' in msg
                    or 'resource_exhausted' in msg
                )
                if is_quota and attempt < attempts:
                    logger.warning(
                        f"  Sheets quota hit (attempt {attempt}/{attempts}) — "
                        f"backing off {backoff[attempt]}s: {e}"
                    )
                    continue
                if attempt < attempts:
                    logger.warning(
                        f"  Sheets write transient error (attempt {attempt}/{attempts}) — "
                        f"forcing reconnect: {e}"
                    )
                    self._force_reconnect()
                    continue
                logger.error(f"  ✗ Sheets write failed after {attempt} attempts: {e}")
                return False
        return False

    # Append-side auto-grow: when the tab's free row buffer drops below this,
    # we extend the sheet by _ROW_GROW_CHUNK rows so append_row never silently
    # caps out. 100 is small enough to amortize the add_rows API call across
    # many appends, large enough to absorb a burst of concurrent writes.
    _ROW_GROW_HEADROOM = 100
    _ROW_GROW_CHUNK = 1000

    def _ensure_row_capacity(self, ws: gspread.Worksheet, tab_name: str) -> None:
        """Extend ws by _ROW_GROW_CHUNK rows when the used-row count gets
        within _ROW_GROW_HEADROOM of the worksheet's total row count. Cheap
        in steady state (col_values is cached by the seeded URL set size)
        and never shrinks.
        """
        try:
            used = len(self._tab_urls.get(tab_name, set())) + 1  # +1 for header
            total = ws.row_count or 0
            if total - used <= self._ROW_GROW_HEADROOM:
                ws.add_rows(self._ROW_GROW_CHUNK)
                logger.info(
                    f"  Sheets [{tab_name}]: grew capacity by {self._ROW_GROW_CHUNK} "
                    f"rows (used={used}, total was {total})"
                )
        except Exception as e:
            logger.warning(f"  Sheets [{tab_name}]: capacity check failed: {e}")

    def _write_property_once(self, prop: dict, publication_date: int) -> bool:
        tab_name = self._get_tab_name(publication_date)
        try:
            ws = self._get_or_create_worksheet(tab_name)
            self._ensure_row_capacity(ws, tab_name)

            url = (prop.get('url', '') or '').strip()
            if url and url in self._tab_urls.get(tab_name, set()):
                logger.info(f"  Sheets [{tab_name}]: URL already present — skipping duplicate: {url}")
                return True

            images_joined = ', '.join(prop.get('photo_urls', []))

            row = [
                date.today().isoformat(),
                prop.get('url', ''),
                prop.get('address', ''),
                prop.get('listed_since', ''),
                prop.get('days_on_market', '') or '',
                prop.get('asking_price', '') or '',
                # Valuation cells — filled by valuation worker (Walter-free)
                prop.get('woz_value', ''),
                prop.get('suggested_bid', ''),
                '',                                # Bidding Price — EMPTY for user
                prop.get('price_per_m2', '') or '',
                prop.get('living_area', '') or '',
                prop.get('plot_area', '') or '',
                prop.get('rooms', '') or '',
                prop.get('bedrooms', '') or '',
                prop.get('construction_year', '') or '',
                prop.get('property_type', ''),
                prop.get('energielabel', ''),
                prop.get('heating', ''),
                prop.get('insulation', ''),
                prop.get('maintenance_inside', ''),
                prop.get('maintenance_outside', ''),
                prop.get('garden', ''),
                prop.get('garden_orientation', ''),
                prop.get('parking', ''),
                prop.get('vve_contribution', ''),
                prop.get('erfpacht', ''),
                prop.get('acceptance', ''),
                prop.get('description', ''),
                images_joined,
                prop.get('agency_name', ''),
                prop.get('agency_phone', ''),
                prop.get('agency_email', ''),
                prop.get('agency_website', ''),
            ]

            # include_values_in_response=True so we can parse the row
            # number Sheets actually assigned (avoids racing on a local
            # counter when 3 workers append concurrently). Falls back to
            # the old find_row_by_url path on the back-write side if the
            # response shape changes.
            append_resp = ws.append_row(
                row,
                value_input_option='USER_ENTERED',
                include_values_in_response=True,
            )
            # Track the URL so we never append it again this session.
            if url:
                self._tab_urls.setdefault(tab_name, set()).add(url)
                # Cache the assigned row so back-writes can skip the
                # 6-tab scan in find_row_by_url. updatedRange looks
                # like 'TabName!A51:AG51' — grab the first digit run.
                try:
                    rng = (append_resp or {}).get("updates", {}).get("updatedRange", "")
                    m = self._UPDATED_RANGE_RE.search(rng or "")
                    if m:
                        row_num = int(m.group(2))
                        with self._url_to_row_lock:
                            self._url_to_row[url] = (tab_name, row_num)
                except Exception as e:
                    logger.debug(f"  url→row cache update failed: {e}")
            logger.info(
                f"  ✓ Sheets [{tab_name}]: {prop.get('address', prop.get('id', '?'))}"
            )
            return True

        except Exception:
            # Bubble up so the outer write_property can decide to reconnect+retry.
            raise

    def write_properties(self, properties: list, publication_date: int) -> int:
        written = 0
        for prop in properties:
            if self.write_property(prop, publication_date):
                written += 1
        return written

    # ── Valuation back-write ──────────────────────────────────

    # Column letters for the post-Walter, post-Confidence layout (33 cols).
    # G=WOZ, H=Suggested Bid, I=Bidding Price (HUMAN, never written).
    # No Bid Confidence column — confidence still computed for logging only.
    _VAL_COL_WOZ        = 'G'   # 7 — WOZ Value
    _VAL_COL_SUGGESTED  = 'H'   # 8 — Suggested Bid
    _VAL_COL_BIDDING    = 'I'   # 9 — Bidding Price (HUMAN, empty)
    _IDX_WOZ            = 6     # 0-based index for "is this row valued yet?" check
    _IDX_WALTER         = 6     # back-compat alias

    def find_row_by_url(self, url: str) -> Optional[tuple]:
        """Locate a property row across all tabs by its Funda URL (col B).
        Returns (worksheet, row_number) or None.
        """
        self._connect()
        for ws in self._spreadsheet.worksheets():
            try:
                col_b = ws.col_values(2)   # Property URL column
            except Exception:
                continue
            for idx, val in enumerate(col_b, start=1):
                if val and val.strip() == url.strip():
                    return ws, idx
        return None

    def delete_row_by_url(self, url: str) -> bool:
        """Delete the sheet row matching `url` (across all tabs). Returns
        True if a row was deleted. Also evicts the URL from the in-memory
        caches so a later re-scrape can re-add it cleanly."""
        loc = self._lookup_row(url)
        if loc is None:
            loc = self.find_row_by_url(url)
        if loc is None:
            return False
        ws, row_num = loc
        ws.delete_rows(row_num)
        # Cache hygiene: drop the URL + invalidate row cache for that tab,
        # since every row below the deleted one shifted up by 1.
        try:
            with self._url_to_row_lock:
                self._url_to_row.pop(url, None)
                # row numbers for this tab are now stale → drop them all
                stale = [u for u, (t, _) in self._url_to_row.items() if t == ws.title]
                for u in stale:
                    self._url_to_row.pop(u, None)
            if ws.title in self._tab_urls:
                self._tab_urls[ws.title].discard(url)
        except Exception:
            pass
        return True

    def list_pending_valuations(self) -> List[dict]:
        """Return rows where Walter Play-it-Safe (col AF) is empty.
        Each item: {tab, row, url, address, asking_price, days_on_market}.
        """
        self._connect()
        pending: List[dict] = []
        for ws in self._spreadsheet.worksheets():
            try:
                values = ws.get_all_values()
            except Exception as e:
                logger.warning(f"  Could not read {ws.title}: {e}")
                continue
            if len(values) < 2:
                continue
            for row_idx, row in enumerate(values[1:], start=2):
                # Pad row to expected width
                row = row + [''] * (len(HEADERS) - len(row))
                url = row[1]
                if not url:
                    continue
                walter_cell = row[self._IDX_WALTER] if len(row) > self._IDX_WALTER else ''
                if walter_cell.strip():
                    continue   # already valued
                pending.append({
                    'tab':             ws.title,
                    'row':             row_idx,
                    'url':             url,
                    'address':         row[2],
                    'listed_since':    row[3],
                    'days_on_market':  row[4],
                    'asking_price':    row[5],
                    # postcode/house_number not stored in the sheet — the
                    # valuation pass re-derives them from the property page
                    # via Walter (which already needs the full address).
                })
        logger.info(f"Found {len(pending)} pending valuations across all tabs")
        return pending

    def update_valuation_row(self, url: str, valuation: dict, find_retries: int = 3) -> bool:
        """Back-write valuation cells for the row matching `url`.

        Writes only G:H so the human-controlled Bidding Price column (I) is
        NEVER touched:
            G:H → WOZ Value, Suggested Bid
        `valuation` keys: woz_value, suggested_bid.
        (bid_confidence is no longer written to the sheet — kept in logs only.)
        """
        import time
        loc = None
        for attempt in range(1, find_retries + 1):
            loc = self._lookup_row(url)
            if loc is not None:
                break
            if attempt < find_retries:
                logger.debug(
                    f"  Valuation back-write: URL not yet visible in sheet "
                    f"(try {attempt}/{find_retries}) — waiting 3s..."
                )
                time.sleep(3)
        if loc is None:
            logger.warning(
                f"  ✗ Valuation back-write: URL still not found in any tab "
                f"after {find_retries} retries: {url}"
            )
            return False
        ws, row_num = loc
        ok = self._batch_update_with_backoff(
            ws,
            [{
                'range':  f'{self._VAL_COL_WOZ}{row_num}:{self._VAL_COL_SUGGESTED}{row_num}',
                'values': [[
                    valuation.get('woz_value', '')      or '',
                    valuation.get('suggested_bid', '')  or '',
                ]],
            }],
            label=f"Valuation [{ws.title} row {row_num}]",
        )
        if ok:
            logger.info(f"  ✓ Valuation written [{ws.title} row {row_num}]: {url}")
        return ok

    def update_bidding_price(self, url: str, bidding_price: str) -> bool:
        """Write the human-entered Bidding Price (col I) for the row matching `url`.

        Isolated from the scraper's valuation flow — only called when a
        user edits a property's bidding price from the dashboard.
        Returns True on success, False if the URL is not present yet.
        """
        loc = self._lookup_row(url)
        if loc is None:
            logger.warning(f"  ✗ Bidding back-write: URL not found in any tab: {url}")
            return False
        ws, row_num = loc
        ok = self._batch_update_with_backoff(
            ws,
            [{
                'range': f'{self._VAL_COL_BIDDING}{row_num}',
                'values': [[bidding_price or '']],
            }],
            label=f"Bidding [{ws.title} row {row_num}]",
        )
        if ok:
            logger.info(f"  ✓ Bidding price written [{ws.title} row {row_num}]: {bidding_price}")
        return ok

    def update_bidding_formula(self, url: str) -> bool:
        """Write a per-row 20%-off formula to col I for the row matching `url`.

        Used by sheet_sync on freshly-scraped rows so the spreadsheet
        does the math (zero CPU + zero per-row API quota on our side
        — single batch call writes one cell of formula text).

        =IF(F{row}="", "", ROUND(F{row}*0.80))
        """
        loc = self._lookup_row(url)
        if loc is None:
            logger.warning(f"  ✗ Bidding formula back-write: URL not found: {url}")
            return False
        ws, row_num = loc
        ask_col = 'F'  # Asking Price (€) is the 6th column.
        formula = f'=IF({ask_col}{row_num}="","",ROUND({ask_col}{row_num}*0.80))'
        ok = self._batch_update_with_backoff(
            ws,
            [{
                'range': f'{self._VAL_COL_BIDDING}{row_num}',
                'values': [[formula]],
            }],
            label=f"Bidding-formula [{ws.title} row {row_num}]",
        )
        if ok:
            logger.info(f"  ✓ Bidding formula written [{ws.title} row {row_num}]: {url}")
        return ok

    def _batch_update_with_backoff(self, ws, requests: list, label: str) -> bool:
        """Run ws.batch_update with the same retry / backoff policy as
        write_property: 4 attempts with 0/5/15/45s sleeps; on quota errors
        we wait, on other transient errors we force-reconnect and retry.
        """
        import time as _time
        backoff = [0, 5, 15, 45]
        for attempt in range(1, len(backoff) + 1):
            if backoff[attempt - 1] > 0:
                _time.sleep(backoff[attempt - 1])
            try:
                ws.batch_update(requests, value_input_option='USER_ENTERED')
                return True
            except Exception as e:
                msg = str(e).lower()
                is_quota = (
                    '429' in msg
                    or 'quota' in msg
                    or 'rate' in msg
                    or 'resource_exhausted' in msg
                )
                if is_quota and attempt < len(backoff):
                    logger.warning(
                        f"  {label}: quota hit (attempt {attempt}) — backing off {backoff[attempt]}s"
                    )
                    continue
                if attempt < len(backoff):
                    logger.warning(
                        f"  {label}: transient error (attempt {attempt}) — forcing reconnect: {e}"
                    )
                    self._force_reconnect()
                    continue
                logger.error(f"  ✗ {label} failed after {attempt} attempts: {e}")
                return False
        return False

    def clear_all_data_rows(self) -> None:
        """Wipe every data row (row 2 onwards) on every tab — keeps headers.
        Called at the start of a fresh run so each run produces a clean sheet
        with no carry-over from previous runs."""
        self._connect()
        for ws in self._spreadsheet.worksheets():
            try:
                rows = ws.row_count
                cols = ws.col_count
                if rows < 2:
                    continue
                last_col = gspread.utils.rowcol_to_a1(1, cols).rstrip('1')
                ws.batch_clear([f"A2:{last_col}{rows}"])
                logger.info(f"  Cleared data rows on tab: {ws.title}")
            except Exception as e:
                logger.warning(f"  Could not clear tab {ws.title}: {e}")
        # In-memory URL sets are now stale — drop them so fresh writes work.
        self._tab_urls.clear()

    def reformat_all_tabs(self) -> None:
        """Force re-apply formatting to every existing sheet tab."""
        self._connect()
        self._formatted_sheets.clear()
        for ws in self._spreadsheet.worksheets():
            self._apply_sheet_formatting(ws)
            logger.info(f"  Reformatted tab: {ws.title}")

    def get_sheet_url(self) -> str:
        return config.GOOGLE_SHEETS_URL
