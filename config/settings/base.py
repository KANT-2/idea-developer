from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-non-production-key")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
CSRF_FAILURE_VIEW = "apps.common.views.csrf_failure"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.common",
    "apps.integration",
    "apps.jobs",
    "apps.brainstorm",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.RequestContextMiddleware",
    "apps.common.middleware.ApiExceptionMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.common.context_processors.runtime_settings",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "idea_developer"),
        "USER": os.getenv("POSTGRES_USER", "idea_developer"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "60")),
        "OPTIONS": {
            "options": os.getenv(
                "POSTGRES_OPTIONS",
                "-c search_path=idea_developer,public",
            )
        },
    }
}

if os.getenv("INTEGRATION_DB_NAME"):
    DATABASES["integration"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["INTEGRATION_DB_NAME"],
        "USER": os.getenv("INTEGRATION_DB_USER", ""),
        "PASSWORD": os.getenv("INTEGRATION_DB_PASSWORD", ""),
        "HOST": os.getenv("INTEGRATION_DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("INTEGRATION_DB_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("INTEGRATION_DB_CONN_MAX_AGE", "0")),
        "OPTIONS": {
            "options": os.getenv(
                "INTEGRATION_DB_OPTIONS",
                "-c default_transaction_read_only=on -c search_path=public",
            )
        },
    }

DATABASE_ROUTERS = ["apps.integration.db_router.IntegrationViewRouter"]
requested_integration_alias = os.getenv("INTEGRATION_DB_ALIAS") or None
INTEGRATION_DB_ALIAS = requested_integration_alias or (
    "integration" if "integration" in DATABASES else "default"
)
if INTEGRATION_DB_ALIAS not in DATABASES:
    raise RuntimeError(f"Unknown INTEGRATION_DB_ALIAS: {INTEGRATION_DB_ALIAS}")
INTEGRATION_ACTIVE_ROUND_STATUSES = frozenset(env_list("INTEGRATION_ACTIVE_ROUND_STATUSES"))
INTEGRATION_CONTEXT_RESOLVER_CLASS = os.getenv(
    "INTEGRATION_CONTEXT_RESOLVER_CLASS",
    "apps.integration.context.StandaloneSessionContextResolver",
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Seoul")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

API_VERSION = "v1"
POLLING_INTERVAL_MS = int(os.getenv("POLLING_INTERVAL_MS", "3000"))
POLLING_MIN_INTERVAL_MS = int(os.getenv("POLLING_MIN_INTERVAL_MS", "2000"))
POLLING_MAX_INTERVAL_MS = int(os.getenv("POLLING_MAX_INTERVAL_MS", "5000"))

JOB_WORKER_POLL_SECONDS = float(os.getenv("JOB_WORKER_POLL_SECONDS", "5"))
JOB_RUNNER_CLASS = os.getenv(
    "JOB_RUNNER_CLASS",
    "apps.jobs.runners.NoopJobRunner",
)

REACT_VERSION = "18.3.1"
REACT_CDN_URL = f"https://cdn.jsdelivr.net/npm/react@{REACT_VERSION}/umd/react.production.min.js"
REACT_DOM_CDN_URL = (
    f"https://cdn.jsdelivr.net/npm/react-dom@{REACT_VERSION}/umd/react-dom.production.min.js"
)

# Parent handoff point: add the CDN origin to the parent's CSP script-src policy.
CSP_SCRIPT_SRC = env_list("CSP_SCRIPT_SRC", "'self',https://cdn.jsdelivr.net")

LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "apps.common.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.server": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        }
    },
}
