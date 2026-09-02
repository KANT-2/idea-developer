from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.brainstorm.models import (
    AuditLog,
    BrainstormCanvas,
    BrainstormChangeLog,
    BrainstormChangeTarget,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.prds.detail import PrdAccess
from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdChangeHistory,
    PrdQuestion,
    PrdSection,
)

from .brainstorm import EmptyBrainstormInput
from .coaching import sanitize_ai_markdown
from .exceptions import AiOutputValidationError
from .models import (
    AiActionType,
    AiFeatureType,
    AiJob,
    AiJobStatus,
    AiPrdApplyItem,
    AiPrdApplyRecord,
    AiPrdApplyScope,
    AiUsageLog,
    AiUsageStatus,
)
from .services import AiJobService


@dataclass(slots=True)
class PrdApplyConflict(Exception):
    nodes: list[BrainstormNode]
    questions: list[PrdQuestion]


class PrdApplyInputBuilder:
    def build(self, *, canvas, section_id=None, selected_default_nodes=None):
        selected_rows = self._selected_rows(selected_default_nodes)
        sections = self._sections(canvas=canvas, section_id=section_id)
        section_ids = {section.pk for section in sections}
        accepted = list(
            BrainstormNode.objects.filter(
                canvas=canvas,
                node_type=BrainstormNodeType.NOTE,
                status=BrainstormNodeStatus.ACCEPTED,
                is_deleted=False,
                section_id__in=section_ids,
            ).order_by("created_at", "id")
        )
        selected_defaults = self._default_nodes(
            canvas=canvas,
            section_ids=section_ids,
            selected_rows=selected_rows,
        )
        nodes_by_id = {str(node.pk): node for node in [*accepted, *selected_defaults]}
        nodes = list(nodes_by_id.values())
        if not nodes:
            raise EmptyBrainstormInput(message="PRD에 반영할 메모가 없습니다.")
        questions = list(
            PrdQuestion.objects.filter(
                section_id__in=section_ids,
                section__is_deleted=False,
                is_deleted=False,
            )
            .select_related("section", "answer")
            .order_by("section__position", "position", "id")
        )
        if not questions:
            raise ValidationError({"questions": "반영할 활성 PRD 질문이 없습니다."})
        self._enforce_limits(canvas=canvas, sections=sections, questions=questions, nodes=nodes)
        node_ids = [node.pk for node in nodes]
        connections = BrainstormConnection.objects.filter(
            canvas=canvas,
            is_deleted=False,
            node_a_id__in=node_ids,
            node_b_id__in=node_ids,
        ).order_by("created_at", "id")
        unclassified_accepted_ids = list(
            BrainstormNode.objects.filter(
                canvas=canvas,
                node_type=BrainstormNodeType.NOTE,
                status=BrainstormNodeStatus.ACCEPTED,
                section__isnull=True,
                is_deleted=False,
            ).values_list("id", flat=True)
        )
        scope = AiPrdApplyScope.SECTION if section_id is not None else AiPrdApplyScope.ALL
        return {
            "kind": "brainstorm_prd_apply",
            "scope": scope,
            "section_id": section_id,
            "merge_strategy": "ai_integrate",
            "prd": {
                "id": canvas.prd_id,
                "title": canvas.prd.title,
                "description": canvas.prd.description,
                "prd_type": canvas.prd.prd_type,
            },
            "sections": [
                {
                    "id": section.pk,
                    "title": section.title,
                    "guide": section.guide,
                }
                for section in sections
            ],
            "questions": [self._question(question) for question in questions],
            "nodes": [
                {
                    "id": str(node.pk),
                    "content": node.content,
                    "status": node.status,
                    "section_id": node.section_id,
                    "version": node.version,
                    "selection": (
                        "accepted"
                        if node.status == BrainstormNodeStatus.ACCEPTED
                        else "user_selected_default"
                    ),
                }
                for node in nodes
            ],
            "connections": [
                {
                    "node_a_id": str(connection.node_a_id),
                    "node_b_id": str(connection.node_b_id),
                }
                for connection in connections
            ],
            "excluded_unclassified_accepted_node_ids": [
                str(node_id) for node_id in unclassified_accepted_ids
            ],
        }

    @staticmethod
    def _enforce_limits(*, canvas, sections, questions, nodes):
        if len(nodes) > settings.AI_BRAINSTORM_MAX_NODES:
            raise ValidationError(
                {"nodes": f"AI 요청은 메모 {settings.AI_BRAINSTORM_MAX_NODES}개까지 가능합니다."}
            )
        character_count = len(canvas.prd.title) + len(canvas.prd.description)
        character_count += sum(len(section.title) + len(section.guide) for section in sections)
        character_count += sum(
            len(question.prompt) + len(PrdApplyInputBuilder._answer_text(question))
            for question in questions
        )
        character_count += sum(len(node.content) for node in nodes)
        if character_count > settings.AI_CONTEXT_MAX_CHARS:
            raise ValidationError(
                {
                    "context": (
                        "AI PRD 반영 Context가 허용된 "
                        f"{settings.AI_CONTEXT_MAX_CHARS}자를 초과했습니다."
                    )
                }
            )

    @staticmethod
    def _answer_text(question):
        try:
            return question.answer.content
        except PrdAnswer.DoesNotExist:
            return ""

    @staticmethod
    def _question(question):
        answer = PrdApplyInputBuilder._answer_text(question)
        return {
            "id": question.pk,
            "section_id": question.section_id,
            "prompt": question.prompt,
            "current_answer": answer,
            "version": question.version,
        }

    @staticmethod
    def _sections(*, canvas, section_id):
        queryset = PrdSection.objects.filter(prd=canvas.prd, is_deleted=False)
        if section_id is not None:
            if isinstance(section_id, bool) or not isinstance(section_id, int) or section_id < 1:
                raise ValidationError({"section_id": "섹션 ID가 올바르지 않습니다."})
            queryset = queryset.filter(pk=section_id)
        sections = list(queryset.order_by("position", "id"))
        if section_id is not None and not sections:
            raise ValidationError({"section_id": "현재 PRD의 활성 섹션이 아닙니다."})
        if not sections:
            raise ValidationError({"sections": "활성 PRD 섹션이 없습니다."})
        return sections

    @staticmethod
    def _selected_rows(value):
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise ValidationError({"selected_default_nodes": "메모 선택 형식이 올바르지 않습니다."})
        result = []
        seen = set()
        for row in value:
            try:
                node_id = str(uuid.UUID(str(row.get("node_id"))))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValidationError({"node_id": "메모 ID가 올바르지 않습니다."}) from exc
            version = row.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValidationError({"version": "메모 version이 올바르지 않습니다."})
            if node_id in seen:
                raise ValidationError({"selected_default_nodes": "메모를 중복 선택할 수 없습니다."})
            seen.add(node_id)
            result.append({"node_id": node_id, "version": version})
        return result

    @staticmethod
    def _default_nodes(*, canvas, section_ids, selected_rows):
        if not selected_rows:
            return []
        nodes = list(
            BrainstormNode.objects.filter(
                canvas=canvas,
                pk__in=[row["node_id"] for row in selected_rows],
            ).order_by("created_at", "id")
        )
        nodes_by_id = {str(node.pk): node for node in nodes}
        for row in selected_rows:
            node = nodes_by_id.get(row["node_id"])
            if (
                node is None
                or node.node_type != BrainstormNodeType.NOTE
                or node.is_deleted
                or node.status != BrainstormNodeStatus.DEFAULT
                or node.section_id not in section_ids
                or node.version != row["version"]
            ):
                raise ValidationError(
                    {
                        "selected_default_nodes": (
                            "선택한 기본 메모가 최신 반영 대상과 일치하지 않습니다."
                        )
                    }
                )
        return nodes


