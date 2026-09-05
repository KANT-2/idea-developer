import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class ProductionSettingsTests(SimpleTestCase):
    def test_secure_cookies_do_not_depend_on_development_debug_env(self):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                "DJANGO_DEBUG": "true",
                "DJANGO_SECRET_KEY": "production-settings-test-secret",
            }
        )
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; from django.conf import settings; "
                    "print(json.dumps({"
                    "'debug': settings.DEBUG, "
                    "'session': settings.SESSION_COOKIE_SECURE, "
                    "'csrf': settings.CSRF_COOKIE_SECURE"
                    "}))"
                ),
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(
            json.loads(process.stdout),
            {"debug": False, "session": True, "csrf": True},
        )
