from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.common.responses import api_error, api_success
from apps.integration.context import StandaloneSessionContextResolver
from apps.integration.exceptions import IntegrationError
from apps.integration.repository import DjangoViewIntegrationRepository

from .exceptions import AuthenticationFlowError
from .models import LoginAuditLog
from .services import OtpAuthenticationService, mask_email, record_audit


def get_authentication_service():
    return OtpAuthenticationService()


def get_integration_repository():
    return DjangoViewIntegrationRepository()


def get_context_resolver():
    return StandaloneSessionContextResolver()


def _safe_next(request, candidate):
    if (
        candidate
        and candidate.startswith("/")
        and not candidate.startswith("//")
        and url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return candidate
    return None


def _default_success_url():
    return reverse("ideas:home")


def _json_body(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@require_GET
def login_page(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request, request.GET.get("next")) or _default_success_url())
    safe_next = _safe_next(request, request.GET.get("next"))
    if safe_next:
        request.session["authentication_next"] = safe_next
    else:
        request.session.pop("authentication_next", None)
    return render(request, "accounts/login.html")


@require_POST
def request_otp(request):
    payload = _json_body(request)
    if payload is None:
        return api_error(
            code="invalid_json",
            message="요청 형식이 올바르지 않습니다.",
            status=400,
            request_id=getattr(request, "request_id", None),
        )
    try:
        result = get_authentication_service().request_code(request, payload.get("email", ""))
    except AuthenticationFlowError as exc:
        response = api_error(
            code=exc.code,
            message=exc.message,
            status=exc.status,
            details={"retry_after": exc.retry_after} if exc.retry_after else None,
            request_id=getattr(request, "request_id", None),
        )
        if exc.retry_after:
            response["Retry-After"] = str(exc.retry_after)
        return response
    except IntegrationError:
        return api_error(
            code="integration_unavailable",
            message="인증 정보를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            status=503,
            request_id=getattr(request, "request_id", None),
        )

    return api_success(
        {
            "challenge_id": result.challenge_id,
            "masked_email": result.masked_email,
            "expires_in_seconds": result.expires_in_seconds,
            "resend_after_seconds": result.resend_after_seconds,
            "message": result.message,
        },
        status=202,
        request_id=getattr(request, "request_id", None),
    )


@require_POST
def verify_otp(request):
    payload = _json_body(request)
    if payload is None:
        return api_error(
            code="invalid_json",
            message="요청 형식이 올바르지 않습니다.",
            status=400,
            request_id=getattr(request, "request_id", None),
        )
    try:
        get_authentication_service().verify_code(
            request,
            challenge_id=payload.get("challenge_id"),
            code=payload.get("code", ""),
        )
    except AuthenticationFlowError as exc:
        return api_error(
            code=exc.code,
            message=exc.message,
            status=exc.status,
            request_id=getattr(request, "request_id", None),
        )
    except IntegrationError:
        return api_error(
            code="integration_unavailable",
            message="인증 정보를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            status=503,
            request_id=getattr(request, "request_id", None),
        )

    redirect_url = _safe_next(request, request.session.pop("authentication_next", None))
    return api_success(
        {"redirect_url": redirect_url or _default_success_url()},
        request_id=getattr(request, "request_id", None),
    )


@require_POST
def logout_view(request):
    external_user_id = getattr(request.user, "external_user_id", None)
    if request.user.is_authenticated:
        record_audit(
            request,
            LoginAuditLog.Event.LOGOUT,
            external_user_id=external_user_id,
        )
    logout(request)
    return redirect("accounts:login")


@require_GET
def session_home(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?next={reverse('ideas:home')}")
    return render(request, "accounts/session_home.html")


@require_GET
def user_search(request):
    if not request.user.is_authenticated:
        return api_error(
            code="authentication_required",
            message="로그인이 필요합니다.",
            status=401,
            request_id=getattr(request, "request_id", None),
        )
    query = request.GET.get("q", "").strip()
    if len(query) < settings.USER_SEARCH_MIN_LENGTH:
        return api_error(
            code="query_too_short",
            message=f"검색어를 {settings.USER_SEARCH_MIN_LENGTH}자 이상 입력해 주세요.",
            status=400,
            request_id=getattr(request, "request_id", None),
        )
    try:
        round_id = int(request.GET.get("round_id", ""))
        page = max(1, int(request.GET.get("page", "1")))
        requested_page_size = int(request.GET.get("page_size", str(settings.USER_SEARCH_PAGE_SIZE)))
        if requested_page_size <= 0:
            raise ValueError
        page_size = min(requested_page_size, settings.USER_SEARCH_MAX_PAGE_SIZE)
        team_value = request.GET.get("team_id")
        team_id = int(team_value) if team_value else None
    except (TypeError, ValueError):
        return api_error(
            code="invalid_parameter",
            message="회차, 팀 또는 페이지 값이 올바르지 않습니다.",
            status=400,
            request_id=getattr(request, "request_id", None),
        )

    try:
        context = get_context_resolver().resolve(request, round_id=round_id)
        if team_id is not None and team_id != context.team_id:
            raise PermissionDenied
        result_page = get_integration_repository().search_round_users(
            query=query,
            round_id=context.round_id,
            team_id=team_id,
            page=page,
            page_size=page_size,
        )
    except PermissionDenied:
        return api_error(
            code="permission_denied",
            message="이 회차 또는 팀의 사용자를 검색할 권한이 없습니다.",
            status=403,
            request_id=getattr(request, "request_id", None),
        )
    except IntegrationError:
        return api_error(
            code="integration_unavailable",
            message="사용자 정보를 조회할 수 없습니다.",
            status=503,
            request_id=getattr(request, "request_id", None),
        )

    results = []
    for row in result_page.results:
        item = {
            "user_id": row.user_id,
            "participant_id": row.participant_id,
            "display_name": row.display_name,
        }
        if row.has_duplicate_name:
            item["email"] = mask_email(row.email) if row.email else None
            item["team"] = {"team_id": row.team_id, "team_name": row.team_name}
        results.append(item)
    return api_success(
        {
            "results": results,
            "pagination": {
                "page": result_page.page,
                "page_size": result_page.page_size,
                "has_next": result_page.has_next,
            },
        },
        request_id=getattr(request, "request_id", None),
    )


@require_http_methods(["GET", "POST"])
def debug_login(request):
    if not settings.DEBUG:
        raise Http404

    repository = get_integration_repository()
    if request.method == "POST":
        try:
            external_user_id = int(request.POST.get("external_user_id", ""))
        except (TypeError, ValueError):
            return HttpResponseBadRequest("올바른 사용자 ID가 아닙니다.")
        try:
            identity = repository.get_login_identity(external_user_id)
        except IntegrationError:
            return render(request, "integration/unavailable.html", status=503)
        if identity is None:
            raise PermissionDenied
        get_authentication_service().create_debug_session(request, identity)
        return redirect(_safe_next(request, request.POST.get("next")) or _default_success_url())

    query = request.GET.get("q", "").strip()
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1
    result_page = None
    if len(query) >= settings.USER_SEARCH_MIN_LENGTH:
        try:
            result_page = repository.search_login_users(
                query=query,
                page=page,
                page_size=settings.USER_SEARCH_PAGE_SIZE,
            )
        except IntegrationError:
            return render(request, "integration/unavailable.html", status=503)
    return render(
        request,
        "accounts/debug_login.html",
        {"query": query, "result_page": result_page},
    )
