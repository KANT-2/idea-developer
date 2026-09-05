from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from .exceptions import RoundSelectionRequired
from .repository import IntegrationRepository, get_default_integration_repository

PARENT_TUTOR_ROLE = "tutor"
PARENT_ADMIN_ROLE = "admin"


@dataclass(frozen=True, slots=True)
class IntegrationContext:
    user_id: int
    round_id: int | None
    participant_id: int | None
    team_id: int | None
    parent_role: str | None
    is_staff: bool
    is_superuser: bool


def is_tutor_parent_identity(parent_role: str | None) -> bool:
    return (parent_role or "").strip().lower() == PARENT_TUTOR_ROLE


def is_admin_parent_identity(
    *, parent_role: str | None, is_staff: bool, is_superuser: bool
) -> bool:
    normalized_role = (parent_role or "").strip().lower()
    if normalized_role == PARENT_TUTOR_ROLE:
        return False
    return bool(normalized_role == PARENT_ADMIN_ROLE or is_staff or is_superuser)


def is_tutor_context(context: IntegrationContext) -> bool:
    return is_tutor_parent_identity(context.parent_role)


def is_admin_context(context: IntegrationContext) -> bool:
    return is_admin_parent_identity(
        parent_role=context.parent_role,
        is_staff=context.is_staff,
        is_superuser=context.is_superuser,
    )


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
        self.repository = repository or get_default_integration_repository()
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
                return IntegrationContext(
                    user_id=external_user_id,
                    round_id=None,
                    participant_id=None,
                    team_id=None,
                    parent_role=parent_user.parent_role,
                    is_staff=parent_user.is_staff,
                    is_superuser=parent_user.is_superuser,
                )
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
