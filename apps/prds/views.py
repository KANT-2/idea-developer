from __future__ import annotations

import json
from datetime import date

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.services import mask_email
from apps.common.responses import api_error, api_success
from apps.integration.context import StandaloneSessionContextResolver
from apps.integration.exceptions import (
    IntegrationError,
    NoActiveRound,
    RoundSelectionRequired,
)
from apps.integration.repository import DjangoViewIntegrationRepository

from .services import CreatePrdCommand, PrdCreationService


def get_context_resolver():
    return StandaloneSessionContextResolver()


def get_integration_repository():
    return DjangoViewIntegrationRepository()


def _request_id(request):
    return getattr(request, "request_id", None)


def _resolve_context(request: HttpRequest):
    raw_round_id = request.session.get("selected_round_id")
    try:
        selected_round_id = int(raw_round_id) if raw_round_id is not None else None
        if selected_round_id is not None and selected_round_id <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        request.session.pop("selected_round_id", None)
        raise PermissionDenied("The selected round session is invalid.") from exc
    return get_context_resolver().resolve(request, round_id=selected_round_id)


def _context_error(request, exc):
    if isinstance(exc, PermissionDenied):
        return api_error(
            code="permission_denied",
            message="현재 회차에 접근할 권한이 없습니다.",
            status=403,
            request_id=_request_id(request),
        )
    if isinstance(exc, NoActiveRound):
        return api_error(
            code="no_active_round",
            message="진행 중인 회차가 없습니다.",
            status=409,
            request_id=_request_id(request),
        )
    if isinstance(exc, RoundSelectionRequired):
        return api_error(
            code="round_selection_required",
            message="먼저 사용할 회차를 선택해 주세요.",
            status=409,
            request_id=_request_id(request),
        )
    return api_error(
        code="integration_unavailable",
        message="사용자·회차 정보를 확인할 수 없습니다.",
        status=503,
        request_id=_request_id(request),
    )


def _selected_user_ids(request):
    values = request.GET.getlist("selected_user_id")
    if not values:
        comma_separated = request.GET.get("selected_user_ids", "")
        values = [value for value in comma_separated.split(",") if value]
    try:
        selected = {int(value) for value in values}
    except (TypeError, ValueError) as exc:
        raise ValidationError({"selected_user_ids": "사용자 ID가 올바르지 않습니다."}) from exc
    if any(user_id <= 0 for user_id in selected):
        raise ValidationError({"selected_user_ids": "사용자 ID가 올바르지 않습니다."})
    return selected


def _serialize_user(row, selected_user_ids):
    item = {
        "user_id": row.user_id,
        "participant_id": row.participant_id,
        "display_name": row.display_name,
        "selected": row.user_id in selected_user_ids,
    }
    if row.has_duplicate_name:
        item["email"] = mask_email(row.email) if row.email else None
        item["team"] = {"team_id": row.team_id, "team_name": row.team_name}
    return item


@require_GET
def current_team_participants(request):
    if not request.user.is_authenticated:
        return api_error(
            code="authentication_required",
            message="로그인이 필요합니다.",
            status=401,
            request_id=_request_id(request),
        )
    try:
        context = _resolve_context(request)
        selected_user_ids = _selected_user_ids(request) | {context.user_id}
        users = get_integration_repository().list_team_users(
            round_id=context.round_id,
            team_id=context.team_id,
        )
    except ValidationError as exc:
        return _validation_error(request, exc)
    except (PermissionDenied, IntegrationError) as exc:
        return _context_error(request, exc)
    return api_success(
        {
            "round_id": context.round_id,
            "team": {"team_id": context.team_id},
            "users": [_serialize_user(row, selected_user_ids) for row in users],
        },
        request_id=_request_id(request),
    )


