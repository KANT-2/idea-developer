from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render
from django.utils.module_loading import import_string
from django.views.decorators.http import require_http_methods

from .exceptions import (
    IntegrationConfigurationError,
    IntegrationDataIntegrityError,
    IntegrationUnavailableError,
    NoActiveRound,
    RoundSelectionRequired,
)

logger = logging.getLogger(__name__)


def get_context_resolver():
    resolver_class = import_string(settings.INTEGRATION_CONTEXT_RESOLVER_CLASS)
    return resolver_class()


@require_http_methods(["GET", "POST"])
def round_context(request: HttpRequest):
    if not request.user.is_authenticated:
        return HttpResponseForbidden("로그인이 필요합니다.")

    round_source = None
    if request.method == "POST":
        raw_round_id = request.POST.get("round_id")
        round_source = "request"
    elif request.GET.get("round_id") is not None:
        raw_round_id = request.GET["round_id"]
        round_source = "request"
    else:
        raw_round_id = request.session.get("selected_round_id")
        round_source = "session" if raw_round_id is not None else None
    try:
        round_id = int(raw_round_id) if raw_round_id is not None else None
        if round_id is not None and round_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return HttpResponseBadRequest("올바른 회차 ID가 아닙니다.")

    try:
        resolver = get_context_resolver()
        try:
            context = resolver.resolve(request, round_id=round_id)
        except PermissionDenied:
            if round_source != "session":
                raise
            request.session.pop("selected_round_id", None)
            context = resolver.resolve(request)
    except NoActiveRound:
        request.session.pop("selected_round_id", None)
        return render(request, "integration/no_round.html")
    except RoundSelectionRequired as exc:
        return render(
            request,
            "integration/select_round.html",
            {"rounds": exc.rounds},
        )
    except PermissionDenied:
        return render(request, "403.html", status=403)
    except (
        IntegrationUnavailableError,
        IntegrationConfigurationError,
        IntegrationDataIntegrityError,
    ):
        logger.exception("Integration context could not be resolved")
        return render(request, "integration/unavailable.html", status=503)

    if request.method == "POST":
        request.session["selected_round_id"] = context.round_id
    return render(
        request,
        "integration/context_ready.html",
        {"integration_context": context},
    )
