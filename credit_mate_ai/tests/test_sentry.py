from copy import deepcopy

import pytest

from credit_mate_ai.sentry import parse_sample_rate, sanitize_sentry_event


@pytest.mark.parametrize("value, expected", [("0", 0.0), ("0.1", 0.1), ("1", 1.0)])
def test_parse_sample_rate_accepts_inclusive_bounds(value, expected):
    assert parse_sample_rate(value) == expected


@pytest.mark.parametrize("value", ["-0.01", "1.01", "nan", "inf", "-inf"])
def test_parse_sample_rate_rejects_out_of_range_values(value):
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        parse_sample_rate(value)


def test_sentry_event_filter_keeps_only_safe_request_and_user_context():
    event = {
        "environment": "production",
        "release": "creditmate@1.2.3",
        "request": {
            "method": "POST",
            "url": "https://name:secret@example.test/cards/42?token=secret#top",
            "headers": {"Authorization": "secret"},
            "cookies": "session-secret",
            "data": {"email": "person@example.test"},
            "env": {"REMOTE_ADDR": "192.0.2.1"},
        },
        "user": {
            "id": "12345",
            "email": "person@example.test",
            "username": "private-user",
            "ip_address": "192.0.2.1",
        },
        "extra": {"request_body": "private"},
    }

    sanitized = sanitize_sentry_event(deepcopy(event))

    assert sanitized["environment"] == "production"
    assert sanitized["release"] == "creditmate@1.2.3"
    assert sanitized["request"] == {
        "method": "POST",
        "url": "https://example.test/cards/42",
    }
    assert sanitized["user"] == {"id": "12345"}
    assert "secret" not in repr(sanitized)
    assert "person@example.test" not in repr(sanitized)
    assert "192.0.2.1" not in repr(sanitized)


def test_sentry_event_filter_drops_unsafe_user_id_and_malformed_url():
    event = {
        "request": {"method": "GET", "url": "https://[invalid"},
        "user": {"id": "person@example.test", "email": "person@example.test"},
    }

    sanitized = sanitize_sentry_event(event)

    assert sanitized["request"] == {"method": "GET"}
    assert "user" not in sanitized
