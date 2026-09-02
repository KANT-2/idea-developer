from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LocalUserMapping
from apps.ai.models import (
    AiFeatureType,
    AiJob,
    AiPrdApplyItem,
    AiPrdApplyRecord,
)
from apps.ai.providers import AiProviderResult
from apps.ai.services import AiPromptService
from apps.ai.worker import AiJobRunner
from apps.brainstorm.models import (
    AuditLog,
    BrainstormCanvas,
    BrainstormChangeLog,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.context import IntegrationContext
from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdChangeHistory,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
    PrdType,
)


class PrdApplyProvider:
    requests = []

    def generate(self, request, *, timeout_seconds, cancellation_check):
        self.__class__.requests.append(request)
        data = request.user_data["untrusted_user_data"]
        node_ids = [row["id"] for row in data["nodes"]]
        answers = []
        for index, question in enumerate(data["questions"]):
            answers.append(
                {
                    "question_id": question["id"],
                    "draft": f"기존 내용과 메모를 통합한 답변 {question['id']}",
                    "source_node_ids": node_ids if index == 0 else [],
                    "preserved_existing_points": (
                        ["기존 핵심"] if question["current_answer"] else []
                    ),
                    "added_points": ["메모 핵심"],
                    "confidence": 0.9,
                }
            )
        return AiProviderResult(
            output={"answers": answers, "unused_node_ids": [], "warnings": []},
            input_tokens=30,
            output_tokens=20,
            cost_usd=Decimal("0"),
            model="gemini-free-test",
        )


def prd_apply_schema():
    string_array = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "required": ["answers", "unused_node_ids", "warnings"],
        "properties": {
            "answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "question_id",
                        "draft",
                        "source_node_ids",
                        "preserved_existing_points",
                        "added_points",
                        "confidence",
                    ],
                    "properties": {
                        "question_id": {"type": "integer"},
                        "draft": {"type": "string"},
                        "source_node_ids": string_array,
                        "preserved_existing_points": string_array,
                        "added_points": string_array,
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "additionalProperties": False,
                },
            },
            "unused_node_ids": string_array,
            "warnings": string_array,
        },
        "additionalProperties": False,
    }


