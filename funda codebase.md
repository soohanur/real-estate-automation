# Funda Codebase — Beginner-Friendly Guide

This document explains **what every important part of the project does and how
it fits together**, in plain language. If you're new here, read it top to
bottom once — you'll understand the whole system.

---

## 1. What this project is

A real-estate automation platform that:

1. **Scrapes** property listings from **funda.nl** (the Dutch property site).
2. **Saves** them to a **Google Sheet** and a **PostgreSQL database**.
3. Calculates a **bidding price** for each property (asking price minus a
   tiered discount).
4. Lets you **send bid emails** to the selling agencies via **Gmail**.
5. Shows everything in a **dashboard** (Next.js web app).

It runs on a **VPS** (server) at `sons.business`, behind Nginx + SSL.

---

## 2. The big picture (3 parts)

```
┌─────────────────────────────────────────────────────────────┐
│                        ONE GIT REPO                          │
│                                                              │
│   funda/      →  the SCRAPER (browser automation)            │
│   backend/    →  the API (FastAPI) + database                │
│   web/        →  the DASHBOARD (Next.js website)             │
└─────────────────────────────────────────────────────────────┘

       scrapes                    reads/writes            shows
 funda.nl ───▶ funda/ ──▶ Google Sheet ──▶ backend/ ──▶ web/ ──▶ you
                              │                │
                              └──── sync ──────┘
                                              │
                                          Postgres DB
```

**Key idea:** the **scraper writes to the Google Sheet**. The **backend reads
the Sheet into the database** (so the dashboard can filter/sort fast). The
Sheet is the "paper trail"; the database is what the website reads.

---

## 3. `funda/` — the scraper

This is a standalone Python package that drives a real Chrome browser to
collect property data. It does NOT depend on the backend.

```
funda/
├─ main.py                 # entry point to run a scrape directly
├─ run_valuations.py       # standalone job to fill WOZ/valuation columns
├─ src/
│  ├─ config/settings.py   # ALL scraper settings (the single config file)
│  ├─ modules/             # the actual work, one file per job:
│  │  ├─ scraper_controller.py   # the "brain" — runs the whole pipeline
│  │  ├─ property_collector.py   # finds property URLs (date-range search)
│  │  ├─ property_scraper.py     # opens one listing, extracts all fields
│  │  ├─ agency_scraper.py       # finds the agency's email + website
│  │  ├─ browser_automation.py   # starts/controls Chrome (DrissionPage/CDP)
│  │  ├─ sheets_writer.py        # writes rows to Google Sheets
│  │  ├─ kvk_storage.py          # remembers scraped IDs (avoid duplicates)
│  │  ├─ valuation_engine.py     # computes WOZ-based valuation / suggested bid
│  │  ├─ walter_client.py        # talks to "Walter" valuation service
│  │  └─ woz_client.py           # fetches WOZ value (free gov API)
│  └─ utils/
│     ├─ logger.py               # logging setup
│     └─ retry_handler.py        # retry helper
└─ data/permanent_kvk.json # the dedup memory (which IDs already scraped)
```

### How a scrape works (the pipeline)

1. **`scraper_controller.py`** starts everything. You give it a
   `publication_date` (e.g. `31` = "30+ days ago"). It runs two things in
   parallel:
   - **Collection** (`property_collector.py`) — browses funda search pages,
     binary-searches to the right date range, collects property **URLs/IDs**,
     and puts new ones on a work queue. Stops 3 pages past the date window.
   - **Workers** (2 of them) — pull URLs off the queue and scrape each.

2. For each property a worker calls **`property_scraper.py`** (price, address,
   m², energy label, photos, etc.) then **`agency_scraper.py`** (agency email +
   website), then hands the row to **`sheets_writer.py`** to append to the
   Sheet.

3. **`kvk_storage.py`** records each property's funda ID so the same listing is
   never scraped twice (even across runs). Deleting a property removes its ID
   here so it won't come back.

