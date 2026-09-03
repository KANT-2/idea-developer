import json
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LocalUserMapping
from apps.ai.models import (
    AiActionType,
    AiChatHistory,
    AiFeatureType,
    AiUsageLog,
    AiUsageStatus,
)
from apps.brainstorm.models import (
    AuditLog,
    BrainstormCanvas,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.context import IntegrationContext
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdChangeHistory,
    PrdComment,
    PrdCommentType,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
    PrdStatusAuditAction,
    PrdStatusAuditLog,
    PrdType,
)


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


@override_settings(PRD_DETAIL_PAGE_SIZE=2, PRD_DETAIL_MAX_PAGE_SIZE=5)
class PrdDetailApiTests(TestCase):
    def setUp(self):
        users = [user_row(user_id) for user_id in range(7, 14)]
        memberships = [membership_row(user_id) for user_id in range(7, 12)]
        memberships.append(membership_row(12, team_id=31))
        memberships.append(membership_row(13, round_id=2))
        self.repository = FixtureIntegrationRepository(
            users=users,
            memberships=memberships,
            active_statuses={"fixture-running"},
        )
        self.resolver = Mock()
        self.context_patch = patch(
            "apps.prds.views.get_context_resolver", return_value=self.resolver
        )
        self.repository_patch = patch(
            "apps.prds.detail_views.get_integration_repository",
            return_value=self.repository,
        )
        self.context_patch.start()
        self.repository_patch.start()
        self.addCleanup(self.context_patch.stop)
        self.addCleanup(self.repository_patch.stop)

        for user_id in range(7, 14):
            LocalUserMapping.objects.create_user(user_id, f"user{user_id}@example.test")

        self.prd = self.make_prd(creator=7, team_id=30)
        for user_id, role in (
            (7, PrdParticipantRole.OWNER),
            (8, PrdParticipantRole.EDITOR),
            (9, PrdParticipantRole.TUTOR),
            (10, PrdParticipantRole.VIEWER),
        ):
            PrdParticipant.objects.create(
                prd=self.prd,
                user_id=user_id,
                participant_id=user_id * 10,
                role=role,
            )
        self.section = PrdSection.objects.create(
            prd=self.prd,
            title="문제 정의",
            guide="문제를 설명합니다.",
            position=1,
        )
        self.question = PrdQuestion.objects.create(
            section=self.section,
            prompt="어떤 문제인가요?",
            position=1,
            is_completed=True,
        )
        self.answer = PrdAnswer.objects.create(
            question=self.question,
            content="사용자 문제입니다.",
            updated_by_user_id=7,
        )
        PrdQuestion.objects.create(
            section=self.section,
            prompt="삭제 질문",
            position=2,
            is_deleted=True,
            deleted_at=timezone.now(),
        )

        self.team_shared = self.make_prd(creator=8, team_id=30, is_team_shared=True)
        PrdParticipant.objects.create(
            prd=self.team_shared,
            user_id=8,
            participant_id=80,
            role=PrdParticipantRole.OWNER,
        )
        self.private_other_team = self.make_prd(creator=12, team_id=31)
        PrdParticipant.objects.create(
            prd=self.private_other_team,
            user_id=12,
            participant_id=120,
            role=PrdParticipantRole.OWNER,
        )
        self.other_round = self.make_prd(creator=13, team_id=30, round_id=2)
        self.deleted_prd = self.make_prd(creator=7, team_id=30, is_deleted=True)
        self.login_as(7, role=PrdParticipantRole.OWNER)

    def make_prd(
        self,
        *,
        creator,
        team_id,
        round_id=3,
        is_team_shared=False,
        is_deleted=False,
    ):
        return Prd.objects.create(
            title=f"PRD {creator}-{round_id}-{Prd.objects.count()}",
            description="상세 설명",
            deadline=None,
            prd_type=PrdType.NEW_PRODUCT,
            status=PrdStatus.IN_PROGRESS,
            round_id=round_id,
            team_id=team_id,
            is_team_shared=is_team_shared,
            creator_user_id=creator,
            creation_idempotency_key=f"detail-{creator}-{round_id}-{Prd.objects.count()}",
            is_deleted=is_deleted,
            deleted_at=timezone.now() if is_deleted else None,
        )

    def login_as(
        self,
        user_id,
        *,
        role=None,
        round_id=3,
        team_id=30,
        is_staff=False,
        is_superuser=False,
    ):
        self.client.force_login(LocalUserMapping.objects.get(external_user_id=user_id))
        self.resolver.resolve.return_value = IntegrationContext(
            user_id=user_id,
            round_id=round_id,
            participant_id=user_id * 10,
            team_id=team_id,
            parent_role="student",
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    def post_json(self, url, payload):
        return self.client.post(url, json.dumps(payload), content_type="application/json")

    def patch_json(self, url, payload):
        return self.client.patch(url, json.dumps(payload), content_type="application/json")

    def test_initial_detail_contains_basic_sections_questions_answers_and_permissions(self):
        response = self.client.get(reverse("prd_api:detail", args=[self.prd.id]))

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["prd"]["id"], self.prd.id)
        self.assertEqual(data["prd"]["completion_rate"], 100)
        self.assertEqual(len(data["sections"]), 1)
        questions = data["sections"][0]["questions"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["answer"]["content"], "사용자 문제입니다.")
        self.assertEqual(data["permissions"]["role"], "owner")
        self.assertTrue(data["permissions"]["can_edit"])
        self.assertTrue(data["permissions"]["can_comment"])

    def test_owner_saves_answer_with_version_and_change_history(self):
        response = self.patch_json(
            reverse("prd_api:question-answer", args=[self.prd.id, self.question.id]),
            {"content": "수동으로 수정한 답변", "version": 1},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["answer"]["content"], "수동으로 수정한 답변")
        self.assertEqual(data["version"], 2)
        self.assertTrue(data["is_completed"])
        self.answer.refresh_from_db()
        self.assertEqual(self.answer.content, "수동으로 수정한 답변")
        history = PrdChangeHistory.objects.get(event_type="answer_updated")
        self.assertEqual(history.actor_user_id, 7)
        self.assertEqual(history.before_data["content"], "사용자 문제입니다.")

    def test_answer_save_rejects_stale_version_and_read_only_user(self):
        url = reverse("prd_api:question-answer", args=[self.prd.id, self.question.id])
        first = self.patch_json(url, {"content": "최신 답변", "version": 1})
        stale = self.patch_json(url, {"content": "오래된 덮어쓰기", "version": 1})
        self.login_as(10, role=PrdParticipantRole.VIEWER)
        denied = self.patch_json(url, {"content": "권한 없는 답변", "version": 2})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "version_conflict")
        self.assertEqual(
            stale.json()["error"]["details"]["latest"]["answer"]["content"],
            "최신 답변",
        )
        self.assertEqual(denied.status_code, 403)
        self.answer.refresh_from_db()
        self.assertEqual(self.answer.content, "최신 답변")

    def test_completed_prd_locks_manual_answer_save(self):
        self.prd.status = PrdStatus.COMPLETED
        self.prd.completed_at = timezone.now()
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])

        response = self.patch_json(
            reverse("prd_api:question-answer", args=[self.prd.id, self.question.id]),
            {"content": "완료 후 수정", "version": 1},
        )

        self.assertEqual(response.status_code, 403)
        self.answer.refresh_from_db()
        self.assertEqual(self.answer.content, "사용자 문제입니다.")

    def test_owner_manages_participants_and_removal_restores_assignee_atomically(self):
        participants_url = reverse("prd_api:participants", args=[self.prd.id])
        created = self.post_json(
            participants_url,
            {"user_id": 11, "role": PrdParticipantRole.EDITOR},
        )
        duplicate = self.post_json(
            participants_url,
            {"user_id": 11, "role": PrdParticipantRole.VIEWER},
        )
        item_url = reverse("prd_api:participant-item", args=[self.prd.id, 11])
        changed = self.patch_json(item_url, {"role": PrdParticipantRole.TUTOR})

        canvas = BrainstormCanvas.objects.create(prd=self.prd)
        node = BrainstormNode.objects.create(
            canvas=canvas,
            node_type=BrainstormNodeType.NOTE,
            content="담당자 복구",
            color="yellow",
            position_x=0,
            position_y=0,
            author_id=7,
            assignee_id=11,
            status=BrainstormNodeStatus.ACCEPTED,
        )
        removed = self.client.delete(item_url)

        self.assertEqual((created.status_code, duplicate.status_code), (201, 200))
        self.assertTrue(created.json()["data"]["created"])
        self.assertFalse(duplicate.json()["data"]["created"])
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["data"]["role"], PrdParticipantRole.TUTOR)
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(self.prd.participants.filter(user_id=11).exists())
        node.refresh_from_db()
        self.assertEqual(node.assignee_id, 7)
        self.assertEqual(node.version, 2)
        self.assertEqual(AuditLog.objects.get().reason, "participant_removed")
        self.assertEqual(
            list(
                self.prd.change_history.order_by("created_at", "id").values_list(
                    "event_type", flat=True
                )
            ),
            ["participant_added", "participant_role_changed", "participant_removed"],
        )

    def test_participant_management_rechecks_membership_permissions_and_completion_lock(self):
        participants_url = reverse("prd_api:participants", args=[self.prd.id])
        invalid_round = self.post_json(
            participants_url,
            {"user_id": 13, "role": PrdParticipantRole.EDITOR},
        )
        self.login_as(8, role=PrdParticipantRole.EDITOR)
        denied = self.post_json(
            participants_url,
            {"user_id": 11, "role": PrdParticipantRole.EDITOR},
        )
        self.login_as(7, role=PrdParticipantRole.OWNER)
        self.prd.status = PrdStatus.COMPLETED
        self.prd.completed_at = timezone.now()
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])
        locked = self.post_json(
            participants_url,
            {"user_id": 11, "role": PrdParticipantRole.EDITOR},
        )
        owner_delete = self.client.delete(
            reverse("prd_api:participant-item", args=[self.prd.id, 7])
        )

        self.assertEqual(invalid_round.status_code, 400)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(locked.status_code, 403)
        self.assertEqual(owner_delete.status_code, 403)

    def test_owner_completes_and_reopens_with_audited_previous_completion(self):
        completed = self.post_json(
            reverse("prd_api:complete", args=[self.prd.id]),
            {},
        )

        self.assertEqual(completed.status_code, 200)
        self.prd.refresh_from_db()
        completed_at = self.prd.completed_at
        self.assertEqual(self.prd.status, PrdStatus.COMPLETED)
        self.assertIsNotNone(completed_at)
        permissions = self.client.get(reverse("prd_api:detail", args=[self.prd.id])).json()["data"][
            "permissions"
        ]
        self.assertFalse(permissions["can_edit"])
        self.assertFalse(permissions["can_comment"])
        self.assertFalse(permissions["can_apply_ai"])
        self.assertTrue(permissions["can_reopen"])

        missing_reason = self.post_json(
            reverse("prd_api:reopen", args=[self.prd.id]),
            {},
        )
        reopened = self.post_json(
            reverse("prd_api:reopen", args=[self.prd.id]),
            {"reason": "튜터 리뷰 반영"},
        )

        self.assertEqual(missing_reason.status_code, 400)
        self.assertEqual(reopened.status_code, 200)
        self.prd.refresh_from_db()
        self.assertEqual(self.prd.status, PrdStatus.IN_PROGRESS)
        self.assertIsNone(self.prd.completed_at)
        audit = PrdStatusAuditLog.objects.get(action=PrdStatusAuditAction.REOPENED)
        self.assertEqual(audit.actor_user_id, 7)
        self.assertEqual(audit.reason, "튜터 리뷰 반영")
        self.assertEqual(audit.previous_completed_at, completed_at)
        self.assertEqual(
            list(self.prd.change_history.values_list("event_type", flat=True)),
            ["prd_reopened", "prd_completed"],
        )

    def test_only_owner_completes_and_only_owner_or_admin_reopens(self):
        self.login_as(8, role=PrdParticipantRole.EDITOR)
        denied_complete = self.post_json(
            reverse("prd_api:complete", args=[self.prd.id]),
            {},
        )
        self.assertEqual(denied_complete.status_code, 403)

        self.prd.status = PrdStatus.COMPLETED
        self.prd.completed_at = timezone.now()
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])
        denied_reopen = self.post_json(
            reverse("prd_api:reopen", args=[self.prd.id]),
            {"reason": "권한 없음"},
        )
        self.assertEqual(denied_reopen.status_code, 403)

        self.login_as(11, is_staff=True)
        admin_reopen = self.post_json(
            reverse("prd_api:reopen", args=[self.prd.id]),
            {"reason": "관리자 검토 후 재개"},
        )
        self.assertEqual(admin_reopen.status_code, 200)
        self.assertEqual(
            PrdStatusAuditLog.objects.get(action=PrdStatusAuditAction.REOPENED).actor_user_id,
            11,
        )

    def test_incomplete_prd_requires_explicit_completion_confirmation(self):
        self.question.is_completed = False
        self.question.save(update_fields=["is_completed", "updated_at"])
        url = reverse("prd_api:complete", args=[self.prd.id])

        warning = self.post_json(url, {})
        confirmed = self.post_json(url, {"confirm_incomplete": True})

        self.assertEqual(warning.status_code, 400)
        self.assertIn("confirm_incomplete", warning.json()["error"]["details"])
        self.assertEqual(confirmed.status_code, 200)

    def test_completed_comments_are_locked_except_tutor_post_completion_review(self):
        self.prd.status = PrdStatus.COMPLETED
        self.prd.completed_at = timezone.now()
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])
        url = reverse("prd_api:comments", args=[self.prd.id])

        owner_comment = self.post_json(url, {"content": "일반 의견"})
        self.login_as(9, role=PrdParticipantRole.TUTOR)
        tutor_general = self.post_json(url, {"content": "일반 리뷰"})
        tutor_review = self.post_json(
            url,
            {
                "content": "완료 후 검토 의견",
                "comment_type": PrdCommentType.POST_COMPLETION_REVIEW,
            },
        )

        self.assertEqual(owner_comment.status_code, 403)
        self.assertEqual(tutor_general.status_code, 403)
        self.assertEqual(tutor_review.status_code, 201)
        comment = PrdComment.objects.get()
        self.assertEqual(comment.comment_type, PrdCommentType.POST_COMPLETION_REVIEW)
        self.assertFalse(comment.is_contribution_eligible)

        updated = self.patch_json(
            reverse("prd_api:comment-item", args=[self.prd.id, comment.id]),
            {"content": "리뷰 보완"},
        )
        self.assertEqual(updated.status_code, 200)

    def test_completed_general_comment_cannot_be_modified(self):
        comment = PrdComment.objects.create(
            prd=self.prd,
            author_user_id=7,
            author_role_at_created=PrdParticipantRole.OWNER,
            comment_type=PrdCommentType.GENERAL,
            content="완료 전 코멘트",
            is_contribution_eligible=True,
        )
        self.prd.status = PrdStatus.COMPLETED
        self.prd.completed_at = timezone.now()
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])
        url = reverse("prd_api:comment-item", args=[self.prd.id, comment.id])

        self.assertEqual(self.patch_json(url, {"content": "수정"}).status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 403)

    def test_team_shared_viewer_has_read_only_permissions(self):
        self.login_as(11)

        response = self.client.get(reverse("prd_api:detail", args=[self.team_shared.id]))

        self.assertEqual(response.status_code, 200)
        permissions = response.json()["data"]["permissions"]
        self.assertIsNone(permissions["role"])
        self.assertTrue(permissions["can_view"])
        self.assertFalse(permissions["can_edit"])
        self.assertFalse(permissions["can_comment"])

    def test_missing_deleted_other_round_and_unauthorized_are_not_exposed(self):
        self.assertEqual(
            self.client.get(reverse("prd_api:detail", args=[999999])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("prd_api:detail", args=[self.deleted_prd.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("prd_api:detail", args=[self.other_round.id])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("prd_api:detail", args=[self.private_other_team.id])
            ).status_code,
            403,
        )

    def test_roundless_prd_access_and_participant_management_use_explicit_roles(self):
        personal = self.make_prd(creator=7, team_id=None, round_id=None)
        owner = PrdParticipant.objects.create(
            prd=personal,
            user_id=7,
            participant_id=None,
            role=PrdParticipantRole.OWNER,
        )

        detail_response = self.client.get(reverse("prd_api:detail", args=[personal.id]))
        add_response = self.post_json(
            reverse("prd_api:participants", args=[personal.id]),
            {"user_id": 8, "role": PrdParticipantRole.EDITOR},
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(add_response.status_code, 201)
        editor = personal.participants.get(user_id=8)
        self.assertIsNone(editor.participant_id)

        role_response = self.patch_json(
            reverse("prd_api:participant-item", args=[personal.id, 8]),
            {"role": PrdParticipantRole.VIEWER},
        )
        self.assertEqual(role_response.status_code, 200)
        editor.refresh_from_db()
        self.assertEqual(editor.role, PrdParticipantRole.VIEWER)

        owner_delete = self.client.delete(
            reverse("prd_api:participant-item", args=[personal.id, owner.user_id])
        )
        editor_delete = self.client.delete(
            reverse("prd_api:participant-item", args=[personal.id, editor.user_id])
        )
        self.assertEqual(owner_delete.status_code, 400)
        self.assertEqual(editor_delete.status_code, 200)
        self.assertTrue(personal.participants.filter(user_id=7).exists())

        self.login_as(8)
        self.assertEqual(
            self.client.get(reverse("prd_api:detail", args=[personal.id])).status_code,
            403,
        )

    def test_owner_and_editor_general_comments_are_contribution_eligible(self):
        url = reverse("prd_api:comments", args=[self.prd.id])
        owner_response = self.post_json(
            url,
            {
                "content": "전체 코멘트",
                "section_question_id": None,
                "comment_type": "general",
            },
        )
        self.login_as(8, role=PrdParticipantRole.EDITOR)
        editor_response = self.post_json(
            url,
            {
                "content": "질문 코멘트",
                "section_question_id": self.question.id,
            },
        )

        self.assertEqual(owner_response.status_code, 201)
        self.assertEqual(editor_response.status_code, 201)
        comments = list(PrdComment.objects.order_by("author_user_id"))
        self.assertTrue(all(comment.is_contribution_eligible for comment in comments))
        self.assertEqual(comments[0].author_role_at_created, "owner")
        self.assertEqual(comments[1].author_role_at_created, "editor")
        self.assertIsNone(comments[0].section_question_id)
        self.assertEqual(comments[1].section_question_id, self.question.id)

    def test_tutor_guidance_and_review_are_not_contribution_eligible(self):
        self.login_as(9, role=PrdParticipantRole.TUTOR)
        url = reverse("prd_api:comments", args=[self.prd.id])

        guidance = self.post_json(url, {"content": "지도", "comment_type": "guidance"})
        review = self.post_json(url, {"content": "리뷰", "comment_type": "review"})
        general = self.post_json(url, {"content": "일반", "comment_type": "general"})
        post_completion = self.post_json(
            url,
            {"content": "시기 오류", "comment_type": "post_completion_review"},
        )

        self.assertEqual(guidance.status_code, 201)
        self.assertEqual(review.status_code, 201)
        self.assertEqual(general.status_code, 403)
        self.assertEqual(post_completion.status_code, 403)
        self.assertTrue(
            all(not comment.is_contribution_eligible for comment in PrdComment.objects.all())
        )
        self.assertTrue(
            all(comment.author_role_at_created == "tutor" for comment in PrdComment.objects.all())
        )

    def test_viewer_and_team_viewer_cannot_create_comments(self):
        url = reverse("prd_api:comments", args=[self.prd.id])
        self.login_as(10, role=PrdParticipantRole.VIEWER)
        self.assertEqual(self.post_json(url, {"content": "불가"}).status_code, 403)

        self.login_as(11)
        shared_url = reverse("prd_api:comments", args=[self.team_shared.id])
        self.assertEqual(
            self.post_json(shared_url, {"content": "불가"}).status_code,
            403,
        )

    def test_question_must_be_active_and_belong_to_same_prd(self):
        other_section = PrdSection.objects.create(
            prd=self.team_shared,
            title="다른 PRD",
            position=1,
        )
        other_question = PrdQuestion.objects.create(
            section=other_section,
            prompt="다른 질문",
            position=1,
        )
        response = self.post_json(
            reverse("prd_api:comments", args=[self.prd.id]),
            {"content": "잘못된 연결", "section_question_id": other_question.id},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PrdComment.objects.exists())

    def test_comment_update_and_soft_delete_are_author_only(self):
        comment = PrdComment.objects.create(
            prd=self.prd,
            author_user_id=7,
            author_role_at_created=PrdParticipantRole.OWNER,
            comment_type=PrdCommentType.GENERAL,
            content="원문",
            is_contribution_eligible=True,
        )
        url = reverse("prd_api:comment-item", args=[self.prd.id, comment.id])
        self.login_as(8, role=PrdParticipantRole.EDITOR)
        self.assertEqual(self.patch_json(url, {"content": "탈취"}).status_code, 403)

        self.login_as(7, role=PrdParticipantRole.OWNER)
        updated = self.patch_json(url, {"content": "수정"})
        deleted = self.client.delete(url)

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(deleted.status_code, 200)
        comment.refresh_from_db()
        self.assertEqual(comment.content, "수정")
        self.assertTrue(comment.is_deleted)
        self.assertIsNotNone(comment.deleted_at)
        listing = self.client.get(reverse("prd_api:comments", args=[self.prd.id]))
        self.assertEqual(listing.json()["data"]["items"], [])

    def test_comment_list_is_paginated_and_returns_author_snapshot(self):
        for index in range(3):
            PrdComment.objects.create(
                prd=self.prd,
                author_user_id=7,
                author_role_at_created=PrdParticipantRole.OWNER,
                comment_type=PrdCommentType.GENERAL,
                content=f"코멘트 {index}",
                is_contribution_eligible=True,
            )

        response = self.client.get(
            reverse("prd_api:comments", args=[self.prd.id]),
            {"page": 2, "page_size": 2},
        )

        data = response.json()["data"]
        self.assertEqual(data["pagination"]["total_items"], 3)
        self.assertEqual(data["pagination"]["total_pages"], 2)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["author"]["display_name"], "표시명 7")
        self.assertEqual(data["items"][0]["author"]["role_at_created"], "owner")

    def test_ai_usage_chat_and_change_history_are_separate_paginated_apis(self):
        for index in range(3):
            AiUsageLog.objects.create(
                prd=self.prd,
                user_id=7,
                feature_type=AiFeatureType.COACHING,
                action_type=AiActionType.CHAT,
                status=AiUsageStatus.SUCCESS,
                total_tokens=index,
            )
            AiChatHistory.objects.create(
                prd=self.prd,
                user_id=7,
                prompt=f"질문 {index}",
                response=f"응답 {index}",
            )
            PrdChangeHistory.objects.create(
                prd=self.prd,
                actor_user_id=7,
                event_type=f"event_{index}",
                before_data={"index": index - 1},
                after_data={"index": index},
            )

        for route_name in ("ai-usage", "ai-chats", "change-history"):
            with self.subTest(route=route_name):
                response = self.client.get(
                    reverse(f"prd_api:{route_name}", args=[self.prd.id]),
                    {"page": 1, "page_size": 2},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["pagination"]["total_items"], 3)
                self.assertEqual(len(response.json()["data"]["items"]), 2)

    def test_every_detail_endpoint_rechecks_prd_access(self):
        endpoints = (
            reverse("prd_api:detail", args=[self.private_other_team.id]),
            reverse("prd_api:comments", args=[self.private_other_team.id]),
            reverse("prd_api:ai-usage", args=[self.private_other_team.id]),
            reverse("prd_api:ai-chats", args=[self.private_other_team.id]),
            reverse("prd_api:change-history", args=[self.private_other_team.id]),
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 403)
