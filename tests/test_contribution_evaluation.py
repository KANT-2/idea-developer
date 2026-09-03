from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai.contribution import ContributionEvaluationService
from apps.ai.exceptions import AiProviderError
from apps.ai.models import (
    AiFeatureType,
    ContributionCommentScore,
    ContributionEvaluation,
    ContributionEvaluationStatus,
    ContributionUserScore,
)
from apps.ai.providers import AiProviderResult
from apps.ai.services import AiPromptService
from apps.ai.worker import AiJobRunner
from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.detail import PrdAccess
from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdComment,
    PrdCommentType,
    PrdContributionStatus,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
    PrdStatusAuditAction,
    PrdStatusAuditLog,
    PrdType,
)
from apps.prds.status_services import PrdStatusService


class ContributionProvider:
    def generate(self, request, *, timeout_seconds, cancellation_check):
        comments = request.user_data["untrusted_user_data"]["comments"]
        scores = {7: 80, 8: 20}
        return AiProviderResult(
            output={
                "comments": [
                    {
                        "comment_id": row["comment_id"],
                        "reflection_score": scores[row["author_user_id"]],
                        "matched_question_ids": [1],
                        "evidence": ["최종 답변에 핵심 제안이 반영됨"],
                        "reason": "의미적으로 반영됨",
                        "confidence": 0.9,
                    }
                    for row in comments
                ]
            },
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0"),
            model="contribution-test-model-v2",
        )


class FailingContributionProvider:
    def generate(self, request, *, timeout_seconds, cancellation_check):
        raise AiProviderError("failed", code="evaluation_failed", retryable=False)


class InvalidContributionProvider:
    def generate(self, request, *, timeout_seconds, cancellation_check):
        return AiProviderResult(
            output={
                "comments": [
                    {
                        "comment_id": 999999,
                        "reflection_score": 100,
                        "matched_question_ids": [1],
                        "evidence": ["잘못된 근거"],
                        "reason": "잘못된 참조",
                        "confidence": 1,
                    }
                ]
            },
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal("0"),
            model="invalid-provider",
        )


def user_row(user_id, *, active=True):
    return {
        "user_id": user_id,
        "user_email": f"user{user_id}@example.test",
        "primary_email": f"user{user_id}@example.test",
        "first_name": "사용자",
        "last_name": str(user_id),
        "role": "student",
        "approval_status": "approved",
        "is_active": active,
        "is_staff": False,
        "is_superuser": False,
    }


def membership_row(user_id, *, round_id=3, team_id=30):
    return {
        "user_id": user_id,
        "round_id": round_id,
        "round_title": f"회차 {round_id}",
        "round_status": "running",
        "participant_id": user_id * 10,
        "team_id": team_id,
        "team_name": f"팀 {team_id}",
        "display_name_snapshot": f"사용자 {user_id}",
    }


