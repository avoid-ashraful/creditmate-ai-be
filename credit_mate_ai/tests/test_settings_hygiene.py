"""Settings defaults and env parsing, evaluated in a fresh interpreter."""

import json
import os
import subprocess
import sys

BASE_ENV = {"SECRET_KEY": "test", "DATABASE_URL": "postgresql:///unused"}
PROBE = (
    "import json; from credit_mate_ai import settings as s;"
    "print(json.dumps({"
    "'conn': s.DATABASES['default']['CONN_MAX_AGE'],"
    "'csrf': s.CSRF_TRUSTED_ORIGINS,"
    "'level': s.LOGGING['root']['level'],"
    "'static': s.STORAGES['staticfiles']['BACKEND'],"
    "'search': s.SEARCH_ENABLED,"
    "'from': s.DEFAULT_FROM_EMAIL,"
    "}))"
)


def load_settings(**env):
    """Import settings in a subprocess with a controlled environment."""
    clean = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "DEBUG",
            "CONN_MAX_AGE",
            "CSRF_TRUSTED_ORIGINS",
            "LOG_LEVEL",
            "SEARCH_ENABLED",
            "DEFAULT_FROM_EMAIL",
        }
    }
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        env={
            **clean,
            "DJANGO_SETTINGS_MODULE": "credit_mate_ai.settings",
            **BASE_ENV,
            **env,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_defaults_in_production_mode():
    loaded = load_settings(DEBUG="False")

    assert loaded["conn"] == 60
    assert loaded["csrf"] == []
    assert loaded["level"] == "INFO"
    assert loaded["static"] == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    assert loaded["search"] is False
    assert loaded["from"] == "noreply@creditmate.ai"


def test_env_overrides_and_debug_static_storage():
    loaded = load_settings(
        DEBUG="True",
        CONN_MAX_AGE="5",
        CSRF_TRUSTED_ORIGINS=" https://a.example , https://b.example ,",
        LOG_LEVEL="debug",
        SEARCH_ENABLED="true",
    )

    assert loaded["conn"] == 5
    assert loaded["csrf"] == ["https://a.example", "https://b.example"]
    assert loaded["level"] == "DEBUG"
    assert loaded["static"] == "whitenoise.storage.StaticFilesStorage"
    assert loaded["search"] is True
