"""Strava OAuth, token refresh, pagination and rate-limit handling."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
import pytest

from paceboard_api.providers.dto import ResultStatus
from paceboard_api.providers.strava.client import (
    RateLimitState,
    StravaClient,
    StravaNotConnected,
)
from paceboard_api.providers.strava.provider import StravaApiProvider, canonical_sport
from paceboard_api.providers.strava.tokens import StravaTokens, TokenStore

from . import fixtures


@pytest.fixture()
def store(tmp_path) -> TokenStore:
    return TokenStore(tmp_path / "tokens.json", tmp_path / "key")


def make_client(store, handler) -> StravaClient:
    client = StravaClient("12345", "secret", "http://127.0.0.1:8787/cb", store)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def valid_tokens(expires_in: int = 3600) -> StravaTokens:
    return StravaTokens(
        access_token="ACCESS-SENTINEL", refresh_token="REFRESH-SENTINEL",
        expires_at=int(time.time()) + expires_in,
        scope="read,activity:read_all", athlete_id="987654", athlete_name="Test Athlete",
    )


class TestTokenStore:
    def test_tokens_round_trip_and_are_not_plaintext_on_disk(self, store):
        store.save(valid_tokens())
        raw = store.token_path.read_bytes()
        assert b"ACCESS-SENTINEL" not in raw, "the token must not sit in the file as plaintext"
        assert b'"access_token"' not in raw
        assert store.encrypted
        store._cache = None
        store._loaded = False
        assert store.load().access_token == "ACCESS-SENTINEL"

    def test_token_file_is_owner_only(self, store):
        store.save(valid_tokens())
        assert oct(store.token_path.stat().st_mode)[-3:] == "600"
        assert oct(store.key_path.stat().st_mode)[-3:] == "600"

    def test_public_view_never_contains_token_material(self, store):
        view = valid_tokens().public_view()
        assert set(view) == {"athlete_id", "athlete_name", "scope", "expires_at", "expired"}
        serialized = json.dumps(view)
        assert "access_token" not in serialized
        assert "refresh_token" not in serialized
        assert valid_tokens().access_token not in serialized
        assert view["athlete_id"] == "987654"

    def test_expiry_uses_a_leeway_so_a_call_never_races_the_clock(self):
        assert valid_tokens(expires_in=60).is_expired()
        assert not valid_tokens(expires_in=3600).is_expired()

    def test_missing_file_reads_as_disconnected(self, store):
        assert store.load() is None

    def test_corrupt_file_reads_as_disconnected_rather_than_raising(self, store):
        store.token_path.write_bytes(b"not a token file")
        assert store.load() is None

    def test_clear_removes_the_file(self, store):
        store.save(valid_tokens())
        store.clear()
        assert not store.token_path.exists()
        assert store.load() is None


class TestOAuth:
    def test_authorize_url_carries_the_read_scopes_and_a_state(self, store):
        client = make_client(store, lambda r: httpx.Response(200))
        url, state = client.authorization_url()
        # Parameters are percent-encoded in the query string.
        assert "activity%3Aread_all" in url
        assert f"state={state}" in url
        assert "redirect_uri=http" in url
        assert url.startswith("https://www.strava.com/oauth/authorize?")
        assert client.consume_state(state) is True
        assert client.consume_state(state) is False, "state must be single-use"

    def test_unknown_state_is_rejected(self, store):
        client = make_client(store, lambda r: httpx.Response(200))
        assert client.consume_state("forged") is False
        assert client.consume_state(None) is False

    def test_authorize_without_credentials_raises(self, store):
        client = StravaClient("", "", "http://cb", store)
        with pytest.raises(StravaNotConnected):
            client.authorization_url()

    async def test_code_exchange_stores_tokens_and_athlete(self, store):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/oauth/token"
            body = request.content.decode()
            assert "grant_type=authorization_code" in body
            return httpx.Response(200, json=fixtures.STRAVA_TOKEN_RESPONSE)

        client = make_client(store, handler)
        tokens = await client.exchange_code("the-code")
        assert tokens.athlete_id == "987654"
        assert store.load().athlete_name == "Test Athlete"
        await client.close()

    async def test_failed_exchange_does_not_echo_the_response_body(self, store):
        def handler(_request):
            return httpx.Response(400, json={"errors": [{"code": "invalid"}],
                                             "client_secret": "leaked"})

        client = make_client(store, handler)
        with pytest.raises(StravaNotConnected) as excinfo:
            await client.exchange_code("bad")
        assert "leaked" not in str(excinfo.value)
        assert "400" in str(excinfo.value)
        await client.close()


class TestRefresh:
    async def test_expired_token_is_refreshed_before_the_request(self, store):
        store.save(valid_tokens(expires_in=10))
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.url.path == "/oauth/token":
                return httpx.Response(200, json={
                    **fixtures.STRAVA_TOKEN_RESPONSE,
                    "access_token": "fresh",
                    "expires_at": int(time.time()) + 21600,
                })
            assert request.headers["Authorization"] == "Bearer fresh"
            return httpx.Response(200, json=fixtures.STRAVA_ATHLETE)

        client = make_client(store, handler)
        result = await client.athlete()
        assert result.ok
        assert seen[0] == "/oauth/token"
        assert store.load().access_token == "fresh"
        await client.close()

    async def test_a_valid_token_is_not_refreshed(self, store):
        store.save(valid_tokens())
        seen = []

        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json=fixtures.STRAVA_ATHLETE)

        client = make_client(store, handler)
        await client.athlete()
        assert "/oauth/token" not in seen
        await client.close()

    async def test_refresh_keeps_the_old_refresh_token_when_none_is_returned(self, store):
        store.save(valid_tokens(expires_in=10))
        payload = dict(fixtures.STRAVA_TOKEN_RESPONSE)
        payload.pop("refresh_token")

        client = make_client(store, lambda r: httpx.Response(200, json=payload))
        refreshed = await client.refresh(store.load())
        assert refreshed.refresh_token == "REFRESH-SENTINEL"
        await client.close()


class TestRateLimits:
    def test_headers_are_parsed_into_remaining_budget(self):
        state = RateLimitState()
        state.update(httpx.Headers(fixtures.STRAVA_RATE_LIMIT_HEADERS))
        assert state.short_limit == 200
        assert state.short_usage == 47
        assert state.short_remaining == 153
        assert state.daily_remaining == 797
        assert state.as_dict()["daily_limit"] == 2000

    def test_absent_headers_leave_the_budget_unknown_rather_than_zero(self):
        state = RateLimitState()
        state.update(httpx.Headers({}))
        assert state.short_remaining is None
        assert state.daily_remaining is None

    async def test_429_is_reported_as_rate_limited_and_retried(self, store, monkeypatch):
        store.save(valid_tokens())
        calls = {"n": 0}

        def handler(request):
            if request.url.path == "/api/v3/athlete":
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(429, json={}, headers=fixtures.STRAVA_RATE_LIMIT_HEADERS)
                return httpx.Response(200, json=fixtures.STRAVA_ATHLETE)
            return httpx.Response(200, json={})

        client = make_client(store, handler)
        monkeypatch.setattr(StravaClient, "_backoff", staticmethod(lambda *_: 0.0))
        result = await client.get("/athlete", retries=2)
        assert result.ok
        assert calls["n"] == 2
        await client.close()

    async def test_404_is_no_data_and_is_not_retried(self, store):
        store.save(valid_tokens())
        calls = {"n": 0}

        def handler(_request):
            calls["n"] += 1
            return httpx.Response(404, json={})

        client = make_client(store, handler)
        result = await client.get("/activities/1", retries=3)
        assert result.status is ResultStatus.NO_DATA
        assert calls["n"] == 1
        await client.close()


class TestPagination:
    async def test_all_pages_are_walked_until_a_short_page(self, store):
        store.save(valid_tokens())
        pages = {
            1: [dict(fixtures.STRAVA_ACTIVITY, id=i) for i in range(100)],
            2: [dict(fixtures.STRAVA_ACTIVITY, id=1000 + i) for i in range(30)],
        }

        def handler(request):
            if request.url.path != "/api/v3/athlete/activities":
                return httpx.Response(200, json={})
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=pages.get(page, []))

        provider = StravaApiProvider(make_client(store, handler))
        from datetime import date

        summaries, results = await provider.fetch_activities(date(2026, 8, 1), date(2026, 8, 31))
        assert len(summaries) == 130
        assert len(results) == 2
        await provider.close()

    async def test_a_failed_page_stops_paging_without_losing_earlier_rows(self, store, monkeypatch):
        store.save(valid_tokens())
        monkeypatch.setattr(StravaClient, "_backoff", staticmethod(lambda *_: 0.0))

        def handler(request):
            if request.url.path != "/api/v3/athlete/activities":
                return httpx.Response(200, json={})
            page = int(request.url.params.get("page", 1))
            if page == 1:
                return httpx.Response(200, json=[dict(fixtures.STRAVA_ACTIVITY, id=i)
                                                 for i in range(100)])
            return httpx.Response(500, json={})

        provider = StravaApiProvider(make_client(store, handler))
        from datetime import date

        summaries, results = await provider.fetch_activities(date(2026, 8, 1), date(2026, 8, 31))
        assert len(summaries) == 100
        assert results[-1].status is ResultStatus.ERROR
        await provider.close()


class TestDisconnectedBehaviour:
    async def test_every_fetch_reports_unsupported_rather_than_raising(self, store):
        provider = StravaApiProvider(make_client(store, lambda r: httpx.Response(200)))
        from datetime import date

        summaries, results = await provider.fetch_activities(date(2026, 8, 1), date(2026, 8, 2))
        assert summaries == []
        assert results[0].status is ResultStatus.UNSUPPORTED

        streams, stream_results = await provider.fetch_activity_streams("1")
        assert streams is None
        assert stream_results[0].status is ResultStatus.UNSUPPORTED

        assert await provider.fetch_daily(date(2026, 8, 1), ["daily_health"]) == []
        await provider.close()

    async def test_health_explains_what_is_missing(self, store):
        provider = StravaApiProvider(StravaClient("", "", "http://cb", store))
        ok, detail = await provider.health()
        assert ok is False
        assert "not configured" in detail.lower()

    async def test_capabilities_are_listed_as_unavailable_when_disconnected(self, store):
        provider = StravaApiProvider(make_client(store, lambda r: httpx.Response(200)))
        capabilities = await provider.discover_capabilities()
        assert capabilities
        assert all(c.status == "unavailable" for c in capabilities)
        await provider.close()


class TestNormalization:
    @pytest.mark.parametrize(
        "sport_type,expected",
        [("Run", "run"), ("TrailRun", "run"), ("VirtualRide", "ride"),
         ("GravelRide", "ride"), ("WeightTraining", "strength"),
         ("Kayaking", "paddle"), ("Snowshoe", "ski"), ("Kitesurf", "other"),
         (None, "other")],
    )
    def test_sport_mapping(self, sport_type, expected):
        assert canonical_sport(sport_type) == expected

    async def test_summary_carries_the_provider_link_used_for_deduplication(self, store):
        store.save(valid_tokens())
        provider = StravaApiProvider(
            make_client(store, lambda r: httpx.Response(200, json=fixtures.STRAVA_ACTIVITY))
        )
        dto, _ = await provider.fetch_activity_detail("15123456789")
        assert dto.external_id == "garmin_push_24188138095"
        assert dto.upload_id == "16000000001"
        assert dto.start_time_utc == datetime(2026, 8, 20, 5, 33, 0)
        assert dto.start_lat == pytest.approx(59.9139)
        await provider.close()

    async def test_streams_split_latlng_into_two_channels(self, store):
        store.save(valid_tokens())
        provider = StravaApiProvider(
            make_client(store, lambda r: httpx.Response(200, json=fixtures.STRAVA_STREAMS))
        )
        streams, _ = await provider.fetch_activity_streams("1")
        assert streams.channels["lat"][0] == pytest.approx(59.9139)
        assert streams.channels["lng"][0] == pytest.approx(10.7522)
        assert streams.channels["moving"] == [1.0, 1.0, 1.0, 1.0]
        assert streams.point_count == 4
        await provider.close()

    async def test_zone_buckets_become_numbered_zones(self, store):
        store.save(valid_tokens())
        provider = StravaApiProvider(
            make_client(store, lambda r: httpx.Response(200, json=fixtures.STRAVA_ZONES))
        )
        zones, _ = await provider.fetch_activity_zones("1")
        assert [z.zone_number for z in zones] == [1, 2, 3, 4, 5]
        assert zones[2].seconds_in_zone == 1500
        await provider.close()
