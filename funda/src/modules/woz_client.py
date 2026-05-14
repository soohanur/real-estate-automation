"""WOZ-waarde client.

Two-step lookup against public Dutch government APIs:
  1. PDOK locatieserver:    postcode + huisnummer  →  nummeraanduiding ID
  2. Kadaster WOZ API:      nummeraanduiding ID    →  WOZ history (per peildatum)

Returns the most recent `vastgesteldeWaarde` (assessed value) or None.

Both endpoints are free public APIs — no auth, no rate-limit issues for the
volumes we do (a few hundred lookups per day at most).
"""
import json
import re
import urllib.parse
import urllib.request
from typing import Optional

from ..config import config
from ..utils.logger import setup_logger

logger = setup_logger('funda.woz')

PDOK_BASE  = 'https://api.pdok.nl/bzk/locatieserver/search/v3_1/free'
WOZ_BASE   = 'https://api.kadaster.nl/lvwoz/wozwaardeloket-api/v1'
HEADERS    = {'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0 (FundaBot)'}
TIMEOUT    = max(5, getattr(config, 'WOZ_TIMEOUT', 15))


def _normalise_postcode(pc: str) -> str:
    pc = (pc or '').upper().replace(' ', '')
    return pc if re.match(r'^\d{4}[A-Z]{2}$', pc) else ''


def _http_json(url: str) -> Optional[dict]:
    """GET url, parse JSON. Up to 2 attempts (1s sleep between) so a single
    transient blip on PDOK/Kadaster doesn't drop a property's WOZ value."""
    import time
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 1:
                logger.debug(f"WOZ HTTP retry 1/2 {url}: {e}")
                time.sleep(1.0)
                continue
            logger.debug(f"WOZ HTTP fail (final) {url}: {e}")
            return None
    return None


def _find_nummeraanduiding(postcode: str, house_number: str,
                           house_addition: str = '') -> Optional[str]:
    pc = _normalise_postcode(postcode)
    if not pc or not house_number:
        return None
    q_parts = [pc, str(house_number)]
    if house_addition:
        q_parts.append(house_addition)
    q = ' '.join(q_parts)
    url = (
        f"{PDOK_BASE}?q={urllib.parse.quote(q)}"
        f"&fl=nummeraanduiding_id,weergavenaam,huisnummer,huis_nlt,postcode"
        f"&fq=type:adres&rows=5"
    )
    data = _http_json(url)
    if not data:
        return None
    docs = data.get('response', {}).get('docs', []) or []
    if not docs:
        return None
    # Prefer exact huisnummer + addition match; fall back to first hit
    for d in docs:
        if str(d.get('huisnummer')) == str(house_number):
            if not house_addition or house_addition.upper() in (d.get('huis_nlt', '') or '').upper():
                return d.get('nummeraanduiding_id')
    return docs[0].get('nummeraanduiding_id')


_TYPE_PREFIXES = {'huis', 'appartement', 'woonhuis', 'penthouse',
                  'studio', 'villa', 'parkeerplaats', 'bouwgrond'}


def _slug_to_query(slug: str) -> str:
    """Convert a Funda URL-slug like 'rotterdam / appartement-x-4' to a free-text
    query the PDOK locatieserver can resolve (e.g. 'x 4 rotterdam')."""
    parts = slug.split('/')
    city = parts[0].strip().replace('-', ' ')
    rest = parts[1].strip() if len(parts) > 1 else ''
    tokens = rest.split('-')
    if tokens and tokens[0].lower() in _TYPE_PREFIXES:
        tokens = tokens[1:]
    house = ''
    while tokens and re.match(r'^\d+[A-Za-z]?$', tokens[-1]):
        house = tokens.pop(-1) + (' ' + house if house else '')
    street = ' '.join(tokens)
    return f"{street} {house} {city}".strip()


def find_address_from_slug(slug: str) -> Optional[dict]:
    """Resolve a Funda URL-slug to {postcode, house_number, nid, weergavenaam}."""
    if not slug:
        return None
    q = _slug_to_query(slug)
    url = (
        f"{PDOK_BASE}?q={urllib.parse.quote(q)}"
        f"&fl=nummeraanduiding_id,weergavenaam,postcode,huisnummer,huis_nlt"
        f"&fq=type:adres&rows=1"
    )
    data = _http_json(url)
    if not data:
        return None
    docs = data.get('response', {}).get('docs', []) or []
    if not docs:
        return None
    d = docs[0]
    return {
        'postcode':     (d.get('postcode') or '').replace(' ', ''),
        'house_number': str(d.get('huisnummer', '')),
        'huis_nlt':     d.get('huis_nlt', ''),
        'nid':          d.get('nummeraanduiding_id'),
        'weergavenaam': d.get('weergavenaam', ''),
    }


def get_woz_value(postcode: str, house_number: str,
                  house_addition: str = '') -> Optional[dict]:
    """Return {'value': int, 'peildatum': 'YYYY-MM-DD', 'history': [...]} or None."""
    nid = _find_nummeraanduiding(postcode, house_number, house_addition)
    if not nid:
        return None
    data = _http_json(f"{WOZ_BASE}/wozwaarde/nummeraanduiding/{nid}")
    if not data:
        return None
    waarden = data.get('wozWaarden') or []
    if not waarden:
        return None
    # API returns newest-first already, but sort defensively.
    waarden = sorted(waarden, key=lambda w: w.get('peildatum', ''), reverse=True)
    latest = waarden[0]
    val = latest.get('vastgesteldeWaarde')
    try:
        val = int(val)
    except (TypeError, ValueError):
        return None
    return {
        'value':     val,
        'peildatum': latest.get('peildatum', ''),
        'history':   waarden,
    }
