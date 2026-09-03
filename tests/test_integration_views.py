from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from apps.integration.context import IntegrationContext
from apps.integration.exceptions import (
    IntegrationUnavailableError,
    NoActiveRound,
    RoundSelectionRequired,
)
from apps.integration.repository import RoundMembership
from apps.integration.views import round_context


class RoundContextViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, external_user_id=7)
        self.context = IntegrationContext(
            user_id=7,
            round_id=3,
            participant_id=10,
            team_id=30,
            parent_role="fixture-parent-role",
            is_staff=False,
            is_superuser=False,
        )

    def request(self, method="get", data=None):
        request = getattr(self.factory, method)("/integration/round/", data=data or {})
        request.user = self.user
        request.session = {}
        return request

    @patch("apps.integration.views.get_context_resolver")
    def test_single_round_context_is_rendered(self, get_resolver):
        get_resolver.return_value.resolve.return_value = self.context

        response = round_context(self.request())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "회차와 팀 소속이 확인되었습니다")

    @patch("apps.integration.views.get_context_resolver")
    def test_no_round_screen_is_rendered_without_latest_fallback(self, get_resolver):
        get_resolver.return_value.resolve.side_effect = NoActiveRound

        response = round_context(self.request())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "진행 중 회차가 없습니다")

    @patch("apps.integration.views.get_context_resolver")
    def test_multiple_rounds_render_selection_screen(self, get_resolver):
        round_row = RoundMembership(
            user_id=7,
            round_id=3,
            round_title="Fixture Round",
            round_status="fixture-running",
            participant_id=10,
            team_id=30,
            team_name="Fixture Team",
        )
        get_resolver.return_value.resolve.side_effect = RoundSelectionRequired([round_row])

        response = round_context(self.request())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "회차 선택")
        self.assertContains(response, 'value="3"')

    @patch("apps.integration.views.get_context_resolver")
    def test_posted_round_is_revalidated_before_session_storage(self, get_resolver):
        resolver = Mock()
        resolver.resolve.return_value = self.context
        get_resolver.return_value = resolver
        request = self.request("post", {"round_id": "3"})

        response = round_context(request)

        resolver.resolve.assert_called_once_with(request, round_id=3)
        self.assertEqual(request.session["selected_round_id"], 3)
        self.assertEqual(response.status_code, 200)

    @patch("apps.integration.views.get_context_resolver")
    def test_non_participant_gets_403_and_round_is_not_stored(self, get_resolver):
        get_resolver.return_value.resolve.side_effect = PermissionDenied
        request = self.request("post", {"round_id": "99"})

        response = round_context(request)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("selected_round_id", request.session)

    @patch("apps.integration.views.get_context_resolver")
    def test_view_outage_returns_503_and_round_is_not_stored(self, get_resolver):
        get_resolver.return_value.resolve.side_effect = IntegrationUnavailableError
        request = self.request("post", {"round_id": "3"})

        response = round_context(request)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("selected_round_id", request.session)
        self.assertContains(response, "변경 작업을 수행할 수 없습니다", status_code=503)

    @patch("apps.integration.views.get_context_resolver")
    def test_stale_session_round_is_cleared_and_current_round_is_resolved(self, get_resolver):
        resolver = Mock()
        resolver.resolve.side_effect = [PermissionDenied, self.context]
        get_resolver.return_value = resolver
        request = self.request()
        request.session["selected_round_id"] = 2

        response = round_context(request)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("selected_round_id", request.session)
        self.assertEqual(
            resolver.resolve.call_args_list,
            [
                ((request,), {"round_id": 2}),
                ((request,), {}),
            ],
        )

    def test_invalid_round_id_returns_400_without_resolver_call(self):
        response = round_context(self.request("post", {"round_id": "not-an-id"}))

        self.assertEqual(response.status_code, 400)
