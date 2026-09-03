from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.common.responses import api_error, api_success
from apps.integration.exceptions import IntegrationError
from apps.integration.views import render_context_exception
from apps.prds.detail import PrdAccessService, PrdNotFound
from apps.prds.models import PrdQuestion, PrdSection, PrdStatus
from apps.prds.views import _context_error, _request_id, _resolve_context

from .coaching import (
    AiCoachConversationService,
    AiDraftService,
    AiDraftVersionConflict,
)
from .exceptions import (
    AiJobNotCancellable,
    AiJobNotRetryable,
    AiPromptNotConfigured,
    AiUsageLimitExceeded,
)
from .models import AiCoachMessage, AiJob
from .services import AiJobService


@login_required
@require_GET
def prd_write_page(request, prd_id):
    try:
        context = _resolve_context(request)
        access = PrdAccessService().get(prd_id=prd_id, context=context)
    except PrdNotFound as exc:
        raise Http404 from exc
    except (PermissionDenied, IntegrationError) as exc:
        return render_context_exception(request, exc)
    return render(
        request,
        "prds/write.html",
        {
            "prd": access.prd,
            "detail_api_url": reverse("prd_api:detail", args=[prd_id]),
            "participants_api_url": reverse("prd_api:participants", args=[prd_id]),
            "participant_search_api_url": reverse("prd_api:participant-search"),
            "comments_api_url": reverse("prd_api:comments", args=[prd_id]),
            "contributions_api_url": reverse("prd_api:contributions", args=[prd_id]),
            "prd_api_base": reverse("prd_api:detail", args=[prd_id]),
            "ai_api_base": reverse("ai_api:conversation", args=[prd_id]).removesuffix(
                "conversation/"
            ),
        },
    )


def _authentication_error(request):
    if request.user.is_authenticated:
        return None
    return api_error(
        code="authentication_required",
        message="로그인이 필요합니다.",
        status=401,
        request_id=_request_id(request),
    )


def _parse_json(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValidationError({"body": "요청 본문이 올바른 JSON이 아닙니다."}) from exc
    if not isinstance(payload, dict):
        raise ValidationError({"body": "JSON 객체가 필요합니다."})
    return payload


def _access(request, prd_id):
    context = _resolve_context(request)
    access = PrdAccessService().get(prd_id=prd_id, context=context)
    return context, access


def _enforce(access, action):
    role_permission_policy.enforce(
        access.role,
        action,
        is_completed=access.prd.status == PrdStatus.COMPLETED,
    )


def _section(access, value):
    if value in (None, ""):
        return None
    try:
        section_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"section_id": "섹션 ID가 올바르지 않습니다."}) from exc
    if section_id <= 0:
        raise ValidationError({"section_id": "섹션 ID가 올바르지 않습니다."})
    try:
        return PrdSection.objects.get(pk=section_id, prd=access.prd, is_deleted=False)
    except PrdSection.DoesNotExist as exc:
        raise ValidationError({"section_id": "현재 PRD의 섹션이 아닙니다."}) from exc


