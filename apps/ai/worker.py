from __future__ import annotations

import logging
import os
import socket
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from .exceptions import (
    AiOutputValidationError,
    AiProviderError,
    AiProviderTimeout,
)
from .models import AiJob, AiJobStatus, AiUsageLog, AiUsageStatus
from .services import (
    AiPromptEnvelopeBuilder,
    AiReferenceValidator,
    AiStructuredOutputValidator,
)

logger = logging.getLogger(__name__)


class AiJobRunner:
    """Claims one PostgreSQL-backed AI job and executes it outside the web process."""

    def __init__(self, provider=None, worker_id: str | None = None):
        provider_class = import_string(settings.AI_PROVIDER_CLASS)
        self.provider = provider or provider_class()
        self.result_processor = import_string(settings.AI_RESULT_PROCESSOR_CLASS)()
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"

    def run_once(self) -> bool:
        from .coaching import delete_expired_conversations

        delete_expired_conversations()
        if self._recover_one_expired_job():
            return True
        job = self._claim_one()
        if job is None:
            return False
        self._execute(job)
        return True

    @transaction.atomic
    def _claim_one(self) -> AiJob | None:
        now = timezone.now()
        job = (
            AiJob.objects.select_for_update(skip_locked=True)
            .select_related("prompt", "prd")
            .filter(
                status__in=[AiJobStatus.QUEUED, AiJobStatus.RETRY_WAIT],
                available_at__lte=now,
            )
            .order_by("available_at", "created_at", "id")
            .first()
        )
        if job is None:
            return None
        job.status = AiJobStatus.RUNNING
        job.attempt_count += 1
        job.started_at = now
        job.finished_at = None
        job.locked_by = self.worker_id
        job.lease_expires_at = now + timedelta(seconds=job.timeout_seconds)
        job.error_code = ""
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "attempt_count",
                "started_at",
                "finished_at",
                "locked_by",
                "lease_expires_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
        return job

    def _execute(self, job: AiJob) -> None:
        try:
            request = AiPromptEnvelopeBuilder.build(
                prompt=job.prompt,
                user_data=job.input_data,
            )
            result = self.provider.generate(
                request,
                timeout_seconds=job.timeout_seconds,
                cancellation_check=lambda: self._cancel_requested(job.pk),
            )
            output = AiStructuredOutputValidator.validate(
                schema=job.prompt.output_schema,
                output=result.output,
            )
            AiReferenceValidator().validate(prd=job.prd, output=output)
            self._finish_success(job.pk, result=result, output=output)
        except AiProviderTimeout:
            self._finish_failure(
                job.pk,
                error_code="timeout",
                error_message="AI provider timed out.",
                retryable=True,
                timed_out=True,
            )
        except AiProviderError as exc:
            self._finish_failure(
                job.pk,
                error_code=exc.code,
                error_message="AI provider request failed.",
                retryable=exc.retryable,
            )
        except AiOutputValidationError:
            self._finish_failure(
                job.pk,
                error_code="invalid_output",
                error_message="AI output failed server validation.",
                retryable=False,
            )
        except Exception:
            logger.exception("Unexpected AI job failure", extra={"ai_job_id": str(job.pk)})
            self._finish_failure(
                job.pk,
                error_code="internal_error",
                error_message="Unexpected AI worker error.",
                retryable=True,
            )

    @staticmethod
    def _cancel_requested(job_id) -> bool:
        return AiJob.objects.filter(
            pk=job_id,
            status=AiJobStatus.CANCEL_REQUESTED,
        ).exists()

    @transaction.atomic
    def _finish_success(self, job_id, *, result, output) -> None:
        job = AiJob.objects.select_for_update().select_related("prompt", "prd").get(pk=job_id)
        if job.status == AiJobStatus.CANCEL_REQUESTED:
            self._mark_cancelled(job)
            return
        if job.status != AiJobStatus.RUNNING:
            return
        output = self.result_processor.process(job=job, output=output)
        now = timezone.now()
        job.status = AiJobStatus.SUCCEEDED
        job.output_data = output
        job.finished_at = now
        job.lease_expires_at = None
        job.locked_by = ""
        job.save(
            update_fields=[
                "status",
                "output_data",
                "finished_at",
                "lease_expires_at",
                "locked_by",
                "updated_at",
            ]
        )
        input_tokens = max(0, int(result.input_tokens))
        output_tokens = max(0, int(result.output_tokens))
        self._create_usage(
            job,
            status=AiUsageStatus.SUCCESS,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=max(0, result.cost_usd),
            model=result.model or job.prompt.model,
        )
        from .contribution import update_contribution_model

        update_contribution_model(job, result.model or job.prompt.model)

    @transaction.atomic
    def _finish_failure(
        self,
        job_id,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        timed_out: bool = False,
    ) -> None:
        job = AiJob.objects.select_for_update().select_related("prompt", "prd").get(pk=job_id)
        if job.status == AiJobStatus.CANCEL_REQUESTED:
            self._mark_cancelled(job)
            return
        if job.status != AiJobStatus.RUNNING:
            return
        logger.warning(
            "AI job attempt failed",
            extra={
                "ai_job_id": str(job.pk),
                "ai_error_code": error_code,
                "ai_attempt_number": job.attempt_count,
                "ai_retryable": retryable,
            },
        )
        self._create_usage(
            job,
            status=AiUsageStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )
        job.error_code = error_code
        job.error_message = error_message
        job.locked_by = ""
        job.lease_expires_at = None
        if retryable and job.attempt_count < job.max_attempts:
            delay = settings.AI_JOB_RETRY_BASE_SECONDS * (2 ** (job.attempt_count - 1))
            job.status = AiJobStatus.RETRY_WAIT
            job.available_at = timezone.now() + timedelta(seconds=delay)
        else:
            job.status = AiJobStatus.TIMED_OUT if timed_out else AiJobStatus.FAILED
            job.finished_at = timezone.now()
        job.save()
        if job.status in {AiJobStatus.FAILED, AiJobStatus.TIMED_OUT}:
            from .contribution import mark_contribution_job_failed

            mark_contribution_job_failed(job)

    @transaction.atomic
    def _recover_one_expired_job(self) -> bool:
        now = timezone.now()
        job = (
            AiJob.objects.select_for_update(skip_locked=True)
            .select_related("prompt", "prd")
            .filter(
                status__in=[AiJobStatus.RUNNING, AiJobStatus.CANCEL_REQUESTED],
                lease_expires_at__lte=now,
            )
            .order_by("lease_expires_at", "id")
            .first()
        )
        if job is None:
            return False
        if job.status == AiJobStatus.CANCEL_REQUESTED:
            self._mark_cancelled(job)
            return True
        self._create_usage(
            job,
            status=AiUsageStatus.FAILED,
            error_code="worker_lease_expired",
            error_message="AI worker lease expired.",
        )
        job.error_code = "worker_lease_expired"
        job.error_message = "AI worker lease expired."
        job.locked_by = ""
        job.lease_expires_at = None
        if job.attempt_count < job.max_attempts:
            job.status = AiJobStatus.RETRY_WAIT
            job.available_at = now
        else:
            job.status = AiJobStatus.TIMED_OUT
            job.finished_at = now
        job.save()
        if job.status == AiJobStatus.TIMED_OUT:
            from .contribution import mark_contribution_job_failed

            mark_contribution_job_failed(job)
        return True

    def _mark_cancelled(self, job: AiJob) -> None:
        job.status = AiJobStatus.CANCELLED
        job.finished_at = timezone.now()
        job.locked_by = ""
        job.lease_expires_at = None
        job.save(
            update_fields=[
                "status",
                "finished_at",
                "locked_by",
                "lease_expires_at",
                "updated_at",
            ]
        )
        self._create_usage(
            job,
            status=AiUsageStatus.CANCELLED,
            error_code="cancelled",
            error_message="AI job was cancelled.",
        )
        from .contribution import mark_contribution_job_failed

        mark_contribution_job_failed(job)

    @staticmethod
    def _create_usage(
        job,
        *,
        status,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost_usd=0,
        model=None,
        error_code="",
        error_message="",
    ):
        return AiUsageLog.objects.create(
            job=job,
            prd=job.prd,
            user_id=job.user_id,
            feature_type=job.feature_type,
            action_type=job.action_type,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            model=model or job.prompt.model,
            prompt_version=job.prompt.version,
            attempt_number=max(1, job.attempt_count),
            error_code=error_code,
            error_message=error_message,
        )
