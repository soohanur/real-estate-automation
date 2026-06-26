"""
Partner API — private, server-to-server endpoint for an external app
(sons-bidding). Authenticated with a single secret API key, NOT the dashboard
JWT.

Auth: every request must send  Authorization: Bearer <key>
We store only the SHA-256 hash of the key (settings.PARTNER_API_KEY_HASH);
the raw key is compared via a constant-time check. Mint a key with
scripts/mint_partner_key.py.

Endpoint:
  GET /api/v1/partner/property?postcode=7944NN&house_number=21
  GET /api/v1/partner/property?address=Brunel 21, 7944 NN Meppel
  → { "address": ..., "dom": <int|null>, "asking_price": ... }

Matching: Dutch addresses are uniquely keyed by postcode + house number.
We normalise both the query and the stored address to alphanumerics-only and
match house_number+postcode adjacency (they sit next to each other in our
"Street No, 1234 AB City" format). On multiple matches → most recent.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections import deque

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.database import get_db
from ..db.models import Property
from .properties import _dynamic_dom

router = APIRouter(prefix="/partner", tags=["Partner API"])

# ── Simple in-memory rate limit (single partner, single backend process) ──
_RL_MAX = 120          # requests
_RL_WINDOW = 60        # seconds
_RL_HITS: deque[float] = deque()


def _rate_limit() -> None:
    now = time.time()
    while _RL_HITS and now - _RL_HITS[0] > _RL_WINDOW:
        _RL_HITS.popleft()
    if len(_RL_HITS) >= _RL_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded — slow down")
    _RL_HITS.append(now)


async def verify_partner_key(authorization: str = Header(None)) -> None:
    """Constant-time check of the Bearer key against the stored hash."""
    if not settings.PARTNER_API_KEY_HASH:
        raise HTTPException(status_code=503, detail="Partner API not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing API key")
    key = authorization.split(" ", 1)[1].strip()
    incoming = hashlib.sha256(key.encode()).hexdigest()
    if not hmac.compare_digest(incoming, settings.PARTNER_API_KEY_HASH):
        raise HTTPException(status_code=401, detail="Invalid API key")
    _rate_limit()


def _norm(s: str | None) -> str:
    """Uppercase, strip everything except letters + digits."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


@router.get("/property", dependencies=[Depends(verify_partner_key)])
async def partner_property(
    postcode: str | None = Query(None, description="e.g. 7944NN (spaces/case ignored)"),
    house_number: str | None = Query(None, description="e.g. 21 or 21A"),
    address: str | None = Query(None, description="full address fallback"),
    db: AsyncSession = Depends(get_db),
):
    """Look up a property by postcode+house_number (preferred) or full address.
    Returns address, days-on-market, asking price. 404 if not found."""
    if postcode and house_number:
        key = _norm(house_number) + _norm(postcode)
    elif address:
        key = _norm(address)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide postcode + house_number, or address",
        )
    if len(key) < 4:
        raise HTTPException(status_code=400, detail="Query too short")

    # Normalised stored address (alphanumerics only) for a robust contains-match.
    norm_col = func.regexp_replace(func.upper(Property.address), "[^A-Z0-9]", "", "g")
    stmt = (
        select(Property)
        .where(norm_col.like(f"%{key}%"))
        .order_by(Property.created_at.desc())  # most recent on multi-match
        .limit(1)
    )
    obj = (await db.execute(stmt)).scalars().first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Property not found")

    dom_str = _dynamic_dom(obj.listed_since, obj.days_on_market)
    dom = int(dom_str) if dom_str and dom_str.isdigit() else None
    return {
        "address": obj.address,
        "dom": dom,
        "asking_price": obj.asking_price,
    }