@override_settings(
    INTEGRATION_APPROVED_USER_STATUS="approved",
    AI_JOB_MAX_ATTEMPTS=1,
)
class ContributionEvaluationTests(TestCase):
    def setUp(self):
        self.repository = FixtureIntegrationRepository(
            users=[
                user_row(7),
                user_row(8),
                user_row(9),
                user_row(10, active=False),
            ],
            memberships=[
                membership_row(7),
                membership_row(8),
                membership_row(9),
                membership_row(10),
            ],
            active_statuses={"running"},
        )
        self.prd = Prd.objects.create(
            title="기여도 PRD",
            description="최종 설명",
            prd_type=PrdType.NEW_PRODUCT,
            status=PrdStatus.COMPLETED,
            completed_at=timezone.now(),
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="contribution-prd",
        )
        for user_id, role in (
            (7, PrdParticipantRole.OWNER),
            (8, PrdParticipantRole.EDITOR),
            (9, PrdParticipantRole.TUTOR),
            (10, PrdParticipantRole.EDITOR),
        ):
            PrdParticipant.objects.create(
                prd=self.prd,
                user_id=user_id,
                participant_id=user_id * 10,
                role=role,
            )
        self.section = PrdSection.objects.create(prd=self.prd, title="문제", position=1)
        self.question = PrdQuestion.objects.create(
            id=1,
            section=self.section,
            prompt="문제는 무엇인가요?",
            position=1,
            is_completed=True,
        )
        PrdAnswer.objects.create(
            question=self.question,
            content="최종 답변",
            updated_by_user_id=7,
        )
        self.canvas = BrainstormCanvas.objects.create(prd=self.prd)
        self.owner_node = self.note(author=7, assignee=7, content="소유자 메모")
        self.editor_node = self.note(author=8, assignee=8, content="편집자 메모")
        self.removed_assignee_node = self.note(
            author=7,
            assignee=99,
            content="제거된 담당자 메모",
        )
        self.note(author=7, assignee=7, content="기본", status=BrainstormNodeStatus.DEFAULT)
        self.note(author=7, assignee=7, content="보류", status=BrainstormNodeStatus.HELD)
        deleted = self.note(author=7, assignee=7, content="삭제")
        deleted.soft_delete()
        BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.TITLE,
            content="제목",
            color="gray",
            position_x=0,
            position_y=0,
            author_id=None,
            assignee_id=None,
            status=None,
        )
        self.owner_comment = self.comment(7, PrdParticipantRole.OWNER, eligible=True)
        self.editor_comment = self.comment(8, PrdParticipantRole.EDITOR, eligible=True)
        self.comment(
            9,
            PrdParticipantRole.TUTOR,
            eligible=False,
            comment_type=PrdCommentType.GUIDANCE,
        )
        self.comment(10, PrdParticipantRole.EDITOR, eligible=True)
        self.audit = PrdStatusAuditLog.objects.create(
            prd=self.prd,
            actor_user_id=7,
            action=PrdStatusAuditAction.COMPLETED,
            previous_status=PrdStatus.IN_PROGRESS,
            new_status=PrdStatus.COMPLETED,
        )
        AiPromptService().create_version(
            feature_type=AiFeatureType.CONTRIBUTION_EVALUATION,
            system_instructions="Evaluate semantic reflection, not word overlap.",
            output_schema={
                "type": "object",
                "required": ["comments"],
                "properties": {"comments": {"type": "array", "items": {"type": "object"}}},
                "additionalProperties": False,
            },
            model="contribution-test-model",
            activate=True,
        )

    def note(self, *, author, assignee, content, status=BrainstormNodeStatus.ACCEPTED):
        return BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.NOTE,
            content=content,
            color="yellow",
            position_x=0,
            position_y=0,
            author_id=author,
            assignee_id=assignee,
            status=status,
        )

    def comment(self, user_id, role, *, eligible, comment_type=PrdCommentType.GENERAL):
        return PrdComment.objects.create(
            prd=self.prd,
            section_question=self.question,
            author_user_id=user_id,
            author_role_at_created=role,
            comment_type=comment_type,
            content=f"사용자 {user_id} 의견",
            is_contribution_eligible=eligible,
        )

    def schedule(self):
        return ContributionEvaluationService().schedule_for_completion(
            prd_id=self.prd.pk,
            completion_audit_id=self.audit.pk,
            actor_user_id=7,
            repository=self.repository,
        )

    def test_valid_round_participants_and_confirmed_inputs_are_scored(self):
        evaluation = self.schedule()
        self.assertEqual(evaluation.status, ContributionEvaluationStatus.PENDING)
        self.assertEqual(
            {row["user_id"] for row in evaluation.input_snapshot["participants"]},
            {7, 8, 9},
        )
        self.assertEqual(
            set(evaluation.target_comment_ids),
            {self.owner_comment.pk, self.editor_comment.pk},
        )
        self.removed_assignee_node.refresh_from_db()
        self.assertEqual(self.removed_assignee_node.assignee_id, 7)
        self.assertEqual(self.removed_assignee_node.version, 2)

        self.assertTrue(AiJobRunner(provider=ContributionProvider()).run_once())
        evaluation.refresh_from_db()
        self.prd.refresh_from_db()
        self.assertEqual(evaluation.status, ContributionEvaluationStatus.SUCCEEDED)
        self.assertEqual(evaluation.model, "contribution-test-model-v2")
        self.assertEqual(evaluation.prompt_version, 1)
        self.assertEqual(self.prd.contribution_status, PrdContributionStatus.SUCCEEDED)
        scores = {row.user_id: row for row in ContributionUserScore.objects.all()}
        self.assertEqual(scores[7].memo_raw, 2)
        self.assertEqual(scores[8].memo_raw, 1)
        self.assertEqual(scores[9].memo_raw, 0)
        self.assertEqual(scores[7].comment_contribution, Decimal("80.0000"))
        self.assertEqual(scores[8].comment_contribution, Decimal("20.0000"))
        self.assertEqual(
            sum(row.comment_contribution for row in scores.values()), Decimal("100.0000")
        )
        self.assertEqual(ContributionCommentScore.objects.count(), 2)

    @override_settings(AI_CONTRIBUTION_MAX_COMMENTS=1)
    def test_oversized_contribution_input_fails_without_reverting_completion(self):
        evaluation = self.schedule()

        self.prd.refresh_from_db()
        self.assertEqual(evaluation.status, ContributionEvaluationStatus.FAILED)
        self.assertEqual(evaluation.failure_code, "ValidationError")
        self.assertEqual(self.prd.status, PrdStatus.COMPLETED)
        self.assertEqual(self.prd.contribution_status, PrdContributionStatus.FAILED)
        self.assertIsNone(evaluation.job_id)

    def test_removed_assignee_returns_to_historical_author_even_if_author_was_removed(self):
        historical = self.note(author=98, assignee=99, content="과거 작성자 메모")

        self.schedule()

        historical.refresh_from_db()
        self.assertEqual(historical.assignee_id, 98)
        self.assertEqual(historical.version, 2)

    def test_failure_keeps_prd_completed_and_admin_retries_same_snapshot(self):
        evaluation = self.schedule()
        fingerprint = evaluation.input_fingerprint
        original_input = evaluation.job.input_data
        self.assertTrue(AiJobRunner(provider=FailingContributionProvider()).run_once())
        evaluation.refresh_from_db()
        self.prd.refresh_from_db()
        self.assertEqual(evaluation.status, ContributionEvaluationStatus.FAILED)
        self.assertEqual(self.prd.status, PrdStatus.COMPLETED)
        self.assertEqual(self.prd.contribution_status, PrdContributionStatus.FAILED)

        access = PrdAccess(prd=self.prd, role=None, is_admin=True)
        retried = ContributionEvaluationService().retry_same_input(
            evaluation=evaluation,
            access=access,
        )
        self.assertEqual(retried.input_fingerprint, fingerprint)
        self.assertEqual(retried.job.input_data, original_input)
        self.assertTrue(AiJobRunner(provider=ContributionProvider()).run_once())
        retried.refresh_from_db()
        self.assertEqual(retried.status, ContributionEvaluationStatus.SUCCEEDED)

    def test_recompletion_creates_a_new_calculation_version(self):
        first = self.schedule()
        self.assertTrue(AiJobRunner(provider=ContributionProvider()).run_once())
        self.prd.status = PrdStatus.IN_PROGRESS
        self.prd.completed_at = None
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])
        self.prd.status = PrdStatus.COMPLETED
        self.prd.completed_at = timezone.now()
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])
        second_audit = PrdStatusAuditLog.objects.create(
            prd=self.prd,
            actor_user_id=7,
            action=PrdStatusAuditAction.COMPLETED,
            previous_status=PrdStatus.IN_PROGRESS,
            new_status=PrdStatus.COMPLETED,
        )
        second = ContributionEvaluationService().schedule_for_completion(
            prd_id=self.prd.pk,
            completion_audit_id=second_audit.pk,
            actor_user_id=7,
            repository=self.repository,
        )

        self.assertEqual((first.calculation_version, second.calculation_version), (1, 2))
        self.assertEqual(ContributionEvaluation.objects.count(), 2)
        self.assertTrue(
            ContributionEvaluation.objects.filter(
                pk=first.pk, status=ContributionEvaluationStatus.SUCCEEDED
            ).exists()
        )

    def test_non_admin_cannot_retry(self):
        evaluation = self.schedule()
        self.assertTrue(AiJobRunner(provider=FailingContributionProvider()).run_once())
        access = PrdAccess(prd=self.prd, role=PrdParticipantRole.OWNER, is_admin=False)

        with self.assertRaises(PermissionDenied):
            ContributionEvaluationService().retry_same_input(
                evaluation=evaluation,
                access=access,
            )

    def test_no_eligible_comments_skips_ai_and_still_persists_memo_scores(self):
        PrdComment.objects.filter(pk__in=[self.owner_comment.pk, self.editor_comment.pk]).update(
            is_contribution_eligible=False
        )

        evaluation = self.schedule()

        self.assertEqual(evaluation.status, ContributionEvaluationStatus.SUCCEEDED)
        self.assertIsNone(evaluation.job_id)
        self.assertEqual(ContributionUserScore.objects.count(), 3)
        self.assertFalse(AiJobRunner(provider=ContributionProvider()).run_once())

    def test_unknown_comment_or_question_id_fails_server_validation(self):
        evaluation = self.schedule()

        self.assertTrue(AiJobRunner(provider=InvalidContributionProvider()).run_once())
        evaluation.refresh_from_db()
        self.assertEqual(evaluation.status, ContributionEvaluationStatus.FAILED)
        self.assertFalse(ContributionCommentScore.objects.exists())

    def test_completion_commit_enqueues_evaluation_without_coupling_ai_success(self):
        self.prd.status = PrdStatus.IN_PROGRESS
        self.prd.completed_at = None
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])
        access = PrdAccess(
            prd=self.prd,
            role=PrdParticipantRole.OWNER,
            is_admin=False,
        )

        with (
            patch("apps.prds.views.get_integration_repository", return_value=self.repository),
            self.captureOnCommitCallbacks(execute=True),
        ):
            PrdStatusService().complete(access=access, actor_user_id=7)

        self.prd.refresh_from_db()
        evaluation = ContributionEvaluation.objects.get()
        self.assertEqual(self.prd.status, PrdStatus.COMPLETED)
        self.assertEqual(self.prd.contribution_status, PrdContributionStatus.PENDING)
        self.assertEqual(evaluation.status, ContributionEvaluationStatus.PENDING)
        self.assertIsNotNone(evaluation.job_id)
