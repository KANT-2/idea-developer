import os

from .test import *  # noqa: F403

DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "idea_developer_test"),
        "USER": os.getenv("POSTGRES_USER", "idea_developer"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "idea_developer"),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}
INTEGRATION_DB_ALIAS = "default"
