from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.ai.brainstorm import (
    AiClassificationConflict,
    BrainstormAiRequestService,
    BrainstormClassificationApplyService,
    EmptyBrainstormInput,
)
from apps.ai.exceptions import (
    AiJobNotCancellable,
    AiJobNotRetryable,
    AiPromptNotConfigured,
    AiUsageLimitExceeded,
)
from apps.ai.models import AiJob
from apps.ai.prd_apply import (
    PrdApplyConflict,
    PrdApplyRequestService,
    PrdApplyService,
    serialize_apply_record,
)
from apps.ai.services import AiJobService
from apps.common.responses import api_error, api_success
from apps.integration.exceptions import IntegrationError
from apps.prds.detail import PrdNotFound

from .views import (
    _access,
    _authentication_error,
    _error,
    _latest_cursor,
    _parse_json,
    _request_id,
    _serialize_node,
)


def _enforce_ai(access):
    role_permission_policy.enforce(
        access.role,
        ParticipantAction.REQUEST_AI,
        is_completed=access.prd.status == "completed",
    )


def _ai_error(request, exc):
    if isinstance(exc, PrdApplyConflict):
        return api_error(
            code="version_conflict",
            message="미리보기 이후 메모 또는 PRD 질문이 변경되었습니다.",
            status=409,
            details={
                "latest_nodes": [_serialize_node(node, include_deleted=True) for node in exc.nodes],
                "latest_questions": [
                    {
                        "id": question.pk,
                        "version": question.version,
                        "is_deleted": question.is_deleted,
                    }
                    for question in exc.questions
                ],
            },
            request_id=_request_id(request),
        )
    if isinstance(exc, AiClassificationConflict):
        return api_error(
            code="version_conflict",
            message="분류 미리보기 이후 메모가 변경되었습니다.",
            status=409,
            details={
                "latest_nodes": [
                    _serialize_node(node, include_deleted=True) for node in exc.latest_nodes
                ]
            },
            request_id=_request_id(request),
        )
    if isinstance(exc, AiPromptNotConfigured):
        return api_error(
            code="ai_prompt_not_configured",
            message="AI 기능 설정이 아직 준비되지 않았습니다.",
            status=409,
            request_id=_request_id(request),
        )
    if isinstance(exc, AiUsageLimitExceeded):
        return api_error(
            code="ai_usage_limit_exceeded",
            message="AI 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
            status=429,
            request_id=_request_id(request),
        )
    if isinstance(exc, AiJobNotCancellable | AiJobNotRetryable):
        return api_error(
            code="invalid_job_state",
            message="현재 상태에서는 AI 작업을 변경할 수 없습니다.",
            status=409,
            request_id=_request_id(request),
        )
    return _error(request, exc)


@require_POST
def request_analysis(request, prd_id):
    return _request_feature(request, prd_id, feature="analysis")


@require_POST
def request_classification(request, prd_id):
    return _request_feature(request, prd_id, feature="classification")


@require_POST
def request_prd_apply_preview(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas, _ = _access(request, prd_id, create_canvas=True)
        _enforce_ai(access)
        payload = _parse_json(request)
        job, created = PrdApplyRequestService().request_preview(
            canvas=canvas,
            user_id=context.user_id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            section_id=payload.get("section_id"),
            selected_default_nodes=payload.get("selected_default_nodes"),
        )
        return api_success(
            _serialize_job(job),
            status=202 if created else 200,
            request_id=_request_id(request),
        )
    except EmptyBrainstormInput as exc:
        return api_success({"job": None, "message": exc.message}, request_id=_request_id(request))
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        AiPromptNotConfigured,
        AiUsageLimitExceeded,
    ) as exc:
        return _ai_error(request, exc)


