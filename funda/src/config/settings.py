"""Configuration settings for Funda automation."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
env_path = PROJECT_ROOT / '.env'
load_dotenv(dotenv_path=env_path)


class Config:
    PROJECT_ROOT = PROJECT_ROOT

    # Chrome settings
    CHROME_PROFILE_PATH = os.getenv('CHROME_PROFILE_PATH', '')
    CHROME_PROFILE_NAME = os.getenv('CHROME_PROFILE_NAME', 'Default')

    # Funda URLs
    FUNDA_BASE_URL = os.getenv(
        'FUNDA_BASE_URL', 'https://www.funda.nl'
    )
    FUNDA_SEARCH_URL = os.getenv(
        'FUNDA_SEARCH_URL',
        'https://www.funda.nl/zoeken/koop?selected_area=["nl"]'
        '&publication_date=5&availability=["available"]'
    )

    # Collection settings (larger batches = fewer browser restarts)
    PROPERTIES_TO_COLLECT = int(os.getenv('FUNDA_PROPERTIES_TO_COLLECT', '90'))
    RESULTS_PER_PAGE = int(os.getenv('FUNDA_RESULTS_PER_PAGE', '15'))

    # Step 2: How many properties to process per run (0 = all collected)
    PROPERTIES_TO_PROCESS = int(os.getenv('FUNDA_PROPERTIES_TO_PROCESS', '0'))

    # Output
    OUTPUT_DIR = Path(os.getenv(
        'FUNDA_OUTPUT_DIR',
        str(PROJECT_ROOT / 'funda' / 'csv_files' / 'output')
    ))
    OUTPUT_CSV = os.getenv(
        'FUNDA_OUTPUT_CSV',
        'funda/csv_files/output/funda_properties.csv'
    )

    # State file (remembers last page number, processed IDs)
    STATE_FILE = Path(os.getenv(
        'FUNDA_STATE_FILE',
        str(PROJECT_ROOT / 'funda' / 'data' / 'scraper_state.json')
    ))

    # Chrome profile path (preserves cookies to avoid CAPTCHA)
    CHROME_PROFILE_PATH = str(os.getenv(
        'FUNDA_CHROME_PROFILE',
        str(PROJECT_ROOT / 'funda' / 'chrome_profile_funda')
    ))

    # Browser settings - Headless mode (use True for VPS/production)
    HEADLESS = os.getenv('FUNDA_HEADLESS_MODE', 'True').lower() == 'true'
    IMPLICIT_WAIT = int(os.getenv('FUNDA_IMPLICIT_WAIT', '5'))
    PAGE_LOAD_TIMEOUT = int(os.getenv('FUNDA_PAGE_LOAD_TIMEOUT', '30'))

    # Timing / anti-detection (optimized for speed — CDP is undetectable)
    MIN_DELAY_BETWEEN_PAGES = float(os.getenv('FUNDA_MIN_PAGE_DELAY', '1'))
    MAX_DELAY_BETWEEN_PAGES = float(os.getenv('FUNDA_MAX_PAGE_DELAY', '2.5'))
    MIN_DELAY_BETWEEN_PROPERTIES = float(os.getenv('FUNDA_MIN_PROP_DELAY', '1'))
    MAX_DELAY_BETWEEN_PROPERTIES = float(os.getenv('FUNDA_MAX_PROP_DELAY', '2'))

    # Parallel workers (3 workers — safe limit for 2 vCPU / 8GB VPS, avoids OOM)
    WORKER_COUNT = int(os.getenv('FUNDA_WORKER_COUNT', '3'))

    # Retry
    MAX_RETRIES = int(os.getenv('FUNDA_MAX_RETRIES', '3'))

    LOG_LEVEL = os.getenv('FUNDA_LOG_LEVEL', 'INFO')

    # Google Sheets settings
    GOOGLE_SHEETS_CREDENTIALS = str(os.getenv(
        'GOOGLE_SHEETS_CREDENTIALS',
        str(Path(__file__).parent / 'google_service_account.json')
    ))
    GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv(
        'GOOGLE_SHEETS_SPREADSHEET_ID',
        '1-96C6xdg-gL2kSdWHivE9e-PQucPxS3suB9AO8xDldo'
    )
    GOOGLE_SHEETS_URL = f'https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_SPREADSHEET_ID}/edit'

    # Tab name mapping: days_option -> sheet tab name
    PUBLICATION_DATE_TABS = {
        5: '3-7 Days Ago',
        10: '8-12 Days Ago',
        15: '13-17 Days Ago',
        30: '25-30 Days Ago',
        31: '30+ Days Ago',
    }

    # Date range mapping: days_option -> (start_days_ago, end_days_ago)
    # Properties sorted old->new, so start=oldest, end=newest
    DATE_RANGES = {
        5:  (7, 3),     # 3-7 days ago
        10: (12, 8),    # 8-12 days ago
        15: (17, 13),   # 13-17 days ago
        30: (30, 25),   # 25-30 days ago
        31: (9999, 31), # 31+ days ago
    }

    # Funda publication_date parameter to use for each range
    # Funda only accepts: 1, 3, 5, 10, 30 — any other value is ignored!
    FUNDA_PUB_DATE_PARAM = {
        5:  10,   # 3-7 days ago -> use pub_date=10 (last 10 days)
        10: 30,   # 8-12 days ago -> use pub_date=30 (last 30 days)
        15: 30,   # 13-17 days ago -> use pub_date=30 (last 30 days)
        30: 30,   # 25-30 days ago -> use pub_date=30 (last 30 days)
        31: 0,    # 30+ days -> omit param (search ALL listings)
    }

    # ─── Valuation / Bidding ─────────────────────────────────────
    # Walter Living (browser scraper — Phoenix LiveView chat)
    WALTER_EMAIL    = os.getenv('WALTER_EMAIL', '')
    WALTER_PASSWORD = os.getenv('WALTER_PASSWORD', '')
    WALTER_PROFILE_PATH = str(os.getenv(
        'WALTER_PROFILE_PATH',
        str(PROJECT_ROOT / 'funda' / 'chrome_profile_walter')
    ))
    WALTER_HEADLESS = os.getenv('WALTER_HEADLESS', 'True').lower() == 'true'
    WALTER_RESPONSE_TIMEOUT = int(os.getenv('WALTER_RESPONSE_TIMEOUT', '240'))
    WALTER_PORT = int(os.getenv('WALTER_PORT', '9444'))

    # Master switch: Walter valuation worker in the scrape pipeline. When
    # False, the scraper writes properties to the sheet and returns
    # immediately — no Walter chat session, no 240s per-row response wait,
    # no captcha-driven stalls that previously made the pipeline appear
    # stuck around the 10-minute mark. Standalone valuation cron
    # (run_valuations.py) still works when explicitly invoked.
    VALUATION_ENABLED = os.getenv('FUNDA_VALUATION_ENABLED', 'false').lower() == 'true'

    # Per-property hard watchdog. A single scrape (page nav + parse) normally
    # takes ~6-15s. If a worker's CDP connection silently wedges (Chrome
    # process alive but unresponsive), the scrape call blocks forever — no
    # page_load timeout fires, is_alive() stays True, and the worker stops
    # draining the queue (the "stuck at N, no new writes" failure). When a
    # single property exceeds this many seconds the watchdog force-closes the
    # browser, which makes the hung call raise so the worker recovers and
    # restarts its browser on the next attempt.
    PROPERTY_SCRAPE_TIMEOUT = int(os.getenv('FUNDA_PROPERTY_SCRAPE_TIMEOUT', '120'))
    # Controller-level stall monitor: if total scraped+filtered count doesn't
    # advance for this long while the run is active and not in a captcha
    # cooldown, the monitor force-kills all Chrome so workers rebuild fresh
    # browsers. Belt-and-braces behind the per-property watchdog.
    WORKER_STALL_TIMEOUT = int(os.getenv('FUNDA_WORKER_STALL_TIMEOUT', '300'))
    # Overall-run watchdog: if NOTHING advances — not scraped, not filtered,
    # not collected — for this long, the run is genuinely wedged (e.g. the
    # collector itself hung on a captcha wall). Force-finalize: drain what we
    # have, write Excel, flip status to COMPLETED instead of hanging on
    # RUNNING forever. Generous so legit slow/captcha periods don't trip it.
    RUN_FINALIZE_TIMEOUT = int(os.getenv('FUNDA_RUN_FINALIZE_TIMEOUT', '1200'))

    # WOZ (free public API: wozwaardeloket.nl)
    WOZ_API_BASE = os.getenv(
        'WOZ_API_BASE',
        'https://www.wozwaardeloket.nl/wozwaardeloket-api/v1'
    )
    WOZ_TIMEOUT = int(os.getenv('WOZ_TIMEOUT', '15'))

    # Comparables store (SQLite for sold-properties cache)
    COMPARABLES_DB_PATH = str(os.getenv(
        'COMPARABLES_DB_PATH',
        str(PROJECT_ROOT / 'funda' / 'data' / 'comparables.db')
    ))
    COMPARABLES_MAX_AGE_DAYS = int(os.getenv('COMPARABLES_MAX_AGE_DAYS', '90'))

    # Valuation engine — bid composition rules
    # Bid is derived from `asking × DOM × region` (independent of Walter),
    # then capped by Walter × (1 - BID_MIN_MARGIN) so resale always profits.
    DOM_PREMIUM = {           # days_on_market -> multiplier on asking
        7:  1.03,             # ≤7 days   fresh listing, modest overbid to win
        21: 0.99,             # 8-21 days slightly under asking
        60: 0.95,             # 22-60 days seller getting nervous
        9999: 0.90,           # 60+ days   stale — strong leverage
    }
    REGIONAL_OVERBID = {      # postcode prefix -> regional multiplier on asking
        '10': 1.04, '11': 1.04, '12': 1.03,   # Amsterdam region
        '20': 1.03, '21': 1.02,               # Haarlem / Leiden
        '25': 1.01, '26': 1.01,               # Den Haag
        '30': 1.02, '31': 1.02,               # Rotterdam
        '35': 1.05,                           # Utrecht (hottest)
        'default': 1.00,
    }
    # Profit margin: bid is capped at walter × (1 - BID_MIN_MARGIN) so that
    # reselling at Walter's "Play it Safe" still nets at least this much gross.
    BID_MIN_MARGIN = float(os.getenv('BID_MIN_MARGIN', '0.05'))
    # Floor: never bid below asking × this fraction (insulting low-ball threshold).
    BID_FLOOR_VS_ASKING = float(os.getenv('BID_FLOOR_VS_ASKING', '0.85'))


config = Config()
