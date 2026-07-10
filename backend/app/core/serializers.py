"""
Shared pydantic serializers.

Timestamps are stored as *naive UTC* (datetime.utcnow()). Serialized as-is
they come out like "2026-07-10T04:42:06" with no offset — and JavaScript's
`new Date(...)` parses an offset-less ISO string as **local time**, so the
browser showed UTC values as if they were local (a bid sent 06:42 CEST
rendered as 04:42).

Annotating a field with `UtcDateTime` stamps the UTC offset on the way out
("...T04:42:06Z"), so clients convert to the viewer's timezone correctly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from pydantic import PlainSerializer


def _as_utc_iso(v: Optional[datetime]) -> Optional[str]:
    if v is None:
        return None
    # Naive values are UTC by construction (datetime.utcnow()).
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime,
    PlainSerializer(_as_utc_iso, return_type=str, when_used="json"),
]

__all__ = ["UtcDateTime"]
