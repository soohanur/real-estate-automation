"""
Bidding price — the single source of truth for how a property's bid is
derived from its asking price.

Rule (tiered discount by asking band, with a hard cap on the discount):
    asking < €300k  → 20% off  (×0.80)
    asking ≥ €300k  → 18% off  (×0.82)
    asking ≥ €400k  → 17% off  (×0.83)
    asking ≥ €500k  → 16% off  (×0.84)
    AND the discount is never more than €76,000
        (so bidding is never below asking − 76,000).

Two forms are exposed so the DB value and the Google-Sheet cell always
agree:
  • compute_bidding()  — the Python number stored in Postgres.
  • bidding_formula()  — the equivalent Google-Sheets formula written to
    the sheet's Bidding Price column (so the sheet recalculates itself).

If the rule ever changes, change it HERE. (funda/src/modules/sheets_writer.py
keeps a copy of the formula string for the scraper's own writes — keep the
two in sync; this module is the canonical definition.)
"""
from __future__ import annotations

# Maximum euros the bid may sit below the asking price.
DISCOUNT_CAP = 76000


def bidding_multiplier(asking: int) -> float:
    """Keep-fraction (1 − discount%) for the asking-price band."""
    if asking >= 500000:
        return 0.84  # 16% off
    if asking >= 400000:
        return 0.83  # 17% off
    if asking >= 300000:
        return 0.82  # 18% off
    return 0.80      # 20% off


def compute_bidding(asking: int) -> int:
    """Bidding price as an integer euro amount for a positive asking price."""
    tiered = round(asking * bidding_multiplier(asking))
    return int(max(tiered, asking - DISCOUNT_CAP))


def bidding_formula(col: str, row: int) -> str:
    """The Google-Sheets formula equivalent of compute_bidding(), for the
    Bidding Price cell that references the asking-price cell `col``row`."""
    a = f"{col}{row}"
    return (
        f'=IF({a}="","",'
        f'MAX(ROUND({a}*IF({a}>=500000,0.84,IF({a}>=400000,0.83,'
        f'IF({a}>=300000,0.82,0.80)))),{a}-{DISCOUNT_CAP}))'
    )
