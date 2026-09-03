from __future__ import annotations

from typing import Any

from django.http import JsonResponse


def api_success(
    data: Any = None,
    *,
    status: int = 200,
    request_id: str | None = None,
) -> JsonResponse:
    return JsonResponse(
        {
            "ok": True,
            "data": data,
            "error": None,
            "meta": {"request_id": request_id},
        },
        status=status,
    )


def api_error(
    *,
    code: str,
    message: str,
    status: int,
    details: Any = None,
    request_id: str | None = None,
) -> JsonResponse:
    return JsonResponse(
        {
            "ok": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "meta": {"request_id": request_id},
        },
        status=status,
    )