@require_GET
def search_participants(request):
    if not request.user.is_authenticated:
        return api_error(
            code="authentication_required",
            message="로그인이 필요합니다.",
            status=401,
            request_id=_request_id(request),
        )
    query = request.GET.get("q", "").strip()
    if len(query) < settings.USER_SEARCH_MIN_LENGTH:
        return api_error(
            code="query_too_short",
            message=f"검색어를 {settings.USER_SEARCH_MIN_LENGTH}자 이상 입력해 주세요.",
            status=400,
            request_id=_request_id(request),
        )
    try:
        page = max(1, int(request.GET.get("page", "1")))
        requested_size = int(request.GET.get("page_size", str(settings.USER_SEARCH_PAGE_SIZE)))
        if requested_size <= 0:
            raise ValueError
        page_size = min(requested_size, settings.USER_SEARCH_MAX_PAGE_SIZE)
        context = _resolve_context(request)
        selected_user_ids = _selected_user_ids(request) | {context.user_id}
        result_page = get_integration_repository().search_round_users(
            query=query,
            round_id=context.round_id,
            team_id=None,
            page=page,
            page_size=page_size,
        )
    except (TypeError, ValueError):
        return api_error(
            code="invalid_parameter",
            message="페이지 값이 올바르지 않습니다.",
            status=400,
            request_id=_request_id(request),
        )
    except ValidationError as exc:
        return _validation_error(request, exc)
    except (PermissionDenied, IntegrationError) as exc:
        return _context_error(request, exc)
    return api_success(
        {
            "results": [_serialize_user(row, selected_user_ids) for row in result_page.results],
            "pagination": {
                "page": result_page.page,
                "page_size": result_page.page_size,
                "has_next": result_page.has_next,
            },
        },
        request_id=_request_id(request),
    )


@require_POST
def create_prd(request):
    if not request.user.is_authenticated:
        return api_error(
            code="authentication_required",
            message="로그인이 필요합니다.",
            status=401,
            request_id=_request_id(request),
        )
    try:
        payload = json.loads(request.body or b"{}")
        if not isinstance(payload, dict):
            raise ValidationError({"body": "JSON 객체가 필요합니다."})
        context = _resolve_context(request)
        command = _build_create_command(request, payload, context)
        prd, created = PrdCreationService(get_integration_repository()).create(command)
    except json.JSONDecodeError:
        return api_error(
            code="invalid_json",
            message="요청 본문이 올바른 JSON이 아닙니다.",
            status=400,
            request_id=_request_id(request),
        )
    except ValidationError as exc:
        return _validation_error(request, exc)
    except (PermissionDenied, IntegrationError) as exc:
        return _context_error(request, exc)

    participants = list(
        prd.participants.order_by("created_at", "id").values("user_id", "participant_id", "role")
    )
    return api_success(
        {
            "prd": {
                "id": prd.id,
                "prd_type": prd.prd_type,
                "title": prd.title,
                "description": prd.description,
                "deadline": prd.deadline.isoformat() if prd.deadline else None,
                "status": prd.status,
                "round_id": prd.round_id,
                "team_id": prd.team_id,
                "creator_user_id": prd.creator_user_id,
                "participants": participants,
            },
            "created": created,
        },
        status=201 if created else 200,
        request_id=_request_id(request),
    )


def _build_create_command(request, payload, context):
    title = payload.get("title", "")
    description = payload.get("description", "")
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValidationError({"body": "제목과 한 줄 소개는 문자열이어야 합니다."})
    if "\n" in description or "\r" in description:
        raise ValidationError({"description": "한 줄 소개에는 줄바꿈을 사용할 수 없습니다."})

    raw_participant_ids = payload.get("participant_user_ids", [])
    if not isinstance(raw_participant_ids, list):
        raise ValidationError({"participant_user_ids": "사용자 ID 배열이 필요합니다."})
    if any(
        isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0
        for user_id in raw_participant_ids
    ):
        raise ValidationError({"participant_user_ids": "사용자 ID가 올바르지 않습니다."})

    raw_deadline = payload.get("deadline")
    try:
        deadline = date.fromisoformat(raw_deadline) if raw_deadline else None
    except (TypeError, ValueError) as exc:
        raise ValidationError({"deadline": "날짜는 YYYY-MM-DD 형식이어야 합니다."}) from exc

    idempotency_key = request.headers.get("Idempotency-Key", "")
    return CreatePrdCommand(
        title=title,
        description=description,
        deadline=deadline,
        prd_type=payload.get("prd_type", ""),
        round_id=context.round_id,
        team_id=context.team_id,
        creator_user_id=context.user_id,
        idempotency_key=idempotency_key,
        participant_user_ids=tuple(raw_participant_ids),
    )


def _validation_error(request, exc):
    details = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
    return api_error(
        code="validation_error",
        message="입력값을 확인해 주세요.",
        status=400,
        details=details,
        request_id=_request_id(request),
    )
