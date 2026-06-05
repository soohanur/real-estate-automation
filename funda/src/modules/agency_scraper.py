"""
Agency Scraper Module

Extracts agency (makelaar) contact information:
  1. Phone number  — from the property page tel: link or by
                     clicking "Toon telefoonnummer"
  2. Website URL   — from the agency's funda profile page
  3. Email address — by visiting the agency's own website and
                     searching for mailto: links or email patterns

Works with the BrowserAutomation wrapper (DrissionPage / CDP).
"""
import re
import time
import threading
from typing import Optional, Dict

from ..utils.logger import setup_logger

logger = setup_logger('funda.agency')

# Max time (seconds) to spend on any external agency website. Bumped from
# 12s: the landing-page smart-wait alone ate ~10s, leaving <2s so the
# /contact loop hit the deadline and was skipped — and most agency emails
# live on /contact, not the landing page. 25s lets us actually visit a
# couple of contact pages.
AGENCY_WEBSITE_TIMEOUT = 25

# Regex for email addresses (case-insensitive). Used for plain-text scans;
# mailto: links are parsed separately and trusted more.
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
)

# Contact / about pages where Dutch makelaars put their email. Tried in
# order after the landing page, within AGENCY_WEBSITE_TIMEOUT.
CONTACT_PATHS = [
    '/contact', '/contact/', '/contact-opnemen', '/contactgegevens',
    '/over-ons', '/over-ons/', '/over', '/ons-kantoor', '/kantoor',
    '/vestigingen', '/vestiging', '/kantoren', '/team', '/medewerkers',
    '/makelaars', '/info', '/email',
]

# Real TLDs we accept. Anything else (.push, .min, .map, .json …) is a
# JavaScript token that regex mistook for an email.
_ALLOWED_TLDS = {
    'nl', 'com', 'net', 'org', 'eu', 'be', 'de', 'fr', 'info', 'biz',
    'online', 'nu', 'frl', 'amsterdam', 'email', 'io', 'co', 'app',
}

# Substrings that mark a JS/framework token rather than a real address.
_JUNK_TOKENS = (
    'datalayer', 'alayer.push', 'sentry', 'wixpress', 'fonts.gst',
    '.push', 'gtm-', 'googletag', '@sentry', 'react', 'webpack',
    'adoghq', 'datadog', 'browser-agent', 'cloudflare', 'jsdelivr',
    'cdn.', 'gstatic', '@2x', '@3x', 'example.org',
)

# Role-based local-parts — preferred over personal names, and used to
# rescue emails concatenated with phone numbers (e.g. "0522-252412info@x").
ROLE_PREFIXES = (
    'info', 'contact', 'mail', 'kantoor', 'welkom', 'secretariaat',
    'verkoop', 'sales', 'algemeen', 'wonen', 'makelaardij', 'office',
    'hallo', 'post',
)

# Email addresses to skip (generic/tracking/third-party platform).
SKIP_EMAIL_DOMAINS = {
    'example.com', 'sentry.io', 'wix.com', 'wixpress.com', 'facebook.com',
    'google.com', 'googlemail.com', 'schema.org', 'sentry-next.wixpress.com',
    'w3.org', 'funda.nl', 'localhost', 'domain.com', 'email.com',
    'yourdomain.com', 'sentry.wixpress.com',
}


# Thread-safe agency cache — same agency across all workers
_agency_cache: Dict[str, Dict[str, str]] = {}
_agency_cache_lock = threading.Lock()


