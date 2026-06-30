"""
Google OAuth flow for the shared Gmail sender mailbox.

Flow:
  1. Admin clicks Connect Gmail in the dashboard.
  2. GET /api/v1/auth/google/start  → 302 to Google consent.
  3. User signs in as the sender mailbox + grants gmail.send scope.
  4. Google redirects to /api/v1/auth/google/callback?code=...
  5. We exchange the code for refresh + access tokens; store in DB
     keyed by the granted email address.
  6. gmail_sender.send_message() reads the row, auto-refreshes the
     access token, sends via Gmail API.

Only one Google account is supported for now (settings.GMAIL_SENDER).
Multi-tenant per-org credentials are a later concern.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.database import get_db
from ..db.models import GmailCredential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["Google OAuth"])

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",  # read inbox for the chat inbox
]


def _client_config() -> dict:
    """Build the in-memory client config Google Flow expects."""
    if not (settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET):
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET not configured",
        )
    if not settings.GOOGLE_OAUTH_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_OAUTH_REDIRECT_URI not configured",
        )
    return {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }


def _flow() -> Flow:
    flow = Flow.from_client_config(_client_config(), scopes=_SCOPES)
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    return flow


# PKCE state — google_auth_oauthlib generates a code_verifier on /start
# and Google requires the same value at /callback. Since /start and
# /callback are separate requests, we stash {state: code_verifier} in a
# module-level dict and replay it on callback. Entries are tiny (~50 B)
# and self-purge after exchange. Capped so a misbehaving client can't
# leak memory.
_PKCE_VERIFIERS: dict[str, str] = {}
_PKCE_MAX = 64


@router.get("/start")
async def start_oauth(
    login_hint: Optional[str] = Query(None, description="Pre-fill the sign-in form"),
):
    """Begin Google OAuth — redirects the browser to Google's consent page.

    Use ?login_hint=<email> to pre-fill the sign-in form (e.g. the
    shared sender mailbox). Default = settings.GMAIL_SENDER.
    """
    flow = _flow()
    hint = login_hint or settings.GMAIL_SENDER
    auth_url, state = flow.authorization_url(
        access_type="offline",        # required to get a refresh_token
        include_granted_scopes="true",
        prompt="consent",             # force refresh_token issuance even on re-auth
        login_hint=hint,
    )
    # Stash PKCE verifier so /callback can replay it.
    verifier = getattr(flow, "code_verifier", None)
    if verifier and state:
        if len(_PKCE_VERIFIERS) >= _PKCE_MAX:
            # Drop oldest. dict preserves insertion order.
            _PKCE_VERIFIERS.pop(next(iter(_PKCE_VERIFIERS)))
        _PKCE_VERIFIERS[state] = verifier
    return RedirectResponse(auth_url, status_code=302)


@router.get("/callback")
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Google redirects here after consent. Exchanges `code` for tokens
    and persists them in the gmail_credentials table."""
    if error:
        return HTMLResponse(
            f"<h1>Google sign-in failed</h1><pre>{error}</pre><p>You can close this tab.</p>",
            status_code=400,
        )
    if not code:
        raise HTTPException(status_code=400, detail="Missing ?code= from Google")

    flow = _flow()
    # Replay the PKCE verifier from /start so Google's token endpoint
    # accepts the exchange.
    if state and state in _PKCE_VERIFIERS:
        flow.code_verifier = _PKCE_VERIFIERS.pop(state)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.exception("OAuth token exchange failed")
        return HTMLResponse(
            f"<h1>Token exchange failed</h1><pre>{e}</pre>",
            status_code=400,
        )

    creds = flow.credentials
    if not creds.refresh_token:
        return HTMLResponse(
            "<h1>No refresh_token returned</h1>"
            "<p>Google only issues a refresh_token on first consent. "
            "Go to <a href='https://myaccount.google.com/permissions'>"
            "Google Account → Third-party access</a>, remove this app, "
            "then click Connect Gmail again.</p>",
            status_code=400,
        )

    # Look up the email the user signed in as. gmail.users.getProfile
    # needs gmail.readonly which we did NOT request — only gmail.send.
    # Try it anyway (some workspaces grant a wider scope on consent),
    # otherwise fall back to the configured sender. The user is told
    # to sign in as exactly that mailbox, so the fallback is safe.
    email = None
    try:
        from googleapiclient.discovery import build
        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = gmail.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress")
    except Exception as e:
        logger.warning(f"getProfile unavailable (likely scope-limited): {e}")

    if not email:
        email = settings.GMAIL_SENDER
    if not email:
        return HTMLResponse(
            "<h1>Could not determine signed-in email</h1>"
            "<p>Set GMAIL_SENDER in the backend env and try again.</p>",
            status_code=400,
        )

    # Upsert.
    res = await db.execute(select(GmailCredential).where(GmailCredential.email_address == email))
    row: Optional[GmailCredential] = res.scalar_one_or_none()
    payload = dict(
        email_address=email,
        refresh_token=creds.refresh_token,
        access_token=creds.token,
        token_expiry=creds.expiry,
        scopes=" ".join(creds.scopes or _SCOPES),
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    if row:
        for k, v in payload.items():
            setattr(row, k, v)
        action = "updated"
    else:
        db.add(GmailCredential(**payload))
        action = "saved"
    await db.commit()

    logger.info(f"Gmail OAuth: {action} credentials for {email}")
    # Bounce straight back into the admin panel (chat inbox) — no dead-end page.
    base = (settings.frontend_url or "").rstrip("/")
    return RedirectResponse(f"{base}/emails?gmail=connected", status_code=302)


@router.get("/status")
async def oauth_status(db: AsyncSession = Depends(get_db)):
    """Returns whether the configured GMAIL_SENDER has stored credentials."""
    sender = settings.GMAIL_SENDER
    if not sender:
        return {"connected": False, "reason": "GMAIL_SENDER env var not set"}
    res = await db.execute(select(GmailCredential).where(GmailCredential.email_address == sender))
    row = res.scalar_one_or_none()
    read_enabled = bool(row and row.scopes and "gmail.readonly" in row.scopes)
    return {
        "connected": row is not None,
        "email_address": sender,
        "last_updated": row.updated_at.isoformat() if row else None,
        # True once the mailbox is reconnected with read access (needed to
        # receive replies in the chat inbox).
        "read_enabled": read_enabled,
    }
