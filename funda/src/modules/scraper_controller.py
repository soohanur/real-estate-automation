"""
Funda Scraper Controller — Pipelined

Architecture (v3 — Pipelined mode):
  Collector thread: paginates search results, streams new IDs into work_queue
  N worker threads: start after brief warmup, pull from the same queue
  Writer thread:    writes to Google Sheets from a write queue

  Collection and scraping run IN PARALLEL — total time ≈ max(collection, scraping)
  instead of collection + scraping sequentially.

Key optimizations:
  - Pipelined: workers start scraping while collection is still gathering IDs
  - Worker browsers persist — no open/close per batch
  - Thread-safe agency cache — same agency scraped only once across all workers
  - Reduced delays: 1-2s between properties
  - No cooldown between batches (batching eliminated)
"""
import time
import random
import logging
import threading
import queue
import shutil
from enum import Enum
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path

from funda.src.config import config
from funda.src.modules.browser_automation import BrowserAutomation
from funda.src.modules.property_collector import PropertyCollector, CaptchaBlockedException
from funda.src.modules.property_scraper import PropertyScraper
from funda.src.modules.agency_scraper import AgencyScraper
from funda.src.modules.excel_writer import ExcelWriter
from funda.src.modules.kvk_storage import get_kvk_storage
from funda.src.modules.sheets_writer import SheetsWriter
from funda.src.modules.valuation_engine import ValuationEngine
# WalterClient import removed — valuation is now Walter-free (distribution-based)

logger = logging.getLogger('funda.controller')


# ─────────────────────────────────────────────────────────────────
# Persistent run-state — lets a crashed-mid-run scrape resume from the
# page it stopped on, reusing the ORIGINAL KVK snapshot so the crashed
# run's own already-scraped properties aren't mis-counted as duplicates.
# ─────────────────────────────────────────────────────────────────
import json as _json
_RUN_STATE_FILE = Path(config.PROJECT_ROOT) / 'funda' / 'data' / 'run_state.json'
_RUN_STATE_MAX_AGE_SEC = 30 * 24 * 3600   # 30 days — auto-resume long-paused crashes
_run_state_lock = threading.Lock()


def _save_run_state(state: dict) -> None:
    try:
        _RUN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _run_state_lock:
            _RUN_STATE_FILE.write_text(_json.dumps(state))
    except Exception as e:
        logger.warning(f"Could not save run_state: {e}")


def _load_run_state() -> Optional[dict]:
    try:
        if not _RUN_STATE_FILE.exists():
            return None
        with _run_state_lock:
            return _json.loads(_RUN_STATE_FILE.read_text())
    except Exception as e:
        logger.warning(f"Could not load run_state: {e}")
        return None


def _update_run_state_field(key: str, value) -> None:
    st = _load_run_state()
    if st is None:
        return
    st[key] = value
    _save_run_state(st)


def _update_run_state_page(page: int) -> None:
    st = _load_run_state()
    if st is None:
        return
    # keep the max page seen so a retry that restarts earlier doesn't lose progress
    if page > st.get('last_page', 0):
        st['last_page'] = page
        _save_run_state(st)


def _clear_run_state() -> None:
    try:
        if _RUN_STATE_FILE.exists():
            _RUN_STATE_FILE.unlink()
    except Exception:
        pass


def maybe_resume_run() -> bool:
    """Called once on backend startup. If a run was in progress when the
    backend died (in_progress=True in run_state.json) and it's recent, restart
    that run resuming from the page it stopped on, reusing the original KVK
    snapshot. Returns True if a resume was kicked off.
    """
    st = _load_run_state()
    if not st or not st.get('in_progress'):
        return False
    age = time.time() - st.get('started_at', 0)
    if age > _RUN_STATE_MAX_AGE_SEC:
        logger.info(
            f"Found stale run_state (age {age/3600:.1f}h > "
            f"{_RUN_STATE_MAX_AGE_SEC/3600:.0f}h) — not auto-resuming, clearing."
        )
        _clear_run_state()
        return False
    pub_date  = st.get('publication_date', 5)
    last_page = st.get('last_page', 1)
    snapshot  = set(st.get('session_snapshot', []))
    resume_page = max(1, last_page - 2)
    logger.warning(
        f"Detected interrupted run (pub_date={pub_date}, last_page={last_page}, "
        f"age {age/60:.0f}min, snapshot {len(snapshot)} ids) — AUTO-RESUMING from "
        f"page {resume_page}."
    )
    try:
        start_scraper(
            publication_date=pub_date,
            resume_from_page=resume_page,
            resume_snapshot=snapshot,
        )
        return True
    except Exception as e:
        logger.error(f"Auto-resume failed: {e}")
        return False


def create_browser(profile_path=None, headless=False, profile_name='Default', implicit_wait=10, port=9222):
    """Factory function to create and start a browser instance."""
    browser = BrowserAutomation(
        profile_path=str(profile_path) if profile_path else None,
        profile_name=profile_name,
        headless=headless,
        implicit_wait=implicit_wait,
        port=port,
    )
    browser.start_browser()
    return browser


class ScraperStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class ScraperStats:
    """Real-time scraper statistics."""
    status: ScraperStatus = ScraperStatus.IDLE
    
    # Collection stats
    total_kvk_stored: int = 0
    kvk_collected_this_session: int = 0
    total_search_results: int = 0
    current_batch: int = 0
    
    # Scraping stats
    properties_scraped: int = 0
    properties_filtered: int = 0
    properties_failed: int = 0
    
    # Progress (overall: done / total_search_results)
    current_page: int = 0
    total_pages_scraped: int = 0
    batch_progress: int = 0
    
    # Collection real-time
    collection_status: str = ""  # "collecting" | "done" | "error"
    collection_page: int = 0
    ids_collected: int = 0
    ids_queued: int = 0
    duplicate_in_storage: int = 0
    duplicate_in_retry_queue: int = 0
    
    # Workers
    active_workers: int = 0
    
    # Output
    excel_files_created: int = 0
    sheets_written: int = 0
    valuations_written: int = 0
    valuations_failed: int = 0
    valuations_pending: int = 0
    valuations_fallback: int = 0   # used asking-based formula (Walter unavailable)
    
    # Timing
    start_time: float = 0.0
    elapsed_seconds: float = 0.0
    
    # Error
    last_error: str = ""
    
    # Recovery stats
    browser_restarts: int = 0
    consecutive_failures: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'status': self.status.value,
            'total_kvk_stored': self.total_kvk_stored,
            'kvk_collected_this_session': self.kvk_collected_this_session,
            'total_search_results': self.total_search_results,
            'current_batch': self.current_batch,
            'properties_scraped': self.properties_scraped,
            'properties_filtered': self.properties_filtered,
            'properties_failed': self.properties_failed,
            'current_page': self.current_page,
            'total_pages_scraped': self.total_pages_scraped,
            'batch_progress': self.batch_progress,
            'collection_status': self.collection_status,
            'collection_page': self.collection_page,
            'ids_collected': self.ids_collected,
            'ids_queued': self.ids_queued,
            'duplicate_in_storage': self.duplicate_in_storage,
            # `duplicate_in_retry_queue` is collector-internal noise (the same
            # property re-encountered after a collection-browser crash; only
            # queued once thanks to queued_ids dedup). It is NOT a real
            # duplicate, so we always report 0 to the API to keep the dashboard
            # 'Duplicate' counter equal to "matched KVK from prior sessions".
            'duplicate_in_retry_queue': 0,
            'active_workers': self.active_workers,
            'excel_files_created': self.excel_files_created,
            'sheets_written': self.sheets_written,
            'valuations_written': self.valuations_written,
            'valuations_failed': self.valuations_failed,
            'valuations_pending': self.valuations_pending,
            'valuations_fallback': self.valuations_fallback,
            'elapsed_seconds': self.elapsed_seconds,
            'last_error': self.last_error,
            'browser_restarts': self.browser_restarts,
            'consecutive_failures': self.consecutive_failures,
        }


