"""
Browser Automation Module for Funda

Uses DrissionPage (Chrome DevTools Protocol) to control Chrome.
CDP-based automation is undetectable by standard bot-detection
because it does NOT use the WebDriver wire protocol.

Includes advanced anti-detection:
- Realistic browser fingerprint
- Human-like behavior simulation
- Smart cookie/profile persistence
- Randomized timing patterns
"""
import time
import random
import shutil
from pathlib import Path
from typing import Optional, List

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import ElementNotFoundError

from ..utils.logger import setup_logger

logger = setup_logger('funda.browser')

# Constants
DEFAULT_PAGE_LOAD_TIMEOUT = 60
DEFAULT_WAIT_TIMEOUT = 15

# Realistic User-Agents (updated Chrome versions)
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
]


class BrowserAutomation:
    """
    Chrome browser automation for Funda via CDP (DrissionPage).

    Runs in HEAD mode by default so you can see every step.
    No WebDriver footprint = bypasses Funda's bot detection.
    """

    def __init__(
        self,
        profile_path: Optional[str] = None,
        profile_name: str = 'Default',
        headless: bool = False,
        implicit_wait: int = 10,
        proxy: Optional[str] = None,
        port: int = 9222,
    ):
        self.profile_path = profile_path
        self.profile_name = profile_name
        self.headless = headless
        self.implicit_wait = implicit_wait
        self.proxy = proxy
        self.port = port
        self.page: Optional[ChromiumPage] = None
        self._delay_multiplier = 1.0  # Increases on CAPTCHA detection

        logger.info(f"Browser automation initialized (Headless: {headless}, Port: {port})")

    def start_browser(self) -> None:
        """Start Chrome browser via CDP with stealth."""
        try:
            # Clean up stale lock files that prevent browser startup
            self._cleanup_profile_locks()
            
            # Kill any zombie/orphan Chrome processes
            self._kill_stale_chrome()
            
            co = self._configure_options()

            logger.info("Starting Chrome browser (DrissionPage / CDP)...")
            self.page = ChromiumPage(co)

            # Set default timeouts
            self.page.set.timeouts(
                base=self.implicit_wait,
                page_load=DEFAULT_PAGE_LOAD_TIMEOUT,
                script=30,
            )

            # Inject stealth scripts to hide automation fingerprints
            self._inject_stealth_scripts()

            logger.info("[OK] Chrome browser started successfully")

        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            raise

    def _cleanup_profile_locks(self) -> None:
        """Remove Chrome profile lock files that prevent startup."""
        if not self.profile_path:
            return
        profile_dir = Path(self.profile_path)
        for lock_file in ['SingletonLock', 'SingletonSocket', 'SingletonCookie']:
            lock_path = profile_dir / lock_file
            try:
                if lock_path.exists():
                    lock_path.unlink()
                    logger.info(f"Removed stale lock file: {lock_file}")
            except Exception:
                pass

    def _kill_stale_chrome(self) -> None:
        """Kill any orphaned Chrome processes to free up the debug port."""
        import subprocess
        try:
            subprocess.run(
                ['pkill', '-f', 'chrome.*--remote-debugging-port'],
                capture_output=True, timeout=5,
            )
            time.sleep(1)
        except Exception:
            pass

    def _configure_options(self) -> ChromiumOptions:
        """Configure Chrome options with anti-detection."""
        co = ChromiumOptions()

        # Use system Chrome
        co.set_browser_path('/usr/bin/google-chrome')

        # Set unique debugging port for this instance
        co.set_local_port(self.port)

        # Realistic window size (randomized slightly)
        w = random.randint(1366, 1920)
        h = random.randint(768, 1080)
        co.set_argument('--window-size', f'{w},{h}')
        co.set_argument('--start-maximized')

        # Stability flags
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-software-rasterizer')

        # ── Anti-detection flags ──────────────────────────────
        # Disable automation indicators
        co.set_argument('--disable-blink-features=AutomationControlled')

        # Realistic user agent
        ua = random.choice(USER_AGENTS)
        co.set_argument(f'--user-agent={ua}')
        logger.debug(f"User-Agent: {ua}")

        # Language (Dutch - matches funda.nl)
        co.set_argument('--lang=nl-NL,nl,en-US,en')
        co.set_argument('--accept-lang=nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7')

        # Disable webrtc IP leak
        co.set_argument('--disable-webrtc')

        # Disable crash reporter (reduces fingerprint)
        co.set_argument('--disable-breakpad')
        co.set_argument('--disable-crash-reporter')

        # ── VPS-specific hardening ────────────────────────────
        # Timezone (Netherlands)
        co.set_argument('--timezone=Europe/Amsterdam')

        # Disable automation extensions
        co.set_argument('--disable-extensions')
        co.set_argument('--disable-default-apps')
        co.set_argument('--disable-component-update')
        co.set_argument('--disable-domain-reliability')
        co.set_argument('--disable-features=IsolateOrigins,site-per-process')
        co.set_argument('--disable-hang-monitor')
        co.set_argument('--disable-ipc-flooding-protection')
        co.set_argument('--disable-popup-blocking')
        co.set_argument('--disable-prompt-on-repost')
        co.set_argument('--disable-renderer-backgrounding')
        co.set_argument('--disable-sync')
        co.set_argument('--metrics-recording-only')
        co.set_argument('--no-first-run')

        # Proxy support (residential proxy recommended on VPS)
        if self.proxy:
            co.set_argument(f'--proxy-server={self.proxy}')
            logger.info(f"Using proxy: {self.proxy}")

        # Profile directory (preserves cookies across sessions!)
        if self.profile_path:
            co.set_argument('--user-data-dir', self.profile_path)

        # Headless mode (use new headless which is less detectable)
        if self.headless:
            co.set_argument('--headless=new')

        return co

    def _inject_stealth_scripts(self) -> None:
        """Inject JavaScript to hide automation fingerprints."""
        stealth_js = """
        // Hide webdriver property
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Proper plugins array (realistic Chrome plugins)
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const plugins = [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                ];
                plugins.length = 3;
                return plugins;
            }
        });

        // Proper languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['nl-NL', 'nl', 'en-US', 'en']
        });

        // Hardware concurrency (realistic core count)
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });

        // Device memory
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });

        // Platform
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32'
        });

        // Max touch points (0 = desktop)
        Object.defineProperty(navigator, 'maxTouchPoints', {
            get: () => 0
        });

        // Screen properties
        Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
        Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

        // Chrome object
        if (!window.chrome) {
            window.chrome = {
                runtime: {
                    connect: function() {},
                    sendMessage: function() {}
                },
                loadTimes: function() { return {}; },
                csi: function() { return {}; }
            };
        }

        // Permissions
        const originalQuery = window.navigator.permissions.query;
        if (originalQuery) {
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        }

        // WebGL vendor
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParameter.call(this, parameter);
        };

        // Canvas fingerprint noise (adds tiny random noise to canvas)
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (type === 'image/png' || type === undefined) {
                const ctx = this.getContext('2d');
                if (ctx) {
                    const imageData = ctx.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {
                        imageData.data[i] += (Math.random() * 2 - 1) | 0;
                    }
                    ctx.putImageData(imageData, 0, 0);
                }
            }
            return origToDataURL.apply(this, arguments);
        };

        // Headless detection bypass
        Object.defineProperty(document, 'hidden', { get: () => false });
        Object.defineProperty(document, 'visibilityState', { get: () => 'visible' });

        // Connection type (realistic)
        if (navigator.connection) {
            Object.defineProperty(navigator.connection, 'rtt', { get: () => 50 });
        }
        """
        try:
            self.page.run_js(stealth_js)
            logger.debug("Stealth scripts injected")
        except Exception:
            pass

    # ─── Navigation ───────────────────────────────────────────

    def navigate_to(self, url: str) -> None:
        """Navigate to a URL and re-inject stealth scripts.

        Up to 3 attempts on transient navigation errors (DNS blip,
        connection reset, browser pipe broken). 2s/4s backoff between
        retries. Captcha detection is NOT considered a retry trigger —
        the higher-level captcha handler owns that flow.
        """
        import time as _t
        logger.info(f"Navigating to: {url}")
        last_exc = None
        for attempt in (1, 2, 3):
            try:
                self.page.get(url)
                self._inject_stealth_scripts()
                if self.is_captcha_page():
                    self._delay_multiplier = min(self._delay_multiplier * 1.5, 4.0)
                    logger.warning(
                        f"CAPTCHA detected — delay multiplier increased to "
                        f"{self._delay_multiplier:.1f}x"
                    )
                return
            except Exception as e:
                last_exc = e
                if attempt < 3:
                    sleep_s = 2 * attempt
                    logger.warning(
                        f"navigate_to failed (attempt {attempt}/3): {e} — "
                        f"retrying in {sleep_s}s"
                    )
                    _t.sleep(sleep_s)
                    continue
                logger.error(f"navigate_to failed permanently: {e}")
                raise

    def get_current_url(self) -> str:
        return self.page.url

    def get_title(self) -> str:
        return self.page.title

    def refresh_page(self) -> None:
        self.page.refresh()

    def get_page_source(self) -> str:
        return self.page.html

    # ─── Human Behavior Simulation ────────────────────────────

    def human_scroll(self) -> None:
        """Simulate human-like scrolling on the page."""
        try:
            # Scroll down in random small increments
            total_height = self.page.run_js("return document.body.scrollHeight") or 3000
            current = 0
            while current < total_height * 0.6:
                scroll_amount = random.randint(200, 500)
                self.page.run_js(f"window.scrollBy(0, {scroll_amount})")
                current += scroll_amount
                time.sleep(random.uniform(0.3, 0.8))

            # Sometimes scroll back up a bit
            if random.random() < 0.3:
                self.page.run_js(f"window.scrollBy(0, -{random.randint(100, 300)})")
                time.sleep(random.uniform(0.2, 0.5))
        except Exception:
            pass

    def human_pause(self, min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        """Random pause to simulate reading/thinking."""
        delay = random.uniform(min_sec, max_sec) * self._delay_multiplier
        time.sleep(delay)

    def simulate_browsing(self) -> None:
        """Simulate organic browsing behavior on the current page."""
        try:
            # Random scroll
            self.human_scroll()

            # Random mouse movement via JS
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            self.page.run_js(f"""
                var evt = new MouseEvent('mousemove', {{
                    clientX: {x}, clientY: {y}, bubbles: true
                }});
                document.dispatchEvent(evt);
            """)

            # Read pause
            self.human_pause(1.0, 2.5)
        except Exception:
            pass

    # ─── Element Finding ──────────────────────────────────────

    def wait_for_element(self, locator: str, timeout: int = DEFAULT_WAIT_TIMEOUT):
        """Wait for element. Returns element or None."""
        try:
            return self.page.ele(locator, timeout=timeout)
        except (ElementNotFoundError, Exception):
            return None

    def find_element_safe(self, locator: str, timeout: int = 3):
        """Find single element without throwing. Returns element or None."""
        try:
            return self.page.ele(locator, timeout=timeout)
        except (ElementNotFoundError, Exception):
            return None

    def find_elements_safe(self, locator: str, timeout: int = 3) -> List:
        """Find all matching elements without throwing."""
        try:
            return self.page.eles(locator, timeout=timeout)
        except (ElementNotFoundError, Exception):
            return []

    def find_links_by_href(self, href_contains: str, timeout: int = 5) -> List:
        """
        Find all <a> elements whose href contains the given substring.
        Uses DrissionPage locator: @@tag()=a@@href:{substring}
        """
        locator = f'@@tag()=a@@href:{href_contains}'
        return self.find_elements_safe(locator, timeout=timeout)

    # ─── JavaScript helpers ───────────────────────────────────

    def execute_script(self, script: str, *args):
        """Execute JavaScript in the browser."""
        return self.page.run_js(script, *args)

    def scroll_to_bottom(self) -> None:
        """Scroll to bottom of page."""
        self.page.scroll.to_bottom()

    def scroll_to_element(self, element) -> None:
        """Scroll element into view."""
        try:
            element.scroll.to_see()
        except Exception:
            pass

    # ─── reCAPTCHA / Challenge Detection ──────────────────────

    def is_captcha_page(self) -> bool:
        """Check whether the current page is a Funda reCAPTCHA challenge."""
        try:
            html = self.page.html
            markers = [
                "Je bent bijna op de pagina die je zoekt",
                "fundaCaptchaInput",
                "fundaCaptchaForm",
            ]
            return any(m in html for m in markers)
        except Exception:
            return False

    def wait_for_captcha_solved(self, timeout: int = 20) -> bool:
        """
        Wait briefly for captcha to resolve (e.g. auto-solve).
        In headless mode CAPTCHAs can't be solved manually,
        so we use a short timeout and signal for browser restart.
        """
        logger.warning(f"  CAPTCHA detected — checking for {timeout}s before giving up...")

        start = time.time()
        while time.time() - start < timeout:
            if not self.is_captcha_page():
                logger.info(f"  ✓ Challenge resolved ({time.time()-start:.1f}s)")
                time.sleep(1)
                return True
            time.sleep(2)

        logger.error(f"  ✗ Challenge not resolved within {timeout}s — browser restart needed")
        return False

    # ─── Cookie banner ────────────────────────────────────────

    def accept_cookies(self, timeout: int = 8) -> bool:
        """
        Try to accept cookie consent banner on funda.nl (Didomi).
        Returns True if banner was found and accepted.
        """
        selectors = [
            '#didomi-notice-agree-button',
            '@@tag()=button@@text():Alle cookies accepteren',
            '@@tag()=button@@text():Alles accepteren',
            '@@tag()=button@@text():Akkoord',
            '@@tag()=button@@text():Accept',
            '@@tag()=button@@text():Accepteren',
            'button[id*="accept"]',
        ]

        for sel in selectors:
            try:
                btn = self.page.ele(sel, timeout=min(timeout, 3))
                if btn:
                    btn.click()
                    logger.info("✓ Cookie consent accepted")
                    time.sleep(1)
                    return True
            except (ElementNotFoundError, Exception):
                continue

        logger.debug("No cookie banner found (may already be accepted)")
        return False

    # ─── Lifecycle ────────────────────────────────────────────

    def wipe_profile(self) -> None:
        """Delete the entire Chrome profile directory for a fresh start."""
        if not self.profile_path:
            return
        profile_dir = Path(self.profile_path)
        if profile_dir.exists():
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
                logger.info(f"Wiped Chrome profile: {profile_dir}")
            except Exception as e:
                logger.warning(f"Failed to wipe profile {profile_dir}: {e}")

    def close_browser(self) -> None:
        """Close browser and clean up."""
        if self.page:
            try:
                self.page.quit()
                logger.info("Browser closed")
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            finally:
                self.page = None
                # Clean up lock files after closing
                self._cleanup_profile_locks()

    def is_alive(self) -> bool:
        """Check if browser session is still active."""
        try:
            _ = self.page.url
            return True
        except Exception:
            return False

    def __enter__(self):
        self.start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_browser()
        return False
