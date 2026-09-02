from __future__ import annotations

import json
from math import ceil

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.views.decorators.http import require_GET, require_http_methods

from apps.ai.models import AiChatHistory, AiUsageLog
from apps.common.responses import api_error, api_success
from apps.integration.exceptions import IntegrationError

from .comment_services import PrdCommentService
from .detail import PrdAccessService, PrdNotFound, PrdPermissionPresenter
from .models import (
    PrdComment,
    PrdCommentType,
    PrdQuestion,
    PrdSection,
)
from .status_services import PrdStatusConflict, PrdStatusService
from .views import (
    _context_error,
    _request_id,
    _resolve_context,
    get_integration_repository,
)


def _get_access(request, prd_id):
    context = _resolve_context(request)
    return context, PrdAccessService().get(prd_id=prd_id, context=context)


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
    if isinstance(exc, PrdStatusConflict):
        return api_error(
            code="status_conflict",
            message="현재 PRD 상태에서는 요청한 상태 변경을 수행할 수 없습니다.",
            status=409,
            details={"current_status": exc.current_status},
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
            {"id": prd.id, "status": prd.status, "completed_at": None},
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
        summaries = get_integration_repository().get_round_user_summaries(
            user_ids=tuple(dict.fromkeys(row.author_user_id for row in rows)),
            round_id=context.round_id,
        )
        data = {
            "items": [
                _serialize_comment(
                    row,
                    display_name=(
                        summaries[row.author_user_id].display_name
                        if row.author_user_id in summaries
                        else f"사용자 {row.author_user_id}"
                    ),
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


def _serialize_comment(comment, *, display_name):
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
        "created_at": comment.created_at.isoformat(),
        "updated_at": comment.updated_at.isoformat(),
    }


def _author_display_name(*, user_id, round_id):
    summary = (
        get_integration_repository()
        .get_round_user_summaries(
            user_ids=(user_id,),
            round_id=round_id,
        )
        .get(user_id)
    )
    return summary.display_name if summary else f"사용자 {user_id}"


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
        lambda prd: AiChatHistory.objects.filter(prd=prd),
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
