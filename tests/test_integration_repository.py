from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase

from apps.integration.exceptions import IntegrationUnavailableError
from apps.integration.models import AxUserTeamLoginView, UserRoundTeamView
from apps.integration.repository import (
    DjangoViewIntegrationRepository,
    FailoverIntegrationRepository,
    FixtureIntegrationRepository,
    escape_like_pattern,
)


class DjangoViewIntegrationRepositoryTests(SimpleTestCase):
    def setUp(self):
        self.repository = DjangoViewIntegrationRepository(
            database_alias="default",
            active_statuses={"fixture-running"},
        )

    @patch.object(UserRoundTeamView.objects, "using")
    def test_membership_query_filters_by_user_and_round(self, using):
        query = MagicMock()
        using.return_value.filter.return_value.values.return_value = query
        query.__getitem__.return_value = [
            {
                "user_id": 7,
                "round_id": 3,
                "round_title": "Fixture Round",
                "round_status": "fixture-running",
                "participant_id": 10,
                "team_id": 30,
                "team_name": "Fixture Team",
            }
        ]

        membership = self.repository.get_membership(7, 3)

        using.assert_called_once_with("default")
        using.return_value.filter.assert_called_once_with(user_id=7, round_id=3)
        self.assertEqual(membership.team_id, 30)

    @patch.object(AxUserTeamLoginView.objects, "using")
    def test_database_error_becomes_fail_closed_integration_error(self, using):
        using.side_effect = DatabaseError("fixture outage")

        with self.assertRaises(IntegrationUnavailableError):
            self.repository.get_user(7)

    def test_search_wildcards_are_escaped_as_literal_characters(self):
        self.assertEqual(escape_like_pattern("100%_done!"), "100!%!_done!!")


class FailoverIntegrationRepositoryTests(SimpleTestCase):
    def setUp(self):
        self.primary = MagicMock()
        self.fallback = FixtureIntegrationRepository(
            users=[
                {
                    "user_id": 24,
                    "user_email": "lionel.messi@example.com",
                    "primary_email": "lionel.messi@example.com",
                    "first_name": "리오넬",
                    "last_name": "메시",
                    "display_name_snapshot": "리오넬 메시",
                    "role": "student",
                    "approval_status": "fixture-approved",
                    "is_active": True,
                    "is_staff": False,
                    "is_superuser": False,
                }
            ],
            active_statuses={"fixture-running"},
        )
        self.repository = FailoverIntegrationRepository(self.primary, self.fallback)

    def test_unavailable_primary_uses_development_fixture(self):
        self.primary.search_login_users.side_effect = IntegrationUnavailableError("offline")

        result = self.repository.search_login_users(
            query="리오넬 메시", page=1, page_size=20
        )

        self.assertEqual(result.results[0].user_id, 24)
        self.assertEqual(result.results[0].display_name, "리오넬 메시")

    def test_successful_primary_is_preferred(self):
        expected = object()
        self.primary.get_user.return_value = expected

        self.assertIs(self.repository.get_user(24), expected)