class FundaController:
    """
    Main controller for Funda property scraper.
    
    Handles:
    - Start/Stop/Pause/Resume operations
    - Continuous scraping loop (collect → parallel scrape → repeat)
    - 3 parallel worker threads with separate browsers
    - Thread-safe Google Sheets writing via queue
    - Real-time progress updates
    """

    def __init__(
        self,
        publication_date: int = 5,
        on_progress: Optional[Callable[[ScraperStats], None]] = None,
        resume_from_page: Optional[int] = None,
        resume_snapshot: Optional[set] = None,
    ):
        self.publication_date = publication_date
        self.on_progress = on_progress
        # Resume support (set when a crashed run is being continued):
        #   resume_from_page  — skip binary search, start collection here
        #   resume_snapshot   — reuse the ORIGINAL run's KVK snapshot instead of
        #                       taking a fresh one (so the crashed run's own
        #                       already-scraped properties are NOT counted as
        #                       "duplicate_in_storage" — they're our own work)
        self._resume_from_page = resume_from_page
        self._resume_snapshot = resume_snapshot

        # Internal state
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Set by the overall-run watchdog to force a clean finalize → COMPLETED
        # (as opposed to the user pressing Stop → IDLE). Also sets _stop_event
        # so the collector/workers wind down, but the completion code reads
        # this flag to choose COMPLETED instead of IDLE.
        self._force_finalize = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        
        # Components
        self.browser = None
        self.collector = None
        self.kvk_storage = get_kvk_storage()
        
        # Stats
        self.stats = ScraperStats()
        self._stats_lock = threading.Lock()
        
        # ── Shared CAPTCHA coordination ───────────────────────
        # When ANY worker hits CAPTCHA, ALL workers stop + wipe + restart
        self._captcha_event = threading.Event()      # Signals "CAPTCHA detected"
        self._captcha_lock = threading.Lock()         # Prevents double-trigger
        self._captcha_reset_event = threading.Event() # Signals "restart complete, resume"

    # Funda capped global pagination at ~12,000 reachable listings (≈ last 8d
    # for date_down, ≈ 180d back for date_up). To reach 13-17 / 25-30 / 30+ day
    # buckets, we shrink the search scope with selected_area=<province> so each
    # query stays under the 12k cap. NL has 12 provinces; their union = full
    # Funda catalog. For shallow buckets (3-7d, 8-12d) the global URL still
    # works and is faster, so we keep it.
    _PROVINCE_AREAS = (
        "provincie-drenthe",
        "provincie-flevoland",
        "provincie-friesland",
        "provincie-gelderland",
        "provincie-groningen",
        "provincie-limburg",
        "provincie-noord-brabant",
        "provincie-noord-holland",
        "provincie-overijssel",
        "provincie-utrecht",
        "provincie-zeeland",
        "provincie-zuid-holland",
    )

    def _build_search_url_for_area(self, area: str) -> str:
        base = 'https://www.funda.nl/zoeken/koop'
        funda_pub_date = config.FUNDA_PUB_DATE_PARAM.get(self.publication_date, 30)
        if funda_pub_date == 0:
            return f'{base}?selected_area=["{area}"]&availability=["available"]&sort="date_down"'
        return f'{base}?selected_area=["{area}"]&publication_date={funda_pub_date}&availability=["available"]&sort="date_down"'

    @property
    def search_urls(self) -> list:
        """List of search URLs to walk in sequence.

        Shallow buckets (3-7d, 8-12d): single national URL — fast, fully
        reachable under Funda's 12k pagination cap.
        Deep buckets (13-17d, 25-30d, 30+d): per-province URLs so each query
        stays under the cap.
        """
        if self.publication_date in (5, 10):
            return [self._build_search_url_for_area("nl")]
        return [self._build_search_url_for_area(p) for p in self._PROVINCE_AREAS]

    @property
    def search_url(self) -> str:
        """Backward-compat: first URL only. New code should use search_urls."""
        urls = self.search_urls
        return urls[0] if urls else self._build_search_url_for_area("nl")

    def _update_stats(self, **kwargs):
        """Thread-safe stats update with overall progress calculation."""
        with self._stats_lock:
            for key, value in kwargs.items():
                if hasattr(self.stats, key):
                    setattr(self.stats, key, value)
            
            # Update elapsed time
            if self.stats.start_time > 0:
                self.stats.elapsed_seconds = time.time() - self.stats.start_time
            
            # Update total KVK count
            self.stats.total_kvk_stored = self.kvk_storage.count()
            
            # Overall progress — only meaningful AFTER collection has finished
            # (ids_queued grows during collection, so a mid-collection % would
            # yo-yo). Two-phase model:
            #   - scrape phase  : every queued property → scraped OR filtered OR failed
            #   - valuation phase: only properties that reach the sheet get valued
            #     (filtered ones do NOT — so the valuation target is sheets_written,
            #      not ids_queued. Using ids_queued*2 caps progress at <100% whenever
            #      there are filtered properties — that was the old 87% bug.)
            if self.stats.collection_status == "done" and self.stats.ids_queued > 0:
                scrape_done = (
                    self.stats.properties_scraped
                    + self.stats.properties_filtered
                    + self.stats.properties_failed
                )
                valuation_done = (
                    self.stats.valuations_written
                    + self.stats.valuations_failed
                )
                # scrape target = all queued; valuation target = rows actually written
                total_work = self.stats.ids_queued + max(1, self.stats.sheets_written)
                done = scrape_done + valuation_done
                self.stats.batch_progress = min(100, int(done / total_work * 100))
            else:
                # While collecting, show 0% — the dashboard label already
                # reads "Collecting page X" in this state.
                self.stats.batch_progress = 0
            
            # Notify callback
            if self.on_progress:
                try:
                    self.on_progress(self.stats)
                except Exception as e:
                    logger.error(f"Progress callback error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get current stats as dictionary."""
        with self._stats_lock:
            # Compute elapsed time dynamically
            if self.stats.start_time > 0 and self.stats.status in (ScraperStatus.RUNNING, ScraperStatus.PAUSED):
                self.stats.elapsed_seconds = time.time() - self.stats.start_time
            return self.stats.to_dict()

    def start(self) -> bool:
        """Start the scraping process in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Scraper is already running")
            return False

        self._stop_event.clear()
        self._force_finalize.clear()
        self._pause_event.set()
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        logger.info("Scraper started")
        return True

    def stop(self) -> bool:
        """Stop the scraping process — kills everything immediately."""
        if not self._thread or not self._thread.is_alive():
            logger.warning("Scraper is not running")
            return False

        self._update_stats(status=ScraperStatus.STOPPING)
        self._stop_event.set()
        self._pause_event.set()
        
        logger.info("Stop signal sent — waiting for threads to finish...")

        # Wait for the main thread (which joins all sub-threads) with a timeout
        self._thread.join(timeout=30)

        # Force-kill ALL Chrome processes (including collector) on full stop
        self._kill_all_chrome(include_collector=True)

        # Ensure status is IDLE after stop
        if self._thread and not self._thread.is_alive():
            self._update_stats(status=ScraperStatus.IDLE, active_workers=0)
            logger.info("Scraper fully stopped")
        else:
            # Thread didn't die in 30s — force status anyway
            self._update_stats(status=ScraperStatus.IDLE, active_workers=0)
            logger.warning("Scraper thread still alive after 30s timeout — status forced to IDLE")

        return True

    def _kill_all_chrome(self, include_collector=False):
        """Kill Chrome processes. By default only kills worker Chrome (port 9223+), not the collector (port 9222)."""
        import subprocess
        try:
            if include_collector:
                # Kill ALL Chrome — used when stopping scraper entirely
                subprocess.run(
                    ['pkill', '-9', '-f', 'chrome'],
                    capture_output=True, timeout=10,
                )
                logger.info("All Chrome processes killed (including collector)")
            else:
                # Only kill worker Chrome processes (port 9223+)
                # This preserves the collector browser on port 9222
                for i in range(config.WORKER_COUNT):
                    port = 9223 + i
                    subprocess.run(
                        ['pkill', '-9', '-f', f'remote-debugging-port={port}'],
                        capture_output=True, timeout=5,
                    )
                logger.info(f"Worker Chrome processes killed (ports 9223-{9223 + config.WORKER_COUNT - 1})")
        except Exception as e:
            logger.warning(f"Failed to kill Chrome processes: {e}")

    def pause(self) -> bool:
        """Pause the scraping process."""
        if not self._thread or not self._thread.is_alive():
            return False
        if self.stats.status != ScraperStatus.RUNNING:
            return False
        self._pause_event.clear()
        self._update_stats(status=ScraperStatus.PAUSED)
        logger.info("Scraper paused")
        return True

    def resume(self) -> bool:
        """Resume the scraping process."""
        if self.stats.status != ScraperStatus.PAUSED:
            return False
        self._pause_event.set()
        self._update_stats(status=ScraperStatus.RUNNING)
        logger.info("Scraper resumed")
        return True

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _check_stop(self) -> bool:
        return self._stop_event.is_set()

    def _wait_if_paused(self) -> bool:
        while not self._pause_event.is_set():
            if self._check_stop():
                return True
            time.sleep(0.1)
        return self._check_stop()

    def _restart_browser(self):
        """Safely restart the collection browser."""
        logger.info("Restarting browser...")
        if self.browser:
            try:
                self.browser.close_browser()
            except Exception:
                pass
        
        time.sleep(3)
        self.browser = create_browser(
            profile_path=config.CHROME_PROFILE_PATH,
            headless=config.HEADLESS,
            implicit_wait=config.IMPLICIT_WAIT,
        )
        self._update_stats(browser_restarts=self.stats.browser_restarts + 1)
        logger.info("Browser restarted successfully")

    def _reconnect_sheets(self, sheets_writer):
        """Reconnect Google Sheets if the connection has expired."""
        try:
            sheets_writer._client = None
            sheets_writer._spreadsheet = None
            sheets_writer._connect()
            logger.info("Google Sheets reconnected successfully")
            return True
        except Exception as e:
            logger.error(f"Google Sheets reconnection failed: {e}")
            return False

    def _is_browser_alive(self) -> bool:
        if not self.browser:
            return False
        try:
            return self.browser.is_alive()
        except Exception:
            return False

    def _is_ip_blocked(self, browser=None) -> bool:
        """Check if funda has blocked us. Only checks on funda.nl pages."""
        b = browser or self.browser
        if not b:
            return False
        try:
            current_url = b.get_current_url() or ''
            # Only check on funda.nl pages — external sites trigger false positives
            if 'funda.nl' not in current_url:
                return False
            html = b.get_page_source()
            # Funda-specific block markers only
            funda_block_markers = [
                'Je bent geblokkeerd',
                'Je bent bijna op de pagina',
                'Too Many Requests',
                'Error 429',
            ]
            for marker in funda_block_markers:
                if marker.lower() in html.lower():
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def _split_into_chunks(items: list, n: int) -> list:
        """Split list into n roughly equal chunks."""
        k, m = divmod(len(items), n)
        return [items[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

    def _create_worker_browser(self, worker_id: int):
        """Create a browser for a worker thread with a unique port."""
        worker_profile = f"{config.CHROME_PROFILE_PATH}_w{worker_id}"
        worker_port = 9223 + worker_id  # 9223, 9224, etc.
        browser = BrowserAutomation(
            profile_path=worker_profile,
            profile_name='Default',
            headless=config.HEADLESS,
            implicit_wait=config.IMPLICIT_WAIT,
            port=worker_port,
        )
        # Don't kill other Chrome instances when starting worker browsers
        browser._kill_stale_chrome = lambda: None
        browser.start_browser()
        return browser

    def _wipe_all_worker_profiles(self):
        """Delete all worker Chrome profile directories for a clean restart."""
        for i in range(config.WORKER_COUNT):
            profile_dir = Path(f"{config.CHROME_PROFILE_PATH}_w{i}")
            if profile_dir.exists():
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                    logger.info(f"  Wiped worker profile: {profile_dir}")
                except Exception as e:
                    logger.warning(f"  Failed to wipe profile {profile_dir}: {e}")

    # ── Per-property watchdog ─────────────────────────────────

    def _run_with_watchdog(self, fn, browser, worker_id: int, timeout: int, what: str):
        """Run fn() in the calling (worker) thread, but if it blocks longer
        than `timeout` seconds, force-close `browser` from a watchdog thread
        so the hung CDP call raises and the worker can recover.

        Returns fn()'s result on success; the underlying exception propagates
        if fn raises (including the error caused by the forced close).
        """
        done = threading.Event()

        def _wd():
            # daemon so it never blocks shutdown; one-shot per call
            if not done.wait(timeout):
                logger.error(
                    f"  [W{worker_id}] WATCHDOG: {what} exceeded {timeout}s — "
                    f"force-closing browser to unblock hung worker"
                )
                try:
                    browser.close_browser()
                except Exception:
                    pass

        wd = threading.Thread(target=_wd, daemon=True)
        wd.start()
        try:
            return fn()
        finally:
            done.set()

    # ── Worker thread ─────────────────────────────────────────

    def _worker_scrape(self, worker_id: int, work_queue: queue.Queue, write_queue: queue.Queue):
        """
        Worker thread: pulls properties from shared queue, scrapes with persistent browser.
        
        CAPTCHA handling:
        - When ANY worker detects CAPTCHA, it sets _captcha_event
        - ALL workers see the event, close their browser, and wait
        - The triggering worker kills all Chrome, wipes all profiles, does cooldown
        - After cooldown, all workers restart with fresh browsers
        
        Error handling:
        - Browser crash: auto-restart with escalating cooldown
        - IP block detection: long pause before retry
        - Consecutive failure circuit breaker: 5+ failures → 2 min pause
        - All exceptions caught — worker never crashes permanently
        """
        browser = None
        scrape_count = 0
        consecutive_fails = 0
        restart_count = 0
        MAX_CONSECUTIVE_FAILS = 5
        MAX_RESTARTS_BEFORE_LONG_PAUSE = 3

        try:
            browser = self._create_worker_browser(worker_id)
            scraper = PropertyScraper(browser=browser)
            agency_scraper = AgencyScraper(browser=browser)

            while True:
                if self._check_stop():
                    break

                # ── Check if another worker triggered CAPTCHA restart ──
                if self._captcha_event.is_set():
                    logger.info(f"  [W{worker_id}] CAPTCHA event detected — closing browser and waiting...")
                    try:
                        browser.close_browser()
                    except Exception:
                        pass
                    browser = None

                    # Wait for the coordinated restart to complete
                    while self._captcha_event.is_set() and not self._check_stop():
                        time.sleep(1)

                    if self._check_stop():
                        break

                    # Restart with fresh browser after wipe
                    try:
                        browser = self._create_worker_browser(worker_id)
                        scraper = PropertyScraper(browser=browser)
                        agency_scraper = AgencyScraper(browser=browser)
                        logger.info(f"  [W{worker_id}] Fresh browser started after CAPTCHA reset")
                    except Exception as e:
                        logger.error(f"  [W{worker_id}] Failed to restart after CAPTCHA reset: {e}")
                        time.sleep(10)
                        continue

                    consecutive_fails = 0
                    restart_count = 0

                # ── Circuit breaker: too many consecutive failures ──
                if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                    pause_time = 120  # 2 minutes
                    logger.warning(
                        f"  [W{worker_id}] Circuit breaker: {consecutive_fails} consecutive failures. "
                        f"Pausing {pause_time}s..."
                    )
                    with self._stats_lock:
                        self.stats.consecutive_failures = max(
                            self.stats.consecutive_failures, consecutive_fails
                        )
                    self._update_stats()
                    
                    for _ in range(pause_time):
                        if self._check_stop():
                            break
                        time.sleep(1)
                    
                    consecutive_fails = 0
                    
                    # Restart browser after circuit breaker pause
                    try:
                        if browser:
                            browser.close_browser()
                            browser.wipe_profile()
                    except Exception:
                        pass
                    try:
                        browser = self._create_worker_browser(worker_id)
                        scraper = PropertyScraper(browser=browser)
                        agency_scraper = AgencyScraper(browser=browser)
                        logger.info(f"  [W{worker_id}] Browser restarted after circuit breaker pause")
                    except Exception as e:
                        logger.error(f"  [W{worker_id}] Browser restart failed after circuit breaker: {e}")
                        time.sleep(30)
                        continue

                # Get next property from shared queue
                try:
                    prop_info = work_queue.get(timeout=5)
                except queue.Empty:
                    if self._check_stop():
                        break
                    continue

                if prop_info is None:
                    break  # Sentinel — no more work

                # Skip if already scraped (dedup for collection retry duplicates)
                if self.kvk_storage.exists(prop_info['id']):
                    work_queue.task_done() if hasattr(work_queue, 'task_done') else None
                    continue

                if self._wait_if_paused():
                    break

                scrape_count += 1
                logger.info(f"  [W{worker_id}] #{scrape_count}: {prop_info['address']}")

                success = False
                for attempt in range(1, config.MAX_RETRIES + 1):
                    try:
                        # ── Check browser health ──
                        try:
                            alive = browser.is_alive() if browser else False
                        except Exception:
                            alive = False

                        if not alive:
                            restart_count += 1
                            cooldown = min(5 * restart_count, 30)
                            logger.warning(
                                f"  [W{worker_id}] Browser died (restart #{restart_count}) — "
                                f"cooldown {cooldown}s..."
                            )
                            try:
                                if browser:
                                    browser.close_browser()
                                    browser.wipe_profile()
                            except Exception:
                                pass
                            
                            for _ in range(cooldown):
                                if self._check_stop():
                                    break
                                time.sleep(1)
                            
                            browser = self._create_worker_browser(worker_id)
                            scraper = PropertyScraper(browser=browser)
                            agency_scraper = AgencyScraper(browser=browser)
                            self._update_stats(browser_restarts=self.stats.browser_restarts + 1)

                            if restart_count >= MAX_RESTARTS_BEFORE_LONG_PAUSE:
                                logger.warning(
                                    f"  [W{worker_id}] {restart_count} restarts — taking 60s recovery break"
                                )
                                for _ in range(60):
                                    if self._check_stop():
                                        break
                                    time.sleep(1)
                                restart_count = 0

                        # ── Scrape property (hard watchdog vs CDP hangs) ──
                        result = self._run_with_watchdog(
                            lambda: scraper.scrape_property(prop_info),
                            browser, worker_id,
                            config.PROPERTY_SCRAPE_TIMEOUT, "property scrape",
                        )

                        # ── CAPTCHA: trigger coordinated restart for ALL workers ──
                        if result == 'captcha':
                            logger.warning(
                                f"  [W{worker_id}] CAPTCHA detected — triggering global restart for ALL workers"
                            )
                            # Re-queue the property (not lost)
                            work_queue.put(prop_info)

                            # Coordinate: only one worker does the kill+wipe+cooldown
                            with self._captcha_lock:
                                if not self._captcha_event.is_set():
                                    self._captcha_event.set()
                                    logger.info(f"  [W{worker_id}] CAPTCHA coordinator — killing all Chrome + wiping profiles...")

                                    # Close own browser first
                                    try:
                                        browser.close_browser()
                                    except Exception:
                                        pass
                                    browser = None

                                    # Kill ALL Chrome processes
                                    self._kill_all_chrome()
                                    time.sleep(2)

                                    # Wipe ALL worker profiles for clean start
                                    self._wipe_all_worker_profiles()

                                    # Cooldown so funda forgets us
                                    cooldown_time = 90
                                    logger.info(f"  [W{worker_id}] CAPTCHA cooldown {cooldown_time}s — all workers paused...")
                                    for _ in range(cooldown_time):
                                        if self._check_stop():
                                            break
                                        time.sleep(1)

                                    self._update_stats(browser_restarts=self.stats.browser_restarts + config.WORKER_COUNT)

                                    # Signal all workers to restart
                                    self._captcha_event.clear()
                                    logger.info(f"  [W{worker_id}] CAPTCHA cooldown complete — all workers restarting")
                                else:
                                    # Another worker already handling it
                                    try:
                                        browser.close_browser()
                                    except Exception:
                                        pass
                                    browser = None

                            # Wait for coordinator to finish (if we're not the coordinator)
                            while self._captcha_event.is_set() and not self._check_stop():
                                time.sleep(1)

                            if self._check_stop():
                                break

                            # Restart with fresh browser
                            try:
                                browser = self._create_worker_browser(worker_id)
                                scraper = PropertyScraper(browser=browser)
                                agency_scraper = AgencyScraper(browser=browser)
                                logger.info(f"  [W{worker_id}] Fresh browser started after CAPTCHA reset")
                            except Exception as e:
                                logger.error(f"  [W{worker_id}] Browser restart failed after CAPTCHA: {e}")
                                time.sleep(30)

                            consecutive_fails = 0
                            restart_count = 0
                            break  # Break retry loop, go to next queue item

                        if result is None:
                            # Price-filtered — do NOT add to KVK so we can
                            # re-check this property if its price drops later
                            with self._stats_lock:
                                self.stats.properties_filtered += 1
                            self._update_stats()
                            logger.info(f"  [W{worker_id}]   Filtered (price threshold)")
                            success = True
                            break

                        # ── Scrape agency info (same watchdog) ──
                        result = self._run_with_watchdog(
                            lambda: agency_scraper.scrape_agency(result),
                            browser, worker_id,
                            config.PROPERTY_SCRAPE_TIMEOUT, "agency scrape",
                        )

                        # Use listed_since from collector (search page date header)
                        # instead of individual property page extraction
                        if prop_info.get('listed_since'):
                            result['listed_since'] = prop_info['listed_since']

                        # Queue for sheets writing
                        write_queue.put({
                            'result': result,
                            'prop_id': prop_info['id'],
                            'worker_id': worker_id,
                        })
                        success = True
                        break  # Success

                    except Exception as e:
                        logger.error(f"  [W{worker_id}] Attempt {attempt}/{config.MAX_RETRIES} failed: {e}")
                        if attempt < config.MAX_RETRIES:
                            backoff = random.uniform(3, 8) * attempt
                            time.sleep(backoff)
                        else:
                            # All MAX_RETRIES attempts in this worker visit failed.
                            # Don't lose the property — re-queue it for another
                            # worker visit (potentially a different worker with a
                            # fresh browser). Cap at MAX_WORKER_VISITS so we
                            # eventually give up on genuinely-broken URLs (404,
                            # de-listed, etc.).
                            MAX_WORKER_VISITS = 3
                            visit = prop_info.get('_visit', 1) + 1
                            if visit <= MAX_WORKER_VISITS:
                                prop_info['_visit'] = visit
                                # small jitter so the property doesn't immediately
                                # land back at the same worker
                                time.sleep(random.uniform(2, 6))
                                work_queue.put(prop_info)
                                logger.warning(
                                    f"  [W{worker_id}] All {config.MAX_RETRIES} attempts "
                                    f"failed — re-queued for visit {visit}/{MAX_WORKER_VISITS}: "
                                    f"{prop_info.get('id')}"
                                )
                            else:
                                with self._stats_lock:
                                    self.stats.properties_failed += 1
                                self._update_stats()
                                logger.error(
                                    f"  [W{worker_id}] Gave up on property after "
                                    f"{visit-1} worker visits × {config.MAX_RETRIES} "
                                    f"attempts each = {(visit-1)*config.MAX_RETRIES} total tries: "
                                    f"{prop_info.get('id')}"
                                )

                if success:
                    consecutive_fails = 0
                else:
                    consecutive_fails += 1

                # ── Anti-detection delays ──
                # Use config values for base delay between properties
                delay = random.uniform(config.MIN_DELAY_BETWEEN_PROPERTIES, config.MAX_DELAY_BETWEEN_PROPERTIES)
                # Every 5th property, longer stealth pause
                if scrape_count % 5 == 0:
                    delay += random.uniform(5, 10)
                # Every 20th property, major pause
                if scrape_count % 20 == 0:
                    delay += random.uniform(15, 30)
                    logger.info(f"  [W{worker_id}] Stealth pause {delay:.0f}s after {scrape_count} properties")
                time.sleep(delay)

        except Exception as e:
            logger.error(f"  [W{worker_id}] Fatal error: {e}", exc_info=True)
        finally:
            if browser:
                try:
                    browser.close_browser()
                except Exception:
                    pass
            logger.info(f"  [W{worker_id}] Worker finished ({scrape_count} properties scraped)")

    # ── Sheets writer thread ──────────────────────────────────

    def _sheets_writer_thread(self, write_queue: queue.Queue, sheets_writer,
                              stop_event: threading.Event,
                              batch_results: list, results_lock: threading.Lock,
                              valuation_queue: 'queue.Queue | None' = None):
        """Dedicated writer thread — pops from queue, writes to Sheets one at a time.
        After a successful sheet write, enqueues the row for the Walter worker
        to compute and back-write the 4 valuation cells (G:J).
        """
        while not stop_event.is_set() or not write_queue.empty():
            try:
                item = write_queue.get(timeout=1)
            except queue.Empty:
                continue

            if item is None:
                break  # Sentinel

            result = item['result']
            prop_id = item['prop_id']

            sheet_written = False
            if sheets_writer:
                for retry in range(2):
                    try:
                        sheet_written = sheets_writer.write_property(result, self.publication_date)
                        if sheet_written:
                            break
                    except Exception as e:
                        logger.warning(f"  [Writer] Sheets error (attempt {retry + 1}): {e}")
                        if retry == 0:
                            self._reconnect_sheets(sheets_writer)

            if sheet_written:
                self.kvk_storage.add(prop_id)
                with self._stats_lock:
                    self.stats.sheets_written += 1
                    self.stats.properties_scraped += 1
                    self.stats.total_kvk_stored = self.kvk_storage.count()
                    if valuation_queue is not None:
                        self.stats.valuations_pending += 1
                self._update_stats()

                with results_lock:
                    batch_results.append(result)

                logger.info(f"  [Writer] ✓ {result.get('address', '?')}")

                # Hand off to Walter worker for valuation back-write.
                # price_per_m2 + living_area passed as fallback so the engine
                # can synthesise an asking price when Funda hides it
                # ("Prijs op aanvraag" / range listings).
                if valuation_queue is not None:
                    valuation_queue.put({
                        'url':            result.get('url', ''),
                        'address':        result.get('address', ''),
                        'asking_price':   result.get('asking_price', ''),
                        'days_on_market': result.get('days_on_market', ''),
                        'postcode':       result.get('postcode', ''),
                        'house_number':   result.get('house_number', ''),
                        'house_addition': result.get('house_addition', ''),
                        'price_per_m2':   result.get('price_per_m2', ''),
                        'living_area':    result.get('living_area', ''),
                    })
            else:
                with self._stats_lock:
                    self.stats.properties_failed += 1
                self._update_stats()
                logger.error(f"  [Writer] ✗ Sheet write failed for {prop_id}")

    # ── Walter valuation worker ───────────────────────────────

    def _walter_worker_thread(self, valuation_queue: queue.Queue,
                              sheets_writer,
                              stop_event: threading.Event):
        """Single-threaded Walter worker. Pulls rows freshly written to the
        sheet, runs the ValuationEngine, and back-writes G:J on the same row.

        Why single-threaded: Walter Living's chat UI is rate-limited and
        captcha-prone. Running 1 session at a time is the safe default.
        """
        engine: 'ValuationEngine | None' = None
        try:
            engine = ValuationEngine()  # owns its own WalterClient
            logger.info("  [Walter] Worker started — waiting for valuations to process")

            while True:
                # Drain even after stop is signalled, so already-scraped rows
                # still get their valuation cells filled before we shut down.
                if stop_event.is_set() and valuation_queue.empty():
                    break

                try:
                    item = valuation_queue.get(timeout=1)
                except queue.Empty:
                    continue

                if item is None:
                    break  # Sentinel

                url = item.get('url', '')
                address = item.get('address', '?')

                if self._check_stop():
                    # Hard stop — drop pending valuations
                    with self._stats_lock:
                        self.stats.valuations_pending = max(0, self.stats.valuations_pending - 1)
                    self._update_stats()
                    continue

                try:
                    result = engine.value_property(item)
                    logger.info(
                        f"  [Walter] {address} → {result.reasoning} "
                        f"(conf={result.confidence})"
                    )

                    if not sheets_writer or not url:
                        with self._stats_lock:
                            self.stats.valuations_failed += 1
                            self.stats.valuations_pending = max(0, self.stats.valuations_pending - 1)
                        self._update_stats()
                        continue

                    # Skip back-write if confidence=NONE — nothing useful to write,
                    # leave the row's valuation cells empty so a future pass can retry.
                    if result.confidence == 'NONE':
                        with self._stats_lock:
                            self.stats.valuations_failed += 1
                            self.stats.valuations_pending = max(0, self.stats.valuations_pending - 1)
                        self._update_stats()
                        logger.warning(f"  [Walter] {address}: NONE — leaving row blank for retry")
                        continue

                    ok = False
                    for retry in range(2):
                        try:
                            ok = sheets_writer.update_valuation_row(url, result.as_sheet_dict())
                            if ok:
                                break
                        except Exception as e:
                            logger.warning(f"  [Walter] Sheets back-write error (attempt {retry+1}): {e}")
                            if retry == 0:
                                self._reconnect_sheets(sheets_writer)

                    with self._stats_lock:
                        if ok:
                            self.stats.valuations_written += 1
                            if result.confidence == 'FALLBACK':
                                self.stats.valuations_fallback += 1
                        else:
                            self.stats.valuations_failed += 1
                        self.stats.valuations_pending = max(0, self.stats.valuations_pending - 1)
                    self._update_stats()

                except Exception as e:
                    logger.error(f"  [Walter] Valuation error for {address}: {e}", exc_info=True)
                    with self._stats_lock:
                        self.stats.valuations_failed += 1
                        self.stats.valuations_pending = max(0, self.stats.valuations_pending - 1)
                    self._update_stats()

        except Exception as e:
            logger.error(f"  [Walter] Fatal worker error: {e}", exc_info=True)
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception:
                    pass
            logger.info("  [Walter] Worker finished")

    # ── Main loop ─────────────────────────────────────────────

    def _run_loop(self):
        """
        Pipelined scraping: collection and scraping run in PARALLEL.
        
        - Collector thread pages through search results, streaming new IDs into work_queue
        - Worker threads start after a brief warmup and pull from the same queue
        - Total time ≈ max(collection, scraping) instead of collection + scraping
        """
        self.stats = ScraperStats(
            status=ScraperStatus.RUNNING,
            start_time=time.time(),
            total_kvk_stored=self.kvk_storage.count(),
        )
        self._update_stats()
        
        worker_count = config.WORKER_COUNT
        
        try:
            logger.info("=" * 60)
            logger.info("  PIPELINED MODE: Collection + Scraping in parallel")
            logger.info("=" * 60)
            
            # ── Shared queues ─────────────────────────────────
            work_queue = queue.Queue()
            write_queue = queue.Queue()
            all_results = []
            results_lock = threading.Lock()
            collection_done = threading.Event()
            collection_error = [None]  # Mutable container for error from thread
            progress_state = {
                'collected_offset': 0,
                'queued_offset': 0,
                'last_collected': 0,
                'last_queued': 0,
            }

            # ── Collection thread ─────────────────────────────
            def _on_collection_progress(
                collected,
                queued,
                total_results,
                page,
                skipped_in_storage=0,
                skipped_already_queued=0,
            ):
                """Called by collector every few pages with real-time stats."""
                # Collector restarts from 0 on captcha retry. Keep counters monotonic
                # so dashboard progress does not jump backwards mid-session.
                if collected < progress_state['last_collected'] and progress_state['last_collected'] > 0:
                    progress_state['collected_offset'] += progress_state['last_collected']
                if queued < progress_state['last_queued'] and progress_state['last_queued'] > 0:
                    progress_state['queued_offset'] += progress_state['last_queued']

                effective_collected = progress_state['collected_offset'] + collected
                effective_queued = progress_state['queued_offset'] + queued

                progress_state['last_collected'] = collected
                progress_state['last_queued'] = queued

                with self._stats_lock:
                    current_ids_collected = self.stats.ids_collected
                    current_ids_queued = self.stats.ids_queued

                self._update_stats(
                    total_search_results=total_results,
                    ids_collected=max(current_ids_collected, effective_collected),
                    ids_queued=max(current_ids_queued, effective_queued),
                    kvk_collected_this_session=max(current_ids_queued, effective_queued),
                    # `duplicate_in_storage` is monotonic — these are TRUE duplicates
                    # (already in permanent KVK from prior sessions), they don't
                    # disappear when the collector retries.
                    duplicate_in_storage=max(self.stats.duplicate_in_storage, skipped_in_storage),
                    # `duplicate_in_retry_queue` is per-retry-attempt bookkeeping
                    # (same property re-encountered after a crash). Use the latest
                    # value, not max — so the count resets when the collector
                    # restarts and isn't misleadingly cumulative across retries.
                    duplicate_in_retry_queue=skipped_already_queued,
                    collection_page=page,
                    collection_status="collecting",
                )
                # Persist current page so a crash can resume from here.
                _update_run_state_page(page)

            def _collection_thread():
                """Runs collection in background, streaming IDs to work_queue.

                Retries indefinitely on browser crashes / captcha until either:
                  (a) collection completes naturally (3 'before' pages — we've
                      walked through the whole target window), or
                  (b) the user clicks Stop.

                Backoff doubles each attempt, capped at 10 minutes.
                """
                queued_ids = set()       # Shared across retries — no double-queue
                # Resume point. If this run is continuing a crashed run, start
                # where it stopped (skip pages already collected). Otherwise
                # None → binary search to the target window.
                resume_page = self._resume_from_page
                collection_attempt = 0
                completed_naturally = False
                # KVK snapshot. If continuing a crashed run, REUSE the original
                # run's snapshot — so the crashed run's own already-scraped
                # properties are NOT mis-counted as "duplicate_in_storage".
                # Otherwise take a fresh snapshot at session start.
                if self._resume_snapshot is not None:
                    prior_storage_snapshot = set(self._resume_snapshot)
                    logger.info(
                        f"  RESUMING crashed run: reusing original snapshot "
                        f"({len(prior_storage_snapshot)} ids), starting from page {resume_page or 1}"
                    )
                else:
                    try:
                        prior_storage_snapshot = set(self.kvk_storage.get_all())
                        logger.info(f"  Session-start KVK snapshot: {len(prior_storage_snapshot)} ids")
                    except Exception:
                        prior_storage_snapshot = set()
                # Persist run state so a crash mid-run can be resumed on restart.
                _save_run_state({
                    'publication_date': self.publication_date,
                    'started_at': time.time(),
                    'session_snapshot': sorted(prior_storage_snapshot),
                    'last_page': resume_page or 1,
                    'collection_status': 'collecting',
                    'in_progress': True,
                })
                self._collection_snapshot = prior_storage_snapshot  # for periodic re-save

                while not self._check_stop():
                    try:
                        self._update_stats(collection_status="collecting")
                        if collection_attempt > 0:
                            # Exponential backoff: 15s, 30s, 60s, 90s (cap).
                            # Previous cap of 600s = 10 min made the pipeline
                            # look frozen between collection retries. Funda
                            # captcha/rate signals clear within ~60s; longer
                            # waits don't help and just stall the run.
                            cooldown = min(15 * (2 ** (collection_attempt - 1)), 90)
                            logger.info(
                                f"  Collection retry attempt {collection_attempt} — "
                                f"waiting {cooldown}s before retry "
                                f"(resume from page {resume_page or 1})"
                            )
                            self._update_stats(collection_status=f"recovery_{collection_attempt}")
                            # Heartbeat the cooldown so monitoring sees movement.
                            _last_log = 0
                            for _waited in range(cooldown):
                                if self._check_stop():
                                    break
                                time.sleep(1)
                                if _waited - _last_log >= 15:
                                    logger.info(
                                        f"  Collection cooldown: {_waited}/{cooldown}s "
                                        f"(attempt {collection_attempt})"
                                    )
                                    _last_log = _waited
                            if self._check_stop():
                                break

                        logger.info("Starting Chrome browser for collection...")
                        self.browser = create_browser(
                            profile_path=config.CHROME_PROFILE_PATH,
                            headless=config.HEADLESS,
                            implicit_wait=config.IMPLICIT_WAIT,
                        )

                        date_range = config.DATE_RANGES.get(self.publication_date, (7, 3))

                        # Iterate one or more search URLs (one per province for
                        # deep buckets, one national URL for shallow buckets).
                        # Aggregate state (queued_ids / kvk_storage / work_queue)
                        # carries across URLs so dedup is preserved.
                        urls = self.search_urls
                        total_seen_across_urls = 0
                        total_results_seen = 0
                        for url_idx, url in enumerate(urls, start=1):
                            if self._check_stop():
                                break
                            if len(urls) > 1:
                                logger.info(
                                    f"  ── Collecting URL {url_idx}/{len(urls)} ──"
                                )

                            self.collector = PropertyCollector(
                                browser=self.browser,
                                search_url=url,
                                target_count=99999,
                                min_page_delay=config.MIN_DELAY_BETWEEN_PAGES,
                                max_page_delay=config.MAX_DELAY_BETWEEN_PAGES,
                                on_progress=_on_collection_progress,
                                stop_event=self._stop_event,
                                date_range=date_range,
                            )

                            # resume_from_page only applies to the FIRST URL —
                            # later URLs always start fresh (their own search).
                            self.collector.collect_kvk_numbers(
                                output_queue=work_queue,
                                kvk_storage=self.kvk_storage,
                                queued_ids=queued_ids,
                                resume_from_page=resume_page if url_idx == 1 else None,
                                prior_storage_snapshot=prior_storage_snapshot,
                            )

                            total_seen_across_urls += len(self.collector.collected)
                            total_results_seen += self.collector.total_search_results or 0

                            # Update stats after every URL so the dashboard
                            # reflects per-province progress.
                            if self.collector.total_search_results > 0 or len(urls) > 1:
                                effective_collected = progress_state['collected_offset'] + total_seen_across_urls
                                self._update_stats(
                                    total_search_results=max(self.stats.total_search_results, total_results_seen),
                                    ids_collected=max(self.stats.ids_collected, effective_collected),
                                    ids_queued=max(self.stats.ids_queued, len(queued_ids)),
                                    kvk_collected_this_session=max(self.stats.ids_queued, len(queued_ids)),
                                    duplicate_in_storage=self.stats.duplicate_in_storage,
                                    duplicate_in_retry_queue=self.stats.duplicate_in_retry_queue,
                                    collection_status="collecting" if url_idx < len(urls) else "done",
                                )

                        logger.info(
                            f"  Collection finished naturally — {len(queued_ids)} unique IDs "
                            f"queued, {total_seen_across_urls} total seen across "
                            f"{len(urls)} URL(s)"
                        )
                        completed_naturally = True
                        _update_run_state_field('collection_status', 'done')
                        break

                    except CaptchaBlockedException as e:
                        if self.collector and hasattr(self.collector, '_last_page'):
                            resume_page = max(1, self.collector._last_page - 2)
                        logger.warning(
                            f"  Collection blocked by captcha (attempt #{collection_attempt+1}): "
                            f"{e} — will resume from page {resume_page or 1}"
                        )
                        if self.browser:
                            try:
                                self.browser.close_browser()
                            except Exception:
                                pass
                            try:
                                self.browser.wipe_profile()
                                logger.info("  Wiped collection Chrome profile for fresh start")
                            except Exception as we:
                                logger.warning(f"  Failed to wipe profile: {we}")
                            self.browser = None
                        self._wipe_all_worker_profiles()

                    except Exception as e:
                        if self.collector and hasattr(self.collector, '_last_page'):
                            resume_page = max(1, self.collector._last_page - 2)
                        logger.warning(
                            f"  Collection crashed (attempt #{collection_attempt+1}, "
                            f"{type(e).__name__}: {e}) — will resume from page "
                            f"{resume_page or 1}"
                        )
                        if self.browser:
                            try:
                                self.browser.close_browser()
                            except Exception:
                                pass
                            self.browser = None

                    finally:
                        if self.browser:
                            try:
                                self.browser.close_browser()
                            except Exception:
                                pass
                            self.browser = None

                    collection_attempt += 1
                    # No max-attempt cap — keep retrying until completed_naturally
                    # or the user stops. Each retry pays the exponential cooldown.

                # If we exited the loop because the user stopped (not natural completion),
                # leave collection_status as-is so the dashboard reflects what happened.
                if not completed_naturally and self._check_stop():
                    logger.info("  Collection halted by user stop")
                collection_done.set()

            coll_thread = threading.Thread(target=_collection_thread, daemon=True)
            coll_thread.start()

            # ── Wait briefly for collection warmup ────────────
            # Let collection get ~2-3 pages of IDs (~30 properties) before starting workers
            logger.info("  Waiting 45s for collection warmup before starting workers...")
            for _ in range(45):
                if self._check_stop() or collection_done.is_set():
                    break
                time.sleep(1)

            if self._check_stop():
                self._update_stats(status=ScraperStatus.IDLE)
                return

            if collection_done.is_set() and collection_error[0]:
                self._update_stats(status=ScraperStatus.FAILED, last_error=collection_error[0])
                return

            queued_so_far = work_queue.qsize()
            logger.info(f"  Collection warmup done — {queued_so_far} properties queued so far")

            if queued_so_far == 0 and collection_done.is_set():
                tsr = self.stats.total_search_results
                dup_count = self.stats.duplicate_in_storage
                # Three cases when collection is done with 0 queued:
                #   (a) Funda returned 0 results in window → empty COMPLETED
                #   (b) Funda returned N>0 results but all are already in KVK
                #       storage → happy "fully caught up" COMPLETED
                #   (c) Funda returned N>0 results, none are in storage either,
                #       but date filter found 0 matches → BUG → FAILED with msg
                if tsr == 0:
                    logger.info("Collection finished with no new properties (empty result set)")
                    self._update_stats(status=ScraperStatus.COMPLETED)
                elif dup_count > 0:
                    logger.info(
                        f"Collection finished — all {dup_count} matching "
                        f"properties were already in KVK storage. Nothing new to scrape."
                    )
                    self._update_stats(status=ScraperStatus.COMPLETED)
                else:
                    msg = (
                        f"Collection finished with 0 properties queued, but "
                        f"funda reports {tsr:,} total results in scope and 0 "
                        f"matched our KVK storage. The date filter likely "
                        f"didn't match any listing — Funda HTML may have changed."
                    )
                    logger.error(f"  {msg}")
                    self._update_stats(status=ScraperStatus.FAILED, last_error=msg)
                return

            # ── Initialize Google Sheets ──────────────────────
            sheets_writer = SheetsWriter()
            try:
                sheets_writer._connect()
                logger.info("Google Sheets connected successfully")
            except Exception as e:
                logger.error(f"Google Sheets connection failed: {e}")
                sheets_writer = None

            # ── Start sheets writer thread + optional Walter valuation worker ──
            # Walter is gated behind config.VALUATION_ENABLED. When disabled
            # we pass None as the valuation queue so the writer skips the
            # hand-off — no 240s per-row response wait, no captcha stalls.
            walter_enabled = getattr(config, 'VALUATION_ENABLED', False)
            valuation_queue: queue.Queue = queue.Queue()
            writer_valuation_queue = valuation_queue if walter_enabled else None
            writer_stop = threading.Event()
            writer_thread = threading.Thread(
                target=self._sheets_writer_thread,
                args=(write_queue, sheets_writer, writer_stop, all_results,
                      results_lock, writer_valuation_queue),
                daemon=True,
            )
            writer_thread.start()

            walter_stop = threading.Event()
            walter_thread: 'threading.Thread | None' = None
            if walter_enabled:
                walter_thread = threading.Thread(
                    target=self._walter_worker_thread,
                    args=(valuation_queue, sheets_writer, walter_stop),
                    daemon=True,
                )
                walter_thread.start()
            else:
                logger.info(
                    "  Walter valuation worker DISABLED "
                    "(FUNDA_VALUATION_ENABLED=false) — scrape pipeline "
                    "will not stall on chat / captcha"
                )

            # ── Start persistent worker threads ───────────────
            worker_threads = []
            for i in range(worker_count):
                if self._check_stop():
                    break
                if i > 0:
                    stagger = random.uniform(5, 10)
                    logger.info(f"  Stagger delay: {stagger:.0f}s before worker {i}...")
                    time.sleep(stagger)
                t = threading.Thread(
                    target=self._worker_scrape,
                    args=(i, work_queue, write_queue),
                    daemon=True,
                )
                t.start()
                worker_threads.append(t)
                self._update_stats(active_workers=i + 1)
                logger.info(f"  Worker {i} started (pulling from shared queue)")

            # ── Monitor loop: wait for collection to finish + queue to drain ──
            # Stall guard: if scraped+filtered count stops advancing while
            # there's still work and workers are alive (not a captcha pause),
            # force-kill Chrome so workers rebuild fresh browsers. Backstop
            # behind the per-property watchdog for the case where even
            # close_browser() wedges.
            _stall_last_total = -1
            _stall_since = time.time()
            # Overall-run watchdog: track ANY progress (scraped+filtered+
            # collected). If none of it moves for RUN_FINALIZE_TIMEOUT the run
            # is wedged (e.g. collector hung on captcha) — force-finalize so it
            # reaches COMPLETED instead of hanging on RUNNING forever.
            _last_progress_sig = -1
            _progress_since = time.time()
            while not self._check_stop():
                # ── Overall-run watchdog ──
                progress_sig = (
                    self.stats.properties_scraped
                    + self.stats.properties_filtered
                    + self.stats.ids_collected
                )
                if progress_sig != _last_progress_sig:
                    _last_progress_sig = progress_sig
                    _progress_since = time.time()
                elif time.time() - _progress_since >= config.RUN_FINALIZE_TIMEOUT:
                    logger.error(
                        f"  RUN WATCHDOG: no progress (scraped/filtered/collected) "
                        f"for {config.RUN_FINALIZE_TIMEOUT}s — run is wedged. "
                        f"Force-finalizing → will write Excel + flip to COMPLETED."
                    )
                    self._force_finalize.set()
                    self._stop_event.set()  # wind down collector + workers
                    break

                # Check if collection is done AND queue is empty
                if collection_done.is_set() and work_queue.empty():
                    # Send sentinel values to stop workers
                    for _ in range(worker_count):
                        work_queue.put(None)
                    break
                
                # Check if all workers have died
                alive_workers = sum(1 for t in worker_threads if t.is_alive())
                if alive_workers == 0 and worker_threads:
                    logger.error("  All worker threads have died! Stopping...")
                    self._update_stats(
                        last_error="All workers crashed",
                        active_workers=0,
                    )
                    break
                self._update_stats(active_workers=alive_workers)
                
                # Interruptible sleep so stop is responsive
                for _ in range(3):
                    if self._check_stop():
                        break
                    time.sleep(1)
                
                # Progress update
                total_done = self.stats.properties_scraped + self.stats.properties_filtered
                remaining = work_queue.qsize()
                coll_status = "done" if collection_done.is_set() else "collecting"

                # ── Stall detection ──
                if total_done != _stall_last_total:
                    _stall_last_total = total_done
                    _stall_since = time.time()
                else:
                    stalled_for = time.time() - _stall_since
                    # A real stall = there is QUEUED work the workers aren't
                    # draining. If the queue is empty the workers are simply
                    # idle-waiting for the collector (which may be scanning
                    # pages that only yield duplicates) — that is NOT a hang,
                    # so killing their browsers would be pointless and would
                    # strand them. Only act when remaining > 0.
                    in_captcha = self._captcha_event.is_set()
                    if (
                        stalled_for >= config.WORKER_STALL_TIMEOUT
                        and remaining > 0
                        and alive_workers > 0
                        and not in_captcha
                    ):
                        logger.error(
                            f"  STALL MONITOR: no progress for {stalled_for:.0f}s "
                            f"({remaining} queued but not draining) "
                            f"— force-killing all Chrome so workers rebuild"
                        )
                        try:
                            self._kill_all_chrome()
                        except Exception as e:
                            logger.warning(f"  STALL MONITOR: kill failed: {e}")
                        self._update_stats(
                            browser_restarts=self.stats.browser_restarts + worker_count
                        )
                        _stall_since = time.time()  # reset; give workers time to recover
                
                # Progress based on ids_queued (not total_search_results)
                self._update_stats()
                
                if total_done % 20 < 3:  # Log every ~20 properties
                    logger.info(
                        f"  Pipeline: scraped={total_done} | queued={remaining} | "
                        f"workers={alive_workers}/{worker_count} | collection={coll_status}"
                    )

            # If stopped early, send sentinels
            if self._check_stop():
                for _ in range(worker_count):
                    work_queue.put(None)

            # Wait for all workers to finish.
            # Stop button: short timeout so /stop is responsive.
            # Normal completion: poll-join with heartbeat so a wedged
            # browser / hung CDP connection can't freeze the pipeline at
            # this final barrier — the controller previously called bare
            # t.join() which blocked forever and prevented status from
            # ever flipping to COMPLETED. Workers themselves still finish
            # their current property naturally; this just bounds how long
            # we wait if one becomes unresponsive.
            if self._check_stop():
                for t in worker_threads:
                    t.join(timeout=10)
            else:
                WORKER_DRAIN_HEARTBEAT = 60
                WORKER_DRAIN_MAX_WAIT = 30 * 60  # 30 min hard cap per worker
                for idx, t in enumerate(worker_threads):
                    waited = 0
                    while t.is_alive() and waited < WORKER_DRAIN_MAX_WAIT:
                        t.join(timeout=WORKER_DRAIN_HEARTBEAT)
                        waited += WORKER_DRAIN_HEARTBEAT
                        if t.is_alive():
                            logger.warning(
                                f"  Worker {idx} still draining after {waited}s "
                                f"(work_queue size: {work_queue.qsize()})"
                            )
                    if t.is_alive():
                        logger.error(
                            f"  Worker {idx} did not exit after "
                            f"{WORKER_DRAIN_MAX_WAIT}s — abandoning so pipeline "
                            f"can declare COMPLETED. Browser may need manual cleanup."
                        )

            # Wait for collection thread if still running
            coll_thread.join(timeout=10)

            self._update_stats(active_workers=0)

            # Signal writer thread to drain and stop
            writer_stop.set()
            write_queue.put(None)
            # Writer is fast (just sheet API calls). On stop, 60s force-cut.
            # On normal completion, poll-join with heartbeat so a hung Sheets
            # call (despite the 60s socket timeout) can't silently freeze the
            # pipeline forever.
            if self._check_stop():
                writer_thread.join(timeout=60)
            else:
                _waited_writer = 0
                while writer_thread.is_alive():
                    writer_thread.join(timeout=30)
                    _waited_writer += 30
                    if writer_thread.is_alive():
                        logger.warning(
                            f"  Writer thread still draining after {_waited_writer}s "
                            f"(write_queue size: {write_queue.qsize()})"
                        )

            # ── Drain Walter worker ───────────────────────────
            # Writer is done — no more rows will be enqueued for valuation.
            # Walter worker keeps running until valuation_queue is empty.
            # Stop button: 15s force-cut. Normal completion: NO timeout —
            # Walter is the slow path, every row in the queue MUST get its
            # valuation cells filled before we declare COMPLETED.
            walter_stop.set()
            valuation_queue.put(None)
            if walter_thread is None:
                # Walter was never started — nothing to drain.
                pass
            elif self._check_stop():
                walter_thread.join(timeout=15)
            else:
                # Heartbeat poll-join: Walter is the slow path (chat UI,
                # captcha-prone), but a wedged WalterClient must not freeze
                # the pipeline silently. Log progress every 60s.
                _waited_walter = 0
                while walter_thread.is_alive():
                    walter_thread.join(timeout=60)
                    _waited_walter += 60
                    if walter_thread.is_alive():
                        logger.warning(
                            f"  Walter worker still draining after {_waited_walter}s "
                            f"(valuation_queue size: {valuation_queue.qsize()})"
                        )

            # ── Write Excel output ────────────────────────────
            with results_lock:
                if all_results:
                    logger.info("Writing Excel output...")
                    writer = ExcelWriter(output_dir=config.OUTPUT_DIR)
                    excel_path = writer.write(list(all_results))
                    logger.info(f"  ✓ Excel: {excel_path}")
                    self._update_stats(excel_files_created=self.stats.excel_files_created + 1)

            # ── COMPLETION ─────────────────────────────────────
            total_collected = len(self.collector.collected) if self.collector else 0

            # A genuine user Stop → IDLE. A watchdog force-finalize also sets
            # _stop_event, but means "wrap up what we have" → COMPLETED.
            if self._check_stop() and not self._force_finalize.is_set():
                self._update_stats(status=ScraperStatus.IDLE)
                logger.info("Scraper stopped by user")
            else:
                # Scrape itself succeeded once we got here — every queued
                # property was either scraped, filtered, or recorded as
                # failed. Walter valuations are a downstream side-effect
                # (chat-driven price back-write) and must NOT flip scrape
                # status to FAILED when they don't drain — that was the
                # source of "scrape finished but UI shows FAILED, not
                # COMPLETED" reports. Surface undrained valuations as a
                # warning via last_error; status stays COMPLETED.
                pending = self.stats.valuations_pending
                if pending > 0:
                    warn = (
                        f"Scrape COMPLETED but {pending} valuation(s) "
                        f"unfinished — Walter worker did not drain. "
                        f"Re-run funda/run_valuations.py to back-fill."
                    )
                    logger.warning(f"  {warn}")
                    self._update_stats(
                        status=ScraperStatus.COMPLETED, last_error=warn
                    )
                else:
                    self._update_stats(status=ScraperStatus.COMPLETED)
                    logger.info("Scraper completed - all properties processed (incl. valuations)!")

            logger.info(f"\n{'=' * 60}")
            logger.info("  FINAL SUMMARY")
            logger.info(f"{'=' * 60}")
            logger.info(f"  IDs collected        : {total_collected}")
            logger.info(f"  KVKs in storage      : {self.kvk_storage.count()}")
            logger.info(f"  Properties scraped   : {self.stats.properties_scraped}")
            logger.info(f"  Properties filtered  : {self.stats.properties_filtered}")
            logger.info(f"  Properties failed    : {self.stats.properties_failed}")
            logger.info(f"  Valuations written   : {self.stats.valuations_written}")
            logger.info(f"  Valuations fallback  : {self.stats.valuations_fallback}")
            logger.info(f"  Valuations failed    : {self.stats.valuations_failed}")
            logger.info(f"  Excel files created  : {self.stats.excel_files_created}")
            logger.info(f"  Browser restarts     : {self.stats.browser_restarts}")
            logger.info(f"  Total time           : {self.stats.elapsed_seconds:.1f}s")
            logger.info(f"{'=' * 60}")

        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            self._update_stats(status=ScraperStatus.FAILED, last_error=str(e))

        finally:
            if self.browser:
                try:
                    self.browser.close_browser()
                except:
                    pass
            # Run reached its end (COMPLETED / FAILED / stopped). Mark the
            # persisted run state as no-longer-in-progress so the next backend
            # startup does NOT auto-resume it. (A real crash skips this finally
            # block — uvicorn is killed — so in_progress stays True and we
            # auto-resume on restart.)
            try:
                _update_run_state_field('in_progress', False)
            except Exception:
                pass


# ── Global controller instance for API use ─────────────────────
_controller: Optional[FundaController] = None
_controller_lock = threading.Lock()


def get_controller() -> Optional[FundaController]:
    """Get the current controller instance."""
    return _controller


def start_scraper(
    publication_date: int = 5,
    on_progress: Optional[Callable[[ScraperStats], None]] = None,
    resume_from_page: Optional[int] = None,
    resume_snapshot: Optional[set] = None,
) -> FundaController:
    """Start a new scraper controller.

    If resume_from_page / resume_snapshot are given, this is a continuation of
    a crashed run — collection skips the binary search and starts from that
    page, and the supplied snapshot is reused so the crashed run's own
    already-scraped properties aren't mis-counted as duplicates.

    A fresh manual start (both None) clears any leftover run-state first.
    """
    global _controller

    with _controller_lock:
        if _controller and _controller.is_running():
            raise RuntimeError("Scraper is already running")

        if resume_from_page is None and resume_snapshot is None:
            # Fresh manual start. Discard leftover run-state only — do NOT
            # touch KVK storage or the sheet. They persist across runs and are
            # only cleared manually (frontend "Clear KVK Storage" button, or
            # editing the sheet by hand). Re-running the same date window will
            # therefore skip already-scraped properties (shown as "Duplicate"),
            # which is the intended dedup behaviour.
            _clear_run_state()

        _controller = FundaController(
            publication_date=publication_date,
            on_progress=on_progress,
            resume_from_page=resume_from_page,
            resume_snapshot=resume_snapshot,
        )
        _controller.start()
        return _controller


def stop_scraper() -> bool:
    """Stop the current scraper."""
    if _controller:
        return _controller.stop()
    return False


def pause_scraper() -> bool:
    """Pause the current scraper."""
    if _controller:
        return _controller.pause()
    return False


def resume_scraper() -> bool:
    """Resume the current scraper."""
    if _controller:
        return _controller.resume()
    return False


def get_scraper_stats() -> Dict[str, Any]:
    """Get current scraper stats."""
    if _controller:
        return _controller.get_stats()
    return ScraperStats().to_dict()