class PrdApplyRequestService:
    def __init__(self, builder=None):
        self.builder = builder or PrdApplyInputBuilder()

    @transaction.atomic
    def request_preview(
        self,
        *,
        canvas,
        user_id,
        idempotency_key,
        section_id=None,
        selected_default_nodes=None,
    ):
        canvas = (
            BrainstormCanvas.objects.select_for_update().select_related("prd").get(pk=canvas.pk)
        )
        input_data = self.builder.build(
            canvas=canvas,
            section_id=section_id,
            selected_default_nodes=selected_default_nodes,
        )
        return AiJobService().enqueue(
            prd=canvas.prd,
            user_id=user_id,
            feature_type=AiFeatureType.BRAINSTORM_PRD_APPLY,
            action_type=AiActionType.PRD_APPLY,
            input_data=input_data,
            idempotency_key=idempotency_key,
        )


class PrdApplyResultProcessor:
    def process(self, *, job, output):
        if (
            job.feature_type != AiFeatureType.BRAINSTORM_PRD_APPLY
            or job.input_data.get("kind") != "brainstorm_prd_apply"
        ):
            return output
        self._require_keys(output, {"answers", "unused_node_ids", "warnings"})
        if not isinstance(output["answers"], list):
            raise AiOutputValidationError("answers must be an array.")
        input_questions = {row["id"]: row for row in job.input_data.get("questions", [])}
        allowed_nodes = {row["id"] for row in job.input_data.get("nodes", [])}
        answers = []
        seen_questions = set()
        used_nodes = set()
        for row in output["answers"]:
            if not isinstance(row, dict):
                raise AiOutputValidationError("Each answer must be an object.")
            self._require_keys(
                row,
                {
                    "question_id",
                    "draft",
                    "source_node_ids",
                    "preserved_existing_points",
                    "added_points",
                    "confidence",
                },
            )
            question_id = row["question_id"]
            if question_id not in input_questions or question_id in seen_questions:
                raise AiOutputValidationError("AI referenced an unavailable or duplicate question.")
            source_ids = self._ids(row["source_node_ids"], allowed_nodes, "source_node_ids")
            used_nodes.update(source_ids)
            draft = sanitize_ai_markdown(row["draft"]).strip()
            if not draft:
                raise AiOutputValidationError("AI returned an empty integrated draft.")
            answers.append(
                {
                    "question_id": question_id,
                    "question_prompt": input_questions[question_id]["prompt"],
                    "section_id": input_questions[question_id]["section_id"],
                    "question_version": input_questions[question_id]["version"],
                    "existing_answer": input_questions[question_id]["current_answer"],
                    "draft": draft,
                    "source_node_ids": source_ids,
                    "preserved_existing_points": self._strings(
                        row["preserved_existing_points"], "preserved_existing_points"
                    ),
                    "added_points": self._strings(row["added_points"], "added_points"),
                    "confidence": str(self._confidence(row["confidence"])),
                }
            )
            seen_questions.add(question_id)
        if seen_questions != set(input_questions):
            raise AiOutputValidationError("AI must return one draft for every target question.")
        unused = self._ids(output["unused_node_ids"], allowed_nodes, "unused_node_ids")
        if used_nodes.intersection(unused) or used_nodes.union(unused) != allowed_nodes:
            raise AiOutputValidationError(
                "Used and unused nodes must partition the selected nodes."
            )
        return {
            "answers": answers,
            "unused_node_ids": unused,
            "warnings": self._strings(output["warnings"], "warnings"),
        }

    @staticmethod
    def _require_keys(value, keys):
        if not isinstance(value, dict) or not keys.issubset(value):
            raise AiOutputValidationError("AI output is missing required PRD apply fields.")

    @staticmethod
    def _ids(value, allowed, field):
        if not isinstance(value, list):
            raise AiOutputValidationError(f"{field} must be an array.")
        result = [str(item) for item in value]
        if len(result) != len(set(result)) or not set(result).issubset(allowed):
            raise AiOutputValidationError(f"{field} contains an unavailable or duplicate node.")
        return result

    @staticmethod
    def _strings(value, field):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise AiOutputValidationError(f"{field} must be a string array.")
        return [sanitize_ai_markdown(item) for item in value]

    @staticmethod
    def _confidence(value):
        if isinstance(value, bool):
            raise AiOutputValidationError("confidence must be between 0 and 1.")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AiOutputValidationError("confidence must be between 0 and 1.") from exc
        if not result.is_finite() or result < 0 or result > 1:
            raise AiOutputValidationError("confidence must be between 0 and 1.")
        return result.quantize(Decimal("0.0001"))


