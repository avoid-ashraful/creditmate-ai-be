"""HTTP-only settings for the isolated loopback performance environment."""

from credit_mate_ai.settings import *  # noqa: F403

if ENVIRONMENT != "production-like":  # noqa: F405
    raise RuntimeError("Performance settings require ENVIRONMENT=production-like")
if DATABASES["default"]["NAME"] != "creditmate_perf":  # noqa: F405
    raise RuntimeError("Performance settings require the isolated performance database")
if REDIS_CACHE_URL != "redis://127.0.0.1:6379/6":  # noqa: F405
    raise RuntimeError("Performance settings require the isolated Redis database 6")
if ALLOWED_HOSTS != ["127.0.0.1", "localhost"]:  # noqa: F405
    raise RuntimeError("Performance settings require loopback hosts")

SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
