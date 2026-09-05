from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai.models import (
    AiActionType,
    AiFeatureType,
    AiJob,
    AiJobStatus,
    AiPrdApplyRecord,
    AiPrdApplyScope,
    AiPrompt,
    ContributionEvaluation,
    ContributionEvaluationStatus,
)
from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.jobs.cleanup import BackgroundDataCleanupService
from apps.prds.models import (
    Prd,
    PrdDeletionAction,
    PrdDeletionAuditLog,
    PrdParticipant,
    PrdParticipantRole,
    PrdSection,
    PrdStatus,
    PrdStatusAuditAction,
    PrdStatusAuditLog,
    PrdType,
)


class BrainstormExportCleanupBase(TestCase):
    def setUp(self):
        self.prd = Prd.objects.create(
            title="위험한 / PRD .. 이름 🔥",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="export-cleanup-prd",
        )
        PrdParticipant.objects.create(
            prd=self.prd,
            user_id=7,
            participant_id=70,
            role=PrdParticipantRole.OWNER,
        )
        self.section = PrdSection.objects.create(prd=self.prd, title="문제 #1", position=1)
        self.canvas = BrainstormCanvas.objects.create(prd=self.prd)

    def note(self, content, *, status=BrainstormNodeStatus.DEFAULT, section=None, deleted=False):
        if section is not None and status == BrainstormNodeStatus.DEFAULT:
            status = BrainstormNodeStatus.ACCEPTED
        return BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.NOTE,
            content=content,
            color="yellow",
            position_x=Decimal("10"),
            position_y=Decimal("20"),
            section=section,
            author_id=7,
            assignee_id=7,
            status=status,
            is_deleted=deleted,
            deleted_at=timezone.now() if deleted else None,
        )


