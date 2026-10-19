# Source from the worktree root. Never enable shell tracing here.
export DEBUG=False ENVIRONMENT=production-like
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export DATABASE_URL=postgresql:///creditmate_perf
export ALLOWED_HOSTS=127.0.0.1,localhost
export SECURE_SSL_REDIRECT=False SECURE_HSTS_SECONDS=0
export SECURE_HSTS_INCLUDE_SUBDOMAINS=False SECURE_HSTS_PRELOAD=False
export SESSION_COOKIE_SECURE=False CSRF_COOKIE_SECURE=False
export CACHE_BACKEND=redis REDIS_CACHE_URL=redis://127.0.0.1:6379/6
export SEARCH_ENABLED=False SEARCH_SYNC_MODE=off
export THROTTLE_RATE_ANON=100000/min THROTTLE_RATE_USER=100000/min
export THROTTLE_RATE_BURST=1000/sec
export DJANGO_SETTINGS_MODULE=scripts.performance.local_settings