class AgencyScraper:
    """
    Scrapes agency contact details from funda and the agency website.

    Designed for speed: extracts phone from the property page DOM
    (already loaded), only navigates away for website/email.
    Uses a thread-safe cache to avoid re-scraping the same agency.
    """

    def __init__(self, browser):
        self.browser = browser

    # ─── Public API ───────────────────────────────────────────

    def scrape_agency(self, property_data: dict) -> dict:
        """
        Enrich property_data with agency email and website.

        Expects property_data to already contain:
          - agency_funda_url  (e.g. https://www.funda.nl/makelaar/63661)
          - agency_phone      (may be empty)

        Uses cache to avoid re-scraping same agency.
        Updates in-place and returns the same dict.
        """
        agency_funda_url = property_data.get('agency_funda_url', '')
        agency_name = property_data.get('agency_name', '')

        if not agency_funda_url:
            logger.warning("  No agency funda URL — skipping agency scrape")
            return property_data

        # Check cache first
        with _agency_cache_lock:
            cached = _agency_cache.get(agency_funda_url)
            if cached is not None:
                property_data['agency_website'] = cached.get('website', '')
                property_data['agency_email'] = cached.get('email', '')
                logger.info(f"  Agency {agency_name}: cached (website={cached.get('website', '?')}, email={cached.get('email', '?')})")
                return property_data

        logger.info(f"  Scraping agency: {agency_name}")

        # ── Step 1: Visit agency funda page for website URL ───
        website_url = self._get_agency_website(agency_funda_url)
        property_data['agency_website'] = website_url or ''

        if not website_url:
            logger.info("    No agency website found on funda profile")
            # Cache the negative result too
            with _agency_cache_lock:
                _agency_cache[agency_funda_url] = {'website': '', 'email': ''}
            return property_data

        logger.info(f"    Agency website: {website_url}")

        # ── Step 2: Visit agency website for email ────────────
        email = self._find_email_on_website(website_url)
        property_data['agency_email'] = email or ''

        if email:
            logger.info(f"    Agency email: {email}")
        else:
            logger.info("    No email found on agency website")

        # Cache the result
        with _agency_cache_lock:
            _agency_cache[agency_funda_url] = {
                'website': website_url or '',
                'email': email or '',
            }

        return property_data

    # ─── Agency Funda Profile ─────────────────────────────────

    def _get_agency_website(self, funda_url: str) -> Optional[str]:
        """
        Visit the makelaar profile on funda and extract website URL.
        Opens in a new tab to avoid interfering with the main property page.
        """
        agency_tab = None
        try:
            logger.debug(f"    Visiting agency profile: {funda_url}")

            # Open agency profile in a new tab to preserve property page state
            try:
                agency_tab = self.browser.page.new_tab(funda_url)
                self._smart_wait_page(agency_tab, max_wait=8)
            except Exception as e:
                logger.debug(f"    Failed to open agency tab: {e}")
                # Fallback: navigate main tab
                self.browser.navigate_to(funda_url)
                self._smart_wait()
                agency_tab = None

            page = agency_tab if agency_tab else self.browser.page

            # Verify we're on the agency page (not redirected)
            try:
                current_url = page.url if agency_tab else self.browser.get_current_url()
                if current_url and '/makelaar/' not in current_url:
                    logger.warning(f"    Agency page redirect: expected /makelaar/ but got: {current_url[:80]}")
                    return None
            except Exception:
                pass

            # Accept cookies if needed
            try:
                cookie_btn = page.ele('@@tag()=button@@text():accepteer', timeout=2)
                if cookie_btn:
                    cookie_btn.click()
                    time.sleep(0.5)
            except Exception:
                pass

            # Look for external website link
            # Strategy 1: link with "Bezoek website" or similar text
            for text in [
                'Bezoek website', 'Website', 'website',
                'Ga naar website', 'Naar website',
            ]:
                try:
                    el = page.ele(f'@@tag()=a@@text():{text}', timeout=1)
                    if el:
                        href = el.attr('href') or ''
                        if href and not href.startswith('/') and 'funda.nl' not in href:
                            return self._clean_url(href)
                except Exception:
                    continue

            # Strategy 2: look for external links (not funda.nl)
            try:
                all_links = page.eles('tag:a', timeout=2)
                for link in all_links:
                    try:
                        href = link.attr('href') or ''
                        if (
                            href.startswith('http')
                            and 'funda.nl' not in href
                            and 'google' not in href
                            and 'facebook' not in href
                            and 'instagram' not in href
                            and 'linkedin' not in href
                            and 'twitter' not in href
                            and 'youtube' not in href
                            and 'mailto:' not in href
                            and 'tel:' not in href
                        ):
                            return self._clean_url(href)
                    except Exception:
                        continue
            except Exception:
                pass

            # Strategy 3: search __NUXT_DATA__ for website URL
            try:
                nuxt_raw = page.run_js(
                    "var el = document.getElementById('__NUXT_DATA__');"
                    "return el ? el.textContent : null;"
                )
                if nuxt_raw:
                    urls = re.findall(
                        r'https?://(?!.*funda\.nl)[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}[^"]*',
                        nuxt_raw,
                    )
                    for url in urls:
                        if any(skip in url for skip in [
                            'google', 'facebook', 'sentry', 'schema.org',
                            'w3.org', 'cloudflare', 'optimizely', 'qualtrics',
                            'hotjar', 'gtm', 'googleapis',
                        ]):
                            continue
                        return self._clean_url(url)
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"    Error visiting agency profile: {e}")
        finally:
            if agency_tab:
                try:
                    agency_tab.close()
                except Exception:
                    pass

        return None

    # ─── Email Extraction ─────────────────────────────────────

    def _find_email_on_website(self, website_url: str) -> Optional[str]:
        """
        Visit the agency website and search for the best email address.

        Collects candidates from the landing page + several contact/about
        pages, then picks the best by score (domain match > role prefix >
        mailto source). Stops early once a domain-matching role email is
        found. Capped at AGENCY_WEBSITE_TIMEOUT seconds total.
        """
        deadline = time.time() + AGENCY_WEBSITE_TIMEOUT
        site_domain = self._domain_of(website_url)
        candidates: list[tuple[int, str]] = []  # (score, email)

        try:
            logger.debug(f"    Visiting agency website: {website_url}")

            # Open in new tab to preserve current page state
            new_tab = None
            try:
                new_tab = self.browser.page.new_tab(website_url)
                self._smart_wait_page(new_tab, max_wait=8)
            except Exception as e:
                logger.debug(f"    Failed to open new tab: {e}")
                self.browser.navigate_to(website_url)
                self._smart_wait(max_wait=8)

            page = new_tab if new_tab else self.browser.page

            def _harvest():
                """Pull candidates from current page; return True to stop early."""
                for email in self._collect_emails(page):
                    score = self._score_email(email, site_domain)
                    if score > 0:
                        candidates.append((score, email))
                # Stop early only on a strong hit (domain match + role prefix).
                return any(s >= 130 for s, _ in candidates)

            # ── Landing page ──
            if _harvest():
                return self._finish(candidates, new_tab, site_domain)

            # ── Contact / about pages ──
            base_url = self._get_base_url(website_url)
            for path in CONTACT_PATHS:
                if time.time() >= deadline:
                    logger.debug("    Agency website timeout — stopping page search")
                    break
                contact_url = base_url.rstrip('/') + path
                try:
                    page.get(contact_url)
                    self._smart_wait_page(page, max_wait=6)
                    if _harvest():
                        break
                except Exception:
                    continue

            return self._finish(candidates, new_tab, site_domain)

        except Exception as e:
            logger.warning(f"    Error searching agency website: {e}")
            try:
                if 'new_tab' in dir() and new_tab:
                    new_tab.close()
            except Exception:
                pass
            return self._pick_best(candidates, site_domain)

    def _finish(self, candidates, new_tab, site_domain) -> Optional[str]:
        if new_tab:
            try:
                new_tab.close()
            except Exception:
                pass
        return self._pick_best(candidates, site_domain)

    def _collect_emails(self, page) -> list:
        """Return every cleaned, plausible email on the page (mailto links
        first so they rank higher), de-duplicated, order preserved."""
        found: list = []
        seen = set()

        def _add(raw: str):
            email = self._clean_email(raw)
            if email and email not in seen and self._is_valid_email(email):
                seen.add(email)
                found.append(email)

        # 1. mailto: links — most reliable
        try:
            from urllib.parse import unquote
            for link in page.eles('@@tag()=a@@href:mailto:', timeout=3):
                href = link.attr('href') or ''
                if href.lower().startswith('mailto:'):
                    _add(unquote(href[7:].split('?')[0]))
        except Exception:
            pass

        # 2. footer / contact blocks
        try:
            for selector in ['tag:footer', '@@class:footer', '@@id:footer',
                             '@@class:contact', '@@id:contact']:
                try:
                    el = page.ele(selector, timeout=1)
                except Exception:
                    el = None
                if el:
                    for m in EMAIL_PATTERN.findall(el.html):
                        _add(m)
        except Exception:
            pass

        # 3. full page HTML (also catches text + obfuscated "(at)" forms)
        try:
            html = page.html
            for m in EMAIL_PATTERN.findall(html):
                _add(m)
            # de-obfuscate "naam (at) domein (dot) nl" style
            deob = re.sub(r'\s*\(?\s*(at|apenstaartje)\s*\)?\s*', '@', html, flags=re.I)
            deob = re.sub(r'\s*\(?\s*dot\s*\)?\s*', '.', deob, flags=re.I)
            for m in EMAIL_PATTERN.findall(deob):
                _add(m)
        except Exception:
            pass

        return found

    # ─── Helpers ──────────────────────────────────────────────

    @classmethod
    def _clean_email(cls, raw: str) -> Optional[str]:
        """Normalise a raw match into a real email. Strips whitespace and
        labels (e.g. 'Mail: '), and rescues emails glued to phone numbers
        like '0522-252412info@x.nl' -> 'info@x.nl'."""
        if not raw or '@' not in raw:
            return None
        raw = raw.strip().strip('.,;:<>()[]\'"').replace(' ', '')
        try:
            local, domain = raw.rsplit('@', 1)
        except ValueError:
            return None
        # domain: keep only valid leading domain chars
        dm = re.match(r'[a-zA-Z0-9.\-]+', domain)
        if not dm:
            return None
        domain = dm.group(0).strip('.-').lower()
        # drop any "Label:" prefix glued on (e.g. "E-mail:info" -> "info")
        if ':' in local:
            local = local.split(':')[-1]
        # Only rescue concatenation when the local-part STARTS with junk
        # (phone digits / dashes). A name like "sinfo" starts with a letter
        # and must be left alone — we don't want to miscut it to "info".
        if re.match(r'^[^a-zA-Z]', local):
            low = local.lower()
            cut = None
            for kw in ROLE_PREFIXES:
                i = low.find(kw)
                if i != -1 and (cut is None or i < cut):
                    cut = i
            if cut is not None:
                local = local[cut:]
            else:
                local = re.sub(r'^[^a-zA-Z]+', '', local)
        if not local:
            return None
        email = f"{local}@{domain}"
        if re.fullmatch(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', email):
            return email.lower()
        return None

    @staticmethod
    def _domain_of(url_or_email: str) -> str:
        s = (url_or_email or '').lower()
        if '@' in s:
            return s.rsplit('@', 1)[1]
        from urllib.parse import urlparse
        net = urlparse(s if s.startswith('http') else 'https://' + s).netloc
        return net[4:] if net.startswith('www.') else net

    @classmethod
    def _score_email(cls, email: str, site_domain: str) -> int:
        """Higher = better. Domain match dominates, then role prefix."""
        if not email:
            return 0
        local, domain = email.rsplit('@', 1)
        score = 1
        sd = (site_domain or '').lower()
        if sd and (domain == sd or domain.endswith('.' + sd) or sd.endswith('.' + domain)):
            score += 100
        elif sd and (domain.split('.')[0] == sd.split('.')[0]):
            score += 40  # same brand, different TLD
        if local in ROLE_PREFIXES or any(local.startswith(p) for p in ROLE_PREFIXES):
            score += 30
        # Very short non-role locals ("st", "d") are almost always JS noise.
        if len(local) < 3 and local not in ROLE_PREFIXES:
            score -= 200
        # Prefer general/branch addresses (info@, almere@) over a specific
        # agent's "firstname.lastname@" — a generic inbox is safer to email.
        if '.' not in local:
            score += 5
        # mild penalty for free-mail providers (agencies usually self-host)
        if domain in {'gmail.com', 'hotmail.com', 'outlook.com', 'live.nl',
                      'live.com', 'ziggo.nl', 'kpnmail.nl', 'planet.nl', 'hetnet.nl'}:
            score -= 10
        score -= min(len(local), 20) // 10  # prefer shorter local-parts slightly
        return score

    # Minimum score to accept. 40 means the winner MUST share the agency's
    # domain or brand (+100 / +40). A role prefix alone (+30) on a foreign
    # domain — e.g. info@oveon.nl (the web-builder) on scholopurk.nl, or a
    # JS token — is rejected. Better blank than the wrong company's inbox.
    _MIN_ACCEPT_SCORE = 40

    @classmethod
    def _pick_best(cls, candidates, site_domain) -> Optional[str]:
        good = [(s, e) for s, e in candidates if s >= cls._MIN_ACCEPT_SCORE]
        if not good:
            return None
        good.sort(key=lambda t: t[0], reverse=True)
        return good[0][1]

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        """Reject generic/tracking/JS-token addresses that regex on minified
        JavaScript happily produces (e.g. d@alayer.push, fonts.gst@ic.com)."""
        if not email or '@' not in email:
            return False
        local, domain = email.rsplit('@', 1)
        domain = domain.lower()
        if domain in SKIP_EMAIL_DOMAINS:
            return False
        if email.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js',
                           '.webp', '.jpeg', '.ico')):
            return False
        if len(email) > 100:
            return False
        # TLD must be a real one — kills .push/.min/.map/.json JS junk.
        tld = domain.rsplit('.', 1)[-1]
        if tld not in _ALLOWED_TLDS:
            return False
        # Obvious JS / framework tokens anywhere in the address.
        low = email.lower()
        if any(tok in low for tok in _JUNK_TOKENS):
            return False
        return True

    @staticmethod
    def _clean_url(url: str) -> str:
        url = url.strip().rstrip('/')
        if not url.startswith('http'):
            url = 'https://' + url
        return url

    @staticmethod
    def _get_base_url(url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _smart_wait(self, max_wait: int = 15) -> None:
        """Wait for page to fully load using document.readyState."""
        try:
            for _ in range(max_wait * 2):
                state = self.browser.execute_script("return document.readyState")
                if state == "complete":
                    time.sleep(0.3)
                    return
                time.sleep(0.5)
        except Exception:
            time.sleep(1)

    def _smart_wait_page(self, page, max_wait: int = 15) -> None:
        """Wait for a specific page/tab to load using document.readyState."""
        try:
            for _ in range(max_wait * 2):
                state = page.run_js("return document.readyState")
                if state == "complete":
                    time.sleep(0.3)
                    return
                time.sleep(0.5)
        except Exception:
            time.sleep(1)
