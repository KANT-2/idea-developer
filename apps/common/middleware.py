from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .context import request_id_var
from .responses import api_error

logger = logging.getLogger(__name__)


class RequestContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)


class ApiExceptionMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            response = self.get_response(request)
        except Exception:
            if not request.path.startswith("/api/"):
                raise
            logger.exception("Unhandled API exception")
            return api_error(
                code="internal_error",
                message="요청을 처리하는 중 오류가 발생했습니다.",
                status=500,
                request_id=getattr(request, "request_id", None),
            )
        if settings.DEBUG and response.status_code == 404:
            if request.path.startswith("/api/"):
                return api_error(
                    code="not_found",
                    message="요청한 API 경로를 찾을 수 없습니다.",
                    status=404,
                    request_id=getattr(request, "request_id", None),
                )
            return render(request, "404.html", status=404)
        return response
