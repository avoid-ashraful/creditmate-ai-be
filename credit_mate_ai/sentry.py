"""Sentry event privacy helpers."""

import math
import re
from urllib.parse import urlsplit, urlunsplit

_SAFE_USER_ID = re.compile(
    r"^(?:\d{1,20}|[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})$"
)


def parse_sample_rate(value):
    """Parse a Sentry sample rate and reject values outside the SDK range."""
    rate = float(value)
    if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
        raise ValueError("SENTRY_TRACES_SAMPLE_RATE must be between 0.0 and 1.0")
    return rate


def sanitize_sentry_event(event, hint=None):
    """Keep operational context while stripping common request and user PII."""
    request = event.get("request")
    if isinstance(request, dict):
        safe_request = {}
        method = request.get("method")
        if isinstance(method, str):
            safe_request["method"] = method

        url = request.get("url")
        if isinstance(url, str):
            try:
                parsed = urlsplit(url)
                hostname = parsed.hostname or ""
                if parsed.port:
                    hostname = f"{hostname}:{parsed.port}"
                safe_request["url"] = urlunsplit(
                    (parsed.scheme, hostname, parsed.path, "", "")
                )
            except ValueError:
                pass
        event["request"] = safe_request

    user = event.get("user")
    if isinstance(user, dict):
        user_id = user.get("id")
        if isinstance(user_id, (str, int)) and _SAFE_USER_ID.fullmatch(str(user_id)):
            event["user"] = {"id": str(user_id)}
        else:
            event.pop("user", None)

    return event
