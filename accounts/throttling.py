"""Throttling policies for authentication endpoints."""

from credit_mate_ai.throttling import (
    AnonymousThrottle,
    AuthenticatedThrottle,
    BurstThrottle,
)


class AuthBurstThrottle(BurstThrottle):
    """Burst throttle for auth endpoints."""

    scope = "auth_burst"


class AuthAnonThrottle(AnonymousThrottle):
    """Anonymous throttle for auth endpoints."""

    scope = "auth_anon"


class AuthUserThrottle(AuthenticatedThrottle):
    """Authenticated user throttle for auth endpoints."""

    scope = "auth_user"
