from django.conf import settings
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse

from .responses import api_error, api_success


def root_entry(request: HttpRequest):
    """Send the bare domain to the correct first screen."""
    if request.user.is_authenticated:
        return redirect("ideas:home")
    login_name = "accounts_debug:login" if settings.DEBUG else "accounts:login"
    login_url = reverse(login_name)
    return redirect(f"{login_url}?next={reverse('ideas:home')}")


def health(request: HttpRequest):
    if request.method != "GET":
        return api_error(
            code="method_not_allowed",
            message="허용되지 않은 HTTP 메서드입니다.",
            status=405,
            request_id=getattr(request, "request_id", None),
        )
    return api_success(
        {
            "status": "ok",
            "service": "idea-developer",
            "api_version": settings.API_VERSION,
        },
        request_id=getattr(request, "request_id", None),
    )


def api_not_found(request: HttpRequest, exception):
    return api_error(
        code="not_found",
        message="요청한 API 경로를 찾을 수 없습니다.",
        status=404,
        request_id=getattr(request, "request_id", None),
    )


def csrf_failure(request: HttpRequest, reason=""):
    if request.path.startswith("/api/"):
        return api_error(
            code="csrf_failed",
            message="CSRF 검증에 실패했습니다.",
            status=403,
            request_id=getattr(request, "request_id", None),
        )
    from django.views.csrf import csrf_failure as django_csrf_failure

    return django_csrf_failure(request, reason=reason)