4. If valuations are enabled, the **Walter worker** fills WOZ value + suggested
   bid (`valuation_engine.py` + `woz_client.py` + `walter_client.py`).

5. The controller flips status to **COMPLETED** when collection is done AND the
   queue is empty.

### Safety features (so it never hangs)

- **Per-property watchdog** — if scraping one property freezes (Chrome/CDP
  hang), it force-closes that browser after `FUNDA_PROPERTY_SCRAPE_TIMEOUT`
  (120s) so the worker recovers.
- **Stall monitor** — if there's queued work that isn't draining for
  `FUNDA_WORKER_STALL_TIMEOUT` (300s), it kills + rebuilds the worker browsers.
- **Run watchdog** — if NOTHING advances for `FUNDA_RUN_FINALIZE_TIMEOUT`
  (20 min), it force-finalizes the run to COMPLETED instead of hanging forever.
- **CAPTCHA handling** — detects funda's reCAPTCHA, restarts browsers with a
  cooldown.

### Config — one source of truth

All scraper settings live in **`funda/src/config/settings.py`** (the `Config`
class, exposed as `config`). It reads from environment / `.env`. Important keys:
`GOOGLE_SHEETS_CREDENTIALS`, `GOOGLE_SHEETS_SPREADSHEET_ID`, `WORKER_COUNT`,
`MAX_RETRIES`, the watchdog timeouts, `VALUATION_ENABLED`, Walter/WOZ settings.

> (There used to be a second, dead `funda/config.py` — it was removed so there
> is only one config file now.)

---

## 4. `backend/` — the API (FastAPI)

This is the web server the dashboard talks to. It also reads the Sheet into the
database and sends emails.

```
backend/app/
├─ main.py              # creates the FastAPI app, wires routers, startup tasks
├─ core/
│  ├─ config.py         # backend settings (DB URL, JWT, Gmail OAuth, etc.)
│  ├─ security.py       # password hashing + JWT tokens
│  ├─ environment.py    # picks URLs based on dev/prod
│  └─ celery_app.py     # background-task queue config
├─ db/
│  ├─ database.py       # async SQLAlchemy engine + session
│  └─ models.py         # the database TABLES (Property, EmailMessage, User, …)
├─ schemas/
│  ├─ schemas.py        # shared request/response shapes (auth, system, ws)
│  └─ properties.py     # PropertyOut — shared by properties + dashboard routers
├─ services/            # the BUSINESS LOGIC (kept out of the routers):
│  ├─ bidding.py        # ★ the bidding-price rule (single source of truth)
│  ├─ email_service.py  # send an email via Gmail (deliver / require_gmail)
│  ├─ gmail_sender.py   # low-level Gmail API call (build MIME, send)
│  ├─ email_sheet.py    # mirror sent emails into the "Emails" Sheet tab
│  └─ sheet_sync.py     # read the Google Sheet → upsert into the database
├─ api/                 # the ROUTES (thin — they call services):
│  ├─ auth.py           # login / register / JWT
│  ├─ properties.py     # list/get/patch/delete properties, bulk-delete, sync
│  ├─ emails.py         # create/list/send emails, stats
│  ├─ dashboard.py      # aggregate stats + "emails over time" chart data
│  ├─ funda.py          # start/stop/status of the scraper
│  ├─ google_oauth.py   # "Connect Gmail" OAuth flow
│  ├─ system.py         # health checks
│  └─ websocket.py      # live updates
├─ tasks/automation_tasks.py  # Celery background tasks
└─ tests/test_bidding.py      # unit tests for the bidding rule
```

### How the layers fit (important)

```
HTTP request → api/ (router, thin) → services/ (logic) → db/ (tables)
```

- **Routers (`api/`)** only handle the web request/response. They should be
  thin — parse input, call a service, return the result.
- **Services (`services/`)** hold the real logic (sending email, the bidding
  formula, syncing the sheet). This is so the same logic can be reused and
  tested without going through HTTP.
