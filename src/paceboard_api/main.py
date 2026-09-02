"""FastAPI application factory.

Security posture, enforced here rather than left to deployment:

* binds to loopback unless the operator explicitly opts out, and warns loudly
  when they do — this database contains personal health data;
* CORS is restricted to the local dashboard origin, with credentials disabled;
* request bodies are capped, so a malformed client cannot exhaust memory;
* every response carries no-store plus a restrictive referrer policy, because
  browser caches and referrers are how local data leaks outward.
"""

from __future__ import annotations

import contextlib
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api import errors
from .api.routers import (
    activities,
    export,
    gear,
    health,
    overview,
    raw,
    settings_router,
    status,
    strava_auth,
    sync,
    training,
)
from .config import Settings, get_settings
from .db.session import get_engine
from .ingest import scheduler as scheduler_module
from .logging_conf import configure_logging, get_logger

log = get_logger("paceboard.main")

API_PREFIX = "/api/v1"

DESCRIPTION = """
Local-first personal fitness analytics over Garmin and Strava data.

Garmin data is read through the read-only Garmin MCP server; Strava through the
official REST API. This API serves only normalized, locally stored data — it
never proxies provider credentials to the browser.
"""


def _warn_if_public(settings: Settings) -> None:
    if settings.is_loopback:
        return
    if not settings.allow_non_loopback:
        raise RuntimeError(
            f"Refusing to bind Paceboard to {settings.host!r}. This API serves "
            f"personal health data with no authentication and must stay on "
            f"loopback. If you genuinely intend to expose it on a trusted "
            f"network, set PACEBOARD_ALLOW_NON_LOOPBACK=true — and put "
            f"authentication in front of it."
        )
    log.warning(
        "Paceboard is bound to a NON-LOOPBACK address and has no authentication. "
        "Anyone who can reach this host can read your health data.",
        extra={"host": settings.host},
    )


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    get_engine()
    scheduler_module.start(settings)
    log.info(
        "Paceboard API ready",
        extra={"host": settings.host, "port": settings.api_port,
               "database": str(settings.database_path),
               "strava_configured": settings.strava_configured},
    )
    try:
        yield
    finally:
        scheduler_module.shutdown()
        from .providers.registry import get_registry

        await get_registry().aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    _warn_if_public(settings)

    app = FastAPI(
        title="Paceboard API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def _limits_and_headers(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and int(length) > settings.max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={"error": {"code": "payload_too_large",
                                   "message": "Request body exceeds the configured limit",
                                   "detail": {"limit_bytes": settings.max_request_bytes}}},
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    errors.install_handlers(app)

    for router in (
        status.router, sync.router, overview.router, activities.router,
        health.router, training.router, gear.router, raw.router,
        export.router, settings_router.router, strava_auth.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/scheduler", tags=["status"], summary="Scheduled jobs")
    def scheduler_state() -> dict[str, object]:
        return {
            "enabled": settings.scheduler_enabled,
            "jobs": scheduler_module.jobs(),
        }

    return app


app = create_app  # uvicorn --factory paceboard_api.main:app
