"""Business counters and the ``/metrics`` endpoint for Credit Mate AI.

HTTP RED metrics (request rate, errors, latency per view) are recorded by
``credit_mate_ai.prometheus_middleware``. This module owns the business
counters that the Grafana business row reads and the endpoint that exposes
every series in the default Prometheus registry.

``/metrics`` is closed by default. It is served only when the request
presents ``Authorization: Bearer <METRICS_TOKEN>`` or comes from an address in
``METRICS_ALLOWED_IPS``. The address check uses ``REMOTE_ADDR`` only, since
``X-Forwarded-For`` is set by the client and cannot be trusted here.
"""

import hmac
import ipaddress

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, generate_latest

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods

SEARCH_TYPES = ("search", "suggest", "typeahead", "advanced")

# Incremented by ``increment_comparison`` once a comparison flow exists. The
# codebase has no comparison endpoint yet, so this stays at 0.
creditmate_comparisons_total = Counter(
    "creditmate_comparisons_total",
    "Credit card comparisons started",
)

# Incremented by ``increment_search`` in the search, suggest, typeahead and
# advanced-search handlers. ``search_type`` takes one of ``SEARCH_TYPES``.
creditmate_searches_total = Counter(
    "creditmate_searches_total",
    "Search requests that reached a search handler",
    ["search_type"],
)

# Incremented by ``increment_signup`` once a signup flow exists. The codebase
# has no signup flow yet, so this stays at 0.
creditmate_signups_total = Counter(
    "creditmate_signups_total",
    "User signups",
)

# Pre-create the label sets so every search type is exposed at 0 from start-up.
for _search_type in SEARCH_TYPES:
    creditmate_searches_total.labels(search_type=_search_type)


def increment_comparison():
    """Count one started credit card comparison.

    Returns
    -------
    None
    """
    creditmate_comparisons_total.inc()


def increment_search(search_type):
    """Count one search request.

    Parameters
    ----------
    search_type : str
        One of ``SEARCH_TYPES``. Any other value raises ``ValueError`` so that
        label cardinality stays bounded.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If ``search_type`` is not a known search type.
    """
    if search_type not in SEARCH_TYPES:
        raise ValueError(f"unknown search type: {search_type!r}")
    creditmate_searches_total.labels(search_type=search_type).inc()


def increment_signup():
    """Count one completed user signup.

    Returns
    -------
    None
    """
    creditmate_signups_total.inc()


@require_http_methods(["GET", "HEAD"])
def metrics_view(request):
    """Expose every registered Prometheus series in the text format.

    Parameters
    ----------
    request : HttpRequest
        Must carry a valid bearer token or come from an allowed address.

    Returns
    -------
    HttpResponse
        The metrics exposition with status 200, or 403 when the caller is not
        authorized.
    """
    if not is_metrics_request_allowed(request):
        return HttpResponseForbidden("Forbidden", content_type="text/plain")
    return HttpResponse(generate_latest(REGISTRY), content_type=CONTENT_TYPE_LATEST)


def is_metrics_request_allowed(request):
    """Decide whether a request may read ``/metrics``.

    Parameters
    ----------
    request : HttpRequest
        Incoming request.

    Returns
    -------
    bool
        True when the bearer token matches ``METRICS_TOKEN`` or the client
        address is in ``METRICS_ALLOWED_IPS``. False when neither setting is
        configured.
    """
    token = getattr(settings, "METRICS_TOKEN", "")
    if token and _bearer_token_matches(request, token):
        return True
    return _client_address_allowed(request)


def _bearer_token_matches(request, token):
    """Compare the ``Authorization`` header with the configured bearer token.

    Parameters
    ----------
    request : HttpRequest
        Incoming request.
    token : str
        Expected token from settings.

    Returns
    -------
    bool
        True when the header is ``Bearer <token>``. The comparison runs in
        constant time.
    """
    scheme, _, provided = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not provided:
        return False
    return hmac.compare_digest(provided.encode(), token.encode())


def _client_address_allowed(request):
    """Check whether ``REMOTE_ADDR`` falls inside an allowed IP or CIDR range.

    Parameters
    ----------
    request : HttpRequest
        Incoming request.

    Returns
    -------
    bool
        True when the address is inside a configured network. Invalid entries
        are skipped.
    """
    entries = getattr(settings, "METRICS_ALLOWED_IPS", [])
    if not entries:
        return False
    try:
        client_address = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return False
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if client_address in network:
            return True
    return False
