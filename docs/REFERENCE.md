# Paceboard

A local-first personal fitness analytics application. It continuously ingests
your Garmin and Strava data into a SQLite database on your own machine,
normalizes it, derives training and recovery analytics from it, and serves it to
a dense React dashboard through a local REST API.

Nothing about the data pipeline depends on an LLM. Claude and MCP are optional
interfaces *on top of* the resulting database — Paceboard ships a read-only MCP
server for exactly that — but they are never the thing that moves data.

```
Garmin MCP (read-only) ──┐
                          ├──▶ provider adapters ──▶ ingestion + scheduler
Strava REST API ─────────┘                               │
                                                         ├──▶ raw payload store
                                                         ├──▶ normalized SQLite
                                                         ├──▶ derived analytics
                                                         └──▶ REST API (:8787)
                                                                    │
                                                          React dashboard (:3000)
```

Everything binds to `127.0.0.1`. Your health data does not leave the machine.

---

## Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Authenticating Garmin](#authenticating-garmin)
- [Starting Garmin MCP safely](#starting-garmin-mcp-safely)
- [Starting Paceboard](#starting-paceboard)
- [Connecting Strava](#connecting-strava)
- [Environment variables](#environment-variables)
- [Backfill and sync behaviour](#backfill-and-sync-behaviour)
- [Data model and storage](#data-model-and-storage)
- [Derived analytics](#derived-analytics)
- [REST API](#rest-api)
- [The Paceboard MCP server](#the-paceboard-mcp-server)
- [Privacy and security](#privacy-and-security)
- [Backups](#backups)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Extending Paceboard](#extending-paceboard)
- [Repository layout](#repository-layout)

---

## Architecture

| Layer | Location | What it does |
|---|---|---|
| Garmin MCP server | `src/garmin_mcp/` | The existing 110-tool MCP server. Paceboard talks to it over streamable HTTP and only ever calls read tools. See [GARMIN_MCP.md](../GARMIN_MCP.md). |
| Provider adapters | `src/paceboard_api/providers/` | `GarminMcpProvider` and `StravaApiProvider` behind one `FitnessProvider` protocol. They return typed DTOs and keep the original response alongside. |
| Ingestion | `src/paceboard_api/ingest/` | Raw payload store, normalizers, cross-provider deduplication, the sync orchestrator, and the APScheduler jobs. |
| Storage | `src/paceboard_api/db/` | SQLAlchemy 2.x models over SQLite, with Alembic migrations. |
| Analytics | `src/paceboard_api/analytics/` | Pure formula functions plus a service that computes and persists derived metrics with full provenance. |
| REST API | `src/paceboard_api/api/` | FastAPI, versioned at `/api/v1`, documented at `/docs`. |
| Dashboard | `dashboard/` | React 18 + TypeScript + Vite, TanStack Query, Recharts. Talks only to the Paceboard API. |
| Paceboard MCP | `src/paceboard_api/mcp_server/` | Read-only MCP server over the normalized database. Optional. |

### Two design rules worth knowing up front

**Garmin is reached only through MCP.** Paceboard never imports
`python-garminconnect`. The MCP server owns the Garmin session and its tokens;
Paceboard sees tool responses and nothing else. This is what keeps working while
Garmin's Developer Program is closed.

**A metric that cannot be computed says so.** Absent data is never rendered as
zero, and never estimated from a proxy. Every derived metric returns either a
value with its formula version and input sources, or an explicit reason it is
unavailable — which the dashboard prints verbatim.

---

## Prerequisites

- **Python 3.10+** (3.12 recommended) and [`uv`](https://docs.astral.sh/uv/)
- **Node.js 22+** and npm
- A **Garmin Connect account**
- Optionally, a **Strava account** (everything works without one)

No Docker is required. The whole app is three processes plus a SQLite file.

---

## Installation

```bash
git clone https://github.com/mariusdale/paceboard.git garmin_mcp
cd garmin_mcp

make install          # uv sync --extra paceboard, then npm install in dashboard/

cp .env.example .env
chmod 600 .env        # it will hold your Strava secret
```

---

## Authenticating Garmin

Once, interactively. Tokens are written to `~/.garminconnect` and reused
afterwards; Paceboard never sees them.

```bash
uv run garmin-mcp-auth
```

Follow the prompts, including the MFA code if your account uses one. Tokens last
roughly a year. Re-run this command when they expire.

---

## Starting Garmin MCP safely

```bash
./scripts/garmin-mcp-readonly.sh
```

This starts the MCP server on `http://127.0.0.1:8000/mcp` with an allowlist of
**82 read-only tools** — every tool Paceboard maps, and nothing else. Tools that
create, upload, edit, schedule, set, log, import or delete anything are not
registered at all, so they cannot be invoked even by a bug.

The allowlist is generated from the tool catalog, and the generator refuses to
emit a tool matching a mutating name pattern:

```bash
make allowlist        # regenerates scripts/garmin-mcp-readonly.sh
```

Verify it is up:

```bash
curl http://127.0.0.1:8000/healthz     # -> ok
make smoke                             # lists mapped/unmapped tools, makes one read call
```

> The MCP transport performs no authentication. The script binds to loopback and
> you should keep it there — anything that can reach the port can read your
> entire Garmin history.

---

## Starting Paceboard

In a second terminal:

```bash
make dev              # or: ./scripts/dev.sh
```

That applies migrations, starts the API and the dashboard, and prints:

```
  Paceboard is running (loopback only)

    Dashboard   http://127.0.0.1:3000
    REST API    http://127.0.0.1:8787/api/v1
    API docs    http://127.0.0.1:8787/docs
    Garmin MCP  http://127.0.0.1:8000/mcp
```

**Open http://127.0.0.1:3000.** Then either press **Sync now** in the header, or
run the initial backfill from the shell:

```bash
make backfill                                     # the configured window, 90 days
uv run --extra paceboard paceboard-api sync --mode backfill --days 365
```

A 90-day Garmin backfill takes a few minutes: it walks roughly 15 tools per day
plus per-activity detail and FIT streams, with bounded concurrency so Garmin does
not rate-limit you.

### Individual processes

```bash
make api        # API only
make web        # dashboard only
make migrate    # migrations only
make sync       # one incremental sync, then exit
```

---

## Connecting Strava

Paceboard is fully functional on Garmin data alone. Until Strava credentials
exist, the Connections page shows **"Strava not connected"** and every Strava
route returns a typed, explicit not-configured response.

To connect:

1. Go to <https://www.strava.com/settings/api> and create an application. Fill
   the form in like this:

   | Field | Value | Why |
   |---|---|---|
   | Application Name | `Paceboard` | Free text; shown on the consent screen. |
   | Category | `Training` | Free choice, no effect. |
   | Website | `http://127.0.0.1:3000` | Required but cosmetic — Strava never fetches it and it plays no part in OAuth. Any real URL works if the validator objects. |
   | Authorization Callback Domain | `127.0.0.1` | **The one that matters.** |

2. **Authorization Callback Domain must be exactly `127.0.0.1`** — domain only,
   no `http://`, no port, no path. Strava matches it against the *host* of the
   redirect URI, and since a port is not part of the domain, `127.0.0.1` covers
   Paceboard's `http://127.0.0.1:8787/api/v1/auth/strava/callback`.

   Use `127.0.0.1`, not `localhost`: Strava treats them as different hosts, and
   `STRAVA_REDIRECT_URI` defaults to `127.0.0.1`. If you prefer `localhost`,
   change both to match. This is the field people get wrong most often.

3. Copy the Client ID and Client Secret into `.env`:

   ```dotenv
   STRAVA_CLIENT_ID=123456
   STRAVA_CLIENT_SECRET=your-secret-here
   STRAVA_REDIRECT_URI=http://127.0.0.1:8787/api/v1/auth/strava/callback
   ```

4. Restart the Paceboard API.
5. Open **Connections → Strava → Connect Strava** and approve the request.

Paceboard requests read-only scopes (`read,activity:read_all,profile:read_all`)
and never writes to Strava. Tokens are encrypted at rest and refreshed
automatically; **Disconnect and revoke** deauthorizes at Strava and deletes the
local file.

### Webhooks

The webhook endpoints are implemented (`GET`/`POST /api/v1/auth/strava/webhook`)
but a loopback-bound Paceboard is not reachable from Strava's servers, so local
installs fall back to polling every `STRAVA_POLL_MINUTES`. If you expose the API
through a tunnel, set `STRAVA_WEBHOOK_VERIFY_TOKEN` and register the
subscription; no code changes are needed.

---

## Environment variables

Everything lives in `.env`; see [`.env.example`](.env.example) for the annotated
full list. The ones you are most likely to change:

| Variable | Default | Meaning |
|---|---|---|
| `GARMIN_MCP_URL` | `http://127.0.0.1:8000/mcp` | Where the Garmin MCP server listens |
| `PACEBOARD_HOST` | `127.0.0.1` | API bind address; non-loopback is refused unless you opt in |
| `PACEBOARD_API_PORT` | `8787` | REST API port |
| `PACEBOARD_WEB_PORT` | `3000` | Dashboard port |
| `PACEBOARD_TIMEZONE` | `Europe/Oslo` | Display timezone; storage is always UTC |
| `PACEBOARD_DATABASE_PATH` | `./data/paceboard.sqlite3` | Database location |
| `PACEBOARD_BACKFILL_DAYS` | `90` | Initial backfill window |
| `PACEBOARD_FAST_INTERVAL_MINUTES` | `15` | Cadence for today's health and recent activities |
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | empty | Strava application credentials |

---

## Backfill and sync behaviour

Three modes, all idempotent — running the same window twice produces the same
database:

| Mode | Window | Typical trigger |
|---|---|---|
| `today` | today only | the 15-minute job |
| `incremental` | last `PACEBOARD_RECONCILE_DAYS` days | Sync now, the daily job |
| `backfill` | last `PACEBOARD_BACKFILL_DAYS` days | first run, or after adding a provider |

The scheduler runs three jobs:

| Job | Cadence | What it calls |
|---|---|---|
| fast | every 15 min | today's health snapshot + recent activities, plus detail/streams for anything new |
| daily | 04:15 local | reconciles the last 3 days, refreshes trends, account metadata and gear |
| derived | every 6 h | recomputes CTL/ATL/TSB, weekly volume, monotony and strain |

Only the `fast`-cadence tools run every quarter-hour. Calling all 50-odd mapped
tools that often would exhaust your rate budget for no benefit.

**Enrichment is resumable.** Activity detail and FIT streams are fetched in
batches (25 details, 10 stream sets per run) against a per-record watermark, so a
large backfill drains over consecutive runs instead of hammering Garmin once.

**Partial success is a first-class outcome.** One tool erroring does not abort
the run; the run finishes as `partial` and the failure is recorded against that
capability. Absences (`no data`, `unsupported`) are recorded but are *not* errors.

A long backfill can be cancelled from **Connections → Cancel run**, or
`POST /api/v1/sync/{id}/cancel`.

---

## Data model and storage

SQLite at `./data/paceboard.sqlite3` (WAL mode, `0600` permissions), 28 tables.
Expect roughly 20–40 MB per year of training; **Connections → Storage** shows the
live figure and per-table row counts.

- **Provider plumbing** — `provider_connections`, `provider_capabilities`,
  `sync_runs`, `sync_errors`, `sync_watermarks`, `raw_payloads`
- **Identity** — `athletes`, `devices`, `gear`, `heart_rate_zones`
- **Activities** — `activities` (canonical), `activity_source_records` (one per
  provider), `activity_laps`, `activity_splits`, `activity_zones`,
  `activity_streams`, `duplicate_candidates`
- **Daily health** — `daily_health`, `sleep_records`, `hrv_records`,
  `stress_records`, `body_battery_records`, `body_composition`
- **Training** — `training_status`, `training_load`, `performance_metrics`,
  `derived_metrics`
- **Preferences** — `app_settings`

Conventions that hold everywhere:

- Provider IDs are **strings** (Garmin activity ids exceed 2^53).
- Timestamps are **UTC**; the provider's local string and UTC offset are kept
  alongside.
- Every row carries its **source**.
- Raw payloads are kept verbatim with their endpoint, parameters, retrieval time
  and schema version — including the ones that returned nothing, which is what
  makes the Data Explorer's coverage view honest. The one exception is FIT
  per-sample record pages: their provenance row is stored but the body is not,
  because those samples are already kept compressed in `activity_streams` and
  duplicating them as JSON would add hundreds of megabytes a year. The row says
  so explicitly rather than appearing empty.
- Streams are stored one row per channel, zlib-compressed.

### Cross-provider deduplication

A Garmin-recorded ride usually appears in Strava minutes later. Paceboard keeps
**both** raw records forever and decides whether they describe the same session:

- an explicit provider link (Strava's `external_id` naming the Garmin activity,
  or a shared `upload_id`) is decisive;
- otherwise sport family must be compatible and starts must fall within
  `PACEBOARD_DEDUPE_START_TOLERANCE_SECONDS`, after which duration and distance
  agreement are scored continuously rather than pass/fail;
- score ≥ 0.85 merges automatically, ≥ 0.55 goes to the **review strip** at the
  top of the Activities page, below that stays separate.

When merged, each canonical field is chosen by an explicit preference order —
Garmin for device-native measurements and physiology, Strava for its own title
and social metadata — and the winner is recorded in `field_provenance`, which the
activity detail page will show you on request.

---

## Derived analytics

All formulas live in `src/paceboard_api/analytics/formulas.py`, are pure, are
individually unit-tested, and return `None` rather than a guess:

| Metric | Formula | Needs |
|---|---|---|
| CTL / ATL | exponentially weighted 42-day / 7-day average of daily TRIMP | activities with HR |
| TSB (form) | CTL − ATL | the above |
| TRIMP | Banister: `min × HRr × 0.64 × e^(k·HRr)` | avg HR, resting HR, max HR |
| Monotony / strain | Foster: `mean/SD` over 7 days, `weekly load × monotony` | ≥ 3 training days |
| Normalized power | Coggan: 30 s rolling average, 4th power, 4th root | ≥ 30 s of power |
| Intensity factor / TSS | `NP/FTP`, `(s·NP·IF)/(FTP·3600)·100` | power + a recorded FTP |
| Aerobic decoupling | `(EF₁ − EF₂)/EF₁ × 100` over session halves | ≥ 20 paired HR samples |
| Grade-adjusted pace | Minetti metabolic cost polynomial, valid to ±45 % | speed + grade |
| Power/pace curves | best sustained average per duration | streams |
| Best efforts | fastest time over each target distance | distance + time streams |
| HRV baseline | 7-night trailing mean, plus % deviation | 7 nights of HRV |
| Resting-HR baseline | 28-day trailing mean | 28 days |
| Sleep debt | shortfall vs 8 h over 7 nights, floored at zero | sleep records |
| Sleep consistency | bedtime SD mapped to 0–100, zero at 120 min SD | ≥ 3 bedtimes |
| Correlations | Pearson *r* with sample size | ≥ 5 paired days |

Persisted derived metrics record their **formula version**, **input sources**,
**units** and **calculation time**. Bump `FORMULA_VERSION` when a formula
changes, so old values stay identifiable rather than being silently rewritten.

Garmin's own acute/chronic load is ingested and displayed **alongside**
Paceboard's TRIMP-based series, never blended into it — the two use different
units and averaging them would be meaningless.

---

## REST API

OpenAPI at <http://127.0.0.1:8787/docs>. Every route is under `/api/v1`.

```bash
# Status, connections, capabilities
curl -s localhost:8787/api/v1/status | jq '.counts'
curl -s localhost:8787/api/v1/connections | jq '.[].status'
curl -s 'localhost:8787/api/v1/capabilities?status=unavailable' | jq '.[].name'

# Sync
curl -s -X POST localhost:8787/api/v1/sync \
  -H 'Content-Type: application/json' \
  -d '{"providers":["garmin"],"mode":"backfill"}'
curl -s localhost:8787/api/v1/sync/latest | jq '{status, records_written, errors}'

# Activities
curl -s 'localhost:8787/api/v1/activities?sport=run&limit=10' | jq '.page'
curl -s localhost:8787/api/v1/activities/1 | jq '{name, sport, distance_m, field_provenance}'
curl -s 'localhost:8787/api/v1/activities/1/streams?channels=heartrate,velocity_smooth&max_points=500' | jq '.point_count'
curl -s localhost:8787/api/v1/activities/1/analysis | jq '.metrics.aerobic_decoupling'

# Health and training
curl -s 'localhost:8787/api/v1/health/daily?days=30' | jq 'length'
curl -s localhost:8787/api/v1/health/recovery/summary | jq '.hrv_deviation'
curl -s 'localhost:8787/api/v1/training/load?days=90' | jq '{ctl: .ctl[-1], tsb: .tsb[-1]}'
curl -s 'localhost:8787/api/v1/training/zones?days=90' | jq '.distribution'

# Raw provider data and exports
curl -s 'localhost:8787/api/v1/raw-data?status=no_data&limit=5' | jq '.items[].endpoint'
curl -s 'localhost:8787/api/v1/export.csv?dataset=daily_health&days=90' -o daily_health.csv
```

Errors are always the same shape:

```json
{"error": {"code": "not_found", "message": "Activity 9999 was not found", "detail": null}}
```

Codes: `bad_request`, `validation_error`, `not_found`, `conflict`,
`payload_too_large`, `provider_unavailable`, `internal_error`.

---

## The Paceboard MCP server

Optional, read-only, and backed by the **normalized database** — it never
contacts Garmin or Strava. If a number is missing there, run a sync; do not call
this server harder.

```bash
uv run --extra paceboard paceboard-mcp                 # stdio
PACEBOARD_MCP_TRANSPORT=streamable-http \
  uv run --extra paceboard paceboard-mcp               # http://127.0.0.1:8788/mcp
```

Tools: `query_activities`, `get_activity_analysis`, `get_recovery_summary`,
`get_training_load`, `compare_periods`, `find_correlations`,
`get_data_freshness`.

For Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "paceboard": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/garmin_mcp", "run",
               "--extra", "paceboard", "paceboard-mcp"],
      "env": { "PACEBOARD_DATABASE_PATH": "/absolute/path/to/garmin_mcp/data/paceboard.sqlite3" }
    }
  }
}
```

> If you previously configured a `paceboard` MCP entry pointing at
> `PACEBOARD_URL=http://localhost:3000`, that was the old Claude-mediated
> ingestion bridge. It has been retired (kept for reference under
> `legacy/paceboard_mcp_bridge/`); replace the entry with the block above.

---

## Privacy and security

- **Loopback by default.** Binding elsewhere is refused unless you set
  `PACEBOARD_ALLOW_NON_LOOPBACK=true`, and even then the API has no
  authentication — put a reverse proxy with auth in front of it first.
- **Credentials never reach the browser.** Garmin tokens stay with the MCP
  server; Strava tokens stay in the backend. No API route returns token material.
- **Encrypted Strava tokens.** Sealed with Fernet using a key at
  `data/paceboard.key`, mode `0600`. Honest limitation: the key sits beside the
  token file, so this protects against a leaked backup or a synced folder, not
  against an attacker who already has your user account.
- **Redacting logs.** Structured logs record tool name, argument *keys*,
  duration and status. Response bodies are never logged, and a filter scrubs
  anything token-shaped even if a dependency logs it.
- **Maps are off by default.** A GPS trace is the most identifying data here, so
  routes are hidden until you turn them on, and even then Paceboard draws them
  locally as an SVG polyline with **no network request**. Fetching map tiles is a
  separate opt-in, because it would send your coordinates to a tile server.
- **No mutating Garmin tools.** Enforced in three places: the launch script's
  allowlist, the MCP client, and the API's tool-invocation route.
- **Request limits and validation.** Bodies are capped at 2 MB; date ranges,
  pagination, tool names and tool arguments are all validated.
- **Your data is deletable and exportable.** Scoped CSV/JSON exports per dataset,
  and **Connections → Delete stored data** (raw / derived / everything), gated on
  typing the scope back.
- **No third-party analytics or error reporting.** Nothing is sent anywhere.
- `.env`, `data/`, `.e2e/` and token files are git-ignored.

---

## Backups

The database is a single file. Back it up with SQLite's own backup command so
you get a consistent copy even while the app is running:

```bash
sqlite3 data/paceboard.sqlite3 ".backup 'backups/paceboard-$(date +%F).sqlite3'"
```

Restore by stopping Paceboard and copying the file back. `data/paceboard.key` is
needed to decrypt Strava tokens — back it up separately from the database, or
simply reconnect Strava after a restore.

---

## Testing

```bash
make test           # backend tests + frontend typecheck and lint
make check          # the above plus a production dashboard build
make e2e            # Playwright, in fixture mode

uv run --extra paceboard pytest -q -m "not e2e"     # backend only
uv run --extra paceboard pytest tests/paceboard -q  # Paceboard only
cd dashboard && npm run typecheck && npm run lint && npm run build
```

The Playwright suite runs against **fixture mode**: a scratch database under
`.e2e/` seeded with clearly labelled synthetic data and a deliberately
unreachable Garmin MCP, so it needs no account and touches no real data.

To browse the UI with fixture data yourself:

```bash
PACEBOARD_DATABASE_PATH=./data/fixtures.sqlite3 \
  uv run --extra paceboard paceboard-api seed-fixtures --days 90
PACEBOARD_DATABASE_PATH=./data/fixtures.sqlite3 PACEBOARD_FIXTURE_MODE=true make dev
```

Every fixture row is stored with `source="fixture"` and the dashboard shows a
persistent banner. `seed-fixtures` refuses to run against a database that already
contains real activity records.

---

## Troubleshooting

**`Cannot reach Garmin MCP` / the Connections page shows Garmin disconnected**
Check `curl http://127.0.0.1:8000/healthz`. If it fails, start
`./scripts/garmin-mcp-readonly.sh`. If `GARMIN_MCP_URL` points at another port,
make sure `.env` and the server agree.

**`Garmin authentication expired`**
Your Garmin tokens lapsed. Run `uv run garmin-mcp-auth` and restart the MCP
server. Paceboard picks up automatically on the next sync.

**Garmin rate limits (429)**
The client backs off exponentially with jitter, starting at 20 s for rate limits.
If you keep hitting them, lower `GARMIN_MCP_CONCURRENCY` to 1–2 and backfill in
shorter windows (`--days 30`) rather than a year at once.

**A tool shows as `unavailable` in the Data Explorer**
The MCP server did not register it. Either it is filtered by
`GARMIN_ENABLED_TOOLS`, or the installed server version predates it. Paceboard
records the capability as unavailable and carries on; nothing else breaks.

**A tool shows `unsupported` / "Your device does not support this metric"**
Your watch does not record it. Running tolerance, endurance score and hill score
are the usual ones. This is an absence, not an error, and is recorded as such.

**`Date range too large (61 days). Maximum is 30 days.`**
Handled automatically — those tools declare `max_range_days` in the catalog and
the provider splits the window. If you see it from a manual Data Explorer call,
shorten the range.

**Strava rate limits**
Strava allows 100 reads / 15 min and 1000 / day. Paceboard tracks the
`X-RateLimit-*` headers (visible on the Connections page) and backs off from 60 s
on a 429. A large backfill may need to resume in the next window; it is
resumable, so just run it again.

**Strava callback fails**
The **Authorization Callback Domain** must be exactly `127.0.0.1` — not
`localhost`, not a URL. `STRAVA_REDIRECT_URI` must match `PACEBOARD_API_PORT`.

**Sync says `partial`**
One or more capabilities failed while the rest succeeded. Open
**Connections → Sync → Issues in this run** for the specific tool and message.

**Port already in use**
Change `PACEBOARD_API_PORT` / `PACEBOARD_WEB_PORT` in `.env`, or stop the other
process. The dashboard's dev server uses `strictPort`, so it fails loudly rather
than silently moving.

**The dashboard is empty after a sync**
Check `GET /api/v1/status` → `counts`. If they are zero, look at
`GET /api/v1/sync/latest` → `errors`.

---

## Extending Paceboard

### Adding a Garmin MCP tool

1. Add a `ToolSpec` to `src/paceboard_api/providers/garmin/catalog.py`, giving it
   a category, scope (`daily` / `range` / `activity` / `account`), cadence,
   expected argument names, and a `handler` name. Set `max_range_days` if the
   tool caps its window. The catalog rejects mutating names at import time.
2. Write the handler in `src/paceboard_api/ingest/normalize_garmin.py`, decorated
   with `@handler("your_handler_name")`. Return the number of rows written, and
   leave absent provider fields as `None`.
3. Add a migration if you needed new columns:
   `uv run --extra paceboard alembic revision --autogenerate -m "add x"`.
4. Regenerate the launch allowlist: `make allowlist`.
5. Add a fixture and a test in `tests/paceboard/`. `test_normalization.py`
   asserts every scheduled tool has a registered handler.

### Adding a provider

1. Implement the `FitnessProvider` protocol from
   `src/paceboard_api/providers/base.py`. Return DTOs plus the untouched
   `ProviderResult`s.
2. Add a normalizer module exposing `get_handler(name)`.
3. Register the adapter in `src/paceboard_api/providers/registry.py` and add its
   name to `PROVIDER_NAMES`.
4. Add its sport mapping and, if it can record the same session as an existing
   provider, its field preference order in `src/paceboard_api/ingest/activities.py`.

Nothing in the API, analytics or dashboard needs to change.

---

## Repository layout

```
src/garmin_mcp/          The Garmin MCP server (unchanged; see GARMIN_MCP.md)
src/paceboard_api/       The Paceboard backend
  config.py              Settings from the environment
  db/                    SQLAlchemy models and session handling
  migrations/            Alembic
  providers/             Provider adapters (garmin/, strava/) and the registry
  ingest/                Raw store, normalizers, dedupe, sync, scheduler
  analytics/             Formulas and the analytics service
  api/                   FastAPI routers and schemas
  mcp_server/            Read-only MCP over the normalized database
  fixtures_mode.py       Labelled synthetic data for development and e2e
dashboard/               React + TypeScript dashboard
  src/pages/             Overview, Activities, Activity detail, Recovery,
                         Training, Data Explorer, Connections
  e2e/                   Playwright
scripts/                 garmin-mcp-readonly.sh, dev.sh, e2e-server.sh
tests/paceboard/         Paceboard test suite and fixtures
tests/unit|integration/  The existing Garmin MCP tests
legacy/                  Retired implementations, kept for reference
data/                    Your database and tokens (git-ignored)
```

### About `legacy/`

Two earlier implementations were retired rather than deleted:

- `legacy/paceboard-sites-dashboard/` — the previous hosted Cloudflare/Sites
  dashboard. **It contains its own nested `.git` repository, left untouched**, so
  its history survives in place. It is git-ignored by the outer repository rather
  than embedded as a submodule or gitlink, so the two histories stay independent
  and neither can clobber the other. Nothing in the running app depends on it.
- `legacy/paceboard_mcp_bridge/` — the MCP bridge that had Claude carry data into
  the dashboard. Paceboard now ingests directly, so this is no longer used.

---

## Credits and licence

Paceboard is MIT licensed. It is built on top of
[**Taxuspt/garmin_mcp**](https://github.com/Taxuspt/garmin_mcp) by Alexandre
Domingues and its contributors — also MIT — which provides the Garmin Connect MCP
server in `src/garmin_mcp/` that Paceboard reads all Garmin data through. That
work is unmodified here; Paceboard treats it as the provider boundary and adds
the ingestion pipeline, database, analytics, REST API and dashboard around it.

If you find a bug in Garmin tool coverage or in a Garmin response shape, it very
likely belongs upstream — please report it at
<https://github.com/Taxuspt/garmin_mcp/issues> so everyone benefits.

Both copyright notices are in [LICENSE](../LICENSE).

## Using this yourself

Paceboard reads *your* Garmin account, so there is nothing to sign up for and no
server to share. Anyone who wants to run it does the same thing you did:

```bash
git clone https://github.com/mariusdale/paceboard.git paceboard
cd paceboard
make install
cp .env.example .env
uv run garmin-mcp-auth          # their own Garmin login
./scripts/garmin-mcp-readonly.sh
make dev                        # second terminal
```

Their data lives in their own `data/paceboard.sqlite3` and never leaves their
machine. Nothing in this repository is shared between installations.

## Built dashboard service

`npm --prefix dashboard run build` builds the dashboard;
`npm --prefix dashboard start` serves that build at **http://127.0.0.1:3001**
and forwards API requests to the local Paceboard backend on port 8787.
Use `PACEBOARD_WEB_PORT` and `PACEBOARD_API_PORT` to override those ports.
The server binds only to loopback and does not require a Vite development session.
Rebuild after frontend edits. The backend and Garmin MCP must also be running.