@override_settings(
    AI_PROVIDER_CLASS="tests.test_prd_apply_ai.PrdApplyProvider",
    AI_JOB_MAX_ATTEMPTS=1,
)
class PrdApplyAiTests(TestCase):
    def setUp(self):
        PrdApplyProvider.requests = []
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
        self.resolver_patch = patch("apps.prds.views.get_context_resolver", return_value=resolver)
        self.resolver_patch.start()
        self.addCleanup(self.resolver_patch.stop)
        self.client.force_login(LocalUserMapping.objects.create_user(7, "owner@example.test"))
        session = self.client.session
        session["selected_round_id"] = 3
        session.save()
        self.prd = Prd.objects.create(
            title="통합 PRD",
            description="통합 설명",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="apply-prd",
        )
        PrdParticipant.objects.create(
            prd=self.prd,
            user_id=7,
            participant_id=70,
            role=PrdParticipantRole.OWNER,
        )
        self.section_a = PrdSection.objects.create(
            prd=self.prd, title="문제", guide="문제를 설명합니다.", position=1
        )
        self.section_b = PrdSection.objects.create(
            prd=self.prd, title="해결", guide="해결책을 설명합니다.", position=2
        )
        self.question_a1 = PrdQuestion.objects.create(
            section=self.section_a, prompt="어떤 문제인가요?", position=1
        )
        self.question_a2 = PrdQuestion.objects.create(
            section=self.section_a, prompt="누구의 문제인가요?", position=2
        )
        self.question_b = PrdQuestion.objects.create(
            section=self.section_b, prompt="어떻게 해결하나요?", position=1
        )
        PrdAnswer.objects.create(
            question=self.question_a1,
            content="기존 핵심 답변",
            updated_by_user_id=7,
        )
        self.canvas = BrainstormCanvas.objects.create(prd=self.prd)
        self.accepted_a = self.note(
            "채택 문제 메모", section=self.section_a, status=BrainstormNodeStatus.ACCEPTED
        )
        self.default_a = self.note("선택 가능한 기본 메모", section=self.section_a)
        self.accepted_b = self.note(
            "채택 해결 메모", section=self.section_b, status=BrainstormNodeStatus.ACCEPTED
        )
        self.unclassified = self.note("미분류 채택 메모", status=BrainstormNodeStatus.ACCEPTED)
        self.held = self.note("보류 메모", status=BrainstormNodeStatus.HELD)
        self.deleted = self.note(
            "삭제 메모",
            section=self.section_a,
            status=BrainstormNodeStatus.ACCEPTED,
            is_deleted=True,
        )
        BrainstormConnection.objects.create(
            canvas=self.canvas,
            node_a=self.accepted_a,
            node_b=self.default_a,
        )
        AiPromptService().create_version(
            feature_type=AiFeatureType.BRAINSTORM_PRD_APPLY,
            system_instructions="Integrate existing answers and selected notes naturally.",
            output_schema=prd_apply_schema(),
            model="gemini-free-test",
            activate=True,
        )

    def note(self, content, *, section=None, status=BrainstormNodeStatus.DEFAULT, is_deleted=False):
        return BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.NOTE,
            content=content,
            color="yellow",
            position_x=0,
            position_y=0,
            section=section,
            status=status,
            author_id=7,
            assignee_id=7,
            is_deleted=is_deleted,
            deleted_at=(self.prd.created_at if is_deleted else None),
        )

    def url(self, name, **kwargs):
        return reverse(f"brainstorm_api:{name}", kwargs={"prd_id": self.prd.pk, **kwargs})

    def post(self, name, payload, key):
        return self.client.post(
            self.url(name),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

    def preview(self, *, section_id=None, selected=True, key="preview-key"):
        payload = {}
        if section_id is not None:
            payload["section_id"] = section_id
        if selected:
            payload["selected_default_nodes"] = [
                {"node_id": str(self.default_a.pk), "version": self.default_a.version}
            ]
        response = self.post("ai-prd-apply-preview", payload, key)
        return response, AiJob.objects.get(pk=response.json()["data"]["id"])

    def run_job(self):
        self.assertTrue(AiJobRunner(worker_id="prd-apply-worker").run_once())

    def apply_payload(self, job, questions):
        return {
            "preview_request_id": str(job.pk),
            "node_versions": [
                {"node_id": row["id"], "version": row["version"]} for row in job.input_data["nodes"]
            ],
            "approved_questions": [
                {"question_id": question.pk, "version": question.version} for question in questions
            ],
        }

    def test_section_preview_uses_accepted_and_explicit_default_only(self):
        response, job = self.preview(section_id=self.section_a.pk)
        node_ids = {row["id"] for row in job.input_data["nodes"]}

        self.assertEqual(response.status_code, 202)
        self.assertEqual(node_ids, {str(self.accepted_a.pk), str(self.default_a.pk)})
        self.assertEqual(job.input_data["scope"], "section")
        self.assertEqual(job.input_data["merge_strategy"], "ai_integrate")
        self.assertEqual(len(job.input_data["connections"]), 1)
        self.assertEqual(
            job.input_data["excluded_unclassified_accepted_node_ids"],
            [str(self.unclassified.pk)],
        )
        first = job.input_data["questions"][0]
        self.assertEqual(first["current_answer"], "기존 핵심 답변")

    def test_full_preview_uses_classified_accepted_across_sections(self):
        response, job = self.preview(selected=False, key="full-preview")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(job.input_data["scope"], "all")
        self.assertEqual(
            {row["id"] for row in job.input_data["nodes"]},
            {str(self.accepted_a.pk), str(self.accepted_b.pk)},
        )
        self.assertEqual(
            {row["id"] for row in job.input_data["questions"]},
            {self.question_a1.pk, self.question_a2.pk, self.question_b.pk},
        )

    def test_preview_does_not_overwrite_and_only_approved_question_is_saved(self):
        _, job = self.preview(section_id=self.section_a.pk)
        self.run_job()
        job.refresh_from_db()
        self.assertEqual(PrdAnswer.objects.get(question=self.question_a1).content, "기존 핵심 답변")
        self.assertFalse(PrdAnswer.objects.filter(question=self.question_a2).exists())

        response = self.post(
            "ai-prd-apply-apply",
            self.apply_payload(job, [self.question_a1]),
            "apply-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["applied"])
        self.question_a1.refresh_from_db()
        self.prd.refresh_from_db()
        self.assertEqual(self.question_a1.version, 2)
        self.assertEqual(self.prd.version, 2)
        self.assertEqual(
            PrdAnswer.objects.get(question=self.question_a1).content,
            f"기존 내용과 메모를 통합한 답변 {self.question_a1.pk}",
        )
        self.assertFalse(PrdAnswer.objects.filter(question=self.question_a2).exists())
        record = AiPrdApplyRecord.objects.get()
        item = AiPrdApplyItem.objects.get(record=record)
        self.assertEqual(item.existing_answer, "기존 핵심 답변")
        self.assertEqual(item.question_prompt, "어떤 문제인가요?")
        self.assertEqual(item.question_version_before, 1)
        self.assertEqual(
            {row["node_id"] for row in item.source_nodes},
            {str(self.accepted_a.pk), str(self.default_a.pk)},
        )
        self.assertEqual(record.actor_user_id, 7)
        self.assertEqual(record.model, "gemini-free-test")
        self.assertEqual(record.prompt_version, 1)
        self.assertTrue(PrdChangeHistory.objects.filter(event_type="brainstorm_ai_prd_applied"))
        self.assertTrue(BrainstormChangeLog.objects.filter(action="prd_apply_completed"))
        self.assertTrue(AuditLog.objects.filter(action="prd_apply_completed"))

        duplicate = self.post(
            "ai-prd-apply-apply",
            self.apply_payload(job, [self.question_a1]),
            "apply-key",
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["data"]["applied"])
        self.assertEqual(AiPrdApplyRecord.objects.count(), 1)

    def test_node_change_after_preview_rolls_back_all_answers(self):
        _, job = self.preview(section_id=self.section_a.pk)
        self.run_job()
        job.refresh_from_db()
        BrainstormNode.objects.filter(pk=self.default_a.pk).update(version=2)

        response = self.post(
            "ai-prd-apply-apply",
            self.apply_payload(job, [self.question_a1, self.question_a2]),
            "node-conflict",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(PrdAnswer.objects.get(question=self.question_a1).content, "기존 핵심 답변")
        self.assertFalse(PrdAnswer.objects.filter(question=self.question_a2).exists())
        self.assertFalse(AiPrdApplyRecord.objects.exists())

    def test_question_change_after_preview_rolls_back(self):
        _, job = self.preview(section_id=self.section_a.pk)
        self.run_job()
        job.refresh_from_db()
        PrdQuestion.objects.filter(pk=self.question_a1.pk).update(version=2)

        response = self.post(
            "ai-prd-apply-apply",
            self.apply_payload(job, [self.question_a1]),
            "question-conflict",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(PrdAnswer.objects.get(question=self.question_a1).content, "기존 핵심 답변")

    def test_held_deleted_unclassified_and_unselected_default_cannot_be_forced(self):
        response = self.post(
            "ai-prd-apply-preview",
            {
                "section_id": self.section_a.pk,
                "selected_default_nodes": [
                    {"node_id": str(self.held.pk), "version": self.held.version}
                ],
            },
            "invalid-selection",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AiJob.objects.count(), 0)

    def test_tutor_cannot_preview_or_apply(self):
        PrdParticipant.objects.filter(prd=self.prd, user_id=7).update(role=PrdParticipantRole.TUTOR)
        response = self.post(
            "ai-prd-apply-preview",
            {"section_id": self.section_a.pk},
            "tutor-preview",
        )
        self.assertEqual(response.status_code, 403)

    def test_completed_prd_blocks_preview_and_apply(self):
        _, job = self.preview(section_id=self.section_a.pk)
        self.run_job()
        job.refresh_from_db()
        self.prd.status = PrdStatus.COMPLETED
        self.prd.completed_at = timezone.now()
        self.prd.save(update_fields=["status", "completed_at", "updated_at"])

        preview = self.post(
            "ai-prd-apply-preview",
            {"section_id": self.section_a.pk},
            "completed-preview",
        )
        apply_response = self.post(
            "ai-prd-apply-apply",
            self.apply_payload(job, [self.question_a1]),
            "completed-apply",
        )

        self.assertEqual(preview.status_code, 403)
        self.assertEqual(apply_response.status_code, 403)
        self.assertEqual(
            PrdAnswer.objects.get(question=self.question_a1).content,
            "기존 핵심 답변",
        )
