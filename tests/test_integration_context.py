from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from apps.integration.context import (
    StandaloneSessionContextResolver,
    TestIntegrationContextResolver,
)
from apps.integration.exceptions import (
    IntegrationUnavailableError,
    NoActiveRound,
    RoundSelectionRequired,
)
from apps.integration.repository import FixtureIntegrationRepository
from tests.fixtures.integration_views import (
    AX_USER_TEAM_LOGIN_ROWS,
    USER_ROUND_TEAM_ROWS,
)


class StandaloneSessionContextResolverTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.request.session = {}
        self.request.user = SimpleNamespace(
            is_authenticated=True,
            external_user_id=7,
            is_staff=True,
            is_superuser=True,
        )
        self.repository = FixtureIntegrationRepository(
            users=AX_USER_TEAM_LOGIN_ROWS,
            memberships=USER_ROUND_TEAM_ROWS,
            active_statuses={"fixture-running"},
        )
        self.resolver = StandaloneSessionContextResolver(self.repository)

    def test_single_active_round_is_selected_from_round_team_view(self):
        context = self.resolver.resolve(self.request)

        self.assertEqual(context.user_id, 7)
        self.assertEqual(context.round_id, 3)
        self.assertEqual(context.participant_id, 10)
        self.assertEqual(context.team_id, 30)
        self.assertEqual(context.parent_role, "fixture-parent-role")
        self.assertFalse(context.is_staff)
        self.assertFalse(context.is_superuser)

    def test_selected_round_is_revalidated_by_user_and_round(self):
        context = self.resolver.resolve(self.request, round_id=3)

        self.assertEqual(context.team_id, 30)

    def test_rejects_round_where_user_is_not_an_active_participant(self):
        with self.assertRaises(PermissionDenied):
            self.resolver.resolve(self.request, round_id=999)

        with self.assertRaises(PermissionDenied):
            self.resolver.resolve(self.request, round_id=2)

    def test_no_active_round_does_not_fall_back_to_latest(self):
        repository = FixtureIntegrationRepository(
            users=AX_USER_TEAM_LOGIN_ROWS,
            memberships=USER_ROUND_TEAM_ROWS,
            active_statuses={"different-active-value"},
        )

        with self.assertRaises(NoActiveRound):
            StandaloneSessionContextResolver(repository).resolve(self.request)

    def test_multiple_active_rounds_require_user_selection(self):
        second_active = {
            **USER_ROUND_TEAM_ROWS[0],
            "round_id": 4,
            "round_title": "Fixture Round 4",
            "participant_id": 11,
            "team_id": 40,
        }
        repository = FixtureIntegrationRepository(
            users=AX_USER_TEAM_LOGIN_ROWS,
            memberships=[USER_ROUND_TEAM_ROWS[0], second_active],
            active_statuses={"fixture-running"},
        )

        with self.assertRaises(RoundSelectionRequired) as raised:
            StandaloneSessionContextResolver(repository).resolve(self.request)

        self.assertEqual({row.round_id for row in raised.exception.rounds}, {3, 4})

    def test_view_outage_is_not_bypassed_for_a_write_context(self):
        class UnavailableRepository:
            def get_user(self, user_id):
                raise IntegrationUnavailableError

        with self.assertRaises(IntegrationUnavailableError):
            StandaloneSessionContextResolver(UnavailableRepository()).resolve(
                self.request, round_id=3
            )

    def test_test_resolver_uses_the_same_context_contract(self):
        context = TestIntegrationContextResolver(self.repository).resolve(self.request, round_id=3)

        self.assertEqual(context.user_id, 7)

    def test_rejects_anonymous_or_unmapped_local_user(self):
        self.request.user = SimpleNamespace(is_authenticated=False)
        with self.assertRaises(PermissionDenied):
            self.resolver.resolve(self.request, round_id=3)

        self.request.user = SimpleNamespace(is_authenticated=True)
        with self.assertRaises(PermissionDenied):
            self.resolver.resolve(self.request, round_id=3)
