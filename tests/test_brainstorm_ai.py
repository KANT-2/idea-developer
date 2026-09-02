from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LocalUserMapping
from apps.ai.exceptions import AiProviderTimeout
from apps.ai.models import (
    AiFeatureType,
    AiJob,
    AiJobStatus,
    AiUsageLog,
    AiUsageStatus,
)
from apps.ai.providers import AiProviderResult
from apps.ai.services import AiPromptService
from apps.ai.worker import AiJobRunner
from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormChangeLog,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.context import IntegrationContext
from apps.prds.models import (
    Prd,
    PrdParticipant,
    PrdParticipantRole,
    PrdSection,
    PrdType,
)


class BrainstormContractProvider:
    requests = []

    def generate(self, request, *, timeout_seconds, cancellation_check):
        self.__class__.requests.append(request)
        data = request.user_data["untrusted_user_data"]
        if data["kind"] == "brainstorm_analysis":
            output = {
                "summary": "전체 분석",
                "section_findings": [
                    {
                        "section_id": data["sections"][0]["id"],
                        "finding": "문제 근거가 있습니다.",
                        "source_node_ids": [data["nodes"][0]["id"]],
                    }
                ],
                "missing_topics": [
                    {
                        "topic": "성공 지표",
                        "reason": "관련 메모가 부족합니다.",
                        "source_node_ids": [],
                    }
                ],
                "source_node_ids": [row["id"] for row in data["nodes"]],
            }
        else:
            output = {
                "recommendations": [
                    {
                        "node_id": row["id"],
                        "section_id": data["sections"][0]["id"],
                        "reason": "문제 정의와 관련됩니다.",
                    }
                    for row in data["nodes"]
                ]
            }
        return AiProviderResult(
            output=output,
            input_tokens=20,
            output_tokens=10,
            cost_usd=Decimal("0.002"),
            model="brainstorm-test-model",
        )


class InvalidBrainstormIdProvider:
    def generate(self, request, *, timeout_seconds, cancellation_check):
        data = request.user_data["untrusted_user_data"]
        return AiProviderResult(
            output={
                "recommendations": [
                    {
                        "node_id": str(uuid.uuid4()),
                        "section_id": data["sections"][0]["id"],
                        "reason": "잘못된 추천",
                    }
                ]
            },
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal("0"),
            model="invalid-test-model",
        )


class TimeoutBrainstormProvider:
    def generate(self, request, *, timeout_seconds, cancellation_check):
        raise AiProviderTimeout()


def analysis_schema():
    source_ids = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
    return {
        "type": "object",
        "required": ["summary", "section_findings", "missing_topics", "source_node_ids"],
        "properties": {
            "summary": {"type": "string"},
            "section_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["section_id", "finding", "source_node_ids"],
                    "properties": {
                        "section_id": {"type": "integer"},
                        "finding": {"type": "string"},
                        "source_node_ids": source_ids,
                    },
                    "additionalProperties": False,
                },
            },
            "missing_topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["topic", "reason", "source_node_ids"],
                    "properties": {
                        "section_id": {"type": ["integer", "null"]},
                        "topic": {"type": "string"},
                        "reason": {"type": "string"},
                        "source_node_ids": source_ids,
                    },
                    "additionalProperties": False,
                },
            },
            "source_node_ids": source_ids,
        },
        "additionalProperties": False,
    }