- **Models (`db/models.py`)** define the database tables.

### ★ The bidding rule — `services/bidding.py`

This is the most-changed piece, so it lives in ONE file and has tests.

```
bidding = asking − discount
discount = tiered % of asking, BUT never more than €76,000

  asking  < €300k   → 20% off
  asking ≥ €300k    → 18% off
  asking ≥ €400k    → 17% off
  asking ≥ €500k    → 16% off
  (cap: discount ≤ €76,000)
```

It exposes:
- `compute_bidding(asking)` → the number stored in the database.
- `bidding_formula(col, row)` → the equivalent Google-Sheets formula written
  into the Sheet's "Bidding Price" column (so the Sheet recalculates itself).

Both `api/properties.py` and `services/sheet_sync.py` use this file. The scraper
(`funda/.../sheets_writer.py`) keeps an identical copy of the formula string
(because the scraper package must not import the backend) — a comment there
points back to this file as the source of truth.

### Sheet ↔ Database sync — `services/sheet_sync.py`

The scraper writes to the Sheet; this service reads the **5 property tabs**
(`3-7 / 8-12 / 13-17 / 25-30 / 30+ Days Ago`) and **upserts** rows into the
`properties` table (matched by URL). It runs:
- automatically every 30s (a loop started in `main.py`), and
- on demand via the **Sync from Sheet** button (`POST /properties/sync`).

It deliberately **skips the "Emails" tab** (that tab holds email records, not
properties).

### Email sending — `services/email_service.py` + `gmail_sender.py`

- `deliver(db, email)` — tries to send one email via Gmail, then marks it
  `sent` / `failed` and mirrors the status onto the property. Never crashes on a
  send failure (records the error instead).
- `gmail_sender.send_via_gmail(...)` — the low-level Gmail API call (refreshes
  the OAuth token, builds the MIME message, sends).
- Connecting Gmail is a one-time OAuth done through `api/google_oauth.py`
  ("Connect Gmail" button).

### Database tables — `db/models.py`

- **Property** — one scraped listing (all the Sheet columns + `email_status`,
  `display_order`, timestamps).
- **EmailMessage** — one email (to, subject, body, `body_html`, status, sent_at).
- **GmailCredential** — the stored OAuth token for the sending mailbox.
- **User / APIKey / Job / JobLog / SystemMetrics / ToolConfig** — auth + job
  tracking.

---

## 5. `web/` — the dashboard (Next.js)

The website you actually click around in. Built with Next.js (App Router),
React, TypeScript, Tailwind.

```
web/src/
├─ app/                       # pages (App Router — folder = URL)
│  ├─ (app)/dashboard/page.tsx   # stats + "emails over time" chart
│  ├─ (app)/data/page.tsx        # ★ Global Data table (the main screen)
│  ├─ (app)/data/[id]/page.tsx   # one property's detail page
│  ├─ (app)/emails/page.tsx      # email activity + Connect Gmail + Send
│  ├─ (app)/scraper/page.tsx     # start/stop scraper + live status
│  ├─ (app)/layout.tsx           # sidebar + shell around the app pages
│  └─ login/page.tsx             # login screen
├─ components/
│  ├─ properties-table/       # the big data table (its own folder):
│  │  ├─ index.tsx               # table shell (desktop + mobile, virtualized)
│  │  ├─ row.tsx                 # one row (cells + action icons)
│  │  ├─ columns.ts              # column list + widths + grid template
│  │  └─ cells/                  # one file per special cell:
│  │     ├─ address.tsx          #   address + copy button
│  │     ├─ bidding.tsx          #   editable bidding price
│  │     ├─ website.tsx          #   open-in-new-tab link
│  │     ├─ copy-contact.tsx     #   phone/email + copy button
│  │     ├─ expandable-text.tsx  #   click to expand long text (no popup)
│  │     └─ images.tsx           #   photo thumbnails → lightbox
│  ├─ email-modal.tsx         # the "send email" popup (uses the template)
│  ├─ email-report-chart.tsx  # the dashboard bar chart (click a bar → emails)
│  └─ date-range-filter.tsx   # Today/Week/Month/Custom calendar picker
└─ lib/
   ├─ api.ts                  # axios client (adds JWT, base URL)
   ├─ api/properties.ts       # property API calls (list, delete, bulk, sync)
   ├─ api/emails.ts           # email API calls (list, send, gmail status)
   ├─ api/dashboard.ts        # dashboard/chart API calls
   ├─ api/funda.ts            # scraper start/stop/status calls
   ├─ email-template.ts       # ★ the Dutch bid-email HTML + text template
   └─ utils.ts                # helpers (formatting, classnames)
```

