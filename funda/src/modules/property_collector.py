"""
Property Collector Module — Date-Range Aware

Navigates funda.nl search listing pages sorted oldest-first (sort=date_up),
extracts property IDs grouped by their listing date from the search page
date headers (e.g. "Vrijdag 6 maart"), and collects only properties
within the configured date range.

Smart navigation:
  - Binary search to jump directly to the first page of the target date range
  - Sequential collection within the range
  - Stops when the date goes past the range end
  - Extracts listing date from search page headers (no need to visit each property)

Date header structure on funda (sort=date_up):
  <div class="font-semibold mb-4">Vrijdag 6 maart</div>
  ...property cards for that day...
  <div class="font-semibold mb-4">Zaterdag 7 maart</div>
  ...property cards for that day...

  Today is shown as "Vandaag" instead of a date string.
  A single search page can have MULTIPLE date headers when properties
  span two days (transition pages).
"""
import json
import re
import time
import random
import urllib.parse
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
from ..utils.logger import setup_logger

logger = setup_logger('funda.collector')


class CaptchaBlockedException(Exception):
    """Raised when captcha blocks collection and cannot be auto-solved."""
    pass


# Regex to extract the 8-digit funda object ID from a detail URL
FUNDA_ID_PATTERN = re.compile(r'/(\d{7,10})/?(?:\?|$)')

# Dutch month names -> month number
DUTCH_MONTHS = {
    'januari': 1, 'februari': 2, 'maart': 3, 'april': 4,
    'mei': 5, 'juni': 6, 'juli': 7, 'augustus': 8,
    'september': 9, 'oktober': 10, 'november': 11, 'december': 12,
}

# Date range configuration: days_option -> (start_days_ago, end_days_ago)
DATE_RANGES = {
    5:  (7, 3),     # 3-7 days ago
    10: (12, 8),    # 8-12 days ago
    15: (17, 13),   # 13-17 days ago
    30: (30, 25),   # 25-30 days ago
    31: (9999, 31), # 31+ days ago (everything older than 30 days)
}


def _parse_dutch_date(text: str, reference_year: int = None) -> Optional[date]:
    """
    Parse a Dutch date header like 'Vrijdag 6 maart' into a date object.
    Returns today's date for 'Vandaag', yesterday for 'Gisteren'.
    """
    text = text.strip()

    if text.lower() == 'vandaag':
        return date.today()

    if text.lower() == 'gisteren':
        return date.today() - timedelta(days=1)

    # Pattern: "Vrijdag 6 maart" -> day=6, month=maart
    match = re.match(r'(?:\w+)\s+(\d{1,2})\s+(\w+)', text)
    if not match:
        return None

    day_num = int(match.group(1))
    month_name = match.group(2).lower()
    month_num = DUTCH_MONTHS.get(month_name)

    if not month_num:
        return None

    year = reference_year or date.today().year
    try:
        d = date(year, month_num, day_num)
        # If parsed date is in the future, it's likely last year
        if d > date.today():
            d = date(year - 1, month_num, day_num)
        return d
    except ValueError:
        return None


def _date_to_dutch(d: date) -> str:
    """Convert a date to Dutch format for display, e.g. '6 maart 2026'."""
    month_names = {
        1: 'januari', 2: 'februari', 3: 'maart', 4: 'april',
        5: 'mei', 6: 'juni', 7: 'juli', 8: 'augustus',
        9: 'september', 10: 'oktober', 11: 'november', 12: 'december',
    }
    return f"{d.day} {month_names[d.month]} {d.year}"


