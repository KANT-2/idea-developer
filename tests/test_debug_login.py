from unittest.mock import patch

from django.contrib.auth import SESSION_KEY
from django.test import TestCase, override_settings
from django.urls import Resolver404, resolve, reverse

from apps.accounts.checks import (
    debug_login_not_deployed,
    production_email_backend_is_real,
)
from apps.accounts.models import LoginAuditLog
from apps.accounts.services import OtpAuthenticationService
from apps.integration.repository import FixtureIntegrationRepository
from tests.fixtures.integration_views import (
    AX_USER_TEAM_LOGIN_ROWS,
    USER_ROUND_TEAM_ROWS,
)


class DebugLoginDeploymentTests(TestCase):
    def test_production_urlconf_does_not_register_debug_login(self):
        with self.assertRaises(Resolver404):
            resolve("/accounts/dev/login/")
        self.assertEqual(self.client.get("/accounts/dev/login/").status_code, 404)
        self.assertEqual(debug_login_not_deployed(None), [])

    @override_settings(DEBUG=False, ROOT_URLCONF="tests.debug_urlconf")
    def test_deployment_check_detects_accidentally_registered_debug_url(self):
        errors = debug_login_not_deployed(None)

        self.assertEqual([error.id for error in errors], ["accounts.E001"])
        self.assertEqual(self.client.get("/accounts/dev/login/").status_code, 404)

    @override_settings(
        DEBUG=False,
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    )
    def test_deployment_check_rejects_non_delivery_email_backend(self):
        errors = production_email_backend_is_real(None)

        self.assertEqual([error.id for error in errors], ["accounts.E002"])


@override_settings(DEBUG=True, ROOT_URLCONF="tests.debug_urlconf", USER_SEARCH_PAGE_SIZE=1)
class DebugLoginFlowTests(TestCase):
    def setUp(self):
        second_user = {
            **AX_USER_TEAM_LOGIN_ROWS[0],
            "user_id": 8,
            "user_email": "member2@example.test",
            "primary_email": "member2@example.test",
            "display_name_snapshot": "테스트 사용자 2",
        }
        self.repository = FixtureIntegrationRepository(
            users=[AX_USER_TEAM_LOGIN_ROWS[0], second_user],
            memberships=USER_ROUND_TEAM_ROWS,
            active_statuses={"fixture-running"},
        )
        self.repository_patch = patch(
            "apps.accounts.views.get_integration_repository",
            return_value=self.repository,
        )
        self.service_patch = patch(
            "apps.accounts.views.get_authentication_service",
            return_value=OtpAuthenticationService(self.repository),
        )
        self.repository_patch.start()
        self.service_patch.start()
        self.addCleanup(self.repository_patch.stop)
        self.addCleanup(self.service_patch.stop)

    def test_debug_page_warns_and_does_not_list_users_without_search(self):
        response = self.client.get(reverse("accounts_debug:login"))

        self.assertContains(response, "개발 전용 로그인")
        self.assertNotContains(response, "member@example.test")

    def test_debug_search_is_paginated(self):
        response = self.client.get(reverse("accounts_debug:login"), {"q": "테스트"})

        self.assertContains(response, "member@example.test")
        self.assertNotContains(response, "member2@example.test")
        self.assertContains(response, "다음")

    def test_selected_user_is_revalidated_and_session_is_created(self):
        response = self.client.post(
            reverse("accounts_debug:login"),
            {"external_user_id": "7"},
        )

        self.assertRedirects(response, reverse("ideas:home"))
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertTrue(
            LoginAuditLog.objects.filter(
                event=LoginAuditLog.Event.DEBUG_LOGIN,
                external_user_id=7,
            ).exists()
        )

    def test_unknown_selected_user_is_denied(self):
        response = self.client.post(
            reverse("accounts_debug:login"),
            {"external_user_id": "999"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(SESSION_KEY, self.client.session)
