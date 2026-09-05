# Paceboard

Your Garmin and Strava data, together in a personal dashboard. Follow sleep,
HRV, recovery, activity and training with a midnight theme, interactive charts,
and a clear view of what your devices have actually measured.

**Runs on your computer. Uses your accounts. No hosted account or AI subscription required.**

- Sleep score, duration and stages, plus trends over time
- HRV, resting heart rate, Body Battery and training readiness where supported
- Combined Garmin and Strava activity history, filters and session details
- Training volume, load, fitness and fatigue with documented calculations
- Automatic syncing, CSV/JSON exports and local data deletion

Missing measurements are marked as unavailable. Device support and account
history determine which metrics you see. This project is independent of Garmin
and Strava and builds on [Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp).

## Get started

Supported setup: **macOS or Linux**. On Windows, use **WSL2** and run the same
commands inside your Linux terminal. Native Windows setup is not supported yet.

Install [Node.js 22 or newer](https://nodejs.org/),
[uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Git](https://git-scm.com/downloads). The setup script installs Python 3.12
through uv and uses the checked-in dependency lockfiles.

```bash
git clone https://github.com/mariusdale/paceboard.git
cd paceboard
./scripts/setup.sh
./scripts/start.sh
```

The setup asks for your timezone, helps you sign in to Garmin (including MFA),
and optionally configures Strava. Password entry is hidden; your Garmin password
is not saved by the setup wizard. Rerunning setup preserves existing configuration
unless you explicitly enter replacement values.

The start command launches all three services and opens
[the dashboard](http://127.0.0.1:3000). If your browser does not open automatically,
visit that address yourself. Keep the terminal open; **Ctrl-C** stops the app.
Your data stays saved for the next run.

### Bring in your history

1. Open **Connections** in the dashboard.
2. If you configured Strava, click **Connect** and approve access in Strava.
3. Under **Sync → Backfill history**, choose **Last 90 days**, **Last 365 days**,
   or **Custom number of days** (1–3,650), then click **Backfill**.
   All windows include today; your saved default remains available.
4. Watch the sync status, then open **Overview**. A large import may take time;
   provider rate limits can delay it. Rerun the backfill to resume.

The running app checks recent data every 15 minutes. Use **Sync now** for a fresh
read. The app must be running, and your watch must have uploaded to Garmin
Connect, for new measurements to appear.

### Optional Strava setup

Garmin works without Strava. To add Strava, create your own application in
[Strava API settings](https://www.strava.com/settings/api), then enter its Client
ID and Client Secret in the setup wizard. Do not use or share someone else's secret.

| Strava setting | Value |
| --- | --- |
| Website | `http://127.0.0.1:3000` |
| Authorization Callback Domain | `127.0.0.1` |

The default callback URL is
`http://127.0.0.1:8787/api/v1/auth/strava/callback`.
If you change the API port, update `STRAVA_REDIRECT_URI` in `.env` too.
Strava controls API eligibility and application limits; check its current
[developer documentation](https://developers.strava.com/docs/getting-started/)
if API settings are unavailable for your account.

You can add Strava later by rerunning setup, then restarting the app and
clicking Connect in Connections. Secrets stay in your local `.env`; provider
tokens stay on the backend.

## Everyday use

```bash
./scripts/start.sh      # start everything; Ctrl-C to stop
```

To update, stop the app, then run:

```bash
git pull --ff-only
./scripts/setup.sh
./scripts/start.sh
```

Your `.env`, database and tokens are excluded from Git. Back up your data before
upgrading; see [backup instructions](docs/REFERENCE.md#backups).

## If something goes wrong

| Problem | Next step |
| --- | --- |
| Missing uv, Node or npm | Install the prerequisites above, reopen your terminal and rerun setup. |
| A port is already in use | Stop the existing Paceboard instance. The launcher never stops someone else's process. |
| Garmin sign-in expired | Stop the app, run `uv run --python 3.12 garmin-mcp-auth`, then start again. |
| Empty dashboard | Open Connections, check provider status, then run Backfill. |
| Strava callback fails | Use `127.0.0.1`, not `localhost`, in the callback domain and URL. |
| A service fails to start | Read `data/logs/garmin.log`, `api.log`, or `dashboard.log`. Remove personal information before sharing logs. |
| Some health metrics are missing | Check device support and watch sync. Missing data is not replaced with invented scores. |

## Your data and privacy

All services bind to `127.0.0.1`. This is a single-user local app; it has no
network login system. Do not expose its ports publicly.

- Garmin session tokens default to `~/.garminconnect`; Strava tokens and the
  database default to `data/` in your checkout.
- Garmin and Strava requests use your own accounts. Map tiles, if you opt in,
  contact a third-party tile service. There is no third-party analytics.
- `.env`, local databases, logs, backups and exported GPS files are ignored by Git.
- Export or delete stored data from **Connections**. Uninstalling code alone does
  not delete your data or Garmin tokens.

## Development and contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development, tests and pull requests,
[SECURITY.md](SECURITY.md) for reporting vulnerabilities, and the
[technical reference](docs/REFERENCE.md) for architecture, settings and API details.

Licensed under [MIT](LICENSE), retaining the original Garmin MCP attribution.
