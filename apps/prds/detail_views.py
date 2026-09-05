from __future__ import annotations

import json
from datetime import date, timedelta
from math import ceil

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Prefetch
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.ai.contribution import ContributionEvaluationService
from apps.ai.exceptions import AiJobNotRetryable, AiPromptNotConfigured, AiUsageLimitExceeded
from apps.ai.models import AiCoachChatLog, AiJob, AiJobStatus, AiUsageLog, ContributionEvaluation
from apps.common.responses import api_error, api_success
from apps.integration.exceptions import IntegrationError

from .comment_services import PrdCommentService
from .detail import PrdAccessService, PrdNotFound, PrdPermissionPresenter
from .exporting import PrdMarkdownExporter
from .models import (
    Prd,
    PrdAnswer,
    PrdChangeHistory,
    PrdComment,
    PrdCommentType,
    PrdDeletionAction,
    PrdDeletionAuditLog,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
)
from .services import PrdParticipantService
from .status_services import PrdStatusConflict, PrdStatusService
from .views import (
    _context_error,
    _request_id,
    _resolve_context,
    get_integration_repository,
)


class PrdQuestionVersionConflict(Exception):
    def __init__(self, question):
        self.question = question


class PrdVersionConflict(Exception):
    def __init__(self, prd):
        self.prd = prd


def _get_access(request, prd_id):
    context = _resolve_context(request)
    return context, PrdAccessService().get(prd_id=prd_id, context=context)


def _participant_summaries(repository, *, user_ids, round_id):
    if round_id is not None:
        return {
            user_id: summary.display_name
            for user_id, summary in repository.get_round_user_summaries(
                user_ids=user_ids,
                round_id=round_id,
            ).items()
        }
    return {
        user_id: summary.display_name
        for user_id, summary in repository.get_user_summaries(
            user_ids=tuple(user_ids),
        ).items()
    }


def _error_response(request, exc):
    if isinstance(exc, PrdNotFound):
        return api_error(
            code="not_found",
            message="PRD를 찾을 수 없습니다.",
            status=404,
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
    if isinstance(exc, PrdQuestionVersionConflict):
        return api_error(
            code="version_conflict",
            message="다른 사용자가 먼저 답변을 변경했습니다. 최신 내용을 확인해 주세요.",
            status=409,
            details={"latest": _serialize_question(exc.question)},
            request_id=_request_id(request),
        )
    if isinstance(exc, PrdVersionConflict):
        return api_error(
            code="version_conflict",
            message="다른 사용자가 먼저 PRD를 변경했습니다. 최신 내용을 확인해 주세요.",
            status=409,
            details={
                "latest": {
                    "version": exc.prd.version,
                    "status": exc.prd.status,
                    "deadline": exc.prd.deadline.isoformat() if exc.prd.deadline else None,
                }
            },
            request_id=_request_id(request),
        )
    if isinstance(exc, PrdStatusConflict):
        return api_error(
            code="status_conflict",
            message="현재 PRD 상태에서는 요청한 상태 변경을 수행할 수 없습니다.",
            status=409,
            details={"current_status": exc.current_status},
            request_id=_request_id(request),
        )
    if isinstance(exc, AiJobNotRetryable | AiPromptNotConfigured):
        return api_error(
            code="contribution_retry_unavailable",
            message="현재 기여도 계산은 재평가할 수 없습니다.",
            status=409,
            request_id=_request_id(request),
        )
    if isinstance(exc, AiUsageLimitExceeded):
        return api_error(
            code="ai_usage_limit_exceeded",
            message="AI 사용 한도에 도달했습니다.",
            status=429,
            request_id=_request_id(request),
        )
    return _context_error(request, exc)


def _require_authentication(request):
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


def _pagination(request):
    try:
        page = int(request.GET.get("page", "1"))
        requested_size = int(request.GET.get("page_size", str(settings.PRD_DETAIL_PAGE_SIZE)))
    except ValueError as exc:
        raise ValidationError({"pagination": "페이지 값은 정수여야 합니다."}) from exc
    if page <= 0 or requested_size <= 0:
        raise ValidationError({"pagination": "페이지 값은 1 이상이어야 합니다."})
    return page, min(requested_size, settings.PRD_DETAIL_MAX_PAGE_SIZE)


def _paginate(queryset, *, page, page_size, serializer):
    total_items = queryset.count()
    offset = (page - 1) * page_size
    items = [serializer(row) for row in queryset[offset : offset + page_size]]
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": ceil(total_items / page_size) if total_items else 0,
        },
    }


