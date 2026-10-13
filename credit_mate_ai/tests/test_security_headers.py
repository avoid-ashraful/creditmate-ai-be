import importlib

from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, override_settings

from credit_mate_ai.middleware import SecurityHeadersMiddleware

DEFAULT_CSP = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"


def ok_response(request):
    return HttpResponse("ok")


def make_request(secure=False):
    return RequestFactory().get("/api/banks/", secure=secure)


@override_settings(
    CSP_HEADER=DEFAULT_CSP,
    X_FRAME_OPTIONS="DENY",
    REFERRER_POLICY="strict-origin-when-cross-origin",
)
def test_default_security_headers_applied():
    response = SecurityHeadersMiddleware(ok_response)(make_request())
    assert response.headers["Content-Security-Policy"] == DEFAULT_CSP
    assert "default-src" not in DEFAULT_CSP
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


@override_settings(
    CSP_HEADER="default-src 'self' https://cdn.example.com; frame-ancestors 'none'",
)
def test_csp_header_is_configurable():
    response = SecurityHeadersMiddleware(ok_response)(make_request())
    assert (
        response.headers["Content-Security-Policy"]
        == "default-src 'self' https://cdn.example.com; frame-ancestors 'none'"
    )


@override_settings(REFERRER_POLICY="no-referrer", X_FRAME_OPTIONS="DENY")
def test_referrer_policy_is_configurable():
    response = SecurityHeadersMiddleware(ok_response)(make_request())
    assert response.headers["Referrer-Policy"] == "no-referrer"


@override_settings(X_FRAME_OPTIONS="DENY", CSP_HEADER=DEFAULT_CSP)
def test_x_frame_options_overrides_existing_header():
    def framed(request):
        response = HttpResponse("framed")
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    response = SecurityHeadersMiddleware(framed)(make_request())
    assert response.headers["X-Frame-Options"] == "DENY"


@override_settings(SECURE_SSL_REDIRECT=False, SECURE_HSTS_SECONDS=0)
def test_hsts_absent_in_debug_settings():
    middleware = SecurityMiddleware(ok_response)
    response = middleware(make_request(secure=True))
    assert "Strict-Transport-Security" not in response.headers


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SECURE_HSTS_SECONDS=31536000,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
    SECURE_HSTS_PRELOAD=True,
)
def test_hsts_present_in_production_settings():
    middleware = SecurityMiddleware(ok_response)
    response = middleware(make_request(secure=True))
    assert (
        response.headers["Strict-Transport-Security"]
        == "max-age=31536000; includeSubDomains; preload"
    )


def test_production_settings_block_enables_hsts():
    import os

    import credit_mate_ai.settings as settings_module

    env_backup = os.environ.copy()
    try:
        os.environ["DEBUG"] = "False"
        os.environ.pop("SECURE_HSTS_SECONDS", None)
        module = importlib.reload(settings_module)
        assert module.SECURE_HSTS_SECONDS == 31536000
        assert module.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
        assert module.SECURE_HSTS_PRELOAD is True
        assert module.CSP_HEADER == DEFAULT_CSP
    finally:
        os.environ.clear()
        os.environ.update(env_backup)
        importlib.reload(settings_module)
