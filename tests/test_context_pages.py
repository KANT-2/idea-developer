from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import LocalUserMapping
from apps.integration.exceptions import (
    IntegrationUnavailableError,
    NoActiveRound,
    RoundSelectionRequired,
)
from apps.integration.repository import RoundMembership


class ContextPageFailureTests(TestCase):
    def setUp(self):
        user = LocalUserMapping.objects.create_user(7, "owner@example.test")
        self.client.force_login(user)

    def _assert_for_both_pages(self, side_effect, *, status, contains):
        resolver = Mock()
        resolver.resolve.side_effect = side_effect
        with patch("apps.prds.views.get_context_resolver", return_value=resolver):
            for url in (
                reverse("brainstorm-page", args=[999]),
                reverse("prd-write-page", args=[999]),
            ):
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, status)
                    self.assertContains(response, contains, status_code=status)

    def test_no_active_round_renders_safe_empty_state(self):
        self._assert_for_both_pages(
            NoActiveRound("none"),
            status=200,
            contains="현재 참여할 수 있는 진행 중 회차가 없습니다.",
        )

    def test_multiple_rounds_render_selection_instead_of_server_error(self):
        membership = RoundMembership(
            user_id=7,
            round_id=3,
            round_title="3회차",
            round_status="running",
            participant_id=70,
            team_id=30,
            team_name="30팀",
        )
        self._assert_for_both_pages(
            RoundSelectionRequired((membership,)),
            status=200,
            contains="회차 선택",
        )

    def test_view_failure_renders_service_unavailable(self):
        self._assert_for_both_pages(
            IntegrationUnavailableError("outage"),
            status=503,
            contains="사용자·회차 정보를 확인할 수 없습니다.",
        )
