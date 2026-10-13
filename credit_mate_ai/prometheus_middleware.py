"""Per-view RED metrics for Django requests.

The series names and label sets match django-prometheus, because the alert
and recording rules in the monitoring repository query them directly:

- ``django_http_requests_total_by_view_transport_method_total``
  labels: ``view``, ``transport``, ``method``
- ``django_http_responses_total_by_status_view_method_total``
  labels: ``status``, ``view``, ``method``
- ``django_http_requests_latency_seconds_by_view_method``
  (exposed as ``..._bucket``, ``..._sum`` and ``..._count``)
  labels: ``view``, ``method``

``view`` is the resolved URL name. Unresolved paths report ``unknown``, so the
label set stays bounded whatever paths clients request. ``method`` is limited
to the standard HTTP verbs, with anything else reported as ``OTHER``.

The /metrics endpoint and the health probes are not recorded, so scraping and
probing do not inflate the request rate.

The middleware is appended to ``MIDDLEWARE``, so it runs innermost. Responses
that earlier middleware returns directly, such as CSRF 403s and body-limit
413/415s, are not recorded.
"""

import time

from prometheus_client import Counter, Histogram

EXCLUDED_VIEW_NAMES = frozenset({"metrics", "healthz", "readyz", "health_check"})
KNOWN_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

HTTP_REQUESTS = Counter(
    "django_http_requests_total_by_view_transport_method",
    "HTTP requests by view, transport and method",
    ["view", "transport", "method"],
)

HTTP_RESPONSES = Counter(
    "django_http_responses_total_by_status_view_method",
    "HTTP responses by status code, view and method",
    ["status", "view", "method"],
)

HTTP_LATENCY = Histogram(
    "django_http_requests_latency_seconds_by_view_method",
    "HTTP request latency in seconds by view and method",
    ["view", "method"],
)


class PrometheusMetricsMiddleware:
    """Record request count, status count and latency for each request.

    Parameters
    ----------
    get_response : callable
        Next middleware or view in the chain.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        """Process one request and record its metrics.

        Parameters
        ----------
        request : HttpRequest
            Incoming request.

        Returns
        -------
        HttpResponse
            The response from the rest of the chain, unchanged.
        """
        started = time.perf_counter()
        response = self.get_response(request)
        view = _view_label(getattr(request, "resolver_match", None))
        if view in EXCLUDED_VIEW_NAMES:
            return response

        elapsed = time.perf_counter() - started
        method = request.method if request.method in KNOWN_METHODS else "OTHER"
        transport = "https" if request.is_secure() else "http"
        HTTP_REQUESTS.labels(view=view, transport=transport, method=method).inc()
        HTTP_RESPONSES.labels(
            status=str(response.status_code), view=view, method=method
        ).inc()
        HTTP_LATENCY.labels(view=view, method=method).observe(elapsed)
        return response


def _view_label(resolver_match):
    """Return the bounded ``view`` label for a resolved request.

    Parameters
    ----------
    resolver_match : ResolverMatch or None
        The match Django stored on the request, or None when resolution failed.

    Returns
    -------
    str
        The URL name, ``unnamed`` for unnamed patterns, or ``unknown`` when the
        path did not resolve.
    """
    if resolver_match is None:
        return "unknown"
    return resolver_match.url_name or "unnamed"
