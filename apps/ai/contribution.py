from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.brainstorm.models import (
    BrainstormChangeLog,
    BrainstormChangeTarget,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.exceptions import IntegrationError
from apps.prds.detail import PrdAccess
from apps.prds.models import (
    Prd,
    PrdComment,
    PrdCommentType,
    PrdContributionStatus,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdStatus,
    PrdStatusAuditAction,
    PrdStatusAuditLog,
)

from .coaching import sanitize_ai_markdown
from .exceptions import AiOutputValidationError, AiPromptNotConfigured, AiUsageLimitExceeded
from .models import (
    AiActionType,
    AiFeatureType,
    AiJob,
    ContributionCommentScore,
    ContributionEvaluation,
    ContributionEvaluationStatus,
    ContributionUserScore,
)
from .services import AiJobService

SCORE_QUANTUM = Decimal("0.0001")
logger = logging.getLogger(__name__)


class ContributionEvaluationService:
    """Creates an immutable completion snapshot and its versioned score result."""

    def schedule_for_completion(
        self,
        *,
        prd_id: int,
        completion_audit_id: int,
        actor_user_id: int,
        repository=None,
    ) -> ContributionEvaluation:
        from apps.prds.views import get_integration_repository

        existing = ContributionEvaluation.objects.filter(
            completion_audit_id=completion_audit_id
        ).first()
        if existing:
            return existing
        repository = repository or get_integration_repository()
        try:
            snapshot = self._build_snapshot(prd_id=prd_id, repository=repository)
            evaluation = self._create_evaluation(
                prd_id=prd_id,
                completion_audit_id=completion_audit_id,
                snapshot=snapshot,
            )
            if not snapshot["comments"]:
                return ContributionResultProcessor().persist(
                    evaluation=evaluation,
                    output={"comments": []},
                )
            job, _ = AiJobService().enqueue(
                prd=evaluation.prd,
                user_id=actor_user_id,
                feature_type=AiFeatureType.CONTRIBUTION_EVALUATION,
                action_type=AiActionType.CONTRIBUTION_EVALUATION,
                input_data={
                    **snapshot,
                    "kind": "contribution_evaluation",
                    "evaluation_id": evaluation.pk,
                },
                idempotency_key=f"contribution-evaluation-{evaluation.pk}",
            )
            evaluation.job = job
            evaluation.model = job.prompt.model
            evaluation.prompt_version = job.prompt.version
            evaluation.save(update_fields=["job", "model", "prompt_version"])
            return evaluation
        except (
            IntegrationError,
            AiPromptNotConfigured,
            AiUsageLimitExceeded,
            ValidationError,
        ) as exc:
            return self._record_scheduling_failure(
                prd_id=prd_id,
                completion_audit_id=completion_audit_id,
                error=exc,
            )
        except Exception as exc:
            logger.exception(
                "Contribution evaluation scheduling failed",
                extra={"prd_id": prd_id, "completion_audit_id": completion_audit_id},
            )
            return self._record_scheduling_failure(
                prd_id=prd_id,
                completion_audit_id=completion_audit_id,
                error=exc,
            )

    @transaction.atomic
    def retry_same_input(self, *, evaluation: ContributionEvaluation, access: PrdAccess):
        if not access.is_admin:
            raise PermissionDenied("Only an administrator can retry contribution evaluation.")
        # ``job`` is nullable. PostgreSQL cannot lock the nullable side of the
        # OUTER JOIN produced by select_related("job"). Lock only the
        # evaluation row and fetch related rows normally when accessed below.
        evaluation = ContributionEvaluation.objects.select_for_update().get(pk=evaluation.pk)
        if evaluation.status != ContributionEvaluationStatus.FAILED:
            raise ValidationError({"evaluation": "실패한 기여도 계산만 재평가할 수 있습니다."})
        if not {"participants", "comments", "prd", "accepted_memos"}.issubset(
            evaluation.input_snapshot
        ):
            raise ValidationError(
                {"evaluation": "완료 시점 입력 스냅샷이 없어 동일 입력 재평가가 불가능합니다."}
            )
        if evaluation.job_id:
            job = AiJobService().retry(
                job_id=evaluation.job_id,
                user_id=evaluation.job.user_id,
            )
        else:
            job, _ = AiJobService().enqueue(
                prd=evaluation.prd,
                user_id=evaluation.completion_audit.actor_user_id,
                feature_type=AiFeatureType.CONTRIBUTION_EVALUATION,
                action_type=AiActionType.CONTRIBUTION_EVALUATION,
                input_data={
                    **evaluation.input_snapshot,
                    "kind": "contribution_evaluation",
                    "evaluation_id": evaluation.pk,
                },
                idempotency_key=f"contribution-evaluation-{evaluation.pk}",
            )
            evaluation.job = job
            evaluation.model = job.prompt.model
            evaluation.prompt_version = job.prompt.version
        evaluation.status = ContributionEvaluationStatus.PENDING
        evaluation.failure_code = ""
        evaluation.failure_message = ""
        evaluation.calculated_at = None
        evaluation.save()
        self._sync_current_prd_status(evaluation, PrdContributionStatus.PENDING)
        return evaluation

    def _build_snapshot(self, *, prd_id, repository):
        prd = Prd.objects.get(pk=prd_id)
        participants = list(PrdParticipant.objects.filter(prd=prd).order_by("user_id"))
        memberships = repository.get_eligible_memberships(
            user_ids=tuple(row.user_id for row in participants),
            round_id=prd.round_id,
        )
        membership_by_user = {row.user_id: row for row in memberships}
        participant_user_ids = {row.user_id for row in participants}
        eligible_user_ids = set(membership_by_user)
        self._restore_removed_assignees(
            prd=prd,
            participant_user_ids=participant_user_ids,
        )

        accepted_candidates = list(
            BrainstormNode.objects.filter(
                canvas__prd=prd,
                node_type=BrainstormNodeType.NOTE,
                status=BrainstormNodeStatus.ACCEPTED,
                is_deleted=False,
                assignee_id__in=eligible_user_ids,
            )
            .select_related("canvas")
            .order_by("-canvas__version_number", "-updated_at", "id")
        )
        # A new board version clones the preceding board. Count the same idea
        # lineage once, using its newest accepted representation and final
        # assignee, while retaining accepted ideas that exist only in an older
        # version.
        nodes_by_lineage = {}
        for node in accepted_candidates:
            nodes_by_lineage.setdefault(node.lineage_id, node)
        nodes = sorted(nodes_by_lineage.values(), key=lambda row: str(row.pk))
        contributors_by_lineage = self._memo_contributors(
            prd=prd,
            nodes=nodes,
            eligible_user_ids=eligible_user_ids,
        )
        comments = list(
            PrdComment.objects.filter(
                prd=prd,
                is_deleted=False,
                is_contribution_eligible=True,
                comment_type=PrdCommentType.GENERAL,
                author_role_at_created__in=[
                    PrdParticipantRole.OWNER,
                    PrdParticipantRole.EDITOR,
                ],
                author_user_id__in=eligible_user_ids,
            )
            .select_related("section_question__section")
            .order_by("id")
        )
        questions = list(
            PrdQuestion.objects.filter(
                section__prd=prd,
                section__is_deleted=False,
                is_deleted=False,
                is_held=False,
            )
            .select_related("section", "answer")
            .order_by("section__position", "position", "id")
        )
        snapshot = {
            "prd": {
                "id": prd.pk,
                "version": prd.version,
                "round_id": prd.round_id,
                "title": prd.title,
                "description": prd.description,
                "type": prd.prd_type,
                "sections": self._serialize_questions(questions),
            },
            "participants": [
                {
                    "user_id": user_id,
                    "participant_id": membership_by_user[user_id].participant_id,
                }
                for user_id in sorted(eligible_user_ids)
            ],
            "accepted_memos": [
                {
                    "node_id": str(node.pk),
                    "lineage_id": str(node.lineage_id),
                    "canvas_version": node.canvas.version_number,
                    "version": node.version,
                    "assignee_id": node.assignee_id,
                    "contributor_user_ids": contributors_by_lineage[node.lineage_id],
                }
                for node in nodes
            ],
            "comments": [self._serialize_comment(comment) for comment in comments],
        }
        self._enforce_snapshot_limits(snapshot)
        return snapshot

    @classmethod
    def _memo_contributors(cls, *, prd, nodes, eligible_user_ids):
        """Return each accepted idea's creator and meaningful content editors.

        Canvas cloning, assignment, section/status, colour, and position changes
        do not create contribution credit. A user receives at most one credit for
        a lineage, regardless of how many board versions they edit.
        """
        if not nodes:
            return {}
        lineage_ids = {node.lineage_id for node in nodes}
        lineage_nodes = list(
            BrainstormNode.objects.filter(
                canvas__prd=prd,
                lineage_id__in=lineage_ids,
                node_type=BrainstormNodeType.NOTE,
            ).values("id", "lineage_id")
        )
        lineage_by_target_id = {str(row["id"]): row["lineage_id"] for row in lineage_nodes}
        contributors = {lineage_id: set() for lineage_id in lineage_ids}
        for node in nodes:
            if node.author_id in eligible_user_ids:
                contributors[node.lineage_id].add(node.author_id)

        content_changes = BrainstormChangeLog.objects.filter(
            canvas__prd=prd,
            action="node_content_updated",
            target_type=BrainstormChangeTarget.NODE,
            target_id__in=lineage_by_target_id,
            actor_user_id__in=eligible_user_ids,
        ).order_by("created_at", "id")
        for change in content_changes:
            before = change.before_data.get("content")
            after = change.after_data.get("content")
            if not isinstance(before, str) or not isinstance(after, str):
                continue
            if cls._normalize_memo_content(before) == cls._normalize_memo_content(after):
                continue
            lineage_id = lineage_by_target_id.get(change.target_id)
            if lineage_id is not None:
                contributors[lineage_id].add(change.actor_user_id)

        return {lineage_id: sorted(user_ids) for lineage_id, user_ids in contributors.items()}

    @staticmethod
    def _normalize_memo_content(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).strip()
        return re.sub(r"\s+", " ", normalized)

    @staticmethod
    def _enforce_snapshot_limits(snapshot):
        if len(snapshot["accepted_memos"]) > settings.AI_BRAINSTORM_MAX_NODES:
            raise ValidationError(
                {
                    "accepted_memos": (
                        f"기여도 평가는 메모 {settings.AI_BRAINSTORM_MAX_NODES}개까지 가능합니다."
                    )
                }
            )
        if len(snapshot["comments"]) > settings.AI_CONTRIBUTION_MAX_COMMENTS:
            raise ValidationError(
                {
                    "comments": (
                        "기여도 평가는 코멘트 "
                        f"{settings.AI_CONTRIBUTION_MAX_COMMENTS}개까지 가능합니다."
                    )
                }
            )
        character_count = len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
        if character_count > settings.AI_CONTRIBUTION_MAX_CHARS:
            raise ValidationError(
                {
                    "input": (
                        f"기여도 평가 입력이 {settings.AI_CONTRIBUTION_MAX_CHARS}자를 초과했습니다."
                    )
                }
            )

    @staticmethod
    def _serialize_questions(questions):
        sections = {}
        for question in questions:
            section = sections.setdefault(
                question.section_id,
                {
                    "section_id": question.section_id,
                    "title": question.section.title,
                    "questions": [],
                },
            )
            try:
                answer = question.answer.content
            except ObjectDoesNotExist:
                answer = ""
            section["questions"].append(
                {
                    "question_id": question.pk,
                    "question": question.prompt,
                    "answer": answer,
                    "version": question.version,
                }
            )
        return list(sections.values())

    @staticmethod
    def _serialize_comment(comment):
        question = comment.section_question
        return {
            "comment_id": comment.pk,
            "author_user_id": comment.author_user_id,
            "content": comment.content,
            "question_id": question.pk if question else None,
            "question": question.prompt if question else None,
            "section_id": question.section_id if question else None,
            "section_title": question.section.title if question else None,
        }

    @staticmethod
    @transaction.atomic
    def _restore_removed_assignees(*, prd, participant_user_ids):
        nodes = BrainstormNode.objects.select_for_update().filter(
            canvas__prd=prd,
            node_type=BrainstormNodeType.NOTE,
            is_deleted=False,
        )
        for node in nodes:
            if node.assignee_id is not None and node.assignee_id not in participant_user_ids:
                BrainstormNode.objects.filter(pk=node.pk).update(
                    assignee_id=node.author_id,
                    version=F("version") + 1,
                    updated_at=timezone.now(),
                )

    @transaction.atomic
    def _create_evaluation(self, *, prd_id, completion_audit_id, snapshot):
        prd = Prd.objects.select_for_update().get(pk=prd_id)
        calculation_version = (
            ContributionEvaluation.objects.filter(prd=prd).aggregate(
                value=Max("calculation_version")
            )["value"]
            or 0
        ) + 1
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evaluation = ContributionEvaluation.objects.create(
            prd=prd,
            completion_audit=PrdStatusAuditLog.objects.get(
                pk=completion_audit_id,
                prd=prd,
                action=PrdStatusAuditAction.COMPLETED,
            ),
            calculation_version=calculation_version,
            prd_version=prd.version,
            input_fingerprint=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            input_snapshot=snapshot,
            target_node_ids=[row["node_id"] for row in snapshot["accepted_memos"]],
            target_comment_ids=[row["comment_id"] for row in snapshot["comments"]],
        )
        prd.contribution_status = PrdContributionStatus.PENDING
        prd.save(update_fields=["contribution_status", "updated_at"])
        return evaluation

    def _record_scheduling_failure(self, *, prd_id, completion_audit_id, error):
        with transaction.atomic():
            try:
                evaluation = ContributionEvaluation.objects.select_for_update().get(
                    completion_audit_id=completion_audit_id
                )
            except ContributionEvaluation.DoesNotExist:
                prd = Prd.objects.select_for_update().get(pk=prd_id)
                version = (
                    ContributionEvaluation.objects.filter(prd=prd).aggregate(
                        value=Max("calculation_version")
                    )["value"]
                    or 0
                ) + 1
                snapshot = {"snapshot_error": type(error).__name__}
                evaluation = ContributionEvaluation.objects.create(
                    prd=prd,
                    completion_audit_id=completion_audit_id,
                    calculation_version=version,
                    prd_version=prd.version,
                    input_fingerprint=hashlib.sha256(
                        json.dumps(snapshot, sort_keys=True).encode()
                    ).hexdigest(),
                    input_snapshot=snapshot,
                )
            evaluation.status = ContributionEvaluationStatus.FAILED
            evaluation.failure_code = type(error).__name__
            evaluation.failure_message = "기여도 계산 작업을 시작하지 못했습니다."
            evaluation.calculated_at = timezone.now()
            evaluation.save()
            self._sync_current_prd_status(evaluation, PrdContributionStatus.FAILED)
            return evaluation

    @staticmethod
    def _sync_current_prd_status(evaluation, status):
        latest_id = (
            ContributionEvaluation.objects.filter(prd=evaluation.prd)
            .order_by("-calculation_version")
            .values_list("id", flat=True)
            .first()
        )
        if latest_id == evaluation.pk and evaluation.prd.status == PrdStatus.COMPLETED:
            Prd.objects.filter(pk=evaluation.prd_id).update(contribution_status=status)


class ContributionResultProcessor:
    def process(self, *, job: AiJob, output: dict) -> dict:
        if job.feature_type != AiFeatureType.CONTRIBUTION_EVALUATION:
            return output
        if job.input_data.get("kind") != "contribution_evaluation":
            raise AiOutputValidationError("Contribution job input is invalid.")
        try:
            evaluation = ContributionEvaluation.objects.get(
                pk=job.input_data.get("evaluation_id"),
                job=job,
            )
        except ContributionEvaluation.DoesNotExist as exc:
            raise AiOutputValidationError("Contribution evaluation no longer exists.") from exc
        self.persist(evaluation=evaluation, output=output)
        return output

    @transaction.atomic
    def persist(self, *, evaluation, output):
        evaluation = (
            ContributionEvaluation.objects.select_for_update()
            .select_related("prd")
            .get(pk=evaluation.pk)
        )
        if evaluation.status == ContributionEvaluationStatus.SUCCEEDED:
            return evaluation
        rows = self._validate_output(evaluation=evaluation, output=output)
        ContributionCommentScore.objects.filter(evaluation=evaluation).delete()
        ContributionUserScore.objects.filter(evaluation=evaluation).delete()

        comment_raw = defaultdict(lambda: Decimal("0"))
        comment_ids = defaultdict(list)
        comment_evidence = defaultdict(list)
        comments_by_id = {
            row["comment_id"]: row for row in evaluation.input_snapshot.get("comments", [])
        }
        for row in rows:
            source = comments_by_id[row["comment_id"]]
            comment_raw[source["author_user_id"]] += row["reflection_score"]
            comment_ids[source["author_user_id"]].append(row["comment_id"])
            comment_evidence[source["author_user_id"]].append(
                {
                    "comment_id": row["comment_id"],
                    "evidence": row["evidence"],
                    "reason": row["reason"],
                }
            )
            ContributionCommentScore.objects.create(
                evaluation=evaluation,
                comment_id=row["comment_id"],
                author_user_id=source["author_user_id"],
                reflection_score=row["reflection_score"],
                matched_question_ids=row["matched_question_ids"],
                evidence=row["evidence"],
                reason=row["reason"],
                confidence=row["confidence"],
            )

        node_ids = defaultdict(list)
        for row in evaluation.input_snapshot.get("accepted_memos", []):
            # Snapshots created before lineage contribution tracking retain the
            # former final-assignee behaviour for safe, repeatable retries.
            contributor_user_ids = row.get("contributor_user_ids")
            if contributor_user_ids is None:
                contributor_user_ids = [row["assignee_id"]]
            for user_id in contributor_user_ids:
                node_ids[user_id].append(row["node_id"])
        user_ids = [row["user_id"] for row in evaluation.input_snapshot.get("participants", [])]
        memo_raw = {user_id: len(node_ids[user_id]) for user_id in user_ids}
        memo_scores = self._normalize(memo_raw, user_ids)
        comment_scores = self._normalize(comment_raw, user_ids)
        participants = {
            row["user_id"]: row for row in evaluation.input_snapshot.get("participants", [])
        }
        for user_id in user_ids:
            total = ((memo_scores[user_id] + comment_scores[user_id]) / Decimal("2")).quantize(
                SCORE_QUANTUM, rounding=ROUND_HALF_UP
            )
            ContributionUserScore.objects.create(
                evaluation=evaluation,
                user_id=user_id,
                participant_id=participants[user_id]["participant_id"],
                memo_raw=memo_raw[user_id],
                memo_contribution=memo_scores[user_id],
                comment_raw=comment_raw[user_id],
                comment_contribution=comment_scores[user_id],
                total_score=total,
                node_ids=node_ids[user_id],
                comment_ids=comment_ids[user_id],
                evidence={"comment_evaluations": comment_evidence[user_id]},
            )
        evaluation.status = ContributionEvaluationStatus.SUCCEEDED
        evaluation.evidence = {
            "formula": "0.5 * comment_contribution + 0.5 * memo_contribution",
            "comment_score_total": str(sum(comment_raw.values(), Decimal("0"))),
        }
        evaluation.failure_code = ""
        evaluation.failure_message = ""
        evaluation.calculated_at = timezone.now()
        evaluation.save()
        ContributionEvaluationService._sync_current_prd_status(
            evaluation, PrdContributionStatus.SUCCEEDED
        )
        return evaluation

    def _validate_output(self, *, evaluation, output):
        if not isinstance(output, dict) or not isinstance(output.get("comments"), list):
            raise AiOutputValidationError("Contribution output comments must be an array.")
        expected = set(evaluation.target_comment_ids)
        question_ids = {
            question["question_id"]
            for section in evaluation.input_snapshot.get("prd", {}).get("sections", [])
            for question in section.get("questions", [])
        }
        normalized = []
        seen = set()
        for row in output["comments"]:
            if not isinstance(row, dict):
                raise AiOutputValidationError("Each contribution comment must be an object.")
            required = {
                "comment_id",
                "reflection_score",
                "matched_question_ids",
                "evidence",
                "reason",
                "confidence",
            }
            if not required.issubset(row):
                raise AiOutputValidationError("Contribution output is missing required fields.")
            comment_id = row["comment_id"]
            if isinstance(comment_id, bool) or not isinstance(comment_id, int):
                raise AiOutputValidationError("comment_id must be an integer.")
            if comment_id in seen or comment_id not in expected:
                raise AiOutputValidationError("Contribution output referenced an invalid comment.")
            seen.add(comment_id)
            matched = row["matched_question_ids"]
            if not isinstance(matched, list) or any(
                isinstance(value, bool) or not isinstance(value, int) for value in matched
            ):
                raise AiOutputValidationError("matched_question_ids must be integers.")
            if len(matched) != len(set(matched)) or not set(matched).issubset(question_ids):
                raise AiOutputValidationError("Contribution output referenced an invalid question.")
            evidence = row["evidence"]
            if not isinstance(evidence, list) or any(
                not isinstance(value, str) for value in evidence
            ):
                raise AiOutputValidationError("evidence must be an array of strings.")
            score = self._decimal(row["reflection_score"], minimum=0, maximum=100)
            confidence = self._decimal(row["confidence"], minimum=0, maximum=1)
            normalized.append(
                {
                    "comment_id": comment_id,
                    "reflection_score": score,
                    "matched_question_ids": matched,
                    "evidence": [sanitize_ai_markdown(value) for value in evidence],
                    "reason": sanitize_ai_markdown(row["reason"]),
                    "confidence": confidence,
                }
            )
        if seen != expected:
            raise AiOutputValidationError("Every eligible comment must be evaluated exactly once.")
        return normalized

    @staticmethod
    def _decimal(value, *, minimum, maximum):
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AiOutputValidationError("Contribution score must be numeric.") from exc
        if not result.is_finite() or result < minimum or result > maximum:
            raise AiOutputValidationError("Contribution score is outside its allowed range.")
        return result.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _normalize(raw_scores, user_ids):
        total = sum((Decimal(raw_scores[user_id]) for user_id in user_ids), Decimal("0"))
        if total <= 0:
            return {user_id: Decimal("0.0000") for user_id in user_ids}
        result = {
            user_id: (Decimal(raw_scores[user_id]) * Decimal("100") / total).quantize(
                SCORE_QUANTUM, rounding=ROUND_HALF_UP
            )
            for user_id in user_ids
        }
        recipient = next(user_id for user_id in reversed(user_ids) if raw_scores[user_id] > 0)
        result[recipient] += Decimal("100.0000") - sum(result.values(), Decimal("0"))
        return result


def mark_contribution_job_failed(job: AiJob) -> None:
    if job.feature_type != AiFeatureType.CONTRIBUTION_EVALUATION:
        return
    try:
        evaluation = ContributionEvaluation.objects.select_related("prd").get(job=job)
    except ContributionEvaluation.DoesNotExist:
        return
    evaluation.status = ContributionEvaluationStatus.FAILED
    evaluation.failure_code = job.error_code or job.status
    evaluation.failure_message = job.error_message or "기여도 AI 평가에 실패했습니다."
    evaluation.calculated_at = timezone.now()
    evaluation.save(update_fields=["status", "failure_code", "failure_message", "calculated_at"])
    ContributionEvaluationService._sync_current_prd_status(evaluation, PrdContributionStatus.FAILED)


def update_contribution_model(job: AiJob, model: str) -> None:
    if job.feature_type == AiFeatureType.CONTRIBUTION_EVALUATION:
        ContributionEvaluation.objects.filter(job=job).update(model=model)
