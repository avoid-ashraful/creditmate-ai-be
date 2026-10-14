import pytest
from rest_framework.test import APIClient
from rest_framework.views import APIView

from django.contrib.auth.models import User
from django.test import RequestFactory
from django.urls import reverse

from credit_mate_ai.throttling import (
    AnonymousThrottle,
    AuthenticatedThrottle,
    BurstThrottle,
    TrustedClientRateThrottle,
)


class FixedClock:
    def __init__(self):
        self.now = 1000000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture()
def clock():
    return FixedClock()


@pytest.fixture()
def throttles(clock, monkeypatch):
    instances = {
        "anon": AnonymousThrottle(),
        "user": AuthenticatedThrottle(),
        "burst": BurstThrottle(),
    }
    for throttle in instances.values():
        monkeypatch.setattr(type(throttle), "timer", clock)
    return instances


@pytest.fixture()
def anonymous_api_client():
    client = APIClient(enforce_csrf_checks=False)
    client.defaults["REMOTE_ADDR"] = "203.0.113.10"
    return client


@pytest.fixture()
def authenticated_api_client(db):
    user = User.objects.create_user(username="rate-limit-user", password="test-password")
    client = APIClient(enforce_csrf_checks=False)
    client.force_authenticate(user=user)
    client.defaults["REMOTE_ADDR"] = "203.0.113.11"
    return client


@pytest.mark.django_db
def test_anonymous_rate_limit_is_one_hundred_per_minute(
    anonymous_api_client, throttles, monkeypatch
):
    monkeypatch.setattr(APIView, "throttle_classes", [AnonymousThrottle])
    responses = [
        anonymous_api_client.get(reverse("bank-list"), REMOTE_ADDR="203.0.113.10")
        for _ in range(101)
    ]
    assert [response.status_code for response in responses[:100]] == [200] * 100
    assert responses[100].status_code == 429


def test_configured_rate_boundaries(throttles):
    assert throttles["anon"].num_requests == 100
    assert throttles["anon"].duration == 60
    assert throttles["user"].num_requests == 1000
    assert throttles["user"].duration == 60
    assert throttles["burst"].num_requests == 10
    assert throttles["burst"].duration == 1


@pytest.mark.django_db
def test_authenticated_rate_limit_is_one_thousand_per_minute(
    authenticated_api_client, throttles, monkeypatch
):
    monkeypatch.setattr(APIView, "throttle_classes", [AuthenticatedThrottle])
    responses = [authenticated_api_client.get(reverse("bank-list")) for _ in range(1001)]
    assert [response.status_code for response in responses[:1000]] == [200] * 1000
    assert responses[1000].status_code == 429


@pytest.mark.django_db
def test_burst_rate_limit_is_ten_per_second(anonymous_api_client, throttles, monkeypatch):
    responses = [
        anonymous_api_client.get(reverse("bank-list"), REMOTE_ADDR="203.0.113.10")
        for _ in range(11)
    ]
    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[10].status_code == 429
    assert responses[10]["Retry-After"] == "1"


@pytest.mark.django_db
def test_burst_window_expires_and_allows_next_request(
    anonymous_api_client, throttles, clock, monkeypatch
):
    monkeypatch.setattr(APIView, "throttle_classes", [BurstThrottle])
    for _ in range(10):
        response = anonymous_api_client.get(
            reverse("bank-list"), REMOTE_ADDR="203.0.113.10"
        )
        assert response.status_code == 200
    clock.advance(1)
    assert (
        anonymous_api_client.get(
            reverse("bank-list"), REMOTE_ADDR="203.0.113.10"
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_public_forwarded_for_does_not_create_separate_rate_identity(
    throttles, monkeypatch
):
    forwarded_keys = set()
    for forwarded_for in ("198.51.100.1", "198.51.100.2", "198.51.100.3"):
        request = RequestFactory().get(
            "/", HTTP_X_FORWARDED_FOR=forwarded_for, REMOTE_ADDR="203.0.113.10"
        )
        request.user = None
        forwarded_keys.add(throttles["anon"].get_cache_key(request, None))
    assert forwarded_keys == {"throttle_anon_203.0.113.10"}


def test_throttle_uses_direct_remote_address(clock, throttles):
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="198.51.100.99")
    request.META["REMOTE_ADDR"] = "203.0.113.10"
    assert throttles["anon"].get_ident(request) == "203.0.113.10"


def test_custom_wait_reports_burst_duration(clock, throttles):
    composite = TrustedClientRateThrottle()
    for throttle in (
        composite.anon_throttle,
        composite.auth_throttle,
        composite.burst_throttle,
    ):
        throttle.timer = clock
    request = RequestFactory().get("/")
    request.user = None
    request.META["REMOTE_ADDR"] = "203.0.113.10"
    for _ in range(10):
        assert composite.allow_request(request, None)
    assert composite.allow_request(request, None) is False
    assert composite.wait() == 1
