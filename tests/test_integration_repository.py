from unittest.mock import MagicMock, patch

from django.db import DatabaseError, OperationalError
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import LocalUserMapping
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

        result = self.repository.search_login_users(query="리오넬 메시", page=1, page_size=20)

        self.assertEqual(result.results[0].user_id, 24)
        self.assertEqual(result.results[0].display_name, "리오넬 메시")

        user = self.repository.get_user(24)

        self.assertEqual(user.user_id, 24)
        self.primary.get_user.assert_not_called()

    def test_successful_primary_is_preferred(self):
        expected = object()
        self.primary.get_user.return_value = expected

        self.assertIs(self.repository.get_user(24), expected)

    def test_connection_failure_also_uses_development_fixture(self):
        # 뷰 조회가 실패하는 것과 접속 자체가 안 되는 것은 다른 예외로 온다.
        # 부모 DB가 완전히 죽어 있으면 조회를 시작하기도 전에 접속 단계에서
        # OperationalError가 나므로, 이것도 IntegrationUnavailableError와
        # 똑같이 폴백을 타야 한다.
        self.primary.search_login_users.side_effect = OperationalError(
            "connection timeout expired"
        )

        result = self.repository.search_login_users(query="리오넬 메시", page=1, page_size=20)

        self.assertEqual(result.results[0].user_id, 24)
        self.primary.get_user.assert_not_called()


class FailoverTransactionIsolationTests(TestCase):
    def test_missing_parent_view_does_not_poison_outer_transaction(self):
        primary = DjangoViewIntegrationRepository(database_alias="default")
        fallback = FixtureIntegrationRepository(
            users=[
                {
                    "user_id": 24,
                    "user_email": "lionel.messi@example.com",
                    "primary_email": "lionel.messi@example.com",
                    "first_name": "리오넬",
                    "last_name": "메시",
                    "role": "student",
                    "approval_status": "fixture-approved",
                    "is_active": True,
                    "is_staff": False,
                    "is_superuser": False,
                }
            ],
            active_statuses={"fixture-running"},
        )
        repository = FailoverIntegrationRepository(primary, fallback)

        user = repository.get_user(24)

        self.assertEqual(user.user_id, 24)
        # This query fails with InFailedSqlTransaction on PostgreSQL unless the
        # failed VIEW read was rolled back to an inner savepoint.
        self.assertEqual(LocalUserMapping.objects.count(), 0)
