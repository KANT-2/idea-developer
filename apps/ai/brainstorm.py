from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormChangeLog,
    BrainstormChangeTarget,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.brainstorm.services import BrainstormAccessService
from apps.prds.detail import PrdAccess
from apps.prds.models import PrdSection

from .coaching import sanitize_ai_markdown
from .exceptions import AiOutputValidationError
from .models import AiActionType, AiFeatureType, AiJob, AiJobStatus
from .services import AiJobService


@dataclass(slots=True)
class AiClassificationConflict(Exception):
    latest_nodes: list[BrainstormNode]


class EmptyBrainstormInput(Exception):
    def __init__(self, *, statistics=None, message="분석할 메모가 없습니다."):
        super().__init__(message)
        self.statistics = statistics
        self.message = message


class BrainstormAiInputBuilder:
    def analysis(self, *, canvas: BrainstormCanvas) -> dict[str, Any]:
        sections = list(
            PrdSection.objects.filter(prd=canvas.prd, is_deleted=False).order_by("position", "id")
        )
        active_notes = list(
            BrainstormNode.objects.filter(
                canvas=canvas,
                node_type=BrainstormNodeType.NOTE,
                is_deleted=False,
            ).order_by("created_at", "id")
        )
        statistics = self.statistics(sections=sections, notes=active_notes)
        if not active_notes:
            raise EmptyBrainstormInput(statistics=statistics)
        self._enforce_limits(active_notes)
        node_ids = [node.pk for node in active_notes]
        connections = BrainstormConnection.objects.filter(
            canvas=canvas,
            is_deleted=False,
            node_a_id__in=node_ids,
            node_b_id__in=node_ids,
        ).order_by("created_at", "id")
        return {
            "kind": "brainstorm_analysis",
            "prd": {
                "id": canvas.prd_id,
                "title": canvas.prd.title,
                "description": canvas.prd.description,
                "prd_type": canvas.prd.prd_type,
            },
            "sections": [self._section(section) for section in sections],
            "nodes": [self._analysis_node(node) for node in active_notes],
            "connections": [
                {
                    "node_a_id": str(connection.node_a_id),
                    "node_b_id": str(connection.node_b_id),
                }
                for connection in connections
            ],
            "server_statistics": statistics,
        }

    def classification(self, *, canvas: BrainstormCanvas) -> dict[str, Any]:
        sections = list(
            PrdSection.objects.filter(prd=canvas.prd, is_deleted=False).order_by("position", "id")
        )
        nodes = list(
            BrainstormNode.objects.filter(
                canvas=canvas,
                node_type=BrainstormNodeType.NOTE,
                section__isnull=True,
                is_deleted=False,
            )
            .exclude(status=BrainstormNodeStatus.HELD)
            .order_by("created_at", "id")
        )
        if not nodes:
            raise EmptyBrainstormInput(message="분류할 미분류 메모가 없습니다.")
        if not sections:
            raise ValidationError({"sections": "분류 대상으로 사용할 활성 PRD 섹션이 없습니다."})
        self._enforce_limits(nodes)
        return {
            "kind": "brainstorm_classification",
            "sections": [self._section(section) for section in sections],
            "nodes": [
                {
                    "id": str(node.pk),
                    "content": node.content,
                    "version": node.version,
                }
                for node in nodes
            ],
        }

    @staticmethod
    def statistics(*, sections, notes):
        regular = [node for node in notes if node.status != BrainstormNodeStatus.HELD]
        per_section = []
        for section in sections:
            section_nodes = [node for node in regular if node.section_id == section.pk]
            per_section.append(
                {
                    "section_id": section.pk,
                    "title": section.title,
                    "total": len(section_nodes),
                    "accepted": sum(
                        node.status == BrainstormNodeStatus.ACCEPTED for node in section_nodes
                    ),
                }
            )
        return {
            "total": len(regular),
            "accepted": sum(node.status == BrainstormNodeStatus.ACCEPTED for node in regular),
            "held": sum(node.status == BrainstormNodeStatus.HELD for node in notes),
            "unclassified": sum(node.section_id is None for node in regular),
            "sections": per_section,
            "empty_section_ids": [row["section_id"] for row in per_section if row["total"] == 0],
        }

    @staticmethod
    def _section(section):
        return {
            "id": section.pk,
            "title": section.title,
            "guide": section.guide,
            "position": section.position,
        }

    @staticmethod
    def _analysis_node(node):
        return {
            "id": str(node.pk),
            "content": node.content,
            "status": node.status,
            "section_id": node.section_id,
            "assignee_id": node.assignee_id,
            "version": node.version,
        }

    @staticmethod
    def _enforce_limits(nodes):
        if len(nodes) > settings.AI_BRAINSTORM_MAX_NODES:
            raise ValidationError(
                {"nodes": f"AI 요청은 메모 {settings.AI_BRAINSTORM_MAX_NODES}개까지 가능합니다."}
            )
        character_count = sum(len(node.content) for node in nodes)
        if character_count > settings.AI_BRAINSTORM_MAX_CHARS:
            raise ValidationError(
                {
                    "nodes": (
                        "AI 요청에 포함할 메모 내용이 "
                        f"{settings.AI_BRAINSTORM_MAX_CHARS}자를 초과했습니다."
                    )
                }
            )