def _enforce_participant_management(access):
    if access.prd.status == "completed":
        raise PermissionDenied("완료된 PRD의 참여자는 변경할 수 없습니다.")
    if access.is_admin:
        return
    if access.role is None:
        raise PermissionDenied("참여자 관리 권한이 없습니다.")
    role_permission_policy.enforce(access.role, ParticipantAction.MANAGE_PARTICIPANTS)


def _serialize_participant(participant, *, display_name=None):
    return {
        "user_id": participant.user_id,
        "participant_id": participant.participant_id,
        "role": participant.role,
        "display_name": display_name or f"사용자 {participant.user_id}",
        "created_at": participant.created_at.isoformat(),
    }


@require_GET
def prd_detail(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        sections = list(
            PrdSection.objects.filter(prd=access.prd, is_deleted=False)
            .prefetch_related(
                Prefetch(
                    "questions",
                    queryset=PrdQuestion.objects.filter(is_deleted=False).select_related("answer"),
                )
            )
            .order_by("position", "id")
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)

    latest_completion_reason = None
    if access.prd.status == PrdStatus.COMPLETED:
        latest_completion_reason = (
            access.prd.status_audit_logs.filter(action="completed")
            .order_by("-created_at", "-id")
            .values_list("reason", flat=True)
            .first()
        )

    return api_success(
        {
            "prd": {
                "id": access.prd.id,
                "title": access.prd.title,
                "description": access.prd.description,
                "prd_type": access.prd.prd_type,
                "status": access.prd.status,
                "completed_at": (
                    access.prd.completed_at.isoformat() if access.prd.completed_at else None
                ),
                "auto_completed": (
                    latest_completion_reason == PrdStatusService.AUTO_COMPLETION_REASON
                ),
                "version": access.prd.version,
                "contribution_status": access.prd.contribution_status,
                "deadline": (access.prd.deadline.isoformat() if access.prd.deadline else None),
                "round_id": access.prd.round_id,
                "team_id": access.prd.team_id,
                "creator_user_id": access.prd.creator_user_id,
                "completion_rate": access.prd.completion_rate,
                "created_at": access.prd.created_at.isoformat(),
                "updated_at": access.prd.updated_at.isoformat(),
            },
            "sections": [_serialize_section(section) for section in sections],
            "permissions": PrdPermissionPresenter().describe(access),
        },
        request_id=_request_id(request),
    )


def _parse_deadline(value) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValidationError({"deadline": "마감일은 YYYY-MM-DD 형식이어야 합니다."})
    parsed = parse_date(value)
    if parsed is None:
        raise ValidationError({"deadline": "마감일은 YYYY-MM-DD 형식이어야 합니다."})
    return parsed


@require_http_methods(["PATCH"])
def prd_metadata(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        payload = _parse_json(request)
        version = payload.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError({"version": "PRD version이 올바르지 않습니다."})
        supplied = {key for key in ("title", "description", "status", "deadline") if key in payload}
        if not supplied:
            raise ValidationError({"body": "수정할 PRD 기본 정보가 필요합니다."})

        permissions = PrdPermissionPresenter().describe(access)
        if supplied & {"title", "description"} and not permissions["can_edit"]:
            raise PermissionDenied("PRD 제목과 한 줄 소개를 수정할 권한이 없습니다.")
        if "deadline" in supplied and not permissions["can_edit_deadline"]:
            raise PermissionDenied("PRD 마감일을 수정할 권한이 없습니다.")
        if "status" in supplied and not permissions["can_change_status"]:
            raise PermissionDenied("PRD 상태를 변경할 권한이 없습니다.")

        requested_status = payload.get("status")
        if "status" in supplied:
            if requested_status not in PrdStatus.values:
                raise ValidationError({"status": "지원하지 않는 PRD 상태입니다."})
            if requested_status == PrdStatus.COMPLETED:
                raise ValidationError({"status": "PRD 완료는 완료 기능을 이용해 주세요."})

        normalized_title = payload.get("title")
        if "title" in supplied:
            if not isinstance(normalized_title, str):
                raise ValidationError({"title": "제목은 문자열이어야 합니다."})
            normalized_title = normalized_title.strip()
            if not normalized_title:
                raise ValidationError({"title": "제목을 입력해 주세요."})
            if len(normalized_title) > 255:
                raise ValidationError({"title": "제목은 255자 이하여야 합니다."})

        normalized_description = payload.get("description")
        if "description" in supplied:
            if not isinstance(normalized_description, str):
                raise ValidationError({"description": "한 줄 소개는 문자열이어야 합니다."})
            normalized_description = normalized_description.strip()
            if "\n" in normalized_description or "\r" in normalized_description:
                raise ValidationError(
                    {"description": "한 줄 소개에는 줄바꿈을 사용할 수 없습니다."}
                )
            if len(normalized_description) > 500:
                raise ValidationError({"description": "한 줄 소개는 500자 이하여야 합니다."})

        with transaction.atomic():
            prd = Prd.objects.select_for_update().get(pk=access.prd.pk, is_deleted=False)
            if prd.version != version:
                raise PrdVersionConflict(prd)
            completed_deadline_only = prd.status == PrdStatus.COMPLETED and supplied == {"deadline"}
            if prd.status == PrdStatus.COMPLETED and not completed_deadline_only:
                raise PermissionDenied("완료된 PRD는 다시 연 후 수정할 수 있습니다.")

            before = {
                "title": prd.title,
                "description": prd.description,
                "status": prd.status,
                "deadline": prd.deadline.isoformat() if prd.deadline else None,
            }
            if "title" in supplied:
                prd.title = normalized_title
            if "description" in supplied:
                prd.description = normalized_description
            if "status" in supplied:
                prd.status = requested_status
            if "deadline" in supplied:
                parsed_deadline = _parse_deadline(payload.get("deadline"))
                if prd.status == PrdStatus.COMPLETED and (
                    parsed_deadline is None or parsed_deadline < timezone.localdate()
                ):
                    raise ValidationError(
                        {"deadline": "다시 열려면 마감 기한을 오늘 이후로 변경해 주세요."}
                    )
                prd.deadline = parsed_deadline
            after = {
                "title": prd.title,
                "description": prd.description,
                "status": prd.status,
                "deadline": prd.deadline.isoformat() if prd.deadline else None,
            }
            if before != after:
                prd.version += 1
                prd.save(update_fields=[*supplied, "version", "updated_at"])
                PrdChangeHistory.objects.create(
                    prd=prd,
                    actor_user_id=context.user_id,
                    event_type="prd_metadata_updated",
                    before_data=before,
                    after_data=after,
                )

        return api_success(
            {
                "id": prd.id,
                "title": prd.title,
                "description": prd.description,
                "status": prd.status,
                "deadline": prd.deadline.isoformat() if prd.deadline else None,
                "version": prd.version,
            },
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdVersionConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


def _required_prd_version(payload):
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValidationError({"version": "PRD version이 올바르지 않습니다."})
    return version


def _record_deletion_audit(*, prd, action, actor_user_id, details=None):
    return PrdDeletionAuditLog.objects.create(
        prd_id=prd.pk,
        title_snapshot=prd.title,
        creator_user_id=prd.creator_user_id,
        actor_user_id=actor_user_id,
        action=action,
        details=details or {},
    )


@require_http_methods(["DELETE"])
def delete_prd(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        if not (access.is_admin or access.role == PrdParticipantRole.OWNER):
            raise PermissionDenied("PRD 소유자 또는 관리자만 삭제할 수 있습니다.")
        version = _required_prd_version(_parse_json(request))
        now = timezone.now()
        with transaction.atomic():
            prd = Prd.objects.select_for_update().get(pk=access.prd.pk, is_deleted=False)
            if prd.version != version:
                raise PrdVersionConflict(prd)
            prd.is_deleted = True
            prd.deleted_at = now
            prd.purge_requested_at = None
            prd.purge_requested_by_user_id = None
            prd.version += 1
            prd.save(
                update_fields=[
                    "is_deleted",
                    "deleted_at",
                    "purge_requested_at",
                    "purge_requested_by_user_id",
                    "version",
                    "updated_at",
                ]
            )
            AiJob.objects.filter(
                prd=prd,
                status__in=[AiJobStatus.QUEUED, AiJobStatus.RUNNING, AiJobStatus.RETRY_WAIT],
            ).update(status=AiJobStatus.CANCEL_REQUESTED, cancel_requested_at=now)
            _record_deletion_audit(
                prd=prd,
                action=PrdDeletionAction.TRASHED,
                actor_user_id=context.user_id,
                details={"deleted_at": now.isoformat()},
            )
        return api_success(
            {
                "id": prd.pk,
                "state": "trash",
                "deleted_at": prd.deleted_at.isoformat(),
                "retention_days": settings.PRD_TRASH_RETENTION_DAYS,
                "version": prd.version,
            },
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdVersionConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


def _deleted_prd_for_context(*, context, prd_id, for_update=False):
    queryset = Prd.objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        prd = queryset.get(pk=prd_id, is_deleted=True)
    except Prd.DoesNotExist as exc:
        raise PrdNotFound from exc
    if prd.creator_user_id != context.user_id and not (context.is_staff or context.is_superuser):
        raise PermissionDenied("이 휴지통 PRD에 접근할 권한이 없습니다.")
    return prd


@require_GET
def trash_prds(request):
    if response := _require_authentication(request):
        return response
    try:
        context = _resolve_context(request)
        page = max(1, int(request.GET.get("page", "1")))
        page_size = min(50, max(1, int(request.GET.get("page_size", "20"))))
        queryset = Prd.objects.filter(is_deleted=True)
        if not (context.is_staff or context.is_superuser):
            queryset = queryset.filter(creator_user_id=context.user_id)
        total_items = queryset.count()
        rows = list(
            queryset.order_by("-deleted_at", "-id")[(page - 1) * page_size : page * page_size]
        )
        now = timezone.now()
        items = []
        for prd in rows:
            purge_at = prd.deleted_at + timedelta(days=settings.PRD_TRASH_RETENTION_DAYS)
            days_remaining = max(0, ceil((purge_at - now).total_seconds() / 86400))
            items.append(
                {
                    "id": prd.pk,
                    "title": prd.title,
                    "description": prd.description,
                    "deleted_at": prd.deleted_at.isoformat(),
                    "purge_at": purge_at.isoformat(),
                    "days_remaining": days_remaining,
                    "state": "deleted_complete" if prd.purge_requested_at else "recoverable",
                    "version": prd.version,
                    "can_restore": prd.purge_requested_at is None,
                }
            )
        return api_success(
            {
                "items": items,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": max(1, ceil(total_items / page_size)),
                },
            },
            request_id=_request_id(request),
        )
    except (TypeError, ValueError):
        return api_error(
            code="invalid_parameter",
            message="페이지 값이 올바르지 않습니다.",
            status=400,
            request_id=_request_id(request),
        )
    except (PermissionDenied, IntegrationError) as exc:
        return _error_response(request, exc)


@require_http_methods(["POST"])
def restore_prd(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context = _resolve_context(request)
        version = _required_prd_version(_parse_json(request))
        with transaction.atomic():
            prd = _deleted_prd_for_context(context=context, prd_id=prd_id, for_update=True)
            if prd.version != version:
                raise PrdVersionConflict(prd)
            is_admin = context.is_staff or context.is_superuser
            if prd.purge_requested_at is not None and not is_admin:
                raise PermissionDenied("삭제 완료된 PRD는 관리자를 통해서만 복구할 수 있습니다.")
            prd.is_deleted = False
            prd.deleted_at = None
            prd.purge_requested_at = None
            prd.purge_requested_by_user_id = None
            prd.version += 1
            prd.save(
                update_fields=[
                    "is_deleted",
                    "deleted_at",
                    "purge_requested_at",
                    "purge_requested_by_user_id",
                    "version",
                    "updated_at",
                ]
            )
            _record_deletion_audit(
                prd=prd,
                action=PrdDeletionAction.RESTORED,
                actor_user_id=context.user_id,
            )
        return api_success(
            {"id": prd.pk, "state": "restored", "version": prd.version},
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdVersionConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


@require_http_methods(["POST"])
def confirm_prd_deletion(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context = _resolve_context(request)
        version = _required_prd_version(_parse_json(request))
        with transaction.atomic():
            prd = _deleted_prd_for_context(context=context, prd_id=prd_id, for_update=True)
            if prd.version != version:
                raise PrdVersionConflict(prd)
            if prd.purge_requested_at is None:
                prd.purge_requested_at = timezone.now()
                prd.purge_requested_by_user_id = context.user_id
                prd.version += 1
                prd.save(
                    update_fields=[
                        "purge_requested_at",
                        "purge_requested_by_user_id",
                        "version",
                        "updated_at",
                    ]
                )
                _record_deletion_audit(
                    prd=prd,
                    action=PrdDeletionAction.DELETE_COMPLETED,
                    actor_user_id=context.user_id,
                    details={"purge_after_days": settings.PRD_TRASH_RETENTION_DAYS},
                )
        return api_success(
            {"id": prd.pk, "state": "deleted_complete", "version": prd.version},
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdVersionConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


@require_GET
def export_markdown(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        exported = PrdMarkdownExporter().export(prd=access.prd)
        response = HttpResponse(exported.content, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = exported.content_disposition
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


@require_http_methods(["GET", "POST"])
def participants(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        repository = get_integration_repository()
        if request.method == "POST":
            _enforce_participant_management(access)
            payload = _parse_json(request)
            user_id = payload.get("user_id")
            if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
                raise ValidationError({"user_id": "사용자 ID가 올바르지 않습니다."})
            participant, created = PrdParticipantService(repository).add_participant(
                prd=access.prd,
                user_id=user_id,
                role=payload.get("role", PrdParticipantRole.EDITOR),
                actor_user_id=context.user_id,
            )
            summaries = _participant_summaries(
                repository,
                user_ids=(participant.user_id,),
                round_id=access.prd.round_id,
            )
            return api_success(
                {
                    **_serialize_participant(
                        participant,
                        display_name=summaries.get(participant.user_id),
                    ),
                    "created": created,
                },
                status=201 if created else 200,
                request_id=_request_id(request),
            )

        page, page_size = _pagination(request)
        queryset = PrdParticipant.objects.filter(prd=access.prd).order_by("created_at", "id")
        total_items = queryset.count()
        rows = list(queryset[(page - 1) * page_size : page * page_size])
        summaries = _participant_summaries(
            repository,
            user_ids=tuple(row.user_id for row in rows),
            round_id=access.prd.round_id,
        )
        return api_success(
            {
                "items": [
                    _serialize_participant(
                        row,
                        display_name=(summaries.get(row.user_id)),
                    )
                    for row in rows
                ],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": ceil(total_items / page_size) if total_items else 0,
                },
            },
            request_id=_request_id(request),
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


@require_http_methods(["PATCH", "DELETE"])
def participant_item(request, prd_id, user_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        _enforce_participant_management(access)
        try:
            participant = PrdParticipant.objects.select_related("prd").get(
                prd=access.prd,
                user_id=user_id,
            )
        except PrdParticipant.DoesNotExist as exc:
            raise PrdNotFound from exc
        service = PrdParticipantService(get_integration_repository())
        if request.method == "PATCH":
            payload = _parse_json(request)
            participant = service.update_role(
                participant=participant,
                role=payload.get("role"),
                actor_user_id=context.user_id,
            )
            return api_success(
                _serialize_participant(participant),
                request_id=_request_id(request),
            )
        reassigned_nodes = service.remove_participant(
            participant=participant,
            actor_user_id=context.user_id,
        )
        return api_success(
            {
                "deleted": True,
                "reassigned_node_ids": [str(node.pk) for node in reassigned_nodes],
            },
            request_id=_request_id(request),
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


@require_http_methods(["POST"])
def complete_prd(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        payload = _parse_json(request)
        confirm_incomplete = payload.get("confirm_incomplete", False)
        if not isinstance(confirm_incomplete, bool):
            raise ValidationError({"confirm_incomplete": "확인 값은 boolean이어야 합니다."})
        prd = PrdStatusService().complete(
            access=access,
            actor_user_id=context.user_id,
            confirm_incomplete=confirm_incomplete,
        )
        return api_success(
            {
                "id": prd.id,
                "status": prd.status,
                "completed_at": prd.completed_at.isoformat(),
                "contribution_status": prd.contribution_status,
            },
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdStatusConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


@require_http_methods(["POST"])
def reopen_prd(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        payload = _parse_json(request)
        prd = PrdStatusService().reopen(
            access=access,
            actor_user_id=context.user_id,
            reason=payload.get("reason", ""),
        )
        return api_success(
            {
                "id": prd.id,
                "status": prd.status,
                "completed_at": None,
                "contribution_status": prd.contribution_status,
            },
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdStatusConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


def _serialize_section(section):
    return {
        "id": section.id,
        "title": section.title,
        "guide": section.guide,
        "position": section.position,
        "questions": [_serialize_question(question) for question in section.questions.all()],
    }


def _serialize_question(question):
    try:
        answer = question.answer
    except ObjectDoesNotExist:
        answer = None
    return {
        "id": question.id,
        "prompt": question.prompt,
        "position": question.position,
        "is_completed": question.is_completed,
        "is_held": question.is_held,
        "version": question.version,
        "answer": (
            {
                "id": answer.id,
                "content": answer.content,
                "updated_by_user_id": answer.updated_by_user_id,
                "updated_at": answer.updated_at.isoformat(),
            }
            if answer
            else None
        ),
    }


@require_http_methods(["PATCH"])
def question_answer(request, prd_id, question_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        if not PrdPermissionPresenter().describe(access)["can_edit"]:
            raise PermissionDenied("PRD 답변을 수정할 권한이 없습니다.")
        payload = _parse_json(request)
        content = payload.get("content")
        version = payload.get("version")
        if not isinstance(content, str):
            raise ValidationError({"content": "답변은 문자열이어야 합니다."})
        if len(content) > settings.AI_DRAFT_MAX_LENGTH:
            raise ValidationError(
                {"content": f"답변은 {settings.AI_DRAFT_MAX_LENGTH}자 이하여야 합니다."}
            )
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError({"version": "질문 version이 올바르지 않습니다."})
        with transaction.atomic():
            try:
                question = (
                    PrdQuestion.objects.select_for_update()
                    .select_related("section__prd")
                    .get(
                        pk=question_id,
                        section__prd=access.prd,
                        section__is_deleted=False,
                        is_deleted=False,
                    )
                )
            except PrdQuestion.DoesNotExist as exc:
                raise PrdNotFound from exc
            if question.version != version:
                raise PrdQuestionVersionConflict(question)
            if question.is_held:
                raise ValidationError({"question": "보류된 질문은 답변을 수정할 수 없습니다."})
            try:
                previous = question.answer.content
            except ObjectDoesNotExist:
                previous = ""
            answer, _ = PrdAnswer.objects.update_or_create(
                question=question,
                defaults={"content": content, "updated_by_user_id": context.user_id},
            )
            question.version += 1
            question.is_completed = bool(content.strip())
            question.save(update_fields=["version", "is_completed", "updated_at"])
            PrdChangeHistory.objects.create(
                prd=access.prd,
                actor_user_id=context.user_id,
                event_type="answer_updated",
                before_data={"question_id": question.id, "content": previous},
                after_data={"question_id": question.id, "content": content},
            )
        question.answer = answer
        return api_success(
            _serialize_question(question),
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdQuestionVersionConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


@require_http_methods(["PATCH"])
def question_hold(request, prd_id, question_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        if not PrdPermissionPresenter().describe(access)["can_edit"]:
            raise PermissionDenied("질문 보류 상태를 변경할 권한이 없습니다.")
        payload = _parse_json(request)
        is_held = payload.get("is_held")
        version = payload.get("version")
        if not isinstance(is_held, bool):
            raise ValidationError({"is_held": "보류 여부는 boolean이어야 합니다."})
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError({"version": "질문 version이 올바르지 않습니다."})
        with transaction.atomic():
            try:
                question = (
                    PrdQuestion.objects.select_for_update()
                    .select_related("section__prd")
                    .get(
                        pk=question_id,
                        section__prd=access.prd,
                        section__is_deleted=False,
                        is_deleted=False,
                    )
                )
            except PrdQuestion.DoesNotExist as exc:
                raise PrdNotFound from exc
            if question.version != version:
                raise PrdQuestionVersionConflict(question)
            previous = question.is_held
            if previous != is_held:
                question.is_held = is_held
                question.version += 1
                question.save(update_fields=["is_held", "version", "updated_at"])
                now = timezone.now()
                Prd.objects.filter(pk=access.prd.pk).update(
                    version=F("version") + 1,
                    updated_at=now,
                )
                PrdChangeHistory.objects.create(
                    prd=access.prd,
                    actor_user_id=context.user_id,
                    event_type="question_hold_changed",
                    before_data={"question_id": question.id, "is_held": previous},
                    after_data={
                        "question_id": question.id,
                        "is_held": question.is_held,
                        "question_version": question.version,
                    },
                )
        current_prd = Prd.objects.with_completion_rate().get(pk=access.prd.pk)
        return api_success(
            {
                "question": _serialize_question(question),
                "completion_rate": current_prd.completion_rate,
            },
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PrdQuestionVersionConflict,
        PermissionDenied,
        IntegrationError,
        ValidationError,
    ) as exc:
        return _error_response(request, exc)


@require_http_methods(["GET", "POST"])
def comments(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        if request.method == "POST":
            payload = _parse_json(request)
            question_id = payload.get("section_question_id")
            if isinstance(question_id, bool) or (
                question_id is not None and (not isinstance(question_id, int) or question_id <= 0)
            ):
                raise ValidationError({"section_question_id": "질문 ID가 올바르지 않습니다."})
            comment_type = payload.get("comment_type")
            if comment_type is not None and comment_type not in PrdCommentType.values:
                raise ValidationError({"comment_type": "코멘트 유형이 올바르지 않습니다."})
            comment = PrdCommentService().create(
                access=access,
                author_user_id=context.user_id,
                content=payload.get("content", ""),
                section_question_id=question_id,
                requested_type=comment_type,
            )
            return api_success(
                _serialize_comment(
                    comment,
                    display_name=_author_display_name(
                        user_id=context.user_id,
                        round_id=context.round_id,
                    ),
                    actor_user_id=context.user_id,
                    access=access,
                ),
                status=201,
                request_id=_request_id(request),
            )

        page, page_size = _pagination(request)
        queryset = PrdComment.objects.filter(prd=access.prd, is_deleted=False)
        raw_question_id = request.GET.get("section_question_id")
        if raw_question_id:
            try:
                question_id = int(raw_question_id)
            except ValueError as exc:
                raise ValidationError(
                    {"section_question_id": "질문 ID가 올바르지 않습니다."}
                ) from exc
            queryset = queryset.filter(section_question_id=question_id)
        rows = list(queryset[(page - 1) * page_size : page * page_size])
        total_items = queryset.count()
        summaries = _participant_summaries(
            get_integration_repository(),
            user_ids=tuple(dict.fromkeys(row.author_user_id for row in rows)),
            round_id=access.prd.round_id,
        )
        data = {
            "items": [
                _serialize_comment(
                    row,
                    display_name=(
                        summaries.get(row.author_user_id, f"사용자 {row.author_user_id}")
                    ),
                    actor_user_id=context.user_id,
                    access=access,
                )
                for row in rows
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": ceil(total_items / page_size) if total_items else 0,
            },
        }
        return api_success(data, request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


@require_http_methods(["PATCH", "DELETE"])
def comment_item(request, prd_id, comment_id):
    if response := _require_authentication(request):
        return response
    try:
        context, access = _get_access(request, prd_id)
        try:
            comment = PrdComment.objects.get(
                pk=comment_id,
                prd=access.prd,
                is_deleted=False,
            )
        except PrdComment.DoesNotExist as exc:
            raise PrdNotFound from exc
        service = PrdCommentService()
        if request.method == "PATCH":
            payload = _parse_json(request)
            comment = service.update(
                access=access,
                comment=comment,
                actor_user_id=context.user_id,
                content=payload.get("content", ""),
            )
            return api_success(
                _serialize_comment(
                    comment,
                    display_name=_author_display_name(
                        user_id=context.user_id,
                        round_id=context.round_id,
                    ),
                    actor_user_id=context.user_id,
                    access=access,
                ),
                request_id=_request_id(request),
            )
        service.delete(
            access=access,
            comment=comment,
            actor_user_id=context.user_id,
        )
        return api_success({"deleted": True}, request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


def _serialize_comment(comment, *, display_name, actor_user_id=None, access=None):
    can_modify = bool(
        actor_user_id == comment.author_user_id
        and access is not None
        and (
            access.prd.status != "completed"
            or (
                access.role == PrdParticipantRole.TUTOR
                and comment.comment_type == PrdCommentType.POST_COMPLETION_REVIEW
            )
        )
    )
    return {
        "id": comment.id,
        "section_question_id": comment.section_question_id,
        "author": {
            "user_id": comment.author_user_id,
            "display_name": display_name,
            "role_at_created": comment.author_role_at_created,
        },
        "comment_type": comment.comment_type,
        "content": comment.content,
        "is_contribution_eligible": comment.is_contribution_eligible,
        "can_modify": can_modify,
        "created_at": comment.created_at.isoformat(),
        "updated_at": comment.updated_at.isoformat(),
    }


def _author_display_name(*, user_id, round_id):
    return _participant_summaries(
        get_integration_repository(),
        user_ids=(user_id,),
        round_id=round_id,
    ).get(user_id, f"사용자 {user_id}")


@require_GET
def ai_usage_history(request, prd_id):
    return _paginated_detail_endpoint(
        request,
        prd_id,
        lambda prd: AiUsageLog.objects.filter(prd=prd).order_by("-created_at", "-id"),
        lambda row: {
            "id": row.id,
            "user_id": row.user_id,
            "feature_type": row.feature_type,
            "action_type": row.action_type,
            "status": row.status,
            "total_tokens": row.total_tokens,
            "created_at": row.created_at.isoformat(),
        },
    )


@require_GET
def ai_chat_history(request, prd_id):
    return _paginated_detail_endpoint(
        request,
        prd_id,
        lambda prd: AiCoachChatLog.objects.filter(prd=prd),
        lambda row: {
            "id": row.id,
            "user_id": row.user_id,
            "prompt": row.prompt,
            "response": row.response,
            "created_at": row.created_at.isoformat(),
        },
    )


@require_GET
def change_history(request, prd_id):
    return _paginated_detail_endpoint(
        request,
        prd_id,
        lambda prd: prd.change_history.all(),
        lambda row: {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "event_type": row.event_type,
            "before_data": row.before_data,
            "after_data": row.after_data,
            "created_at": row.created_at.isoformat(),
        },
    )


@require_GET
def contribution_results(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        if not access.is_admin:
            raise PermissionDenied("기여도 결과는 관리자만 조회할 수 있습니다.")
        evaluations = (
            ContributionEvaluation.objects.filter(prd=access.prd)
            .select_related("job")
            .prefetch_related("user_scores", "comment_scores")
            .order_by("-calculation_version")
        )
        user_ids = tuple(
            dict.fromkeys(
                score.user_id
                for evaluation in evaluations
                for score in evaluation.user_scores.all()
            )
        )
        display_names = _participant_summaries(
            get_integration_repository(),
            user_ids=user_ids,
            round_id=access.prd.round_id,
        )
        return api_success(
            {
                "items": [
                    _serialize_contribution(row, display_names=display_names) for row in evaluations
                ]
            },
            request_id=_request_id(request),
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


@require_http_methods(["POST"])
def retry_contribution(request, prd_id, calculation_version):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        if not access.is_admin:
            raise PermissionDenied("기여도 재평가는 관리자만 실행할 수 있습니다.")
        try:
            evaluation = ContributionEvaluation.objects.get(
                prd=access.prd,
                calculation_version=calculation_version,
            )
        except ContributionEvaluation.DoesNotExist as exc:
            raise PrdNotFound from exc
        evaluation = ContributionEvaluationService().retry_same_input(
            evaluation=evaluation,
            access=access,
        )
        display_names = _participant_summaries(
            get_integration_repository(),
            user_ids=tuple(score.user_id for score in evaluation.user_scores.all()),
            round_id=access.prd.round_id,
        )
        return api_success(
            _serialize_contribution(evaluation, display_names=display_names),
            status=202,
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        AiJobNotRetryable,
        AiPromptNotConfigured,
        AiUsageLimitExceeded,
    ) as exc:
        return _error_response(request, exc)


def _serialize_contribution(evaluation, *, display_names=None):
    display_names = display_names or {}
    return {
        "calculation_version": evaluation.calculation_version,
        "prd_version": evaluation.prd_version,
        "status": evaluation.status,
        "input_fingerprint": evaluation.input_fingerprint,
        "model": evaluation.model or None,
        "prompt_version": evaluation.prompt_version,
        "target_node_ids": evaluation.target_node_ids,
        "target_comment_ids": evaluation.target_comment_ids,
        "evidence": evaluation.evidence,
        "failure_code": evaluation.failure_code or None,
        "calculated_at": (
            evaluation.calculated_at.isoformat() if evaluation.calculated_at else None
        ),
        "scores": [
            {
                "user_id": score.user_id,
                "display_name": display_names.get(score.user_id, "알 수 없는 참여자"),
                "participant_id": score.participant_id,
                "memo_raw": float(score.memo_raw),
                "memo_contribution": float(score.memo_contribution),
                "comment_raw": float(score.comment_raw),
                "comment_contribution": float(score.comment_contribution),
                "total_score": float(score.total_score),
                "node_ids": score.node_ids,
                "comment_ids": score.comment_ids,
                "evidence": score.evidence,
            }
            for score in evaluation.user_scores.all()
        ],
        "comment_scores": [
            {
                "comment_id": score.comment_id,
                "author_user_id": score.author_user_id,
                "reflection_score": float(score.reflection_score),
                "matched_question_ids": score.matched_question_ids,
                "evidence": score.evidence,
                "reason": score.reason,
                "confidence": float(score.confidence),
            }
            for score in evaluation.comment_scores.all()
        ],
    }


def _paginated_detail_endpoint(request, prd_id, queryset_factory, serializer):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        page, page_size = _pagination(request)
        data = _paginate(
            queryset_factory(access.prd),
            page=page,
            page_size=page_size,
            serializer=serializer,
        )
        return api_success(data, request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)
