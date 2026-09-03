from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import LocalUserMapping
from apps.integration.context import IntegrationContext
from apps.integration.repository import FixtureIntegrationRepository
from tests.fixtures.integration_views import AX_USER_TEAM_LOGIN_ROWS, USER_ROUND_TEAM_ROWS


@override_settings(USER_SEARCH_PAGE_SIZE=10)
class UserSearchApiTests(TestCase):
    def setUp(self):
        duplicate_user = {
            **AX_USER_TEAM_LOGIN_ROWS[0],
            "user_id": 8,
            "user_email": "duplicate@example.test",
            "primary_email": "duplicate@example.test",
        }
        unique_user = {
            **AX_USER_TEAM_LOGIN_ROWS[0],
            "user_id": 9,
            "user_email": "unique@example.test",
            "primary_email": "unique@example.test",
        }
        inactive_user = {
            **AX_USER_TEAM_LOGIN_ROWS[0],
            "user_id": 10,
            "user_email": "inactive-search@example.test",
            "primary_email": "inactive-search@example.test",
            "is_active": False,
        }
        memberships = [
            USER_ROUND_TEAM_ROWS[0],
            {
                **USER_ROUND_TEAM_ROWS[0],
                "user_id": 8,
                "participant_id": 11,
                "team_id": 31,
                "team_name": "다른 팀",
            },
            {
                **USER_ROUND_TEAM_ROWS[0],
                "user_id": 9,
                "participant_id": 12,
                "display_name_snapshot": "고유 이름",
            },
            {
                **USER_ROUND_TEAM_ROWS[0],
                "user_id": 10,
                "participant_id": 13,
                "display_name_snapshot": "비활성 이름",
            },
        ]
        self.repository = FixtureIntegrationRepository(
            users=[AX_USER_TEAM_LOGIN_ROWS[0], duplicate_user, unique_user, inactive_user],
            memberships=memberships,
            active_statuses={"fixture-running"},
        )
        self.context = IntegrationContext(
            user_id=7,
            round_id=3,
            participant_id=10,
            team_id=30,
            parent_role="fixture-parent-role",
            is_staff=False,
            is_superuser=False,
        )
        self.resolver = Mock()
        self.resolver.resolve.return_value = self.context
        self.resolver_patch = patch(
            "apps.accounts.views.get_context_resolver", return_value=self.resolver
        )
        self.repository_patch = patch(
            "apps.accounts.views.get_integration_repository",
            return_value=self.repository,
        )
        self.resolver_patch.start()
        self.repository_patch.start()
        self.addCleanup(self.resolver_patch.stop)
        self.addCleanup(self.repository_patch.stop)
        user = LocalUserMapping.objects.create_user(7, "member@example.test")
        self.client.force_login(user)

    def search(self, **params):
        defaults = {"q": "테스트 사용자", "round_id": 3, "page": 1}
        defaults.update(params)
        return self.client.get(reverse("user_api:search"), defaults)

    def test_search_is_trimmed_round_scoped_and_paginates(self):
        response = self.search(q="  테스트 사용자  ")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["pagination"]["page"], 1)
        self.assertEqual(self.resolver.resolve.call_args.kwargs, {"round_id": 3})

    def test_email_and_team_are_returned_only_for_duplicate_names(self):
        duplicate_results = self.search().json()["data"]["results"]
        self.assertTrue(all("email" in row and "team" in row for row in duplicate_results))
        self.assertNotEqual(duplicate_results[0]["email"], "member@example.test")
        self.assertTrue(duplicate_results[0]["email"].endswith("@example.test"))
        self.assertEqual(
            {row["team"]["team_id"] for row in duplicate_results},
            {30, 31},
        )

        unique_result = self.search(q="고유 이름").json()["data"]["results"][0]
        self.assertNotIn("email", unique_result)
        self.assertNotIn("team", unique_result)

    def test_inactive_users_are_excluded(self):
        response = self.search(q="비활성 이름")

        self.assertEqual(response.json()["data"]["results"], [])

    def test_minimum_query_length_is_enforced(self):
        response = self.search(q="한")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "query_too_short")

    def test_team_filter_cannot_target_another_team(self):
        response = self.search(team_id=31)

        self.assertEqual(response.status_code, 403)

    @override_settings(USER_SEARCH_PAGE_SIZE=1)
    def test_search_page_never_returns_all_matching_users(self):
        response = self.search()

        data = response.json()["data"]
        self.assertEqual(len(data["results"]), 1)
        self.assertTrue(data["pagination"]["has_next"])

    @override_settings(USER_SEARCH_MAX_PAGE_SIZE=1)
    def test_requested_page_size_is_capped(self):
        response = self.search(page_size=1000)

        self.assertEqual(response.json()["data"]["pagination"]["page_size"], 1)

    def test_anonymous_search_is_rejected(self):
        self.client.logout()

        response = self.search()

        self.assertEqual(response.status_code, 401)
