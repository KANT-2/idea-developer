from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from jsonschema import Draft202012Validator, SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from apps.brainstorm.models import BrainstormNode
from apps.prds.models import Prd, PrdQuestion, PrdSection

from .exceptions import (
    AiJobNotCancellable,
    AiJobNotRetryable,
    AiOutputValidationError,
    AiPromptNotConfigured,
    AiReferenceValidationError,
    AiUsageLimitExceeded,
)
from .models import (
    AiActionType,
    AiFeatureType,
    AiJob,
    AiJobStatus,
    AiPrompt,
    AiUsageLog,
    AiUsageStatus,
)
from .providers import AiProviderRequest

FEATURE_ACTIONS = {
    AiFeatureType.BRAINSTORM_ANALYSIS: frozenset({AiActionType.ANALYSIS}),
    AiFeatureType.BRAINSTORM_CLASSIFICATION: frozenset({AiActionType.CLASSIFICATION}),
    AiFeatureType.BRAINSTORM_PRD_APPLY: frozenset({AiActionType.PRD_APPLY}),
    AiFeatureType.CONTRIBUTION_EVALUATION: frozenset({AiActionType.CONTRIBUTION_EVALUATION}),
    AiFeatureType.COACHING: frozenset({AiActionType.CHAT, AiActionType.DRAFT}),
}


class AiPromptService:
    @transaction.atomic
    def create_version(
        self,
        *,
        feature_type,
        system_instructions,
        output_schema,
        model,
        activate=False,
    ) -> AiPrompt:
        if feature_type not in AiFeatureType.values:
            raise ValidationError({"feature_type": "지원하지 않는 AI 기능입니다."})
        if not isinstance(system_instructions, str) or not system_instructions.strip():
            raise ValidationError({"system_instructions": "시스템 지시가 필요합니다."})
        if not isinstance(model, str) or not model.strip():
            raise ValidationError({"model": "모델 이름이 필요합니다."})
        if not isinstance(output_schema, dict):
            raise ValidationError({"output_schema": "JSON Schema 객체가 필요합니다."})
        try:
            Draft202012Validator.check_schema(output_schema)
        except SchemaError as exc:
            raise ValidationError(
                {"output_schema": f"유효하지 않은 JSON Schema: {exc.message}"}
            ) from exc
        latest_version = (
            AiPrompt.objects.select_for_update()
            .filter(feature_type=feature_type)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
            or 0
        )
        if activate:
            AiPrompt.objects.filter(feature_type=feature_type, is_active=True).update(
                is_active=False
            )
        return AiPrompt.objects.create(
            feature_type=feature_type,
            version=latest_version + 1,
            system_instructions=system_instructions.strip(),
            output_schema=output_schema,
            model=model.strip(),
            is_active=activate,
        )

    @transaction.atomic
    def activate(self, prompt: AiPrompt) -> AiPrompt:
        AiPrompt.objects.select_for_update().filter(
            feature_type=prompt.feature_type,
            is_active=True,
        ).exclude(pk=prompt.pk).update(is_active=False)
        prompt.is_active = True
        prompt.save(update_fields=["is_active", "updated_at"])
        return prompt


class AiPromptEnvelopeBuilder:
    """Keeps trusted instructions and untrusted user/domain data in separate channels."""

    @staticmethod
    def build(*, prompt: AiPrompt, user_data: dict[str, Any]) -> AiProviderRequest:
        if not isinstance(user_data, dict):
            raise ValidationError({"input_data": "AI 입력 데이터는 JSON 객체여야 합니다."})
        try:
            json.dumps(user_data, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"input_data": "JSON으로 직렬화할 수 없는 값입니다."}) from exc
        return AiProviderRequest(
            model=prompt.model,
            system_instructions=prompt.system_instructions,
            user_data={"untrusted_user_data": user_data},
            output_schema=prompt.output_schema,
        )


class AiStructuredOutputValidator:
    @staticmethod
    def validate(*, schema: dict[str, Any], output: Any) -> dict[str, Any]:
        try:
            Draft202012Validator(schema).validate(output)
        except JsonSchemaValidationError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "$"
            raise AiOutputValidationError(f"AI output failed JSON Schema at {path}.") from exc
        if not isinstance(output, dict):
            raise AiOutputValidationError("AI output must be a JSON object.")
        return output