class BrainstormAiRequestService:
    def __init__(self, builder=None):
        self.builder = builder or BrainstormAiInputBuilder()

    @transaction.atomic
    def request_analysis(self, *, canvas, user_id, idempotency_key):
        canvas = (
            BrainstormCanvas.objects.select_for_update().select_related("prd").get(pk=canvas.pk)
        )
        existing = self._existing(
            canvas=canvas,
            user_id=user_id,
            feature_type=AiFeatureType.BRAINSTORM_ANALYSIS,
            idempotency_key=idempotency_key,
        )
        if existing:
            return existing, False
        input_data = self.builder.analysis(canvas=canvas)
        return AiJobService().enqueue(
            prd=canvas.prd,
            user_id=user_id,
            feature_type=AiFeatureType.BRAINSTORM_ANALYSIS,
            action_type=AiActionType.ANALYSIS,
            input_data=input_data,
            idempotency_key=idempotency_key,
        )

    @transaction.atomic
    def request_classification(self, *, canvas, user_id, idempotency_key):
        canvas = (
            BrainstormCanvas.objects.select_for_update().select_related("prd").get(pk=canvas.pk)
        )
        existing = self._existing(
            canvas=canvas,
            user_id=user_id,
            feature_type=AiFeatureType.BRAINSTORM_CLASSIFICATION,
            idempotency_key=idempotency_key,
        )
        if existing:
            return existing, False
        input_data = self.builder.classification(canvas=canvas)
        return AiJobService().enqueue(
            prd=canvas.prd,
            user_id=user_id,
            feature_type=AiFeatureType.BRAINSTORM_CLASSIFICATION,
            action_type=AiActionType.CLASSIFICATION,
            input_data=input_data,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _existing(*, canvas, user_id, feature_type, idempotency_key):
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key.strip()) > 128
        ):
            raise ValidationError({"idempotency_key": "올바른 Idempotency-Key가 필요합니다."})
        exact = AiJob.objects.filter(
            prd=canvas.prd,
            user_id=user_id,
            feature_type=feature_type,
            idempotency_key=idempotency_key.strip(),
        ).first()
        if exact:
            return exact
        return (
            AiJob.objects.filter(
                prd=canvas.prd,
                user_id=user_id,
                feature_type=feature_type,
                status__in=[
                    AiJobStatus.QUEUED,
                    AiJobStatus.RUNNING,
                    AiJobStatus.RETRY_WAIT,
                    AiJobStatus.CANCEL_REQUESTED,
                ],
            )
            .order_by("created_at")
            .first()
        )


