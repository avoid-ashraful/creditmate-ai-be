"""Custom rate-limiting policies for the public API."""

import math

from rest_framework.throttling import BaseThrottle, SimpleRateThrottle


class CeilingRetryAfterThrottle(SimpleRateThrottle):
    """Round fractional retry periods to whole HTTP Retry-After seconds."""

    def wait(self):
        wait = super().wait()
        return math.ceil(wait) if wait is not None else None


class TrustedClientRateThrottle(BaseThrottle):
    """Apply anonymous, authenticated, and burst policies from one class."""

    def __init__(self):
        self.anon_throttle = AnonymousThrottle()
        self.auth_throttle = AuthenticatedThrottle()
        self.burst_throttle = BurstThrottle()
        self.blocking_throttle = None

    def allow_request(self, request, view):
        for throttle in (self.burst_throttle, self.auth_throttle, self.anon_throttle):
            if throttle.allow_request(request, view):
                continue
            self.blocking_throttle = throttle
            return False
        return True

    def wait(self):
        return self.blocking_throttle.wait() if self.blocking_throttle else None


class AnonymousThrottle(CeilingRetryAfterThrottle):
    """Limit unauthenticated clients without trusting public X-Forwarded-For."""

    scope = "anon"

    def get_ident(self, request):
        return request.META.get("REMOTE_ADDR", "unknown")

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AuthenticatedThrottle(CeilingRetryAfterThrottle):
    """Limit authenticated clients by user ID."""

    scope = "user"

    def get_ident(self, request):
        if request.user and request.user.is_authenticated:
            return request.user.pk
        return request.META.get("REMOTE_ADDR", "unknown")

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class BurstThrottle(CeilingRetryAfterThrottle):
    """Limit short traffic bursts for both anonymous and authenticated clients."""

    scope = "burst"

    def get_ident(self, request):
        if request.user and request.user.is_authenticated:
            return request.user.pk
        return request.META.get("REMOTE_ADDR", "unknown")

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
