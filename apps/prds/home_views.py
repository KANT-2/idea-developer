from __future__ import annotations

from datetime import date

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_GET

from apps.common.responses import api_error, api_success
from apps.integration.exceptions import IntegrationError

from .home import HomeFilters, HomeQueryService
from .views import (
    _context_error,
    _request_id,
    _resolve_context,
    get_integration_repository,
)


def _multiple_values(request, name):
    values = request.GET.getlist(name)
    if len(values) == 1 and "," in values[0]:
        values = values[0].split(",")
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _optional_date(request, name):
    value = request.GET.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: "날짜는 YYYY-MM-DD 형식이어야 합니다."}) from exc


def _optional_positive_int(request, name):
    value = request.GET.get(name)
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError({name: "양의 정수가 필요합니다."}) from exc
    if parsed <= 0:
        raise ValidationError({name: "양의 정수가 필요합니다."})
    return parsed


def _parse_filters(request):
    try:
        page = int(request.GET.get("page", "1"))
        requested_page_size = int(request.GET.get("page_size", str(settings.HOME_PAGE_SIZE)))
    except ValueError as exc:
        raise ValidationError({"pagination": "페이지 값은 정수여야 합니다."}) from exc
    return HomeFilters(
        tab=request.GET.get("tab", "all"),
        statuses=_multiple_values(request, "status"),
        prd_types=_multiple_values(request, "prd_type"),
        deadline_from=_optional_date(request, "deadline_from"),
        deadline_to=_optional_date(request, "deadline_to"),
        participant_user_id=_optional_positive_int(request, "participant_user_id"),
        team_id=_optional_positive_int(request, "team_id"),
        sort=request.GET.get("sort", "default"),
        page=page,
        page_size=min(requested_page_size, settings.HOME_MAX_PAGE_SIZE),
    )


@require_GET
def home(request):
    if not request.user.is_authenticated:
        return api_error(
            code="authentication_required",
            message="로그인이 필요합니다.",
            status=401,
            request_id=_request_id(request),
        )
    try:
        context = _resolve_context(request)
        filters = _parse_filters(request)
        data = HomeQueryService(get_integration_repository()).get_home(
            context=context,
            filters=filters,
        )
    except ValidationError as exc:
        details = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        return api_error(
            code="validation_error",
            message="필터 값을 확인해 주세요.",
            status=400,
            details=details,
            request_id=_request_id(request),
        )
    except (PermissionDenied, IntegrationError) as exc:
        return _context_error(request, exc)
    return api_success(data, request_id=_request_id(request))