### Key screens

- **Global Data** (`data/page.tsx`) — the main table. Filter by email status
  (defaults to "Not sent"), days-on-market, search. Each row has: open on funda,
  send email, **delete** (red trash → confirm → removes from Sheet + DB + KVK).
  **Select checkboxes** allow **bulk delete**. Cells expand inline when text is
  too long; the address has a copy button.
- **Emails** (`emails/page.tsx`) — scrollable activity list with a date filter,
  Connect-Gmail banner, per-row Send, and "Send all queued". Click a row to read
  the full email (renders the HTML).
- **Dashboard** (`dashboard/page.tsx`) — totals + the "Emails sent over time"
  chart. Clicking a bar jumps to the Emails list filtered to that date.

### The bid email — `lib/email-template.ts`

Builds the Dutch bid letter (subject + plain text + styled HTML) from a
property's data: agency name, address, and the **bidding price** (the tiered/
capped value). Sent via the backend, which delivers it through Gmail.

---

## 6. How data flows (end to end)

```
1. SCRAPE   funda/ collects + scrapes → writes rows to Google Sheet
2. SYNC     backend/services/sheet_sync.py reads Sheet → upserts Postgres
3. SHOW     web/ calls backend api/ → renders the Global Data table
4. BID      services/bidding.py decides the price (DB value + Sheet formula)
5. EMAIL    you click Send → api/emails → services/email_service → Gmail
6. RECORD   email saved in DB + mirrored to the "Emails" Sheet tab
```

---

## 7. Where things run (deployment)

- **VPS** at `173.212.246.224`, domain `sons.business` (Nginx + Let's Encrypt).
- **systemd services:** `datainfo-backend` (FastAPI/uvicorn) and
  `datainfo-frontend` (Next.js). The scraper runs inside the backend process.
- **Code path on server:** `/opt/datainfo/` (mirrors this repo).
- **Deploy** = copy changed files to `/opt/datainfo/`, then
  `systemctl restart datainfo-backend` (and rebuild + restart the frontend for
  web changes).
- **Secrets** (`.env`, Google credential JSONs) live on the server and are
  **gitignored** — never committed.

---

## 8. Quick "where do I change X?" cheat sheet

| I want to change… | Edit this |
|---|---|
| The bidding price rule | `backend/app/services/bidding.py` (+ keep the formula copy in `funda/.../sheets_writer.py` in sync) |
| The bid email wording/look | `web/src/lib/email-template.ts` |
| Scraper behaviour / timeouts | `funda/src/config/settings.py` + `funda/src/modules/scraper_controller.py` |
| How agency emails are found | `funda/src/modules/agency_scraper.py` |
| The Global Data table columns | `web/src/components/properties-table/columns.ts` |
| A database table | `backend/app/db/models.py` (then an Alembic migration) |
| An API route | `backend/app/api/…` (logic goes in `backend/app/services/…`) |

---

## 9. Tests

`backend/tests/` (pytest). Currently covers the bidding rule (tiers + cap +
formula). Run with:

```bash
cd backend && pytest
```

Add tests here for any logic that keeps changing.