class AiReferenceValidator:
    NODE_SINGLE_KEYS = frozenset({"node_id"})
    NODE_LIST_KEYS = frozenset({"node_ids", "source_node_ids", "unused_node_ids"})
    SECTION_SINGLE_KEYS = frozenset({"section_id"})
    SECTION_LIST_KEYS = frozenset({"section_ids"})
    QUESTION_SINGLE_KEYS = frozenset({"question_id"})
    QUESTION_LIST_KEYS = frozenset({"question_ids"})

    def validate(self, *, prd: Prd, output: dict[str, Any]) -> dict[str, Any]:
        collected = {"node": set(), "section": set(), "question": set()}
        self._collect(output, collected)
        valid_nodes = {
            str(value)
            for value in BrainstormNode.objects.filter(
                canvas__prd=prd,
                pk__in=collected["node"],
                is_deleted=False,
            ).values_list("pk", flat=True)
        }
        valid_sections = {
            value
            for value in PrdSection.objects.filter(
                prd=prd,
                pk__in=collected["section"],
                is_deleted=False,
            ).values_list("pk", flat=True)
        }
        valid_questions = {
            value
            for value in PrdQuestion.objects.filter(
                section__prd=prd,
                pk__in=collected["question"],
                is_deleted=False,
                section__is_deleted=False,
            ).values_list("pk", flat=True)
        }
        invalid = {
            "node_ids": sorted(collected["node"] - valid_nodes),
            "section_ids": sorted(collected["section"] - valid_sections),
            "question_ids": sorted(collected["question"] - valid_questions),
        }
        invalid = {key: values for key, values in invalid.items() if values}
        if invalid:
            raise AiReferenceValidationError(
                "AI output referenced identifiers outside the current PRD: "
                + json.dumps(invalid, ensure_ascii=False)
            )
        return output

    def _collect(self, value, collected):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in self.NODE_SINGLE_KEYS:
                    if item is not None:
                        collected["node"].add(str(item))
                elif key in self.NODE_LIST_KEYS:
                    self._collect_id_list(item, collected["node"], stringify=True)
                elif key in self.SECTION_SINGLE_KEYS:
                    if item is not None:
                        collected["section"].add(self._positive_int(item, key))
                elif key in self.SECTION_LIST_KEYS:
                    self._collect_id_list(item, collected["section"], stringify=False)
                elif key in self.QUESTION_SINGLE_KEYS:
                    if item is not None:
                        collected["question"].add(self._positive_int(item, key))
                elif key in self.QUESTION_LIST_KEYS:
                    self._collect_id_list(item, collected["question"], stringify=False)
                self._collect(item, collected)
        elif isinstance(value, list):
            for item in value:
                self._collect(item, collected)

    def _collect_id_list(self, value, target, *, stringify):
        if not isinstance(value, list):
            raise AiReferenceValidationError("AI identifier collection must be an array.")
        for item in value:
            target.add(str(item) if stringify else self._positive_int(item, "identifier"))

    @staticmethod
    def _positive_int(value, key):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise AiReferenceValidationError(f"AI output {key} must be a positive integer.")
        return value


class AiUsageLimiter:
    def enforce(self, *, user_id: int, feature_type: str) -> None:
        window_start = timezone.now() - timedelta(days=1)
        job_count = AiJob.objects.filter(
            user_id=user_id,
            feature_type=feature_type,
            created_at__gte=window_start,
        ).count()
        totals = AiUsageLog.objects.filter(
            user_id=user_id,
            feature_type=feature_type,
            created_at__gte=window_start,
        ).aggregate(tokens=Sum("total_tokens"), cost=Sum("cost_usd"))
        if job_count >= settings.AI_DAILY_REQUEST_LIMIT:
            raise AiUsageLimitExceeded("Daily AI request limit exceeded.")
        if (totals["tokens"] or 0) >= settings.AI_DAILY_TOKEN_LIMIT:
            raise AiUsageLimitExceeded("Daily AI token limit exceeded.")
        if (totals["cost"] or Decimal("0")) >= settings.AI_DAILY_COST_LIMIT_USD:
            raise AiUsageLimitExceeded("Daily AI cost limit exceeded.")


