"""``paceboard-api`` — run the server, migrate, or trigger a sync from the shell."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta

from .config import get_settings
from .logging_conf import configure_logging, get_logger

log = get_logger("paceboard.cli")


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config
    from .config import REPO_ROOT

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "src/paceboard_api/migrations"))
    command.upgrade(config, "head")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paceboard-api", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the API server (default)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--no-migrate", action="store_true",
                       help="Skip the automatic 'alembic upgrade head' on start")

    sub.add_parser("migrate", help="Apply database migrations and exit")

    sync_cmd = sub.add_parser("sync", help="Run one sync and exit")
    sync_cmd.add_argument("--mode", choices=("incremental", "backfill", "today"),
                          default="incremental")
    sync_cmd.add_argument("--days", type=int,
                          help="Override the window size, in days")
    sync_cmd.add_argument("--providers", default="garmin,strava")
    sync_cmd.add_argument("--no-enrich", action="store_true")

    sub.add_parser("smoke", help="Read-only Garmin MCP connectivity check")

    seed = sub.add_parser(
        "seed-fixtures",
        help="Fill the database with clearly labelled synthetic data (development only)",
    )
    seed.add_argument("--days", type=int, default=90)

    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    command = args.command or "serve"

    if command == "migrate":
        _run_migrations()
        print(f"Database migrated: {settings.database_path}")
        return 0

    if command == "sync":
        _run_migrations()
        from .ingest.sync import SyncRequest, run_sync

        end = date.today()
        start = end - timedelta(days=args.days - 1) if args.days else None
        request = SyncRequest(
            providers=tuple(p.strip() for p in args.providers.split(",") if p.strip()),
            mode=args.mode, start=start, end=end, trigger="cli",
            enrich=not args.no_enrich,
        )
        run_id = asyncio.run(run_sync(request))
        print(f"Sync run {run_id} finished. See GET /api/v1/sync/{run_id}.")
        return 0

    if command == "seed-fixtures":
        _run_migrations()
        from .db.session import session_scope
        from .fixtures_mode import FixtureRefused, seed

        try:
            with session_scope() as session:
                written = seed(session, days=args.days)
        except FixtureRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Seeded fixture data into {settings.database_path}: {written}")
        print("Every row is labelled source='fixture'. Start the API with "
              "PACEBOARD_FIXTURE_MODE=true so the dashboard says so.")
        return 0

    if command == "smoke":
        return asyncio.run(_smoke(settings))

    if not getattr(args, "no_migrate", False):
        _run_migrations()

    import uvicorn

    host = getattr(args, "host", None) or settings.host
    port = getattr(args, "port", None) or settings.api_port
    print(f"Paceboard API   http://{host}:{port}")
    print(f"OpenAPI docs    http://{host}:{port}/docs")
    uvicorn.run(
        "paceboard_api.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=getattr(args, "reload", False),
        log_config=None,
    )
    return 0


async def _smoke(settings) -> int:
    """Verify the Garmin MCP is reachable without printing any personal value."""
    from .providers.garmin.provider import GarminMcpProvider

    provider = GarminMcpProvider.from_settings(settings)
    try:
        ok, detail = await provider.health()
        if not ok:
            print(f"Garmin MCP unreachable: {detail}", file=sys.stderr)
            return 1
        capabilities = await provider.discover_capabilities()
        available = [c for c in capabilities if c.status == "available"]
        unavailable = [c for c in capabilities if c.status == "unavailable"]
        unmapped = [c for c in capabilities if c.status == "unmapped"]
        print(f"Garmin MCP OK at {settings.garmin_mcp_url}")
        print(f"  mapped and available : {len(available)}")
        print(f"  mapped but missing   : {len(unavailable)}"
              + (f" ({', '.join(c.name for c in unavailable)})" if unavailable else ""))
        print(f"  extra read tools     : {len(unmapped)}")
        result = await provider.call_tool("get_unit_system", {})
        # Report only the outcome class, never the returned value.
        print(f"  sample read call     : get_unit_system -> {result.status.value}")
        return 0
    finally:
        await provider.close()


if __name__ == "__main__":
    raise SystemExit(main())
