"""Garmin MCP response classification.

These tests pin the exact behaviour the ingestion pipeline depends on: a
"no data" sentence must never be mistaken for an error, and an error must never
be mistaken for absence.
"""

from __future__ import annotations

import json

import pytest

from paceboard_api.providers.dto import ResultStatus
from paceboard_api.providers.garmin.parsing import (
    classify_text,
    extract_text,
    parse_tool_text,
)

from . import fixtures


class TestJsonResponses:
    def test_curated_json_parses_to_ok(self):
        status, data, message = parse_tool_text(json.dumps(fixtures.GARMIN_STATS))
        assert status is ResultStatus.OK
        assert data["total_steps"] == 9124
        assert message is None

    def test_json_array_parses(self):
        status, data, _ = parse_tool_text(json.dumps(fixtures.GARMIN_DEVICES))
        assert status is ResultStatus.OK
        assert data[0]["device_name"] == "Forerunner 965"

    def test_malformed_json_is_an_error_not_no_data(self):
        status, data, message = parse_tool_text('{"date": "2026-08-20", ')
        assert status is ResultStatus.ERROR
        assert data is None
        assert "Malformed JSON" in message

    @pytest.mark.parametrize("payload", fixtures.GARMIN_EMPTY_JSON)
    def test_json_carrying_only_echoed_request_fields_is_no_data(self, payload):
        status, data, message = parse_tool_text(json.dumps(payload))
        assert status is ResultStatus.NO_DATA
        assert "no values" in (message or "").lower()

    def test_payload_with_one_real_field_is_ok(self):
        status, _, _ = parse_tool_text(json.dumps({"date": "2026-08-20", "avg_spo2": 96}))
        assert status is ResultStatus.OK


class TestPlainTextResponses:
    @pytest.mark.parametrize(
        "key,expected",
        [
            ("no_gear", ResultStatus.NO_DATA),
            ("no_readiness", ResultStatus.NO_DATA),
            ("no_weight", ResultStatus.NO_DATA),
            ("unsupported", ResultStatus.UNSUPPORTED),
            ("range_too_large", ResultStatus.INVALID_REQUEST),
            ("tool_error", ResultStatus.ERROR),
            ("rate_limited", ResultStatus.RATE_LIMITED),
            ("auth_expired", ResultStatus.ERROR),
            ("timeout", ResultStatus.TIMEOUT),
        ],
    )
    def test_each_real_sentence_is_classified(self, key, expected):
        status, data, message = parse_tool_text(fixtures.GARMIN_TEXT_RESPONSES[key])
        assert status is expected, f"{key}: {message}"
        assert data is None
        assert message

    def test_empty_response_is_no_data(self):
        status, _, message = parse_tool_text("   ")
        assert status is ResultStatus.NO_DATA
        assert message == "Empty response"

    def test_unrecognised_sentence_is_an_error_not_silently_dropped(self):
        status, _, _ = parse_tool_text("Something entirely unexpected happened here")
        assert status is ResultStatus.ERROR

    def test_message_is_bounded(self):
        _, message = classify_text("No data found. " + "x" * 5000)
        assert len(message) <= 300


class TestStatusSemantics:
    def test_permanent_statuses_are_not_retried(self):
        for status in (ResultStatus.NO_DATA, ResultStatus.UNSUPPORTED,
                       ResultStatus.INVALID_REQUEST):
            assert status.is_permanent
            assert not status.is_retryable

    def test_transient_statuses_are_retryable(self):
        for status in (ResultStatus.RATE_LIMITED, ResultStatus.TIMEOUT,
                       ResultStatus.PROTOCOL_ERROR):
            assert status.is_retryable
            assert not status.is_permanent

    def test_plain_error_is_neither_retried_forever_nor_treated_as_absence(self):
        assert not ResultStatus.ERROR.is_permanent
        assert not ResultStatus.ERROR.is_retryable


class TestExtractText:
    def test_concatenates_text_content_blocks(self):
        class Block:
            def __init__(self, text):
                self.text = text

        assert extract_text([Block("abc"), Block("def")]) == "abcdef"

    def test_ignores_non_text_content(self):
        class Image:
            data = b"..."

        assert extract_text([Image()]) == ""

    def test_accepts_dict_shaped_content(self):
        assert extract_text([{"type": "text", "text": "hi"}]) == "hi"


def test_activity_summary_prefers_explicit_utc_timestamp():
    from paceboard_api.providers.garmin.provider import GarminMcpProvider
    from unittest.mock import Mock
    provider = GarminMcpProvider(Mock())
    row = provider._summary_from_list_item({'id': 1, 'type': 'running', 'start_time': '2026-09-04 15:06:38', 'start_time_gmt': '2026-09-04 13:06:38'})
    assert row.start_time_utc.hour == 13