class AiJobService:
    def __init__(self, limiter: AiUsageLimiter | None = None):
        self.limiter = limiter or AiUsageLimiter()

    @transaction.atomic
    def enqueue(
        self,
        *,
        prd: Prd,
        user_id: int,
        feature_type: str,
        action_type: str,
        input_data: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[AiJob, bool]:
        self._validate_request(
            user_id=user_id,
            feature_type=feature_type,
            action_type=action_type,
            input_data=input_data,
            idempotency_key=idempotency_key,
        )
        existing = AiJob.objects.filter(
            user_id=user_id,
            prd=prd,
            feature_type=feature_type,
            idempotency_key=idempotency_key.strip(),
        ).first()
        if existing:
            return existing, False
        self.limiter.enforce(user_id=user_id, feature_type=feature_type)
        try:
            prompt = AiPrompt.objects.get(feature_type=feature_type, is_active=True)
        except AiPrompt.DoesNotExist as exc:
            raise AiPromptNotConfigured(f"No active prompt for {feature_type}.") from exc
        try:
            with transaction.atomic():
                job = AiJob.objects.create(
                    prd=prd,
                    prompt=prompt,
                    user_id=user_id,
                    feature_type=feature_type,
                    action_type=action_type,
                    idempotency_key=idempotency_key.strip(),
                    input_data=input_data,
                    max_attempts=settings.AI_JOB_MAX_ATTEMPTS,
                    timeout_seconds=settings.AI_JOB_TIMEOUT_SECONDS,
                )
        except IntegrityError:
            job = AiJob.objects.get(
                user_id=user_id,
                prd=prd,
                feature_type=feature_type,
                idempotency_key=idempotency_key.strip(),
            )
            return job, False
        return job, True

    @transaction.atomic
    def cancel(self, *, job_id, user_id: int) -> AiJob:
        job = AiJob.objects.select_for_update().select_related("prompt").get(pk=job_id)
        if job.user_id != user_id:
            raise AiJobNotCancellable("Only the requesting user can cancel this AI job.")
        if job.status in {
            AiJobStatus.SUCCEEDED,
            AiJobStatus.FAILED,
            AiJobStatus.CANCELLED,
            AiJobStatus.TIMED_OUT,
        }:
            raise AiJobNotCancellable("The AI job is already finished.")
        now = timezone.now()
        job.cancel_requested_at = now
        if job.status in {AiJobStatus.QUEUED, AiJobStatus.RETRY_WAIT}:
            job.status = AiJobStatus.CANCELLED
            job.finished_at = now
            self._usage_log(job=job, status=AiUsageStatus.CANCELLED, error_code="cancelled")
        else:
            job.status = AiJobStatus.CANCEL_REQUESTED
        job.save(update_fields=["status", "cancel_requested_at", "finished_at", "updated_at"])
        return job

    @transaction.atomic
    def retry(self, *, job_id, user_id: int) -> AiJob:
        job = AiJob.objects.select_for_update().get(pk=job_id)
        if job.user_id != user_id or job.status not in {
            AiJobStatus.FAILED,
            AiJobStatus.TIMED_OUT,
        }:
            raise AiJobNotRetryable("This AI job cannot be retried.")
        self.limiter.enforce(user_id=user_id, feature_type=job.feature_type)
        job.status = AiJobStatus.QUEUED
        job.attempt_count = 0
        job.available_at = timezone.now()
        job.started_at = None
        job.finished_at = None
        job.cancel_requested_at = None
        job.locked_by = ""
        job.lease_expires_at = None
        job.error_code = ""
        job.error_message = ""
        job.save()
        return job

    @staticmethod
    def _usage_log(*, job, status, error_code="", error_message=""):
        return AiUsageLog.objects.create(
            job=job,
            prd=job.prd,
            user_id=job.user_id,
            feature_type=job.feature_type,
            action_type=job.action_type,
            status=status,
            model=job.prompt.model,
            prompt_version=job.prompt.version,
            attempt_number=max(1, job.attempt_count),
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _validate_request(**values):
        errors = {}
        feature_type = values["feature_type"]
        action_type = values["action_type"]
        if values["user_id"] < 1:
            errors["user_id"] = "user_id는 양수여야 합니다."
        if feature_type not in AiFeatureType.values:
            errors["feature_type"] = "지원하지 않는 AI 기능입니다."
        elif action_type not in FEATURE_ACTIONS[feature_type]:
            errors["action_type"] = "AI 기능과 action_type 조합이 올바르지 않습니다."
        if not isinstance(values["input_data"], dict):
            errors["input_data"] = "AI 입력 데이터는 JSON 객체여야 합니다."
        key = values["idempotency_key"]
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > 128:
            errors["idempotency_key"] = "올바른 idempotency key가 필요합니다."
        if errors:
            raise ValidationError(errors)
