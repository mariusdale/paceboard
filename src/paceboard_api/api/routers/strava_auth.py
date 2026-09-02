"""Strava OAuth 2.0 routes and the webhook endpoint.

The full flow is implemented and testable without credentials: every route
returns a clear, typed "not configured" response until ``STRAVA_CLIENT_ID`` and
``STRAVA_CLIENT_SECRET`` exist, at which point the same routes work unchanged.

No route ever returns token material. ``/status`` reports scope, athlete and
expiry only.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...logging_conf import get_logger
from ...providers.registry import get_registry
from ...providers.strava.client import DEFAULT_SCOPES, StravaNotConnected
from ..deps import SettingsDep
from ..errors import bad_request, unavailable

router = APIRouter(prefix="/auth/strava", tags=["strava-auth"])
log = get_logger("paceboard.api.strava")


@router.get("/status", response_model=dict, summary="Strava connection status")
def status() -> dict[str, Any]:
    provider = get_registry().strava
    tokens = provider.client.store.load() if provider.configured else None
    return {
        "configured": provider.configured,
        "connected": tokens is not None,
        "scopes_requested": DEFAULT_SCOPES,
        "athlete": tokens.public_view() if tokens else None,
        "tokens_encrypted": provider.client.store.encrypted,
        "rate_limit": provider.client.rate_limit.as_dict(),
        "message": (
            "Strava not connected — add STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET "
            "to .env, restart Paceboard, then click Connect."
            if not provider.configured
            else "Strava not connected — click Connect to authorize."
            if tokens is None
            else "Connected."
        ),
    }


@router.get("/authorize", response_model=dict, summary="Get the Strava consent URL")
def authorize(settings: SettingsDep, redirect: bool = Query(False)) -> Any:
    provider = get_registry().strava
    try:
        url, state = provider.client.authorization_url()
    except StravaNotConnected as exc:
        raise unavailable(str(exc), {"provider": "strava", "configured": False}) from exc
    if redirect:
        return RedirectResponse(url, status_code=307)
    return {
        "authorize_url": url,
        "state": state,
        "redirect_uri": settings.strava_redirect_uri,
    }


@router.get("/callback", summary="OAuth redirect target")
async def callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
) -> HTMLResponse:
    """Strava redirects the browser here after consent.

    Returns a small self-contained page rather than JSON, because a human is
    looking at it. The authorization code is never logged.
    """
    provider = get_registry().strava
    if error:
        return _page("Strava authorization declined", f"Strava reported: {error}", False)
    if not code:
        return _page("Missing authorization code",
                     "Strava did not include a code in the redirect.", False)
    if not provider.client.consume_state(state):
        # A mismatched state means the callback did not originate from an
        # authorize call this process issued.
        return _page("State mismatch",
                     "This callback did not match a pending authorization request. "
                     "Start again from Settings.", False)
    try:
        tokens = await provider.client.exchange_code(code)
    except StravaNotConnected as exc:
        return _page("Token exchange failed", str(exc), False)
    log.info("Strava connected", extra={"athlete_id": tokens.athlete_id})
    return _page(
        "Strava connected",
        f"Authorized as {tokens.athlete_name or tokens.athlete_id}. "
        f"Granted scopes: {scope or tokens.scope}. You can close this tab and "
        f"return to Paceboard.",
        True,
    )


@router.post("/disconnect", response_model=dict, summary="Revoke and forget Strava tokens")
async def disconnect() -> dict[str, Any]:
    provider = get_registry().strava
    revoked = await provider.client.disconnect()
    return {
        "disconnected": True,
        "revoked_at_strava": revoked,
        "message": "Local Strava tokens deleted."
        + ("" if revoked else " Strava did not confirm revocation; revoke the app "
                              "manually at strava.com/settings/apps if needed."),
    }


@router.get("/webhook", summary="Strava webhook subscription validation")
def webhook_validate(
    settings: SettingsDep,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
) -> dict[str, Any]:
    """Strava's subscription handshake.

    Kept implemented even though a loopback-bound Paceboard is not reachable
    from Strava's servers: the moment the API is exposed through a tunnel, the
    subscription works with no code change. See the README for how to enable it.
    """
    if not settings.strava_webhook_verify_token:
        raise unavailable(
            "STRAVA_WEBHOOK_VERIFY_TOKEN is not configured; webhooks are disabled"
        )
    if hub_mode != "subscribe" or hub_verify_token != settings.strava_webhook_verify_token:
        raise bad_request("Webhook verification failed")
    return {"hub.challenge": hub_challenge}


@router.post("/webhook", response_model=dict, summary="Strava webhook event sink")
async def webhook_event(request: Request) -> dict[str, Any]:
    """Accept and acknowledge an event.

    Strava requires a 200 within two seconds, so the event is only recorded; the
    scheduler's next incremental sync picks up the referenced activity. That
    keeps the handler fast and makes a missed webhook harmless.
    """
    payload = await request.json()
    log.info(
        "Strava webhook event",
        extra={"object_type": str(payload.get("object_type"))[:32],
               "aspect_type": str(payload.get("aspect_type"))[:32]},
    )
    return {"received": True}


def _page(title: str, message: str, ok: bool) -> HTMLResponse:
    color = "#1f7a4d" if ok else "#a02020"
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Paceboard — {title}</title>
<style>
 body{{font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;background:#f6f7f9;
 color:#1a1d21;margin:0;display:grid;place-items:center;height:100vh}}
 .card{{background:#fff;border:1px solid #e2e5ea;border-radius:12px;padding:32px;
 max-width:460px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 h1{{font-size:18px;margin:0 0 8px;color:{color}}}
 p{{margin:0;color:#4a5058}}
</style></head><body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>""",
        status_code=200 if ok else 400,
    )