@override_settings(
    BRAINSTORM_DELETE_RETENTION_DAYS=30,
    AI_PREVIEW_RETENTION_DAYS=7,
    BACKGROUND_CLEANUP_BATCH_SIZE=100,
)
class BackgroundCleanupTests(BrainstormExportCleanupBase):
    @override_settings(PRD_TRASH_RETENTION_DAYS=30)
    def test_cleanup_physically_deletes_prd_only_after_retention(self):
        fresh = Prd.objects.create(
            title="아직 복구 가능한 PRD",
            prd_type=PrdType.NEW_PRODUCT,
            creator_user_id=7,
            creation_idempotency_key="fresh-trash-prd",
            is_deleted=True,
            deleted_at=self.now - timedelta(days=29),
        )
        expired = Prd.objects.create(
            title="보관 기간이 끝난 PRD",
            prd_type=PrdType.NEW_PRODUCT,
            creator_user_id=7,
            creation_idempotency_key="expired-trash-prd",
            is_deleted=True,
            deleted_at=self.now - timedelta(days=30, seconds=1),
        )

        result = BackgroundDataCleanupService().run(now=self.now)

        self.assertEqual(result.prds, 1)
        self.assertTrue(Prd.objects.filter(pk=fresh.pk).exists())
        self.assertFalse(Prd.objects.filter(pk=expired.pk).exists())
        self.assertTrue(
            PrdDeletionAuditLog.objects.filter(
                prd_id=expired.pk,
                action=PrdDeletionAction.PURGED,
            ).exists()
        )

    @override_settings(PRD_TRASH_RETENTION_DAYS=30)
    def test_cleanup_purges_protected_ai_and_contribution_details_before_prd(self):
        expired = Prd.objects.create(
            title="AI 기록이 있는 만료 PRD",
            prd_type=PrdType.NEW_PRODUCT,
            creator_user_id=7,
            creation_idempotency_key="expired-protected-prd",
            is_deleted=True,
            deleted_at=self.now - timedelta(days=31),
        )
        section = PrdSection.objects.create(prd=expired, title="문제", position=1)
        canvas = BrainstormCanvas.objects.create(prd=expired)
        completion_audit = PrdStatusAuditLog.objects.create(
            prd=expired,
            actor_user_id=7,
            action=PrdStatusAuditAction.COMPLETED,
            previous_status=PrdStatus.IN_PROGRESS,
            new_status=PrdStatus.COMPLETED,
        )
        contribution = ContributionEvaluation.objects.create(
            prd=expired,
            completion_audit=completion_audit,
            calculation_version=1,
            prd_version=1,
            status=ContributionEvaluationStatus.SUCCEEDED,
            input_fingerprint="protected-cleanup-input",
        )
        prompt = self.prompt(AiFeatureType.BRAINSTORM_PRD_APPLY)
        preview_job = AiJob.objects.create(
            prd=expired,
            prompt=prompt,
            user_id=7,
            feature_type=AiFeatureType.BRAINSTORM_PRD_APPLY,
            action_type=AiActionType.PRD_APPLY,
            status=AiJobStatus.SUCCEEDED,
            idempotency_key="protected-cleanup-preview",
        )
        apply_record = AiPrdApplyRecord.objects.create(
            prd=expired,
            canvas=canvas,
            preview_job=preview_job,
            section=section,
            scope=AiPrdApplyScope.SECTION,
            actor_user_id=7,
            idempotency_key="protected-cleanup-apply",
            model="gemini-test",
            prompt_version=1,
        )

        result = BackgroundDataCleanupService().run(now=self.now)

        self.assertEqual(result.prds, 1)
        self.assertFalse(Prd.objects.filter(pk=expired.pk).exists())
        self.assertFalse(ContributionEvaluation.objects.filter(pk=contribution.pk).exists())
        self.assertFalse(AiPrdApplyRecord.objects.filter(pk=apply_record.pk).exists())
        self.assertTrue(
            PrdDeletionAuditLog.objects.filter(
                prd_id=expired.pk,
                action=PrdDeletionAction.PURGED,
            ).exists()
        )

    def setUp(self):
        super().setUp()
        self.now = timezone.now()

    def prompt(self, feature_type):
        # 마이그레이션이 미리 심어둔 프롬프트가 있으면 치운다(활성 프롬프트는 기능당 하나뿐).
        AiPrompt.objects.filter(feature_type=feature_type).delete()
        return AiPrompt.objects.create(
            feature_type=feature_type,
            version=1,
            system_instructions="system",
            output_schema={},
            model="gemini-test",
            is_active=True,
        )

    def job(self, *, prompt, action, status=AiJobStatus.SUCCEEDED, old=True, output=None):
        job = AiJob.objects.create(
            prd=self.prd,
            prompt=prompt,
            user_id=7,
            feature_type=prompt.feature_type,
            action_type=action,
            status=status,
            idempotency_key=f"job-{AiJob.objects.count()}",
            input_data={},
            output_data=output or {"preview": "temporary"},
            finished_at=self.now,
        )
        AiJob.objects.filter(pk=job.pk).update(
            finished_at=self.now - timedelta(days=8 if old else 1)
        )
        job.refresh_from_db()
        return job

    def test_purges_only_soft_deletes_older_than_thirty_days(self):
        old = self.note("영구 삭제 대상", deleted=True)
        fresh = self.note("복원 가능", deleted=True)
        active = self.note("활성")
        connected = self.note("연결된 삭제 노드", deleted=True)
        old_connection = BrainstormConnection.objects.create(
            canvas=self.canvas,
            node_a=old,
            node_b=connected,
            is_deleted=True,
            deleted_at=self.now,
        )
        BrainstormNode.objects.filter(pk__in=[old.pk, connected.pk]).update(
            deleted_at=self.now - timedelta(days=31)
        )
        BrainstormConnection.objects.filter(pk=old_connection.pk).update(
            deleted_at=self.now - timedelta(days=31)
        )

        result = BackgroundDataCleanupService().run(now=self.now)

        self.assertEqual(result.nodes, 2)
        self.assertEqual(result.connections, 1)
        self.assertFalse(BrainstormNode.objects.filter(pk=old.pk).exists())
        self.assertFalse(BrainstormConnection.objects.filter(pk=old_connection.pk).exists())
        self.assertTrue(BrainstormNode.objects.filter(pk=fresh.pk).exists())
        self.assertTrue(BrainstormNode.objects.filter(pk=active.pk).exists())

    def test_dry_run_reports_without_deleting_and_command_is_repeatable(self):
        old = self.note("삭제 예정", deleted=True)
        BrainstormNode.objects.filter(pk=old.pk).update(deleted_at=self.now - timedelta(days=31))
        stdout = StringIO()

        call_command("cleanup_background_data", "--dry-run", stdout=stdout)

        self.assertTrue(BrainstormNode.objects.filter(pk=old.pk).exists())
        self.assertIn("Would clean: nodes=1", stdout.getvalue())
        BackgroundDataCleanupService().run(now=self.now)
        second = BackgroundDataCleanupService().run(now=self.now)
        self.assertEqual((second.nodes, second.connections), (0, 0))

    def test_clears_only_expired_temporary_preview_payloads(self):
        analysis_prompt = self.prompt(AiFeatureType.BRAINSTORM_ANALYSIS)
        coaching_prompt = self.prompt(AiFeatureType.COACHING)
        old_preview = self.job(prompt=analysis_prompt, action=AiActionType.ANALYSIS)
        fresh_preview = self.job(
            prompt=analysis_prompt,
            action=AiActionType.ANALYSIS,
            old=False,
        )
        old_chat = self.job(prompt=coaching_prompt, action=AiActionType.CHAT)

        result = BackgroundDataCleanupService().run(now=self.now)

        old_preview.refresh_from_db()
        fresh_preview.refresh_from_db()
        old_chat.refresh_from_db()
        self.assertEqual(result.ai_previews, 1)
        self.assertIsNone(old_preview.output_data)
        self.assertIsNotNone(fresh_preview.output_data)
        # 채팅 결과는 미리보기보다 오래 남는다. 8일은 아직 보관 기간 안이다.
        self.assertIsNotNone(old_chat.output_data)

    def test_chat_payloads_are_cleared_after_the_conversation_retention_window(self):
        coaching_prompt = self.prompt(AiFeatureType.COACHING)
        chat = self.job(prompt=coaching_prompt, action=AiActionType.CHAT)
        AiJob.objects.filter(pk=chat.pk).update(finished_at=self.now - timedelta(days=31))

        result = BackgroundDataCleanupService().run(now=self.now)

        chat.refresh_from_db()
        self.assertEqual(result.ai_previews, 1)
        self.assertIsNone(chat.output_data)

    def test_cleanup_does_not_reset_terminal_failures(self):
        prompt = self.prompt(AiFeatureType.BRAINSTORM_ANALYSIS)
        failed = self.job(
            prompt=prompt,
            action=AiActionType.ANALYSIS,
            status=AiJobStatus.FAILED,
        )
        failed.attempt_count = failed.max_attempts
        failed.error_code = "provider_rejected"
        failed.save(update_fields=["attempt_count", "error_code", "updated_at"])

        BackgroundDataCleanupService().run(now=self.now)

        failed.refresh_from_db()
        self.assertEqual(failed.status, AiJobStatus.FAILED)
        self.assertEqual(failed.attempt_count, failed.max_attempts)