@require_POST
def apply_prd_preview(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas, _ = _access(request, prd_id, create_canvas=True)
        payload = _parse_json(request)
        job = _owned_job(
            access=access,
            user_id=context.user_id,
            job_id=payload.get("preview_request_id"),
        )
        record, applied = PrdApplyService().apply(
            canvas=canvas,
            access=access,
            job=job,
            actor_user_id=context.user_id,
            approved_questions=payload.get("approved_questions"),
            node_versions=payload.get("node_versions"),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return api_success(
            {"applied": applied, "record": serialize_apply_record(record)},
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        PrdApplyConflict,
    ) as exc:
        return _ai_error(request, exc)


def _request_feature(request, prd_id, *, feature):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas, _ = _access(request, prd_id, create_canvas=True)
        _enforce_ai(access)
        key = request.headers.get("Idempotency-Key", "")
        service = BrainstormAiRequestService()
        if feature == "analysis":
            job, created = service.request_analysis(
                canvas=canvas,
                user_id=context.user_id,
                idempotency_key=key,
            )
        else:
            job, created = service.request_classification(
                canvas=canvas,
                user_id=context.user_id,
                idempotency_key=key,
            )
        return api_success(
            _serialize_job(job),
            status=202 if created else 200,
            request_id=_request_id(request),
        )
    except EmptyBrainstormInput as exc:
        return api_success(
            {
                "job": None,
                "message": exc.message,
                "statistics": exc.statistics,
            },
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        AiPromptNotConfigured,
        AiUsageLimitExceeded,
    ) as exc:
        return _ai_error(request, exc)


@require_GET
def job_status(request, prd_id, job_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, _, _ = _access(request, prd_id, create_canvas=True)
        job = _owned_job(access=access, user_id=context.user_id, job_id=job_id)
        return api_success(_serialize_job(job), request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _ai_error(request, exc)


@require_POST
def cancel_job(request, prd_id, job_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, _, _ = _access(request, prd_id, create_canvas=True)
        _owned_job(access=access, user_id=context.user_id, job_id=job_id)
        job = AiJobService().cancel(job_id=job_id, user_id=context.user_id)
        return api_success(_serialize_job(job), request_id=_request_id(request))
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        AiJobNotCancellable,
    ) as exc:
        return _ai_error(request, exc)


@require_POST
def retry_job(request, prd_id, job_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, _, _ = _access(request, prd_id, create_canvas=True)
        _enforce_ai(access)
        _owned_job(access=access, user_id=context.user_id, job_id=job_id)
        job = AiJobService().retry(job_id=job_id, user_id=context.user_id)
        return api_success(
            _serialize_job(job),
            status=202,
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        AiJobNotRetryable,
        AiUsageLimitExceeded,
    ) as exc:
        return _ai_error(request, exc)


@require_POST
def apply_classification(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas, _ = _access(request, prd_id, create_canvas=True)
        payload = _parse_json(request)
        job = _owned_job(
            access=access,
            user_id=context.user_id,
            job_id=payload.get("job_id"),
        )
        operation_id, nodes, applied = BrainstormClassificationApplyService().apply(
            canvas=canvas,
            access=access,
            job=job,
            actor_user_id=context.user_id,
            selections=payload.get("selections"),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return api_success(
            {
                "operation_id": str(operation_id),
                "applied": applied,
                "nodes": [_serialize_node(node) for node in nodes],
                "cursor": _latest_cursor(canvas),
            },
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        AiClassificationConflict,
    ) as exc:
        return _ai_error(request, exc)


def _owned_job(*, access, user_id, job_id):
    try:
        return AiJob.objects.select_related("prd", "prompt").get(
            pk=job_id,
            prd=access.prd,
            user_id=user_id,
        )
    except (AiJob.DoesNotExist, ValidationError, ValueError, TypeError) as exc:
        raise ValidationError({"job_id": "AI 작업을 찾을 수 없습니다."}) from exc


def _serialize_job(job):
    data = {
        "id": str(job.pk),
        "feature_type": job.feature_type,
        "action_type": job.action_type,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "output": job.output_data,
        "error": (
            {"code": job.error_code, "message": job.error_message} if job.error_code else None
        ),
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
    if job.input_data.get("kind") == "brainstorm_analysis":
        data["statistics"] = job.input_data.get("server_statistics")
    if job.input_data.get("kind") == "brainstorm_prd_apply":
        data["preview"] = {
            "scope": job.input_data.get("scope"),
            "section_id": job.input_data.get("section_id"),
            "node_versions": [
                {"node_id": row["id"], "version": row["version"]}
                for row in job.input_data.get("nodes", [])
            ],
            "excluded_unclassified_accepted_node_ids": job.input_data.get(
                "excluded_unclassified_accepted_node_ids", []
            ),
        }
    return data