def _question(access, value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError({"question_id": "질문 ID가 올바르지 않습니다."})
    try:
        return PrdQuestion.objects.select_related("section").get(
            pk=value,
            section__prd=access.prd,
            section__is_deleted=False,
            is_deleted=False,
        )
    except PrdQuestion.DoesNotExist as exc:
        raise ValidationError({"question_id": "현재 PRD의 질문이 아닙니다."}) from exc


def _error(request, exc):
    if isinstance(exc, PrdNotFound):
        return api_error(
            code="not_found",
            message="PRD를 찾을 수 없습니다.",
            status=404,
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
            message="현재 상태에서는 작업을 변경할 수 없습니다.",
            status=409,
            request_id=_request_id(request),
        )
    if isinstance(exc, ValidationError):
        details = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        return api_error(
            code="validation_error",
            message="입력값을 확인해 주세요.",
            status=400,
            details=details,
            request_id=_request_id(request),
        )
    return _context_error(request, exc)


@require_GET
def conversation(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access = _access(request, prd_id)
        section = _section(access, request.GET.get("section_id"))
        current = AiCoachConversationService().get(
            prd=access.prd,
            section=section,
            user_id=context.user_id,
        )
        messages = (
            AiCoachMessage.objects.filter(conversation=current).select_related("job")
            if current
            else AiCoachMessage.objects.none()
        )
        return api_success(
            {
                "conversation_id": current.pk if current else None,
                "prd_id": access.prd.pk,
                "section_id": section.pk if section else None,
                "expires_at": current.expires_at.isoformat() if current else None,
                "messages": [_serialize_message(message) for message in messages],
            },
            request_id=_request_id(request),
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error(request, exc)


@require_POST
def request_chat(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        payload = _parse_json(request)
        context, access = _access(request, prd_id)
        _enforce(access, ParticipantAction.REQUEST_AI)
        section = _section(access, payload.get("section_id"))
        job, created = AiCoachConversationService().request_chat(
            prd=access.prd,
            section=section,
            user_id=context.user_id,
            message=payload.get("message"),
            idempotency_key=_idempotency_key(request, payload),
        )
        return api_success(
            _serialize_job(job),
            status=202 if created else 200,
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
        return _error(request, exc)


@require_POST
def request_draft(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        payload = _parse_json(request)
        context, access = _access(request, prd_id)
        _enforce(access, ParticipantAction.REQUEST_AI)
        question = _question(access, payload.get("question_id"))
        job, created = AiDraftService().request(
            prd=access.prd,
            question=question,
            user_id=context.user_id,
            idempotency_key=_idempotency_key(request, payload),
        )
        return api_success(
            _serialize_job(job),
            status=202 if created else 200,
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
        return _error(request, exc)


@require_GET
def job_status(request, prd_id, job_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access = _access(request, prd_id)
        job = _owned_job(access=access, user_id=context.user_id, job_id=job_id)
        return api_success(_serialize_job(job), request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error(request, exc)


@require_POST
def cancel_job(request, prd_id, job_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access = _access(request, prd_id)
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
        return _error(request, exc)


@require_POST
def retry_job(request, prd_id, job_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access = _access(request, prd_id)
        _enforce(access, ParticipantAction.REQUEST_AI)
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
        return _error(request, exc)


@require_POST
def apply_draft(request, prd_id, job_id):
    if response := _authentication_error(request):
        return response
    try:
        payload = _parse_json(request)
        context, access = _access(request, prd_id)
        _enforce(access, ParticipantAction.APPLY_AI)
        job = _owned_job(access=access, user_id=context.user_id, job_id=job_id)
        question_version = payload.get("question_version")
        if (
            isinstance(question_version, bool)
            or not isinstance(question_version, int)
            or question_version <= 0
        ):
            raise ValidationError({"question_version": "질문 version이 올바르지 않습니다."})
        answer = AiDraftService().apply(
            job=job,
            question_version=question_version,
            content=payload.get("content"),
            user_id=context.user_id,
        )
        answer.question.refresh_from_db()
        return api_success(
            {
                "question_id": answer.question_id,
                "question_version": answer.question.version,
                "answer": {
                    "id": answer.pk,
                    "content": answer.content,
                    "updated_at": answer.updated_at.isoformat(),
                },
            },
            request_id=_request_id(request),
        )
    except AiDraftVersionConflict as exc:
        return api_error(
            code="version_conflict",
            message="질문이 변경되었습니다. 최신 내용을 확인한 뒤 다시 시도해 주세요.",
            status=409,
            details={
                "question_id": exc.question.pk,
                "latest_version": exc.question.version,
            },
            request_id=_request_id(request),
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error(request, exc)


def _idempotency_key(request, payload):
    return request.headers.get("Idempotency-Key") or payload.get("idempotency_key", "")


def _owned_job(*, access, user_id, job_id):
    try:
        return AiJob.objects.select_related("prompt", "prd").get(
            pk=job_id,
            prd=access.prd,
            user_id=user_id,
        )
    except AiJob.DoesNotExist as exc:
        raise ValidationError({"job": "AI 작업을 찾을 수 없습니다."}) from exc


def _serialize_job(job):
    return {
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


def _serialize_message(message):
    return {
        "id": message.pk,
        "sequence": message.sequence,
        "role": message.role,
        "content": message.content,
        "job": (
            {
                "id": str(message.job_id),
                "status": message.job.status,
                "error_code": message.job.error_code or None,
            }
            if message.job_id
            else None
        ),
        "created_at": message.created_at.isoformat(),
    }
