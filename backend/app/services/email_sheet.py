"""
Email → Google Sheet writer.

User spec: emails stored in BOTH database AND Google Sheets. The DB is the
authoritative store; this module just mirrors each email row into an
"Emails" tab of the existing spreadsheet so the user has a paper trail
they can read directly in Sheets.

Best-effort: failures here are logged but do NOT block the API response —
the DB row is the source of truth.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from funda.src.config import config  # noqa: E402

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_TAB_NAME = "Emails"
_HEADERS = [
    "Sent At",
    "Status",
    "To",
    "CC",
    "Subject",
    "Body",
    "Attachment",
    "Property URL",
    "Error",
]


def _open_spreadsheet() -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CREDENTIALS, scopes=_SCOPES
    )
    return gspread.authorize(creds).open_by_key(config.GOOGLE_SHEETS_SPREADSHEET_ID)


def _get_or_create_tab(ss: gspread.Spreadsheet) -> gspread.Worksheet:
    try:
        ws = ss.worksheet(_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=_TAB_NAME, rows=1000, cols=len(_HEADERS))
        ws.update(values=[_HEADERS], range_name="A1")
    else:
        existing = ws.row_values(1)
        if not existing or existing != _HEADERS:
            ws.update(values=[_HEADERS], range_name="A1")
    return ws


def append_email_row(
    *,
    to_email: str,
    cc_emails: Optional[str],
    subject: str,
    body: Optional[str],
    attachment_path: Optional[str],
    property_url: Optional[str],
    status: str,
    error: Optional[str],
    sent_at: Optional[datetime],
) -> bool:
    """Append one email row to the Emails tab. Returns True on success."""
    try:
        ss = _open_spreadsheet()
        ws = _get_or_create_tab(ss)
        row: List[str] = [
            (sent_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S"),
            status,
            to_email or "",
            cc_emails or "",
            subject or "",
            (body or "")[:5000],  # sheet cell length cap
            attachment_path or "",
            property_url or "",
            error or "",
        ]
        ws.append_row(row, value_input_option="RAW")
        return True
    except Exception as e:
        logger.warning("Failed to mirror email to Google Sheet: %s", e)
        return False


__all__ = ["append_email_row"]
