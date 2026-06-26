#!/usr/bin/env python3
"""
Mint a partner API key for the private /partner/* endpoints.

Prints TWO things:
  • KEY   — the raw secret. Shown ONCE. Give this to the partner (securely).
            We never store it; if it's lost you must mint a new one.
  • HASH  — put this in backend/.env as PARTNER_API_KEY_HASH, then restart
            the backend.

Usage:
    python scripts/mint_partner_key.py
"""
import hashlib
import secrets

key = "funda_" + secrets.token_urlsafe(32)
key_hash = hashlib.sha256(key.encode()).hexdigest()

print("=" * 70)
print("PARTNER API KEY — give this to the partner (shown only once):")
print(f"\n    {key}\n")
print("Put THIS in backend/.env (and on the server), then restart backend:")
print(f"\n    PARTNER_API_KEY_HASH={key_hash}\n")
print("Partner calls:")
print("    curl -H 'Authorization: Bearer <KEY>' \\")
print("      'https://sons.business/api/v1/partner/property?postcode=7944NN&house_number=21'")
print("=" * 70)