class BrainstormAiResultProcessor:
    def process(self, *, job: AiJob, output: dict[str, Any]) -> dict[str, Any]:
        if (
            job.feature_type == AiFeatureType.BRAINSTORM_ANALYSIS
            and job.input_data.get("kind") == "brainstorm_analysis"
        ):
            return self._analysis(job=job, output=output)
        if (
            job.feature_type == AiFeatureType.BRAINSTORM_CLASSIFICATION
            and job.input_data.get("kind") == "brainstorm_classification"
        ):
            return self._classification(job=job, output=output)
        return output

    def _analysis(self, *, job, output):
        self._require_keys(
            output, {"summary", "section_findings", "missing_topics", "source_node_ids"}
        )
        allowed_nodes = {row["id"] for row in job.input_data.get("nodes", [])}
        allowed_sections = {row["id"] for row in job.input_data.get("sections", [])}
        source_node_ids = self._node_ids(output["source_node_ids"], allowed_nodes)
        findings = []
        if not isinstance(output["section_findings"], list):
            raise AiOutputValidationError("section_findings must be an array.")
        for row in output["section_findings"]:
            if not isinstance(row, dict):
                raise AiOutputValidationError("Each section finding must be an object.")
            self._require_keys(row, {"section_id", "finding", "source_node_ids"})
            section_id = row["section_id"]
            if section_id not in allowed_sections:
                raise AiOutputValidationError("Analysis referenced an unavailable section.")
            findings.append(
                {
                    "section_id": section_id,
                    "finding": sanitize_ai_markdown(row["finding"]),
                    "source_node_ids": self._node_ids(row["source_node_ids"], allowed_nodes),
                }
            )
        missing_topics = []
        if not isinstance(output["missing_topics"], list):
            raise AiOutputValidationError("missing_topics must be an array.")
        for row in output["missing_topics"]:
            if not isinstance(row, dict):
                raise AiOutputValidationError("Each missing topic must be an object.")
            self._require_keys(row, {"topic", "reason", "source_node_ids"})
            section_id = row.get("section_id")
            if section_id is not None and section_id not in allowed_sections:
                raise AiOutputValidationError("Missing topic referenced an unavailable section.")
            missing_topics.append(
                {
                    "section_id": section_id,
                    "topic": sanitize_ai_markdown(row["topic"]),
                    "reason": sanitize_ai_markdown(row["reason"]),
                    "source_node_ids": self._node_ids(row["source_node_ids"], allowed_nodes),
                }
            )
        return {
            "summary": sanitize_ai_markdown(output["summary"]),
            "section_findings": findings,
            "missing_topics": missing_topics,
            "source_node_ids": source_node_ids,
        }

    def _classification(self, *, job, output):
        self._require_keys(output, {"recommendations"})
        if not isinstance(output["recommendations"], list):
            raise AiOutputValidationError("recommendations must be an array.")
        input_nodes = {row["id"]: row for row in job.input_data.get("nodes", [])}
        allowed_sections = {row["id"] for row in job.input_data.get("sections", [])}
        seen = set()
        recommendations = []
        for row in output["recommendations"]:
            if not isinstance(row, dict):
                raise AiOutputValidationError("Each recommendation must be an object.")
            self._require_keys(row, {"node_id", "section_id", "reason"})
            node_id = str(row["node_id"])
            if node_id not in input_nodes:
                raise AiOutputValidationError("Classification referenced an unavailable node.")
            if node_id in seen:
                raise AiOutputValidationError("Classification returned a duplicate node.")
            if row["section_id"] not in allowed_sections:
                raise AiOutputValidationError("Classification referenced an unavailable section.")
            seen.add(node_id)
            recommendations.append(
                {
                    "node_id": node_id,
                    "node_version": input_nodes[node_id]["version"],
                    "node_content": input_nodes[node_id]["content"],
                    "section_id": row["section_id"],
                    "reason": sanitize_ai_markdown(row["reason"]),
                }
            )
        return {"recommendations": recommendations}

    @staticmethod
    def _require_keys(value, keys):
        if not isinstance(value, dict) or not keys.issubset(value):
            raise AiOutputValidationError(
                "AI output is missing required fields: " + ", ".join(sorted(keys))
            )

    @staticmethod
    def _node_ids(value, allowed):
        if not isinstance(value, list):
            raise AiOutputValidationError("source_node_ids must be an array.")
        normalized = [str(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise AiOutputValidationError("source_node_ids must not contain duplicates.")
        if not set(normalized).issubset(allowed):
            raise AiOutputValidationError("Analysis referenced an unavailable node.")
        return normalized


class BrainstormAiResultRouter:
    def __init__(self):
        from .coaching import AiResultProcessor
        from .prd_apply import PrdApplyResultProcessor

        self.coaching = AiResultProcessor()
        self.brainstorm = BrainstormAiResultProcessor()
        self.prd_apply = PrdApplyResultProcessor()

    def process(self, *, job, output):
        output = self.coaching.process(job=job, output=output)
        output = self.brainstorm.process(job=job, output=output)
        return self.prd_apply.process(job=job, output=output)


class BrainstormClassificationApplyService:
    @transaction.atomic
    def apply(
        self,
        *,
        canvas: BrainstormCanvas,
        access: PrdAccess,
        job: AiJob,
        actor_user_id: int,
        selections: Any,
        idempotency_key: str,
    ):
        BrainstormAccessService.enforce_write(access)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError({"idempotency_key": "Idempotency-Key 헤더가 필요합니다."})
        if len(idempotency_key.strip()) > 128:
            raise ValidationError({"idempotency_key": "Idempotency-Key가 너무 깁니다."})
        job = AiJob.objects.select_for_update().get(pk=job.pk)
        if (
            job.prd_id != canvas.prd_id
            or job.user_id != actor_user_id
            or job.feature_type != AiFeatureType.BRAINSTORM_CLASSIFICATION
            or job.status != AiJobStatus.SUCCEEDED
        ):
            raise ValidationError({"job": "반영할 수 있는 AI 분류 작업이 아닙니다."})
        previous_application = (job.output_data or {}).get("application")
        if previous_application:
            if previous_application.get("idempotency_key") != idempotency_key.strip():
                raise ValidationError({"job": "이미 반영된 AI 분류 작업입니다."})
            nodes = list(
                BrainstormNode.objects.filter(
                    canvas=canvas,
                    pk__in=[row["id"] for row in previous_application["nodes"]],
                ).order_by("id")
            )
            return previous_application["operation_id"], nodes, False
        if not isinstance(selections, list) or not selections:
            raise ValidationError({"selections": "반영할 추천을 하나 이상 선택해 주세요."})
        if not all(isinstance(row, dict) for row in selections):
            raise ValidationError({"selections": "선택한 추천 형식이 올바르지 않습니다."})
        for row in selections:
            try:
                uuid.UUID(str(row.get("node_id")))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValidationError({"node_id": "메모 ID가 올바르지 않습니다."}) from exc
            if (
                isinstance(row.get("section_id"), bool)
                or not isinstance(row.get("section_id"), int)
                or row["section_id"] < 1
            ):
                raise ValidationError({"section_id": "섹션 ID가 올바르지 않습니다."})
            if (
                isinstance(row.get("version"), bool)
                or not isinstance(row.get("version"), int)
                or row["version"] < 1
            ):
                raise ValidationError({"version": "노드 version이 올바르지 않습니다."})
        recommendation_map = {
            row["node_id"]: row for row in (job.output_data or {}).get("recommendations", [])
        }
        selected_ids = [str(row.get("node_id")) for row in selections]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValidationError({"selections": "같은 메모를 중복 선택할 수 없습니다."})
        snapshot_versions = {row["id"]: row["version"] for row in job.input_data.get("nodes", [])}
        sections = {
            section.pk: section
            for section in PrdSection.objects.filter(
                prd=canvas.prd,
                is_deleted=False,
                pk__in=[row.get("section_id") for row in selections],
            )
        }
        canvas = BrainstormCanvas.objects.select_for_update().get(pk=canvas.pk)
        nodes = list(
            BrainstormNode.objects.select_for_update()
            .filter(canvas=canvas, pk__in=selected_ids)
            .order_by("id")
        )
        nodes_by_id = {str(node.pk): node for node in nodes}
        invalid = []
        before = []
        for row in selections:
            node_id = str(row.get("node_id"))
            recommendation = recommendation_map.get(node_id)
            node = nodes_by_id.get(node_id)
            section_id = row.get("section_id")
            version = row.get("version")
            if (
                recommendation is None
                or recommendation["section_id"] != section_id
                or section_id not in sections
                or node is None
                or node.node_type != BrainstormNodeType.NOTE
                or node.is_deleted
                or node.status == BrainstormNodeStatus.HELD
                or node.section_id is not None
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version != snapshot_versions.get(node_id)
                or node.version != version
            ):
                if node is not None and node.version != version:
                    invalid.append(node)
                else:
                    raise ValidationError(
                        {"selections": "선택한 추천이 최신 AI 분류 결과와 일치하지 않습니다."}
                    )
            else:
                before.append(
                    {
                        "id": node_id,
                        "section_id": node.section_id,
                        "version": node.version,
                    }
                )
        if invalid:
            raise AiClassificationConflict(invalid)

        changed_at = timezone.now()
        for row in selections:
            node = nodes_by_id[str(row["node_id"])]
            node.section = sections[row["section_id"]]
            node.version += 1
            node.updated_at = changed_at
        BrainstormNode.objects.bulk_update(nodes, ["section", "version", "updated_at"])
        operation_id = uuid.uuid4()
        after = [
            {"id": str(node.pk), "section_id": node.section_id, "version": node.version}
            for node in nodes
        ]
        BrainstormChangeLog.objects.create(
            canvas=canvas,
            actor_user_id=actor_user_id,
            operation_id=operation_id,
            action="ai_classification_applied",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=str(canvas.pk),
            before_data={"nodes": before},
            after_data={"nodes": after, "ai_job_id": str(job.pk)},
        )
        job.output_data = {
            **(job.output_data or {}),
            "application": {
                "idempotency_key": idempotency_key.strip(),
                "operation_id": str(operation_id),
                "nodes": after,
                "applied_at": changed_at.isoformat(),
            },
        }
        job.save(update_fields=["output_data", "updated_at"])
        return str(operation_id), nodes, True
