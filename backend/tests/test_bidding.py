"""Tests for the bidding-price rule (services.bidding).

This is the business logic that changes most often (tiers + cap), so it gets
the most protection. Pure functions — no DB, no network.

Run:  cd backend && pytest
"""
from app.services.bidding import (
    DISCOUNT_CAP,
    bidding_formula,
    bidding_multiplier,
    compute_bidding,
)


def test_tier_multipliers():
    assert bidding_multiplier(250_000) == 0.80   # < 300k → 20% off
    assert bidding_multiplier(300_000) == 0.82   # 300k+  → 18% off
    assert bidding_multiplier(400_000) == 0.83   # 400k+  → 17% off
    assert bidding_multiplier(500_000) == 0.84   # 500k+  → 16% off
    assert bidding_multiplier(800_000) == 0.84


def test_compute_below_cap_uses_tier_percent():
    assert compute_bidding(250_000) == 200_000   # 20% off
    assert compute_bidding(300_000) == 246_000   # 18% off
    assert compute_bidding(400_000) == 332_000   # 17% off
    assert compute_bidding(500_000) == 424_000   # 16% (80k) but capped at 76k → 424k


def test_compute_cap_engages_for_high_asking():
    # Above ~€475k the 16% discount would exceed €76k, so the cap applies.
    assert compute_bidding(600_000) == 600_000 - DISCOUNT_CAP   # 524_000
    assert compute_bidding(800_000) == 800_000 - DISCOUNT_CAP   # 724_000


def test_discount_never_exceeds_cap():
    for asking in range(100_000, 2_000_001, 25_000):
        bid = compute_bidding(asking)
        assert asking - bid <= DISCOUNT_CAP
        assert bid <= asking


def test_formula_matches_compute():
    # The Sheets formula string must reference the asking cell and carry the cap.
    f = bidding_formula("F", 7)
    assert f.startswith('=IF(F7="","",MAX(ROUND(F7*')
    assert f"F7-{DISCOUNT_CAP}" in f
    assert ">=500000,0.84" in f and ">=300000,0.82" in f
