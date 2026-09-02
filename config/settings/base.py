from __future__ import annotations

import json
import os
from decimal import Decimal
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
    "apps.accounts",
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
    "apps.prds",
    "apps.ai",
]

AUTH_USER_MODEL = "accounts.LocalUserMapping"
LOGIN_URL = "accounts:login"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@example.test")
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
OTP_EXPIRY_SECONDS = 600
OTP_MAX_FAILED_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("OTP_RATE_LIMIT_WINDOW_SECONDS", "900"))
OTP_EMAIL_REQUEST_LIMIT = int(os.getenv("OTP_EMAIL_REQUEST_LIMIT", "5"))
OTP_IP_REQUEST_LIMIT = int(os.getenv("OTP_IP_REQUEST_LIMIT", "20"))
USER_SEARCH_MIN_LENGTH = int(os.getenv("USER_SEARCH_MIN_LENGTH", "2"))
USER_SEARCH_PAGE_SIZE = int(os.getenv("USER_SEARCH_PAGE_SIZE", "20"))
USER_SEARCH_MAX_PAGE_SIZE = int(os.getenv("USER_SEARCH_MAX_PAGE_SIZE", "50"))
HOME_PAGE_SIZE = int(os.getenv("HOME_PAGE_SIZE", "12"))
HOME_MAX_PAGE_SIZE = int(os.getenv("HOME_MAX_PAGE_SIZE", "50"))
PRD_DETAIL_PAGE_SIZE = int(os.getenv("PRD_DETAIL_PAGE_SIZE", "20"))
PRD_DETAIL_MAX_PAGE_SIZE = int(os.getenv("PRD_DETAIL_MAX_PAGE_SIZE", "50"))
PARENT_ROLE_PARTICIPANT_MAP = json.loads(os.getenv("PARENT_ROLE_PARTICIPANT_MAP", "{}"))
PARENT_STAFF_PARTICIPANT_ROLE = os.getenv("PARENT_STAFF_PARTICIPANT_ROLE", "")
PARENT_SUPERUSER_PARTICIPANT_ROLE = os.getenv("PARENT_SUPERUSER_PARTICIPANT_ROLE", "")

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
INTEGRATION_APPROVED_USER_STATUS = os.getenv("INTEGRATION_APPROVED_USER_STATUS", "approved")
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
    "apps.ai.worker.AiJobRunner",
)

# AI providers must read their secret from the environment. The common layer keeps the
# provider pluggable and deliberately defaults to a provider that performs no network call.
AI_PROVIDER_CLASS = os.getenv(
    "AI_PROVIDER_CLASS",
    "apps.ai.providers.UnconfiguredAiProvider",
)
AI_RESULT_PROCESSOR_CLASS = os.getenv(
    "AI_RESULT_PROCESSOR_CLASS",
    "apps.ai.brainstorm.BrainstormAiResultRouter",
)
AI_MODEL_API_KEY = os.getenv("AI_MODEL_API_KEY", "")
AI_JOB_TIMEOUT_SECONDS = int(os.getenv("AI_JOB_TIMEOUT_SECONDS", "30"))
AI_JOB_MAX_ATTEMPTS = int(os.getenv("AI_JOB_MAX_ATTEMPTS", "3"))
AI_JOB_RETRY_BASE_SECONDS = int(os.getenv("AI_JOB_RETRY_BASE_SECONDS", "5"))
AI_DAILY_REQUEST_LIMIT = int(os.getenv("AI_DAILY_REQUEST_LIMIT", "50"))
AI_DAILY_TOKEN_LIMIT = int(os.getenv("AI_DAILY_TOKEN_LIMIT", "200000"))
AI_DAILY_COST_LIMIT_USD = Decimal(os.getenv("AI_DAILY_COST_LIMIT_USD", "20.00"))
AI_CHAT_MESSAGE_MAX_LENGTH = int(os.getenv("AI_CHAT_MESSAGE_MAX_LENGTH", "4000"))
AI_CONTEXT_MAX_CHARS = int(os.getenv("AI_CONTEXT_MAX_CHARS", "20000"))
AI_RESPONSE_MAX_LENGTH = int(os.getenv("AI_RESPONSE_MAX_LENGTH", "12000"))
AI_DRAFT_MAX_LENGTH = int(os.getenv("AI_DRAFT_MAX_LENGTH", "12000"))
AI_CHAT_RECENT_TURNS = 3
AI_TTL_DELETE_BATCH_SIZE = int(os.getenv("AI_TTL_DELETE_BATCH_SIZE", "500"))
AI_BRAINSTORM_MAX_NODES = int(os.getenv("AI_BRAINSTORM_MAX_NODES", "500"))
AI_BRAINSTORM_MAX_CHARS = int(os.getenv("AI_BRAINSTORM_MAX_CHARS", "50000"))

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
