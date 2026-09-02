from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest


@dataclass(frozen=True, slots=True)
class IntegrationContext:
    external_user_id: int
    round_id: int
    participant_id: int | None
    team_id: int | None
    user_role: str | None
    is_staff: bool
    is_superuser: bool


class IntegrationContextResolver(Protocol):
    def resolve(self, request: HttpRequest, *, round_id: int) -> IntegrationContext: ...


class StandaloneSessionContextResolver:
    """Builds context from an authenticated local session principal.

    VIEW validation is intentionally deferred to the integration feature step.
    """

    def resolve(self, request: HttpRequest, *, round_id: int) -> IntegrationContext:
        user = request.user
        if not user.is_authenticated:
            raise PermissionDenied("Authentication is required.")

        external_user_id = getattr(user, "external_user_id", None)
        if external_user_id is None:
            raise PermissionDenied("External user mapping is required.")

        return IntegrationContext(
            external_user_id=int(external_user_id),
            round_id=int(round_id),
            participant_id=request.session.get("participant_id"),
            team_id=request.session.get("team_id"),
            user_role=request.session.get("user_role"),
            is_staff=bool(user.is_staff),
            is_superuser=bool(user.is_superuser),
        )
