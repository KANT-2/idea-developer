from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from .exceptions import NoActiveRound, RoundSelectionRequired
from .repository import DjangoViewIntegrationRepository, IntegrationRepository


@dataclass(frozen=True, slots=True)
class IntegrationContext:
    user_id: int
    round_id: int
    participant_id: int
    team_id: int
    parent_role: str | None
    is_staff: bool
    is_superuser: bool


class IntegrationContextResolver(Protocol):
    def resolve(
        self, request: HttpRequest, *, round_id: int | None = None
    ) -> IntegrationContext: ...


class ExternalUserIdMapper(Protocol):
    def map(self, user) -> int | None: ...


class UserAttributeExternalIdMapper:
    """Reads the explicit parent ID mapping from the local Django user adapter."""

    def map(self, user) -> int | None:
        external_user_id = getattr(user, "external_user_id", None)
        return int(external_user_id) if external_user_id is not None else None


class StandaloneSessionContextResolver:
    """Maps a local authenticated user and validates every round against the VIEW."""

    def __init__(
        self,
        repository: IntegrationRepository | None = None,
        user_id_mapper: ExternalUserIdMapper | None = None,
    ):
        self.repository = repository or DjangoViewIntegrationRepository()
        self.user_id_mapper = user_id_mapper or UserAttributeExternalIdMapper()

    def resolve(self, request: HttpRequest, *, round_id: int | None = None) -> IntegrationContext:
        user = request.user
        if not user.is_authenticated:
            raise PermissionDenied("Authentication is required.")

        external_user_id = self.user_id_mapper.map(user)
        if external_user_id is None:
            raise PermissionDenied("External user mapping is required.")

        parent_user = self.repository.get_user(external_user_id)
        if (
            parent_user is None
            or not parent_user.is_active
            or parent_user.approval_status != settings.INTEGRATION_APPROVED_USER_STATUS
        ):
            raise PermissionDenied("The mapped parent user is not active.")

        if round_id is None:
            active_memberships = self.repository.list_active_memberships(external_user_id)
            if not active_memberships:
                raise NoActiveRound("No active round is available.")
            if len(active_memberships) > 1:
                raise RoundSelectionRequired(active_memberships)
            membership = active_memberships[0]
        else:
            membership = self.repository.get_active_membership(external_user_id, int(round_id))
            if membership is None:
                raise PermissionDenied("The user does not participate in this round.")

        return IntegrationContext(
            user_id=external_user_id,
            round_id=membership.round_id,
            participant_id=membership.participant_id,
            team_id=membership.team_id,
            parent_role=parent_user.parent_role,
            is_staff=parent_user.is_staff,
            is_superuser=parent_user.is_superuser,
        )


class TestIntegrationContextResolver(StandaloneSessionContextResolver):
    """Resolver intended for a FixtureIntegrationRepository in unit tests."""
