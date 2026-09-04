from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LocalUserMapping
from apps.ai.models import AiActionType, AiFeatureType, AiJob, AiJobStatus, AiPrompt
from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.context import IntegrationContext
from apps.jobs.cleanup import BackgroundDataCleanupService
from apps.prds.models import (
    Prd,
    PrdDeletionAction,
    PrdDeletionAuditLog,
    PrdParticipant,
    PrdParticipantRole,
    PrdSection,
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


class BrainstormMarkdownExportTests(BrainstormExportCleanupBase):
    def setUp(self):
        super().setUp()
        context = IntegrationContext(
            user_id=7,
            round_id=3,
            participant_id=70,
            team_id=30,
            parent_role="student",
            is_staff=False,
            is_superuser=False,
        )
        resolver = Mock()
        resolver.resolve.return_value = context
        self.resolver_patch = patch(
            "apps.prds.views.get_context_resolver",
            return_value=resolver,
        )
        self.resolver_patch.start()
        self.addCleanup(self.resolver_patch.stop)
        self.client.force_login(LocalUserMapping.objects.create_user(7, "owner@example.test"))
        session = self.client.session
        session["selected_round_id"] = 3
        session.save()

    def url(self):
        return reverse("brainstorm_api:export-markdown", kwargs={"prd_id": self.prd.pk})

    def test_exports_utf8_section_markdown_and_connected_ideas(self):
        accepted = self.note(
            "고객 인터뷰를 진행한다.",
            status=BrainstormNodeStatus.ACCEPTED,
            section=self.section,
        )
        default = self.note("가설을 먼저 세운다.")
        held = self.note("보류 내용", status=BrainstormNodeStatus.HELD)
        deleted = self.note("삭제 내용", deleted=True)
        title = BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.TITLE,
            content="제목 카드",
            color="blue",
            position_x=0,
            position_y=0,
        )
        BrainstormConnection.objects.create(
            canvas=self.canvas,
            node_a=accepted,
            node_b=default,
        )

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/markdown; charset=utf-8")
        self.assertIn("filename*=UTF-8''brainstorm-", response["Content-Disposition"])
        content = response.content.decode("utf-8")
        self.assertIn("## 문제 \\#1", content)
        self.assertIn("## 미분류", content)
        self.assertIn("고객 인터뷰를 진행한다.", content)
        self.assertIn("가설을 먼저 세운다.", content)
        self.assertIn("연결된 아이디어:\n- IDEA-002", content)
        for excluded in (held.content, deleted.content, title.content):
            self.assertNotIn(excluded, content)

    def test_accepted_flat_export_can_exclude_unclassified(self):
        self.note(
            "채택·분류됨",
            status=BrainstormNodeStatus.ACCEPTED,
            section=self.section,
        )
        self.note("섹션 배치로 자동 채택", section=self.section)
        self.note("미분류 기본 메모")

        response = self.client.get(
            self.url(),
            {
                "scope": "accepted",
                "organization": "flat",
                "include_unclassified": "false",
            },
        )

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("## 아이디어 목록", content)
        self.assertIn("채택·분류됨", content)
        self.assertIn("섹션 배치로 자동 채택", content)
        self.assertNotIn("미분류 기본 메모", content)
        self.assertNotIn("채택·미분류", content)
        filename = response["Content-Disposition"].split('filename="', 1)[1].split('"', 1)[0]
        self.assertNotRegex(filename, r"[/\\:*?<>|]")

    def test_rejects_unknown_export_option(self):
        response = self.client.get(self.url(), {"scope": "held"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")


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
        BrainstormNode.objects.filter(pk=old.pk).update(
            deleted_at=self.now - timedelta(days=31)
        )
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