class PropertyCollector:
    """
    Collects property IDs from funda.nl search result pages.

    Date-range aware: uses search page date headers to collect only
    properties within the configured date range. Uses binary search
    to quickly navigate to the target pages.

    Each collected item is a dict: {id, url, address, listed_since}
    """

    def __init__(
        self,
        browser,
        search_url: str,
        target_count: int = 99999,
        min_page_delay: float = 1.5,
        max_page_delay: float = 3.0,
        on_progress=None,
        stop_event=None,
        date_range: Tuple[int, int] = None,
    ):
        self.browser = browser
        self.search_url = search_url
        self.target_count = target_count
        self.min_page_delay = min_page_delay
        self.max_page_delay = max_page_delay
        self.on_progress = on_progress
        self._stop_event = stop_event

        # Date range (days ago): start_days_ago..end_days_ago
        # e.g. (7, 3) means collect from 7 days ago to 3 days ago
        if date_range:
            self.start_days_ago = date_range[0]  # oldest (=largest number)
            self.end_days_ago = date_range[1]      # newest (=smallest number)
        else:
            self.start_days_ago = 7
            self.end_days_ago = 3

        today = date.today()
        self.target_start_date = today - timedelta(days=self.start_days_ago)
        self.target_end_date = today - timedelta(days=self.end_days_ago)

        # In-memory cache of collected properties
        self.collected: List[dict] = []
        self._seen_ids: set = set()

        # Total search results found on funda
        self.total_search_results: int = 0

        # Track the total page count
        self._total_pages: int = 0

        # Track last successfully processed page (for resume after captcha)
        self._last_page: int = 0

    def _should_stop(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    # --- Public API -----------------------------------------------

    @property
    def collected_kvk(self) -> List[str]:
        return [item["id"] for item in self.collected]

    def collect_kvk_numbers(self, output_queue=None, kvk_storage=None, queued_ids=None,
                            resume_from_page=None, prior_storage_snapshot=None) -> List[str]:
        """
        Main entry point -- date-range aware collection.

        1. Warm up browser, navigate to search
        2. Binary search to find the first page of the target date range
        3. Sequentially collect properties within the date range
        4. Stop when the date goes past the range end

        Args:
            queued_ids: shared set of IDs already queued (persists across retries)
            resume_from_page: skip binary search and start from this page (for captcha retries)
            prior_storage_snapshot: set of KVK ids that were ALREADY in storage when
                this session started. Properties matching this set count as
                duplicate_in_storage. Properties added to storage by THIS session's
                workers are excluded — they get caught by `queued_ids` instead.
        """
        if kvk_storage is None:
            from funda.src.modules.kvk_storage import get_kvk_storage
            kvk_storage = get_kvk_storage()
        if queued_ids is None:
            queued_ids = set()
        # Snapshot what was in storage at session start, so we don't miscount
        # properties scraped by THIS session's workers as "duplicates".
        if prior_storage_snapshot is None:
            try:
                prior_storage_snapshot = set(kvk_storage.get_all())
            except Exception:
                prior_storage_snapshot = set()

        logger.info("=" * 60)
        logger.info(f"  STEP 1 -- Date-Range Collection")
        logger.info(f"  Target: {_date_to_dutch(self.target_start_date)} -> {_date_to_dutch(self.target_end_date)}")
        logger.info(f"  ({self.start_days_ago} days ago -> {self.end_days_ago} days ago)")
        logger.info("=" * 60)

        # 1. Warm up
        logger.info("  Warming up -- visiting funda.nl homepage...")
        self.browser.navigate_to("https://www.funda.nl/")
        self._smart_wait()
        if self._should_stop():
            return []

        self.browser.accept_cookies(timeout=8)
        time.sleep(random.uniform(1, 2))
        if self._should_stop():
            return []

        # 2. Navigate to search page (page 1) to get total results
        #    Retry up to 3 times with increasing cooldown if captcha blocks us
        search_loaded = False
        for attempt in range(3):
            if self._should_stop():
                return []
            if attempt > 0:
                cooldown = 60 * attempt  # 60s, 120s
                logger.info(f"  Retry {attempt}/2 — waiting {cooldown}s before retrying search page...")
                time.sleep(cooldown)
                # Browse homepage again before retry
                self.browser.navigate_to("https://www.funda.nl/")
                self._smart_wait()
                self.browser.accept_cookies(timeout=5)
                time.sleep(random.uniform(2, 4))

            logger.info("  Navigating to search page...")
            self.browser.navigate_to(self.search_url)
            self._smart_wait()

            if self.browser.is_captcha_page():
                logger.warning("reCAPTCHA challenge detected!")
                if not self.browser.wait_for_captcha_solved(timeout=30):
                    logger.warning("reCAPTCHA not solved — will retry after cooldown.")
                    continue
                self._smart_wait()

            search_loaded = True
            break

        if not search_loaded:
            logger.error("reCAPTCHA not solved after 3 attempts — cannot continue.")
            raise CaptchaBlockedException("reCAPTCHA blocked collection after 3 attempts")

        self.browser.accept_cookies(timeout=5)
        time.sleep(random.uniform(0.5, 1))

        self._extract_total_results()
        skipped_in_storage = 0
        skipped_already_queued = 0
        if self.total_search_results > 0 and self.on_progress:
            self.on_progress(0, 0, self.total_search_results, 0, skipped_in_storage, skipped_already_queued)

        # Calculate total pages
        self._total_pages = max(1, (self.total_search_results + 14) // 15)
        logger.info(f"  Total results: {self.total_search_results:,} (~{self._total_pages} pages)")

        # 3. Binary search to find the start page of target date range
        #    (skip if resuming from a known page after captcha)
        if resume_from_page:
            start_page = resume_from_page
            logger.info(f"  Resuming collection from page {start_page} (captcha retry)")
        else:
            start_page = self._find_date_range_start_page()
            if start_page is None:
                logger.warning("  Could not find target date range in search results!")
                return []

            logger.info(f"  Binary search found target range starting at page {start_page}")

            # 4. Go back a few pages to be safe (catch boundary properties)
            start_page = max(1, start_page - 2)
            logger.info(f"  Starting collection from page {start_page} (with 2-page safety margin)")

        # 6. Sequential collection within the date range
        queued_count = 0
        page_number = start_page
        self._last_page = start_page  # Track for resume on captcha
        consecutive_empty = 0
        past_range_count = 0
        no_date_header_streak = 0   # detect broken date-header HTML
        max_pages = self._total_pages + 10

        # Navigate to start page
        if start_page > 1:
            url = self._build_page_url(start_page)
            logger.info(f"  Jumping to page {start_page}...")
            self.browser.navigate_to(url)
            self._smart_wait()

            if self.browser.is_captcha_page():
                logger.warning("reCAPTCHA after jump!")
                if not self.browser.wait_for_captcha_solved(timeout=20):
                    raise CaptchaBlockedException("reCAPTCHA blocked after page jump")
                self._smart_wait()

        while page_number <= max_pages:
            if self._should_stop():
                logger.info("  Collection stopped by user")
                break

            if page_number % 5 == 0 or page_number == start_page:
                logger.info(
                    f"--- Page {page_number} | Collected: {len(self.collected)}"
                    f" | Queued: {queued_count} ---"
                )

            # Extract date headers and properties from this page
            before_count = len(self.collected)
            page_date, new_count, date_status = self._extract_properties_with_dates()

            # ── Guard: detect broken date-header HTML ──────────────
            # If the page has properties but NO parseable date header, the
            # date filter falls through to "in_range" (it can't tell), which
            # would make the collector queue EVERY property on EVERY page —
            # a runaway scrape. If this happens on several pages in a row,
            # Funda has changed their date-header markup. Stop cleanly with
            # a clear error instead of walking all ~1500 pages.
            if date_status != 'empty' and page_date is None:
                no_date_header_streak += 1
                if no_date_header_streak >= 5:
                    raise RuntimeError(
                        f"Date-header parsing broke: 5 consecutive pages "
                        f"({page_number-4}..{page_number}) had properties but "
                        f"no parseable date header. Funda likely changed their "
                        f"HTML — the date filter is no longer reliable. "
                        f"Collection halted to avoid a runaway scrape. "
                        f"Fix: update the date-header regex in "
                        f"_extract_first_date_header / _extract_properties_with_dates."
                    )
            else:
                no_date_header_streak = 0

            # Stream new properties to work queue (dedup against KVK + already-queued set)
            if output_queue is not None and new_count > 0:
                new_items = self.collected[before_count:]
                for item in new_items:
                    if item['id'] in queued_ids:
                        skipped_already_queued += 1
                        continue
                    # Only count as "in storage" if it was already there at SESSION
                    # START. Properties this session's workers added to storage
                    # would be in queued_ids (caught above) — not double-counted.
                    if item['id'] in prior_storage_snapshot:
                        skipped_in_storage += 1
                        continue
                    output_queue.put(item)
                    queued_ids.add(item['id'])
                    queued_count += 1

            # Report progress
            if self.on_progress and page_number % 3 == 0:
                self.on_progress(
                    len(self.collected),
                    queued_count,
                    self.total_search_results,
                    page_number,
                    skipped_in_storage,
                    skipped_already_queued,
                )

            # Check date_status (semantics with sort=date_down, walking forward):
            # 'before' = all properties older than target_start_date (we've walked
            #            PAST the window — stop after a few of these)
            # 'in_range' = at least some properties are in range — collect & continue
            # 'after' = all properties newer than target_end_date (haven't reached
            #           window yet — keep advancing pages)
            # 'empty' = no properties found

            if date_status == 'before':
                past_range_count += 1
                logger.info(f"  Page {page_number}: past target date range (older than {_date_to_dutch(self.target_start_date)}) ({past_range_count}/3)")
                if past_range_count >= 3:
                    logger.info("  3 consecutive pages past range -- collection complete!")
                    break
            elif date_status == 'after':
                past_range_count = 0
            elif date_status == 'empty':
                consecutive_empty += 1
                if self.browser.is_captcha_page():
                    logger.warning("reCAPTCHA appeared!")
                    if not self.browser.wait_for_captcha_solved(timeout=20):
                        raise CaptchaBlockedException("reCAPTCHA blocked mid-collection")
                    self._smart_wait()
                    _, new_count, _ = self._extract_properties_with_dates()
                if consecutive_empty >= 3:
                    logger.info("  3 consecutive empty pages -- end of search results")
                    break
            else:
                consecutive_empty = 0
                past_range_count = 0

            # Navigate to next page
            self._last_page = page_number  # Track for resume on captcha
            page_number += 1
            next_url = self._build_page_url(page_number)
            self.browser.navigate_to(next_url)
            self._smart_wait()

            if self.browser.is_captcha_page():
                logger.warning(f"reCAPTCHA on page {page_number}!")
                if not self.browser.wait_for_captcha_solved(timeout=20):
                    raise CaptchaBlockedException(f"reCAPTCHA blocked on page {page_number}")
                self._smart_wait()

            # Delay between pages (interruptible)
            delay = random.uniform(self.min_page_delay, self.max_page_delay)
            for _ in range(int(delay * 2)):
                if self._should_stop():
                    break
                time.sleep(0.5)

        logger.info("=" * 60)
        logger.info(
            f"  Collection complete: {len(self.collected)} property IDs"
            f" from pages {start_page}-{page_number}"
            f" ({queued_count} queued for scraping)"
        )
        logger.info(f"  Date range: {_date_to_dutch(self.target_start_date)}"
                     f" -> {_date_to_dutch(self.target_end_date)}")
        logger.info("=" * 60)

        # Final progress report
        if self.on_progress:
            self.on_progress(
                len(self.collected),
                queued_count,
                self.total_search_results,
                page_number,
                skipped_in_storage,
                skipped_already_queued,
            )

        return self.collected_kvk

    # --- Binary search for target date range ----------------------

    def _find_date_range_start_page(self) -> Optional[int]:
        """
        Binary search through search results (sorted NEWEST-FIRST via
        sort=date_down) to find the first page containing properties from
        our target_end_date (the newest day in our window).

        With date_down: page 1 = today, higher page = older.
        We seek the smallest page number whose first listing is ≤ target_end_date.

        Page-date relation:
          page_date > target_end_date  → page is too NEW, go forward (higher page)
          page_date < target_start_date → page is too OLD, go back (lower page)
          target_start_date ≤ page_date ≤ target_end_date → in range
        """
        low = 1
        high = self._total_pages
        best_page = None

        logger.info(
            f"  Binary search for {_date_to_dutch(self.target_end_date)} "
            f"in pages 1-{high} (newest-first sort)..."
        )

        for iteration in range(12):
            if self._should_stop():
                return None

            mid = (low + high) // 2
            if mid < 1:
                mid = 1

            page_date = self._probe_page_date(mid)
            if page_date is None:
                logger.warning(f"    Probe p{mid}: no date found, trying p{mid+1}")
                page_date = self._probe_page_date(mid + 1)
                if page_date is None:
                    # Treat as 'too new' and advance
                    low = mid + 1
                    continue

            days_ago = (date.today() - page_date).days
            logger.info(f"    Probe p{mid}: {_date_to_dutch(page_date)} ({days_ago}d ago)")

            if page_date > self.target_end_date:
                # Page is NEWER than our window — go to higher pages (older)
                low = mid + 1
            elif page_date < self.target_start_date:
                # Page is OLDER than our window — go to lower pages (newer)
                high = mid - 1
            else:
                # In range — record and search BACKWARD for the FIRST page of
                # the window (the boundary nearest target_end_date)
                best_page = mid
                high = mid - 1

            if low > high:
                break

            time.sleep(random.uniform(1.0, 2.0))

        if best_page is None:
            best_page = low if low <= self._total_pages else self._total_pages

        return best_page

    def _probe_page_date(self, page_number: int) -> Optional[date]:
        """Navigate to a page and extract the first date header."""
        if page_number < 1 or page_number > self._total_pages:
            return None

        url = self._build_page_url(page_number)
        self.browser.navigate_to(url)
        self._smart_wait()

        if self.browser.is_captcha_page():
            logger.warning(f"  reCAPTCHA during binary search probe (p{page_number})!")
            if not self.browser.wait_for_captcha_solved(timeout=20):
                return None
            self._smart_wait()

        return self._extract_first_date_header()

    # --- NUXT JSON listing extraction (Funda 2026 DOM rewrite) ----
    # Funda removed the legacy `font-semibold mb-4` date headers and the
    # in-card date strings. The page now ships a flat-array JSON blob in a
    # `<script id="__NUXT_DATA__">` tag holding the full search state. Each
    # listing has `publish_date`, `id`, `object_detail_page_relative_url`,
    # and an `address` ref. We parse that blob instead of scraping markup.

    @staticmethod
    def _resolve_nuxt_ref(arr, ref):
        """Nuxt's flat-array format stores values by index. Helper resolves
        an int index into the actual value (one hop). Non-int returned as-is."""
        if isinstance(ref, int):
            try:
                return arr[ref]
            except (IndexError, TypeError):
                return None
        return ref

    def _extract_listings_from_nuxt(self, html: str) -> List[dict]:
        """Parse search-page NUXT_DATA blob into a list of listings.

        Returns list of dicts with keys: id, url, address, publish_date (date).
        Empty list on parse failure or when the blob has no listings.
        """
        m = re.search(
            r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.+?)</script>',
            html,
            re.S,
        )
        if not m:
            return []
        try:
            arr = json.loads(m.group(1))
        except Exception as e:
            logger.debug(f"  NUXT_DATA JSON parse failed: {e}")
            return []

        results: List[dict] = []
        seen_ids: set = set()
        for entry in arr:
            if not isinstance(entry, dict):
                continue
            url_ref = entry.get('object_detail_page_relative_url')
            id_ref = entry.get('id')
            pd_ref = entry.get('publish_date')
            addr_ref = entry.get('address')
            if url_ref is None or id_ref is None or pd_ref is None:
                continue

            url_v = self._resolve_nuxt_ref(arr, url_ref)
            id_v = self._resolve_nuxt_ref(arr, id_ref)
            pd_v = self._resolve_nuxt_ref(arr, pd_ref)

            if not isinstance(url_v, str) or '/detail/koop/' not in url_v:
                continue
            funda_id = str(id_v) if id_v is not None else None
            if not funda_id or funda_id in seen_ids:
                continue

            # Parse ISO publish_date (e.g. '2026-05-14T09:18:44.7889744+02:00')
            publish_date: Optional[date] = None
            if isinstance(pd_v, str):
                try:
                    # Trim sub-second precision Python <3.11 can't handle (>6 digits)
                    iso = re.sub(r'(\.\d{6})\d+', r'\1', pd_v)
                    publish_date = datetime.fromisoformat(iso).date()
                except Exception:
                    pass

            address_str = ''
            if isinstance(addr_ref, int):
                addr = self._resolve_nuxt_ref(arr, addr_ref)
                if isinstance(addr, dict):
                    street = self._resolve_nuxt_ref(arr, addr.get('street_name')) or ''
                    hn = self._resolve_nuxt_ref(arr, addr.get('house_number')) or ''
                    pc = self._resolve_nuxt_ref(arr, addr.get('postal_code')) or ''
                    city = self._resolve_nuxt_ref(arr, addr.get('city')) or ''
                    parts = []
                    if street or hn:
                        parts.append(f"{street} {hn}".strip())
                    if pc or city:
                        parts.append(f"{pc} {city}".strip())
                    address_str = ', '.join(p for p in parts if p)

            seen_ids.add(funda_id)
            results.append({
                'id': funda_id,
                'url': url_v,
                'address': address_str,
                'publish_date': publish_date,
            })
        return results

    def _extract_first_date_header(self) -> Optional[date]:
        """Return publish_date of the first listing on the current page (NUXT)."""
        try:
            html = self.browser.get_page_source()
            listings = self._extract_listings_from_nuxt(html)
            for lst in listings:
                if lst.get('publish_date'):
                    return lst['publish_date']
        except Exception as e:
            logger.debug(f"  Error extracting first publish_date: {e}")
        return None

    # --- Extract properties with date awareness -------------------

    def _extract_properties_with_dates(self) -> Tuple[Optional[date], int, str]:
        """
        Extract properties from current page (NUXT_DATA blob), associating
        each with its publish_date.

        Returns:
            (page_first_date, new_count, status)
            status: 'in_range', 'before', 'after', 'empty'
        """
        try:
            html = self.browser.get_page_source()
        except Exception:
            return (None, 0, 'empty')

        listings = self._extract_listings_from_nuxt(html)
        if not listings:
            return (None, 0, 'empty')

        # First listing's publish_date represents page-level date for the
        # collector's runaway-guard + binary-search probes.
        page_first_date = next(
            (l['publish_date'] for l in listings if l.get('publish_date')),
            None,
        )

        new_count = 0
        has_in_range = False
        has_before = False
        has_after = False

        for lst in listings:
            listing_date: Optional[date] = lst.get('publish_date')
            href = lst['url']
            funda_id = lst['id']
            address = lst.get('address') or self._extract_address_from_url(href)

            # Date-range gate
            if listing_date is not None:
                if listing_date < self.target_start_date:
                    has_before = True
                    continue
                if listing_date > self.target_end_date:
                    has_after = True
                    continue
                has_in_range = True
            else:
                # No date → treat as in-range; runaway guard upstream handles
                # the case where this happens for many pages in a row.
                has_in_range = True

            if funda_id in self._seen_ids:
                continue
            self._seen_ids.add(funda_id)

            listed_since = listing_date.strftime("%Y-%m-%d") if listing_date else ""
            full_url = href if href.startswith('http') else f"https://www.funda.nl{href}"

            self.collected.append({
                "id": funda_id,
                "url": full_url,
                "address": address,
                "listed_since": listed_since,
            })
            new_count += 1
            logger.debug(f"    + ID: {funda_id} | {address} | listed: {listed_since}")

        if has_in_range:
            status = 'in_range'
        elif has_after and not has_before:
            status = 'after'
        elif has_before and not has_after:
            status = 'before'
        elif has_after and has_before:
            status = 'after'
        else:
            status = 'empty'

        if new_count > 0:
            uniq_dates = sorted({l['publish_date'] for l in listings if l.get('publish_date')})
            dates_on_page = [_date_to_dutch(d) for d in uniq_dates]
            logger.info(f"  +{new_count} properties | Dates: {', '.join(dates_on_page)}")

        return (page_first_date, new_count, status)

    # --- URL building ---------------------------------------------

    def _build_page_url(self, page_number: int) -> str:
        """Build pagination URL for given page number."""
        parsed = urllib.parse.urlparse(self.search_url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if page_number > 1:
            params['page'] = [str(page_number)]
        elif 'page' in params:
            del params['page']
        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path,
             parsed.params, new_query, parsed.fragment)
        )

    # --- Helpers --------------------------------------------------

    def _extract_total_results(self) -> None:
        """Extract the total number of search results from the search page."""
        try:
            count_js = """
            var selectors = [
                '[data-test-id="result-count"]',
                '.search-result-header h1',
                '.search-output-result-count',
                'h1.font-semibold',
            ];
            for (var s of selectors) {
                var el = document.querySelector(s);
                if (el && el.textContent) return el.textContent;
            }
            var h1 = document.querySelector('h1');
            return h1 ? h1.textContent : '';
            """
            text = self.browser.execute_script(count_js) or ''

            match = re.search(r'([\d.]+)\s+(?:resulta|woning|koopwoning|huiz)', text, re.IGNORECASE)
            if match:
                count_str = match.group(1).replace('.', '')
                self.total_search_results = int(count_str)
                logger.info(f"  Total search results on funda: {self.total_search_results:,}")
                return

            html = self.browser.get_page_source()
            match = re.search(r'([\d.]+)\s+resultat', html, re.IGNORECASE)
            if match:
                count_str = match.group(1).replace('.', '')
                self.total_search_results = int(count_str)
                logger.info(f"  Total search results on funda: {self.total_search_results:,}")
                return

            page_match = re.findall(r'page=(\d+)', html)
            if page_match:
                max_page = max(int(p) for p in page_match)
                self.total_search_results = max_page * 15
                logger.info(f"  Estimated total results from pagination: ~{self.total_search_results:,}")
                return

            logger.debug("  Could not determine total search results count")
        except Exception as e:
            logger.debug(f"  Error extracting total results: {e}")

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extract numeric funda object ID from detail URL."""
        if not url:
            return None
        match = FUNDA_ID_PATTERN.search(url)
        if match:
            return match.group(1)
        path = urllib.parse.urlparse(url).path.rstrip('/')
        for segment in reversed(path.split('/')):
            if segment.isdigit() and 7 <= len(segment) <= 10:
                return segment
        return None

    def _extract_address_from_url(self, url: str) -> str:
        """Best-effort address extraction from the URL slug."""
        try:
            path = urllib.parse.urlparse(url).path.strip('/')
            parts = path.split('/')
            if len(parts) >= 5:
                return f"{parts[2]} / {parts[3]}"
            elif len(parts) >= 4:
                return parts[2]
        except Exception:
            pass
        return ""

    def _smart_wait(self, max_wait: int = 20) -> None:
        """Wait for page to fully load."""
        try:
            for _ in range(max_wait * 2):
                state = self.browser.execute_script("return document.readyState")
                if state == "complete":
                    time.sleep(1)
                    return
                time.sleep(0.5)
            logger.warning("Page did not reach 'complete' state in time")
        except Exception:
            time.sleep(2)