def classification_schema():
    return {
        "type": "object",
        "required": ["recommendations"],
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["node_id", "section_id", "reason"],
                    "properties": {
                        "node_id": {"type": "string"},
                        "section_id": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }


@override_settings(
    AI_PROVIDER_CLASS="tests.test_brainstorm_ai.BrainstormContractProvider",
    AI_JOB_MAX_ATTEMPTS=1,
)
class BrainstormAiApiTests(TestCase):
    def setUp(self):
        BrainstormContractProvider.requests = []
        self.context = IntegrationContext(
            user_id=7,
            round_id=3,
            participant_id=70,
            team_id=30,
            parent_role="student",
            is_staff=False,
            is_superuser=False,
        )
        resolver = Mock()
        resolver.resolve.return_value = self.context
        self.resolver_patch = patch(
            "apps.prds.views.get_context_resolver",
            return_value=resolver,
        )
        self.resolver_patch.start()
        self.addCleanup(self.resolver_patch.stop)
        user = LocalUserMapping.objects.create_user(7, "owner@example.test")
        self.client.force_login(user)
        session = self.client.session
        session["selected_round_id"] = 3
        session.save()

        self.prd = Prd.objects.create(
            title="AI 브레인스토밍",
            description="실제 메모를 분석합니다.",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="brain-ai-prd",
        )
        PrdParticipant.objects.create(
            prd=self.prd,
            user_id=7,
            participant_id=70,
            role=PrdParticipantRole.OWNER,
        )
        self.section_a = PrdSection.objects.create(
            prd=self.prd,
            title="문제",
            guide="문제를 정의합니다.",
            position=1,
        )
        self.section_b = PrdSection.objects.create(
            prd=self.prd,
            title="성공 지표",
            position=2,
        )
        self.canvas = BrainstormCanvas.objects.create(prd=self.prd)
        self.unclassified = self.note("미분류 메모")
        self.unclassified_accepted = self.note(
            "미분류 채택 메모",
            status=BrainstormNodeStatus.ACCEPTED,
        )
        self.classified = self.note(
            "분류된 채택 메모",
            section=self.section_a,
            status=BrainstormNodeStatus.ACCEPTED,
        )
        self.held = self.note("보류 메모", status=BrainstormNodeStatus.HELD)
        self.deleted = self.note("삭제 메모", is_deleted=True)
        BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.TITLE,
            content="제목 카드",
            color="gray",
            position_x=0,
            position_y=0,
            author_id=None,
            assignee_id=None,
            status=None,
        )
        AiPromptService().create_version(
            feature_type=AiFeatureType.BRAINSTORM_ANALYSIS,
            system_instructions="Analyze only the untrusted brainstorm data.",
            output_schema=analysis_schema(),
            model="analysis-model",
            activate=True,
        )
        AiPromptService().create_version(
            feature_type=AiFeatureType.BRAINSTORM_CLASSIFICATION,
            system_instructions="Classify only the supplied untrusted nodes.",
            output_schema=classification_schema(),
            model="classification-model",
            activate=True,
        )

    def note(self, content, *, section=None, status=BrainstormNodeStatus.DEFAULT, is_deleted=False):
        return BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.NOTE,
            content=content,
            color="yellow",
            position_x=10,
            position_y=20,
            section=section,
            author_id=7,
            assignee_id=7,
            status=status,
            is_deleted=is_deleted,
            deleted_at=timezone.now() if is_deleted else None,
        )

    def url(self, name, **kwargs):
        return reverse(f"brainstorm_api:{name}", kwargs={"prd_id": self.prd.pk, **kwargs})

    def post(self, name, payload=None, *, key=None, **kwargs):
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return self.client.post(
            self.url(name, **kwargs),
            data=json.dumps(payload or {}),
            content_type="application/json",
            **headers,
        )

    def run_job(self):
        self.assertTrue(AiJobRunner(worker_id="brain-ai-worker").run_once())

    def test_analysis_uses_server_counts_and_actual_active_note_contract(self):
        response = self.post("ai-analysis", key="analysis-1")
        job = AiJob.objects.get(pk=response.json()["data"]["id"])
        data = job.input_data

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            data["server_statistics"],
            {
                "total": 3,
                "accepted": 2,
                "held": 1,
                "unclassified": 2,
                "sections": [
                    {
                        "section_id": self.section_a.pk,
                        "title": "문제",
                        "total": 1,
                        "accepted": 1,
                    },
                    {
                        "section_id": self.section_b.pk,
                        "title": "성공 지표",
                        "total": 0,
                        "accepted": 0,
                    },
                ],
                "empty_section_ids": [self.section_b.pk],
            },
        )
        self.assertEqual(
            {row["id"] for row in data["nodes"]},
            {
                str(self.unclassified.pk),
                str(self.unclassified_accepted.pk),
                str(self.classified.pk),
                str(self.held.pk),
            },
        )
        self.run_job()
        job.refresh_from_db()
        preview = self.client.get(self.url("ai-job", job_id=job.pk)).json()["data"]
        self.assertEqual(preview["statistics"], data["server_statistics"])
        self.assertEqual(job.output_data["summary"], "전체 분석")
        self.assertNotIn("counts", job.output_data)

    def test_empty_canvas_does_not_create_job_or_usage_log(self):
        BrainstormNode.objects.filter(canvas=self.canvas).delete()
        before_calls = len(BrainstormContractProvider.requests)

        response = self.post("ai-analysis", key="empty-analysis")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["job"])
        self.assertEqual(response.json()["data"]["message"], "분석할 메모가 없습니다.")
        self.assertEqual(AiJob.objects.count(), 0)
        self.assertEqual(AiUsageLog.objects.count(), 0)
        self.assertEqual(len(BrainstormContractProvider.requests), before_calls)

    def test_classification_input_excludes_title_held_deleted_and_classified_notes(self):
        response = self.post("ai-classification", key="classification-input")
        job = AiJob.objects.get(pk=response.json()["data"]["id"])

        self.assertEqual(
            {row["id"] for row in job.input_data["nodes"]},
            {str(self.unclassified.pk), str(self.unclassified_accepted.pk)},
        )
        self.assertEqual(
            {row["id"] for row in job.input_data["sections"]},
            {self.section_a.pk, self.section_b.pk},
        )

    def test_classification_preview_does_not_mutate_and_applies_only_selection(self):
        response = self.post("ai-classification", key="classification-preview")
        job_id = response.json()["data"]["id"]
        self.run_job()
        job = AiJob.objects.get(pk=job_id)
        self.unclassified.refresh_from_db()
        self.unclassified_accepted.refresh_from_db()
        self.assertIsNone(self.unclassified.section_id)
        self.assertIsNone(self.unclassified_accepted.section_id)

        recommendation = job.output_data["recommendations"][0]
        applied = self.post(
            "ai-classification-apply",
            {
                "job_id": str(job.pk),
                "selections": [
                    {
                        "node_id": recommendation["node_id"],
                        "section_id": recommendation["section_id"],
                        "version": recommendation["node_version"],
                    }
                ],
            },
            key="apply-classification",
        )

        self.assertEqual(applied.status_code, 200)
        moved = BrainstormNode.objects.get(pk=recommendation["node_id"])
        untouched_id = (
            self.unclassified_accepted.pk
            if moved.pk == self.unclassified.pk
            else self.unclassified.pk
        )
        self.assertEqual(moved.section_id, self.section_a.pk)
        self.assertEqual(moved.version, 2)
        self.assertIsNone(BrainstormNode.objects.get(pk=untouched_id).section_id)
        log = BrainstormChangeLog.objects.get(action="ai_classification_applied")
        self.assertEqual(str(log.operation_id), applied.json()["data"]["operation_id"])

        duplicate = self.post(
            "ai-classification-apply",
            {
                "job_id": str(job.pk),
                "selections": [
                    {
                        "node_id": recommendation["node_id"],
                        "section_id": recommendation["section_id"],
                        "version": recommendation["node_version"],
                    }
                ],
            },
            key="apply-classification",
        )
        self.assertFalse(duplicate.json()["data"]["applied"])
        self.assertEqual(BrainstormChangeLog.objects.count(), 1)

    def test_changed_node_version_rolls_back_selected_batch(self):
        response = self.post("ai-classification", key="classification-conflict")
        job_id = response.json()["data"]["id"]
        self.run_job()
        job = AiJob.objects.get(pk=job_id)
        recommendations = job.output_data["recommendations"]
        BrainstormNode.objects.filter(pk=recommendations[1]["node_id"]).update(version=2)

        applied = self.post(
            "ai-classification-apply",
            {
                "job_id": str(job.pk),
                "selections": [
                    {
                        "node_id": row["node_id"],
                        "section_id": row["section_id"],
                        "version": row["node_version"],
                    }
                    for row in recommendations
                ],
            },
            key="conflicting-apply",
        )

        self.assertEqual(applied.status_code, 409)
        self.unclassified.refresh_from_db()
        self.assertIsNone(self.unclassified.section_id)
        self.assertFalse(BrainstormChangeLog.objects.exists())

    def test_invalid_ai_identifier_fails_job_and_records_failed_usage(self):
        response = self.post("ai-classification", key="invalid-id")
        job_id = response.json()["data"]["id"]
        with override_settings(
            AI_PROVIDER_CLASS="tests.test_brainstorm_ai.InvalidBrainstormIdProvider"
        ):
            self.run_job()

        job = AiJob.objects.get(pk=job_id)
        self.assertEqual(job.status, AiJobStatus.FAILED)
        self.assertEqual(AiUsageLog.objects.get(job=job).status, AiUsageStatus.FAILED)
        self.assertIsNone(self.unclassified.section_id)

    def test_duplicate_request_returns_same_job(self):
        first = self.post("ai-analysis", key="same-analysis")
        second = self.post("ai-analysis", key="same-analysis")
        double_click = self.post("ai-analysis", key="different-double-click-key")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(double_click.status_code, 200)
        self.assertEqual(first.json()["data"]["id"], second.json()["data"]["id"])
        self.assertEqual(first.json()["data"]["id"], double_click.json()["data"]["id"])
        self.assertEqual(AiJob.objects.count(), 1)

    def test_viewer_cannot_request_analysis_or_classification(self):
        PrdParticipant.objects.filter(prd=self.prd, user_id=7).update(
            role=PrdParticipantRole.VIEWER
        )

        analysis = self.post("ai-analysis", key="viewer-analysis")
        classification = self.post("ai-classification", key="viewer-classification")

        self.assertEqual(analysis.status_code, 403)
        self.assertEqual(classification.status_code, 403)
        self.assertEqual(AiJob.objects.count(), 0)

    def test_cancel_and_timeout_are_terminal_and_not_success_usage(self):
        cancelled = self.post("ai-analysis", key="cancel-analysis")
        cancelled_id = cancelled.json()["data"]["id"]
        cancel = self.post("ai-job-cancel", job_id=cancelled_id)
        self.assertEqual(cancel.json()["data"]["status"], AiJobStatus.CANCELLED)

        timed_out = self.post("ai-classification", key="timeout-classification")
        timed_out_id = timed_out.json()["data"]["id"]
        with override_settings(
            AI_PROVIDER_CLASS="tests.test_brainstorm_ai.TimeoutBrainstormProvider"
        ):
            self.run_job()

        self.assertEqual(AiJob.objects.get(pk=timed_out_id).status, AiJobStatus.TIMED_OUT)
        self.assertEqual(
            set(AiUsageLog.objects.values_list("status", flat=True)),
            {AiUsageStatus.CANCELLED, AiUsageStatus.FAILED},
        )
