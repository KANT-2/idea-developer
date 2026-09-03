import json
from datetime import date
from unittest.mock import Mock, patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import LocalUserMapping
from apps.integration.context import IntegrationContext
from apps.integration.exceptions import IntegrationUnavailableError
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.models import (
    Prd,
    PrdParticipantRole,
    PrdTemplate,
    PrdTemplateQuestion,
    PrdTemplateSection,
    PrdType,
)


def user_row(user_id, *, email, active=True, approved=True):
    return {
        "user_id": user_id,
        "user_email": email,
        "primary_email": email,
        "first_name": "테스트",
        "last_name": str(user_id),
        "role": "student",
        "approval_status": "fixture-approved" if approved else "waiting",
        "is_active": active,
        "is_staff": False,
        "is_superuser": False,
    }


def membership_row(user_id, participant_id, *, round_id=3, team_id=30, display_name=None):
    return {
        "user_id": user_id,
        "round_id": round_id,
        "round_title": f"회차 {round_id}",
        "round_status": "fixture-running",
        "participant_id": participant_id,
        "team_id": team_id,
        "team_name": f"팀 {team_id}",
        "display_name_snapshot": display_name or f"사용자 {user_id}",
    }


@override_settings(USER_SEARCH_PAGE_SIZE=10, USER_SEARCH_MAX_PAGE_SIZE=20)
class PrdCreationApiTests(TestCase):
    def setUp(self):
        self.users = [
            user_row(7, email="owner@example.test"),
            user_row(8, email="editor@example.test"),
            user_row(9, email="other-team@example.test"),
            user_row(10, email="inactive@example.test", active=False),
            user_row(11, email="past-round@example.test"),
        ]
        self.memberships = [
            membership_row(7, 70, display_name="동명이인"),
            membership_row(8, 80),
            membership_row(9, 90, team_id=31, display_name="동명이인"),
            membership_row(10, 100),
            membership_row(11, 110, round_id=2),
        ]
        self.repository = FixtureIntegrationRepository(
            users=self.users,
            memberships=self.memberships,
            active_statuses={"fixture-running"},
        )
        self.context = IntegrationContext(
            user_id=7,
            round_id=3,
            participant_id=70,
            team_id=30,
            parent_role="student",
            is_staff=False,
            is_superuser=False,
        )
        self.resolver = Mock()
        self.resolver.resolve.return_value = self.context
        self.context_patch = patch(
            "apps.prds.views.get_context_resolver",
            return_value=self.resolver,
        )
        self.repository_patch = patch(
            "apps.prds.views.get_integration_repository",
            return_value=self.repository,
        )
        self.context_patch.start()
        self.repository_patch.start()
        self.addCleanup(self.context_patch.stop)
        self.addCleanup(self.repository_patch.stop)

        user = LocalUserMapping.objects.create_user(7, "owner@example.test")
        self.client.force_login(user)
        session = self.client.session
        session["selected_round_id"] = 3
        session.save()

        PrdTemplate.objects.all().delete()
        template = PrdTemplate.objects.create(
            prd_type=PrdType.NEW_PRODUCT,
            name="신규 프로젝트 템플릿",
        )
        section = PrdTemplateSection.objects.create(
            template=template,
            title="문제",
            guide="문제를 정의합니다.",
            position=1,
        )
        PrdTemplateQuestion.objects.create(
            section=section,
            prompt="어떤 문제인가요?",
            position=1,
        )

    def payload(self, **overrides):
        payload = {
            "prd_type": "new_product",
            "title": "새 PRD",
            "description": "한 줄 소개",
            "deadline": "2027-02-01",
            "participant_user_ids": [8],
        }
        payload.update(overrides)
        return payload

    def post_create(self, payload=None, *, key="create-001", client=None):
        request_client = client or self.client
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
        return request_client.post(
            reverse("prd_api:create"),
            data=json.dumps(payload if payload is not None else self.payload()),
            content_type="application/json",
            **headers,
        )

    def test_current_team_only_and_owner_is_always_selected(self):
        response = self.client.get(
            reverse("prd_api:current-team"),
            {"selected_user_ids": "8"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["round_id"], 3)
        self.assertEqual(data["team"]["team_id"], 30)
        self.assertEqual({row["user_id"] for row in data["users"]}, {7, 8})
        self.assertTrue(all(row["selected"] for row in data["users"]))

    def test_search_is_current_round_scoped_and_returns_selection_state(self):
        response = self.client.get(
            reverse("prd_api:participant-search"),
            {"q": "사용자", "selected_user_ids": "8"},
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertEqual({row["user_id"] for row in results}, {8})
        self.assertTrue(results[0]["selected"])
        self.assertEqual(self.resolver.resolve.call_args.kwargs, {"round_id": 3})

    def test_search_distinguishes_duplicate_names_by_user_id(self):
        response = self.client.get(
            reverse("prd_api:participant-search"),
            {"q": "동명이인"},
        )

        results = response.json()["data"]["results"]
        self.assertEqual({row["user_id"] for row in results}, {7, 9})
        self.assertTrue(all("email" in row and "team" in row for row in results))

    def test_create_uses_context_ids_and_adds_immediate_editors_without_duplicates(self):
        response = self.post_create(
            self.payload(
                round_id=999,
                team_id=999,
                participant_user_ids=[7, 8, 8, 9],
            )
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertTrue(data["created"])
        prd = Prd.objects.get()
        self.assertEqual((prd.round_id, prd.team_id, prd.creator_user_id), (3, 30, 7))
        self.assertEqual(prd.deadline, date(2027, 2, 1))
        participants = {row.user_id: row.role for row in prd.participants.order_by("user_id")}
        self.assertEqual(
            participants,
            {
                7: PrdParticipantRole.OWNER,
                8: PrdParticipantRole.EDITOR,
                9: PrdParticipantRole.EDITOR,
            },
        )
        self.assertEqual(prd.sections.count(), 1)
        self.assertEqual(prd.sections.get().questions.count(), 1)

    def test_roundless_context_supports_parent_search_and_participant_creation(self):
        self.context = IntegrationContext(
            user_id=7,
            round_id=None,
            participant_id=None,
            team_id=None,
            parent_role="student",
            is_staff=False,
            is_superuser=False,
        )
        self.resolver.resolve.return_value = self.context
        session = self.client.session
        session.pop("selected_round_id", None)
        session.save()

        team_response = self.client.get(reverse("prd_api:current-team"))
        search_response = self.client.get(
            reverse("prd_api:participant-search"),
            {"q": "테스트"},
        )
        create_response = self.post_create(
            self.payload(
                round_id=999,
                team_id=999,
                participant_user_ids=[8, 8],
            ),
            key="roundless-api",
        )

        self.assertEqual(team_response.status_code, 200)
        self.assertIsNone(team_response.json()["data"]["team"])
        self.assertEqual(team_response.json()["data"]["users"], [])
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(
            {row["user_id"] for row in search_response.json()["data"]["results"]},
            {7, 8, 9, 11},
        )
        self.assertEqual(create_response.status_code, 201)
        prd = Prd.objects.get()
        self.assertEqual((prd.round_id, prd.team_id), (None, None))
        self.assertEqual(
            list(prd.participants.order_by("user_id").values_list("user_id", "participant_id")),
            [(7, None), (8, None)],
        )

    def test_roundless_creation_rejects_inactive_or_unapproved_parent_user(self):
        self.resolver.resolve.return_value = IntegrationContext(
            7, None, None, None, "student", False, False
        )
        response = self.post_create(
            self.payload(participant_user_ids=[10]),
            key="roundless-inactive",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("participant_user_ids", response.json()["error"]["details"])
        self.assertFalse(Prd.objects.exists())

    def test_retry_with_same_key_returns_original_without_duplicate_rows(self):
        first = self.post_create()
        second = self.post_create(
            self.payload(title="재시도에서 바뀐 제목", participant_user_ids=[9])
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["data"]["created"])
        self.assertEqual(first.json()["data"]["prd"]["id"], second.json()["data"]["prd"]["id"])
        self.assertEqual(Prd.objects.count(), 1)
        prd = Prd.objects.get()
        self.assertEqual(prd.title, "새 PRD")
        self.assertEqual(set(prd.participants.values_list("user_id", flat=True)), {7, 8})

    def test_inactive_missing_and_other_round_users_are_rejected_atomically(self):
        for invalid_user_id in (10, 11, 999):
            with self.subTest(user_id=invalid_user_id):
                response = self.post_create(
                    self.payload(participant_user_ids=[invalid_user_id]),
                    key=f"invalid-{invalid_user_id}",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(
                    "participant_user_ids",
                    response.json()["error"]["details"],
                )
        self.assertFalse(Prd.objects.exists())

    def test_missing_idempotency_key_and_invalid_deadline_are_rejected(self):
        missing_key = self.post_create(key=None)
        invalid_deadline = self.post_create(
            self.payload(deadline="02/01/2027"),
            key="invalid-date",
        )

        self.assertEqual(missing_key.status_code, 400)
        self.assertIn("idempotency_key", missing_key.json()["error"]["details"])
        self.assertEqual(invalid_deadline.status_code, 400)
        self.assertIn("deadline", invalid_deadline.json()["error"]["details"])

    def test_anonymous_and_missing_csrf_are_rejected(self):
        self.client.logout()
        self.assertEqual(self.post_create().status_code, 401)

        csrf_client = Client(enforce_csrf_checks=True)
        user = LocalUserMapping.objects.get(external_user_id=7)
        csrf_client.force_login(user)
        self.assertEqual(self.post_create(client=csrf_client).status_code, 403)

    def test_integration_failure_does_not_create_prd(self):
        self.resolver.resolve.side_effect = IntegrationUnavailableError("outage")

        response = self.post_create()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(Prd.objects.exists())