class PrdApplyService:
    @transaction.atomic
    def apply(
        self,
        *,
        canvas: BrainstormCanvas,
        access: PrdAccess,
        job: AiJob,
        actor_user_id: int,
        approved_questions: Any,
        node_versions: Any,
        idempotency_key: str,
    ):
        self._enforce(access)
        key = self._key(idempotency_key)
        existing = AiPrdApplyRecord.objects.filter(
            prd=canvas.prd, actor_user_id=actor_user_id, idempotency_key=key
        ).first()
        if existing:
            if existing.preview_job_id != job.pk:
                raise ValidationError({"idempotency_key": "다른 미리보기에 사용된 요청 키입니다."})
            return existing, False
        job = AiJob.objects.select_for_update().select_related("prompt").get(pk=job.pk)
        if (
            job.prd_id != canvas.prd_id
            or job.user_id != actor_user_id
            or job.feature_type != AiFeatureType.BRAINSTORM_PRD_APPLY
            or job.status != AiJobStatus.SUCCEEDED
            or job.input_data.get("kind") != "brainstorm_prd_apply"
        ):
            raise ValidationError({"preview_request_id": "반영할 수 있는 미리보기가 아닙니다."})
        previous_preview_application = AiPrdApplyRecord.objects.filter(preview_job=job).first()
        if previous_preview_application:
            raise ValidationError({"preview_request_id": "이미 반영된 미리보기입니다."})
        approvals = self._approvals(approved_questions)
        supplied_nodes = self._node_versions(node_versions)
        snapshot_nodes = {row["id"]: row for row in job.input_data.get("nodes", [])}
        if supplied_nodes != {node_id: row["version"] for node_id, row in snapshot_nodes.items()}:
            raise ValidationError({"node_versions": "미리보기의 전체 메모 버전이 필요합니다."})
        output_answers = {
            row["question_id"]: row for row in (job.output_data or {}).get("answers", [])
        }
        if not set(approvals).issubset(output_answers):
            raise ValidationError({"approved_questions": "미리보기 질문과 일치하지 않습니다."})

        canvas = BrainstormCanvas.objects.select_for_update().get(pk=canvas.pk)
        nodes = list(
            BrainstormNode.objects.select_for_update()
            .filter(canvas=canvas, pk__in=supplied_nodes)
            .order_by("id")
        )
        nodes_by_id = {str(node.pk): node for node in nodes}
        questions = list(
            PrdQuestion.objects.select_for_update()
            .filter(section__prd=canvas.prd, pk__in=approvals)
            .select_related("section")
            .order_by("id")
        )
        questions_by_id = {question.pk: question for question in questions}
        conflict_nodes = []
        for node_id, snapshot in snapshot_nodes.items():
            node = nodes_by_id.get(node_id)
            if (
                node is None
                or node.is_deleted
                or node.node_type != BrainstormNodeType.NOTE
                or node.status == BrainstormNodeStatus.HELD
                or node.status != snapshot["status"]
                or node.section_id != snapshot["section_id"]
                or node.version != snapshot["version"]
            ):
                if node is not None:
                    conflict_nodes.append(node)
                else:
                    raise ValidationError(
                        {"node_versions": "미리보기 메모가 더 이상 존재하지 않습니다."}
                    )
        conflict_questions = []
        input_questions = {row["id"]: row for row in job.input_data.get("questions", [])}
        for question_id, requested_version in approvals.items():
            question = questions_by_id.get(question_id)
            snapshot = input_questions.get(question_id)
            current_answer = (
                PrdApplyInputBuilder._answer_text(question) if question is not None else ""
            )
            if (
                question is None
                or question.is_deleted
                or question.section.is_deleted
                or snapshot is None
                or requested_version != snapshot["version"]
                or question.version != snapshot["version"]
                or question.prompt != snapshot["prompt"]
                or question.section_id != snapshot["section_id"]
                or current_answer != snapshot["current_answer"]
            ):
                if question is not None:
                    conflict_questions.append(question)
                else:
                    raise ValidationError(
                        {"approved_questions": "미리보기 질문이 더 이상 존재하지 않습니다."}
                    )
        if conflict_nodes or conflict_questions:
            raise PrdApplyConflict(conflict_nodes, conflict_questions)

        usage = (
            AiUsageLog.objects.filter(job=job, status=AiUsageStatus.SUCCESS)
            .order_by("-created_at", "-id")
            .first()
        )
        record = AiPrdApplyRecord.objects.create(
            prd=canvas.prd,
            canvas=canvas,
            preview_job=job,
            section_id=job.input_data.get("section_id"),
            scope=job.input_data["scope"],
            actor_user_id=actor_user_id,
            idempotency_key=key,
            model=usage.model if usage else job.prompt.model,
            prompt_version=job.prompt.version,
            unused_node_ids=(job.output_data or {}).get("unused_node_ids", []),
            warnings=(job.output_data or {}).get("warnings", []),
        )
        history_before = []
        history_after = []
        for question_id, question_version in approvals.items():
            question = questions_by_id[question_id]
            preview = output_answers[question_id]
            try:
                answer = question.answer
                existing_answer = answer.content
            except PrdAnswer.DoesNotExist:
                answer = None
                existing_answer = ""
            if existing_answer != preview["existing_answer"]:
                raise PrdApplyConflict([], [question])
            integrated = preview["draft"]
            answer, _ = PrdAnswer.objects.update_or_create(
                question=question,
                defaults={"content": integrated, "updated_by_user_id": actor_user_id},
            )
            question.version += 1
            question.is_completed = bool(integrated.strip())
            question.save(update_fields=["version", "is_completed", "updated_at"])
            source_nodes = [
                {"node_id": node_id, "version": snapshot_nodes[node_id]["version"]}
                for node_id in preview["source_node_ids"]
            ]
            AiPrdApplyItem.objects.create(
                record=record,
                question=question,
                question_version_before=question_version,
                question_prompt=question.prompt,
                existing_answer=existing_answer,
                integrated_answer=answer.content,
                source_nodes=source_nodes,
                preserved_existing_points=preview["preserved_existing_points"],
                added_points=preview["added_points"],
                confidence=Decimal(preview["confidence"]),
            )
            history_before.append(
                {"question_id": question_id, "version": question_version, "answer": existing_answer}
            )
            history_after.append(
                {
                    "question_id": question_id,
                    "version": question.version,
                    "answer": answer.content,
                    "source_nodes": source_nodes,
                }
            )
        now = timezone.now()
        Prd.objects.filter(pk=canvas.prd_id).update(
            version=F("version") + 1,
            updated_at=now,
        )
        PrdChangeHistory.objects.create(
            prd=canvas.prd,
            actor_user_id=actor_user_id,
            event_type="brainstorm_ai_prd_applied",
            before_data={"questions": history_before},
            after_data={"questions": history_after, "record_id": str(record.pk)},
        )
        operation_id = uuid.uuid4()
        BrainstormChangeLog.objects.create(
            canvas=canvas,
            actor_user_id=actor_user_id,
            operation_id=operation_id,
            action="prd_apply_completed",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=str(canvas.pk),
            before_data={"questions": history_before},
            after_data={"questions": history_after, "record_id": str(record.pk)},
        )
        AuditLog.objects.create(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="prd_apply_completed",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=str(canvas.pk),
            reason="ai_prd_apply",
            details={
                "record_id": str(record.pk),
                "preview_request_id": str(job.pk),
                "model": record.model,
                "prompt_version": record.prompt_version,
                "applied_at": now.isoformat(),
            },
        )
        return record, True

    @staticmethod
    def _enforce(access):
        if access.role is None:
            raise PermissionDenied
        role_permission_policy.enforce(
            access.role,
            ParticipantAction.APPLY_AI,
            is_completed=access.prd.status == "completed",
        )

    @staticmethod
    def _key(value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
            raise ValidationError({"idempotency_key": "올바른 Idempotency-Key가 필요합니다."})
        return value.strip()

    @staticmethod
    def _approvals(value):
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(row, dict) for row in value)
        ):
            raise ValidationError({"approved_questions": "승인할 질문이 하나 이상 필요합니다."})
        result = {}
        for row in value:
            question_id = row.get("question_id")
            version = row.get("version")
            if (
                isinstance(question_id, bool)
                or not isinstance(question_id, int)
                or question_id < 1
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version < 1
            ):
                raise ValidationError(
                    {"approved_questions": "질문 ID와 version이 올바르지 않습니다."}
                )
            if question_id in result:
                raise ValidationError({"approved_questions": "질문을 중복 승인할 수 없습니다."})
            result[question_id] = version
        return result

    @staticmethod
    def _node_versions(value):
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(row, dict) for row in value)
        ):
            raise ValidationError({"node_versions": "메모별 version이 필요합니다."})
        result = {}
        for row in value:
            try:
                node_id = str(uuid.UUID(str(row.get("node_id"))))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValidationError({"node_versions": "메모 ID가 올바르지 않습니다."}) from exc
            version = row.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValidationError({"node_versions": "메모 version이 올바르지 않습니다."})
            if node_id in result:
                raise ValidationError({"node_versions": "메모를 중복 제출할 수 없습니다."})
            result[node_id] = version
        return result


def serialize_apply_record(record):
    items = record.items.select_related("question").order_by("question_id")
    return {
        "id": str(record.pk),
        "preview_request_id": str(record.preview_job_id),
        "scope": record.scope,
        "section_id": record.section_id,
        "actor_user_id": record.actor_user_id,
        "model": record.model,
        "prompt_version": record.prompt_version,
        "applied_at": record.created_at.isoformat(),
        "unused_node_ids": record.unused_node_ids,
        "warnings": record.warnings,
        "questions": [
            {
                "question_id": item.question_id,
                "question_version_before": item.question_version_before,
                "question_version_after": item.question.version,
                "question_prompt": item.question_prompt,
                "existing_answer": item.existing_answer,
                "integrated_answer": item.integrated_answer,
                "source_nodes": item.source_nodes,
                "preserved_existing_points": item.preserved_existing_points,
                "added_points": item.added_points,
                "confidence": float(item.confidence),
            }
            for item in items
        ],
    }
