from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase

from apps.integration.exceptions import IntegrationUnavailableError
from apps.integration.models import AxUserTeamLoginView, UserRoundTeamView
from apps.integration.repository import DjangoViewIntegrationRepository, escape_like_pattern


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
