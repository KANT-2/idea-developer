import json
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LocalUserMapping, LoginAuditLog, LoginOtpChallenge
from apps.accounts.services import UNIFORM_REQUEST_MESSAGE, OtpAuthenticationService
from apps.integration.repository import FixtureIntegrationRepository
from tests.fixtures.integration_views import (
    AX_USER_TEAM_LOGIN_ROWS,
    USER_ROUND_TEAM_ROWS,
)


class EmailOtpAuthenticationTests(TestCase):
    def setUp(self):
        self.repository = self.make_repository(AX_USER_TEAM_LOGIN_ROWS)
        self.service_patch = patch(
            "apps.accounts.views.get_authentication_service",
            side_effect=lambda: OtpAuthenticationService(self.repository),
        )
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)
        mail.outbox.clear()

    @staticmethod
    def make_repository(users):
        return FixtureIntegrationRepository(
            users=users,
            memberships=USER_ROUND_TEAM_ROWS,
            active_statuses={"fixture-running"},
        )

    def request_code(self, email="member@example.test", client=None):
        return (client or self.client).post(
            reverse("accounts_api:request-otp"),
            data=json.dumps({"email": email}),
            content_type="application/json",
            REMOTE_ADDR="203.0.113.10",
        )

    def verify_code(self, challenge_id, code, client=None):
        return (client or self.client).post(
            reverse("accounts_api:verify-otp"),
            data=json.dumps({"challenge_id": challenge_id, "code": code}),
            content_type="application/json",
            REMOTE_ADDR="203.0.113.10",
        )

    def issued_code(self):
        match = re.search(r"(\d{6})", mail.outbox[-1].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_normal_authentication_creates_unusable_mapping_and_session(self):
        requested = self.request_code()
        self.assertEqual(requested.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        challenge_id = requested.json()["data"]["challenge_id"]
        issued_code = self.issued_code()
        challenge = LoginOtpChallenge.objects.get(pk=challenge_id)
        self.assertNotEqual(challenge.code_hash, issued_code)
        self.assertNotIn(issued_code, challenge.code_hash)

        verified = self.verify_code(challenge_id, issued_code)

        self.assertEqual(verified.status_code, 200)
        user = LocalUserMapping.objects.get(external_user_id=7)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(int(self.client.session[SESSION_KEY]), user.pk)
        self.assertIsNotNone(user.last_verified_at)
        self.assertTrue(
            LoginAuditLog.objects.filter(
                event=LoginAuditLog.Event.LOGIN_SUCCESS,
                external_user_id=7,
            ).exists()
        )
        self.assertIsNone(AX_USER_TEAM_LOGIN_ROWS[0]["last_login"])

    def test_unknown_inactive_and_unapproved_emails_receive_same_public_message(self):
        unknown = self.request_code("unknown@example.test")

        inactive_row = {
            **AX_USER_TEAM_LOGIN_ROWS[0],
            "user_id": 8,
            "user_email": "inactive@example.test",
            "primary_email": "inactive@example.test",
            "is_active": False,
        }
        unapproved_row = {
            **AX_USER_TEAM_LOGIN_ROWS[0],
            "user_id": 9,
            "user_email": "pending@example.test",
            "primary_email": "pending@example.test",
            "approval_status": "fixture-pending",
        }
        self.repository = self.make_repository([inactive_row, unapproved_row])
        inactive = self.request_code("inactive@example.test")
        unapproved = self.request_code("pending@example.test")

        for response in (unknown, inactive, unapproved):
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["data"]["message"], UNIFORM_REQUEST_MESSAGE)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            LoginOtpChallenge.objects.filter(external_user_id__isnull=True).count(),
            3,
        )

    def test_expired_code_is_rejected(self):
        requested = self.request_code()
        challenge_id = requested.json()["data"]["challenge_id"]
        code = self.issued_code()
        LoginOtpChallenge.objects.filter(pk=challenge_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        response = self.verify_code(challenge_id, code)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"]["code"], "code_expired")

    def test_code_is_one_time_use(self):
        requested = self.request_code()
        challenge_id = requested.json()["data"]["challenge_id"]
        code = self.issued_code()
        self.assertEqual(self.verify_code(challenge_id, code).status_code, 200)

        reused = self.verify_code(challenge_id, code)

        self.assertEqual(reused.status_code, 409)
        self.assertEqual(reused.json()["error"]["code"], "code_already_used")

    def test_five_failures_lock_the_challenge(self):
        requested = self.request_code()
        challenge_id = requested.json()["data"]["challenge_id"]
        issued_code = self.issued_code()
        wrong_code = "000000" if issued_code != "000000" else "000001"

        statuses = [self.verify_code(challenge_id, wrong_code) for _ in range(5)]

        self.assertTrue(all(response.status_code == 400 for response in statuses[:4]))
        self.assertEqual(statuses[4].status_code, 429)
        self.assertEqual(statuses[4].json()["error"]["code"], "attempt_limit")
        self.assertEqual(
            LoginOtpChallenge.objects.get(pk=challenge_id).failed_attempts,
            settings.OTP_MAX_FAILED_ATTEMPTS,
        )
        self.assertEqual(self.verify_code(challenge_id, issued_code).status_code, 429)

    def test_resend_cooldown_is_enforced(self):
        self.assertEqual(self.request_code().status_code, 202)

        response = self.request_code()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "resend_cooldown")
        self.assertIn("Retry-After", response)

    @override_settings(
        OTP_RESEND_COOLDOWN_SECONDS=0,
        OTP_EMAIL_REQUEST_LIMIT=2,
        OTP_IP_REQUEST_LIMIT=20,
    )
    def test_email_request_window_limit_is_enforced(self):
        self.assertEqual(self.request_code().status_code, 202)
        self.assertEqual(self.request_code().status_code, 202)

        response = self.request_code()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "rate_limited")

    @override_settings(
        OTP_RESEND_COOLDOWN_SECONDS=0,
        OTP_EMAIL_REQUEST_LIMIT=100,
        OTP_IP_REQUEST_LIMIT=2,
    )
    def test_ip_request_window_limit_is_enforced(self):
        self.assertEqual(self.request_code("unknown1@example.test").status_code, 202)
        self.assertEqual(self.request_code("unknown2@example.test").status_code, 202)

        response = self.request_code("unknown3@example.test")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "rate_limited")

    def test_safe_internal_next_is_used(self):
        self.client.get(reverse("accounts:login") + "?next=/integration/round/")
        requested = self.request_code()

        response = self.verify_code(requested.json()["data"]["challenge_id"], self.issued_code())

        self.assertEqual(response.json()["data"]["redirect_url"], "/integration/round/")

    def test_external_next_is_rejected(self):
        self.client.get(reverse("accounts:login") + "?next=https://evil.example/phish")
        requested = self.request_code()

        response = self.verify_code(requested.json()["data"]["challenge_id"], self.issued_code())

        self.assertEqual(response.json()["data"]["redirect_url"], reverse("ideas:home"))

    def test_logout_removes_session_and_writes_audit_log(self):
        requested = self.request_code()
        self.verify_code(requested.json()["data"]["challenge_id"], self.issued_code())

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertTrue(
            LoginAuditLog.objects.filter(
                event=LoginAuditLog.Event.LOGOUT,
                external_user_id=7,
            ).exists()
        )

    def test_login_template_contains_accessible_two_step_controls(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertContains(response, 'autocomplete="email"')
        self.assertContains(response, 'autocomplete="one-time-code"')
        self.assertContains(response, 'inputmode="numeric"')
        self.assertContains(response, "accounts/js/login.js")
        self.assertNotContains(response, 'href="/accounts/signup/')
        self.assertNotContains(response, "password-reset")

        script = (settings.BASE_DIR / Path("static/accounts/js/login.js")).read_text(
            encoding="utf-8"
        )
        self.assertIn("X-CSRFToken", script)
        self.assertIn("setBusy", script)
        self.assertIn("setInterval", script)
        self.assertIn("resendButton", script)

    def test_local_mapping_cannot_be_given_a_usable_password(self):
        user = LocalUserMapping.objects.create_user(77, "local@example.test")
        user.set_password("must-not-work")
        user.save()
        user.refresh_from_db()

        self.assertFalse(user.has_usable_password())
        self.assertFalse(self.client.login(external_user_id=77, password="must-not-work"))

        with self.assertRaises(IntegrityError), transaction.atomic():
            LocalUserMapping.objects.filter(pk=user.pk).update(password="usable-value")

    def test_database_rejects_more_than_five_failed_attempts(self):
        challenge_id = self.request_code().json()["data"]["challenge_id"]

        with self.assertRaises(IntegrityError), transaction.atomic():
            LoginOtpChallenge.objects.filter(pk=challenge_id).update(failed_attempts=6)

    def test_csrf_is_required_by_otp_api(self):
        csrf_client = Client(enforce_csrf_checks=True)
        rejected = csrf_client.post(
            reverse("accounts_api:request-otp"),
            data=json.dumps({"email": "member@example.test"}),
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 403)

        csrf_client.get(reverse("accounts:login"))
        token = csrf_client.cookies[settings.CSRF_COOKIE_NAME].value
        accepted = csrf_client.post(
            reverse("accounts_api:request-otp"),
            data=json.dumps({"email": "member@example.test"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
            REMOTE_ADDR="203.0.113.20",
        )
        self.assertEqual(accepted.status_code, 202)
