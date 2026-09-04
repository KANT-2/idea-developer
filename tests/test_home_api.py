from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import LocalUserMapping
from apps.ai.models import AiActionType, AiFeatureType, AiUsageLog, AiUsageStatus
from apps.integration.context import IntegrationContext
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.models import (
    Prd,
    PrdChangeHistory,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
    PrdType,
)

TODAY = date(2026, 9, 2)
NOW = datetime(2026, 9, 2, 12, tzinfo=UTC)


def user_row(user_id):
    return {
        "user_id": user_id,
        "user_email": f"user{user_id}@example.test",
        "primary_email": f"user{user_id}@example.test",
        "first_name": "사용자",
        "last_name": str(user_id),
        "role": "student",
        "approval_status": "fixture-approved",
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
    }


def membership_row(user_id, *, round_id=3, team_id=30):
    return {
        "user_id": user_id,
        "round_id": round_id,
        "round_title": f"회차 {round_id}",
        "round_status": "fixture-running",
        "participant_id": user_id * 10,
        "team_id": team_id,
        "team_name": f"팀 {team_id}",
        "display_name_snapshot": f"표시명 {user_id}",
    }


@override_settings(HOME_PAGE_SIZE=12, HOME_MAX_PAGE_SIZE=20)
class HomeApiTests(TestCase):
    def setUp(self):
        users = [user_row(user_id) for user_id in (7, 8, 9, 10, 11, 12, 13)]
        memberships = [membership_row(user_id) for user_id in (7, 8, 9, 11, 12, 13)]
        memberships.append(membership_row(10, team_id=31))
        self.repository = FixtureIntegrationRepository(
            users=users,
            memberships=memberships,
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
            "apps.prds.views.get_context_resolver", return_value=self.resolver
        )
        self.repository_patch = patch(
            "apps.prds.home_views.get_integration_repository",
            return_value=self.repository,
        )
        self.now_patch = patch("apps.prds.home.timezone.now", return_value=NOW)
        self.today_patch = patch("apps.prds.home.timezone.localdate", return_value=TODAY)
        for active_patch in (
            self.context_patch,
            self.repository_patch,
            self.now_patch,
            self.today_patch,
        ):
            active_patch.start()
            self.addCleanup(active_patch.stop)

        local_user = LocalUserMapping.objects.create_user(7, "user7@example.test")
        self.client.force_login(local_user)
        session = self.client.session
        session["selected_round_id"] = 3
        session.save()

        self.personal = self.make_prd(
            title="진행 개인",
            creator=7,
            status=PrdStatus.IN_PROGRESS,
            prd_type=PrdType.NEW_PRODUCT,
            deadline=TODAY,
            participants=((7, PrdParticipantRole.OWNER),),
            completed_questions=1,
            question_count=2,
            created_at=NOW - timedelta(hours=71),
            updated_at=NOW - timedelta(hours=1),
        )
        self.collaborative = self.make_prd(
            title="완료 협업",
            creator=8,
            status=PrdStatus.COMPLETED,
            prd_type=PrdType.NEW_FEATURE,
            deadline=TODAY + timedelta(days=6),
            participants=(
                (8, PrdParticipantRole.OWNER),
                (7, PrdParticipantRole.VIEWER),
                (9, PrdParticipantRole.EDITOR),
                (11, PrdParticipantRole.EDITOR),
                (12, PrdParticipantRole.EDITOR),
                (13, PrdParticipantRole.EDITOR),
            ),
            completed_questions=1,
            question_count=1,
            created_at=NOW - timedelta(hours=73),
            updated_at=NOW - timedelta(hours=2),
        )
        self.team_shared = self.make_prd(
            title="팀 공유 보류",
            creator=9,
            status=PrdStatus.HELD,
            prd_type=PrdType.IMPROVEMENT,
            team_id=30,
            is_team_shared=True,
            participants=((9, PrdParticipantRole.OWNER),),
            updated_at=NOW - timedelta(hours=3),
        )
        self.dropped = self.make_prd(
            title="드랍 개인",
            creator=7,
            status=PrdStatus.DROPPED,
            prd_type=PrdType.IMPROVEMENT,
            deadline=TODAY + timedelta(days=1),
            participants=((7, PrdParticipantRole.OWNER),),
            updated_at=NOW - timedelta(hours=4),
        )
        self.unauthorized = self.make_prd(
            title="다른 팀 비공개",
            creator=10,
            status=PrdStatus.IN_PROGRESS,
            team_id=31,
            participants=((10, PrdParticipantRole.OWNER),),
        )
        self.other_round = self.make_prd(
            title="다른 회차",
            creator=7,
            status=PrdStatus.IN_PROGRESS,
            round_id=2,
            participants=((7, PrdParticipantRole.OWNER),),
        )
        self.deleted = self.make_prd(
            title="삭제 PRD",
            creator=7,
            status=PrdStatus.IN_PROGRESS,
            participants=((7, PrdParticipantRole.OWNER),),
            is_deleted=True,
        )
        self.add_ai_logs()

    def make_prd(
        self,
        *,
        title,
        creator,
        status,
        prd_type=PrdType.NEW_PRODUCT,
        round_id=3,
        team_id=30,
        is_team_shared=False,
        deadline=None,
        participants=(),
        completed_questions=0,
        question_count=0,
        created_at=None,
        updated_at=None,
        is_deleted=False,
    ):
        prd = Prd.objects.create(
            title=title,
            description=f"{title} 설명",
            deadline=deadline,
            prd_type=prd_type,
            status=status,
            round_id=round_id,
            team_id=team_id,
            is_team_shared=is_team_shared,
            creator_user_id=creator,
            creation_idempotency_key=f"home-{title}",
            is_deleted=is_deleted,
            deleted_at=NOW if is_deleted else None,
        )
        for user_id, role in participants:
            PrdParticipant.objects.create(
                prd=prd,
                user_id=user_id,
                participant_id=user_id * 10,
                role=role,
            )
        if question_count:
            section = PrdSection.objects.create(prd=prd, title="섹션", position=1)
            for position in range(1, question_count + 1):
                PrdQuestion.objects.create(
                    section=section,
                    prompt=f"질문 {position}",
                    position=position,
                    is_completed=position <= completed_questions,
                )
        Prd.objects.filter(pk=prd.pk).update(
            created_at=created_at or NOW - timedelta(days=10),
            updated_at=updated_at or NOW - timedelta(days=5),
        )
        prd.refresh_from_db()
        return prd

    def add_ai_logs(self):
        for _ in range(2):
            AiUsageLog.objects.create(
                prd=self.collaborative,
                user_id=7,
                feature_type=AiFeatureType.COACHING,
                action_type=AiActionType.CHAT,
                status=AiUsageStatus.SUCCESS,
            )
        AiUsageLog.objects.create(
            prd=self.collaborative,
            user_id=7,
            feature_type=AiFeatureType.COACHING,
            action_type=AiActionType.CHAT,
            status=AiUsageStatus.FAILED,
        )
        AiUsageLog.objects.create(
            prd=self.collaborative,
            user_id=7,
            feature_type=AiFeatureType.COACHING,
            action_type=AiActionType.DRAFT,
            status=AiUsageStatus.SUCCESS,
        )
        AiUsageLog.objects.create(
            prd=self.unauthorized,
            user_id=10,
            feature_type=AiFeatureType.COACHING,
            action_type=AiActionType.CHAT,
            status=AiUsageStatus.SUCCESS,
        )

    def get_home(self, **params):
        return self.client.get(reverse("home_api:home"), params)

    def test_home_returns_user_kpis_default_order_and_cards(self):
        response = self.get_home()

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["user"], {"id": 7, "display_name": "표시명 7"})
        self.assertEqual(
            data["kpis"],
            {
                "total_prds": 4,
                "in_progress_prds": 1,
                "completed_prds": 1,
                "due_this_week": 1,
                "average_completion_rate": 38,
                "ai_coaching_count": 2,
            },
        )
        self.assertEqual(
            [item["id"] for item in data["items"]],
            [
                self.personal.id,
                self.collaborative.id,
                self.team_shared.id,
                self.dropped.id,
            ],
        )
        personal = data["items"][0]
        self.assertTrue(personal["show_new_badge"])
        self.assertEqual(personal["completion_rate"], 50)
        self.assertEqual(personal["d_day"], "D-Day")
        self.assertEqual(personal["my_role"], "owner")
        self.assertTrue(personal["can_edit"])
        collaborative = data["items"][1]
        self.assertFalse(collaborative["show_new_badge"])
        self.assertEqual(collaborative["d_day"], "D-6")
        self.assertEqual(collaborative["participant_count"], 6)
        self.assertEqual(len(collaborative["participants"]), 4)
        self.assertEqual(collaborative["ai_coaching_count"], 2)
        self.assertFalse(collaborative["can_edit"])
        team_shared = data["items"][2]
        self.assertIsNone(team_shared["my_role"])
        self.assertFalse(team_shared["can_edit"])

    def test_home_activity_uses_only_prds_where_user_is_a_participant(self):
        own_change = PrdChangeHistory.objects.create(
            prd=self.personal,
            actor_user_id=7,
            event_type="answer_updated",
        )
        teammate_change = PrdChangeHistory.objects.create(
            prd=self.collaborative,
            actor_user_id=8,
            event_type="prd_completed",
        )
        shared_but_not_joined = PrdChangeHistory.objects.create(
            prd=self.team_shared,
            actor_user_id=9,
            event_type="answer_updated",
        )
        PrdChangeHistory.objects.filter(pk=own_change.pk).update(
            created_at=NOW - timedelta(hours=1)
        )
        PrdChangeHistory.objects.filter(pk=teammate_change.pk).update(
            created_at=NOW - timedelta(days=1)
        )
        PrdChangeHistory.objects.filter(pk=shared_but_not_joined.pk).update(
            created_at=NOW - timedelta(minutes=5)
        )

        data = self.get_home().json()["data"]

        self.assertEqual(
            [day["day_label"] for day in data["weekly_activity"]],
            list("월화수목금토일"),
        )
        self.assertEqual([day["count"] for day in data["weekly_activity"]], [0, 0, 1, 0, 0, 0, 0])
        self.assertEqual(
            [activity["prd_id"] for activity in data["recent_activity"]],
            [self.personal.id, self.collaborative.id],
        )
        self.assertEqual(data["recent_activity"][0]["actor_display_name"], "표시명 7")
        self.assertEqual(data["recent_activity"][0]["description"], "질문 답변을 수정했습니다.")
        self.assertNotIn(
            self.team_shared.id,
            [activity["prd_id"] for activity in data["recent_activity"]],
        )

    def test_recent_activity_endpoint_is_paginated_and_protected(self):
        for index in range(10):
            PrdChangeHistory.objects.create(
                prd=self.personal,
                actor_user_id=7,
                event_type="answer_updated",
                after_data={"sequence": index},
            )

        response = self.client.get(
            reverse("home_api:recent-activity"),
            {"page": 2, "page_size": 3},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(
            data["pagination"],
            {"page": 2, "page_size": 3, "total_items": 10, "total_pages": 4},
        )
        self.assertEqual(
            self.client.get(reverse("home_api:recent-activity"), {"page": 0}).status_code,
            400,
        )
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("home_api:recent-activity")).status_code,
            401,
        )

    def test_kpis_do_not_change_when_list_filters_return_empty(self):
        response = self.get_home(status="completed", prd_type="new_product")

        data = response.json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["pagination"]["total_items"], 0)
        self.assertEqual(data["kpis"]["total_prds"], 4)
        self.assertEqual(data["applied_filters"]["statuses"], ["completed"])

    def test_tabs_use_server_participant_count_and_explicit_team_sharing(self):
        project_ids = {item["id"] for item in self.get_home(tab="project").json()["data"]["items"]}
        team_ids = {item["id"] for item in self.get_home(tab="team").json()["data"]["items"]}
        personal_ids = {
            item["id"] for item in self.get_home(tab="personal").json()["data"]["items"]
        }

        self.assertEqual(project_ids, {self.personal.id})
        self.assertEqual(team_ids, {self.collaborative.id, self.team_shared.id})
        self.assertEqual(personal_ids, {self.personal.id, self.dropped.id})

    def test_home_scope_separates_explicit_viewer_participation(self):
        mine = self.get_home(scope="mine").json()["data"]
        viewer = self.get_home(scope="viewer").json()["data"]

        self.assertEqual(
            {item["id"] for item in mine["items"]},
            {self.personal.id, self.team_shared.id, self.dropped.id},
        )
        self.assertEqual([item["id"] for item in viewer["items"]], [self.collaborative.id])
        self.assertEqual(viewer["items"][0]["my_role"], PrdParticipantRole.VIEWER)
        self.assertEqual(viewer["applied_filters"]["scope"], "viewer")
        self.assertEqual(mine["kpis"], viewer["kpis"])

    def test_status_or_filter_and_all_statuses_behavior(self):
        response = self.client.get(
            reverse("home_api:home"),
            [("status", "completed"), ("status", "held")],
        )
        ids = {item["id"] for item in response.json()["data"]["items"]}
        self.assertEqual(ids, {self.collaborative.id, self.team_shared.id})

        all_statuses = self.get_home(status="in_progress,completed,held,dropped")
        self.assertEqual(all_statuses.json()["data"]["pagination"]["total_items"], 4)

    def test_date_boundaries_and_dropped_completed_exclusion(self):
        response = self.get_home(
            deadline_from=TODAY.isoformat(),
            deadline_to=(TODAY + timedelta(days=6)).isoformat(),
            sort="deadline_asc",
        )

        items = response.json()["data"]["items"]
        self.assertEqual(
            [item["id"] for item in items],
            [self.personal.id, self.dropped.id, self.collaborative.id],
        )
        self.assertEqual(response.json()["data"]["kpis"]["due_this_week"], 1)

    def test_due_window_past_and_seventh_day_boundaries_and_new_badge(self):
        Prd.objects.filter(pk=self.personal.pk).update(
            deadline=TODAY - timedelta(days=1),
            created_at=NOW - timedelta(hours=72),
        )
        Prd.objects.filter(pk=self.collaborative.pk).update(
            status=PrdStatus.IN_PROGRESS,
            deadline=TODAY + timedelta(days=7),
        )
        Prd.objects.filter(pk=self.team_shared.pk).update(deadline=TODAY + timedelta(days=6))

        data = self.get_home().json()["data"]
        cards = {item["id"]: item for item in data["items"]}

        self.assertEqual(data["kpis"]["due_this_week"], 1)
        self.assertEqual(cards[self.personal.id]["d_day"], "D+1")
        self.assertEqual(cards[self.collaborative.id]["d_day"], "D-7")
        self.assertEqual(cards[self.team_shared.id]["d_day"], "D-6")
        self.assertFalse(cards[self.personal.id]["show_new_badge"])

    def test_completion_updated_and_ai_sorting(self):
        completion_ids = [
            item["id"] for item in self.get_home(sort="completion_desc").json()["data"]["items"]
        ]
        ai_ids = [
            item["id"] for item in self.get_home(sort="ai_coaching_desc").json()["data"]["items"]
        ]
        updated_ids = [
            item["id"] for item in self.get_home(sort="updated_desc").json()["data"]["items"]
        ]

        self.assertEqual(completion_ids[:2], [self.collaborative.id, self.personal.id])
        self.assertEqual(ai_ids[0], self.collaborative.id)
        self.assertEqual(updated_ids[0], self.personal.id)

    def test_pagination_and_invalid_filters(self):
        page = self.get_home(page=2, page_size=2).json()["data"]
        self.assertEqual(page["pagination"]["total_items"], 4)
        self.assertEqual(page["pagination"]["total_pages"], 2)
        self.assertEqual(len(page["items"]), 2)

        for params in (
            {"tab": "unknown"},
            {"scope": "unknown"},
            {"status": "pending"},
            {"sort": "oldest"},
            {"deadline_from": "2026/09/02"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.get_home(**params).status_code, 400)

    def test_other_team_filter_and_anonymous_access_are_rejected(self):
        self.assertEqual(self.get_home(team_id=31).status_code, 403)
        self.client.logout()
        self.assertEqual(self.get_home().status_code, 401)


class RoundlessHomeApiTests(TestCase):
    def setUp(self):
        self.repository = FixtureIntegrationRepository(
            users=[user_row(7), user_row(8)],
            memberships=[membership_row(7)],
            active_statuses={"fixture-running"},
        )
        self.resolver = Mock()
        self.resolver_patch = patch(
            "apps.prds.views.get_context_resolver", return_value=self.resolver
        )
        self.repository_patch = patch(
            "apps.prds.home_views.get_integration_repository",
            return_value=self.repository,
        )
        self.resolver_patch.start()
        self.repository_patch.start()
        self.addCleanup(self.resolver_patch.stop)
        self.addCleanup(self.repository_patch.stop)
        user = LocalUserMapping.objects.create_user(7, "user7@example.test")
        self.client.force_login(user)

        self.personal = self.make_prd(creator=7, round_id=None, key="personal")
        self.other_personal = self.make_prd(creator=8, round_id=None, key="other-personal")
        self.current_round = self.make_prd(creator=7, round_id=3, key="current")
        self.other_round = self.make_prd(creator=7, round_id=2, key="other-round")

    @staticmethod
    def make_prd(*, creator, round_id, key):
        prd = Prd.objects.create(
            title=key,
            prd_type=PrdType.NEW_PRODUCT,
            round_id=round_id,
            team_id=30 if round_id is not None else None,
            creator_user_id=creator,
            creation_idempotency_key=key,
        )
        PrdParticipant.objects.create(
            prd=prd,
            user_id=creator,
            participant_id=creator * 10 if round_id is not None else None,
            role=PrdParticipantRole.OWNER,
        )
        return prd

    def test_no_round_context_returns_only_explicit_roundless_prds(self):
        self.resolver.resolve.return_value = IntegrationContext(
            7, None, None, None, "student", False, False
        )

        response = self.client.get(reverse("home_api:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["data"]["items"]},
            {self.personal.id},
        )
        data = response.json()["data"]
        self.assertEqual(data["user"]["display_name"], "사용자 7")
        self.assertEqual(data["items"][0]["participants"][0]["display_name"], "사용자 7")

    def test_stale_selected_round_falls_back_to_roundless_home(self):
        roundless_context = IntegrationContext(7, None, None, None, "student", False, False)
        self.resolver.resolve.side_effect = [PermissionDenied, roundless_context]
        session = self.client.session
        session["selected_round_id"] = 999
        session.save()

        response = self.client.get(reverse("home_api:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["data"]["items"]},
            {self.personal.id},
        )
        self.assertNotIn("selected_round_id", self.client.session)
        self.assertEqual(
            self.resolver.resolve.call_args_list,
            [
                ((response.wsgi_request,), {"round_id": 999}),
                ((response.wsgi_request,), {}),
            ],
        )

    def test_round_context_includes_own_roundless_and_current_round_only(self):
        self.resolver.resolve.return_value = IntegrationContext(
            7, 3, 70, 30, "student", False, False
        )

        response = self.client.get(reverse("home_api:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["data"]["items"]},
            {self.personal.id, self.current_round.id},
        )


class EmptyHomeApiTests(TestCase):
    @patch("apps.prds.home.timezone.localdate", return_value=TODAY)
    @patch("apps.prds.home.timezone.now", return_value=NOW)
    @patch("apps.prds.home_views.get_integration_repository")
    @patch("apps.prds.views.get_context_resolver")
    def test_empty_home_returns_zero_kpis(
        self,
        context_resolver,
        repository_factory,
        _now,
        _today,
    ):
        context = IntegrationContext(7, 3, 70, 30, "student", False, False)
        context_resolver.return_value.resolve.return_value = context
        repository_factory.return_value = FixtureIntegrationRepository(
            users=[user_row(7)],
            memberships=[membership_row(7)],
            active_statuses={"fixture-running"},
        )
        user = LocalUserMapping.objects.create_user(7, "user7@example.test")
        self.client.force_login(user)

        response = self.client.get(reverse("home_api:home"))

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["pagination"]["total_pages"], 0)
        self.assertTrue(all(value == 0 for value in data["kpis"].values()))
