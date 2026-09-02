from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.db import DatabaseError

from .exceptions import (
    IntegrationConfigurationError,
    IntegrationDataIntegrityError,
    IntegrationUnavailableError,
)
from .models import AxUserTeamLoginView, UserRoundTeamView

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParentUser:
    user_id: int
    parent_role: str | None
    is_active: bool
    is_staff: bool
    is_superuser: bool


@dataclass(frozen=True, slots=True)
class RoundMembership:
    user_id: int
    round_id: int
    round_title: str
    round_status: str
    participant_id: int
    team_id: int
    team_name: str


class IntegrationRepository(Protocol):
    def get_user(self, user_id: int) -> ParentUser | None: ...

    def get_membership(self, user_id: int, round_id: int) -> RoundMembership | None: ...

    def get_active_membership(self, user_id: int, round_id: int) -> RoundMembership | None: ...

    def list_active_memberships(self, user_id: int) -> tuple[RoundMembership, ...]: ...


class DjangoViewIntegrationRepository:
    """Reads only the two parent-owned PostgreSQL VIEWs."""

    def __init__(self, *, database_alias: str | None = None, active_statuses=None):
        self.database_alias = database_alias or settings.INTEGRATION_DB_ALIAS
        configured_statuses = (
            settings.INTEGRATION_ACTIVE_ROUND_STATUSES
            if active_statuses is None
            else active_statuses
        )
        self.active_statuses = frozenset(configured_statuses)

    def get_user(self, user_id: int) -> ParentUser | None:
        try:
            row = (
                AxUserTeamLoginView.objects.using(self.database_alias)
                .filter(user_id=user_id)
                .values("user_id", "role", "is_active", "is_staff", "is_superuser")
                .first()
            )
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        if row is None:
            return None
        return ParentUser(
            user_id=row["user_id"],
            parent_role=row["role"],
            is_active=row["is_active"],
            is_staff=row["is_staff"],
            is_superuser=row["is_superuser"],
        )

    def get_membership(self, user_id: int, round_id: int) -> RoundMembership | None:
        try:
            rows = list(
                UserRoundTeamView.objects.using(self.database_alias)
                .filter(user_id=user_id, round_id=round_id)
                .values(*self._membership_fields())[:2]
            )
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        if not rows:
            return None
        if len(rows) != 1:
            raise IntegrationDataIntegrityError(
                "Multiple team memberships exist for the requested user and round."
            )
        return self._to_membership(rows[0])

    def get_active_membership(self, user_id: int, round_id: int) -> RoundMembership | None:
        self._require_active_statuses()
        membership = self.get_membership(user_id, round_id)
        if membership is None or membership.round_status not in self.active_statuses:
            return None
        return membership

    def list_active_memberships(self, user_id: int) -> tuple[RoundMembership, ...]:
        self._require_active_statuses()
        try:
            rows = list(
                UserRoundTeamView.objects.using(self.database_alias)
                .filter(user_id=user_id, round_status__in=self.active_statuses)
                .order_by("round_id", "participant_id")
                .values(*self._membership_fields())
            )
        except DatabaseError as exc:
            self._raise_unavailable(exc)

        memberships = tuple(self._to_membership(row) for row in rows)
        round_ids = [membership.round_id for membership in memberships]
        if len(round_ids) != len(set(round_ids)):
            raise IntegrationDataIntegrityError(
                "Multiple team memberships exist in an active round."
            )
        return memberships

    @staticmethod
    def _membership_fields():
        return (
            "user_id",
            "round_id",
            "round_title",
            "round_status",
            "participant_id",
            "team_id",
            "team_name",
        )

    @staticmethod
    def _to_membership(row) -> RoundMembership:
        return RoundMembership(**row)

    @staticmethod
    def _raise_unavailable(exc: DatabaseError):
        logger.exception("Parent integration VIEW query failed")
        raise IntegrationUnavailableError("Parent integration VIEW is unavailable.") from exc

    def _require_active_statuses(self):
        if not self.active_statuses:
            raise IntegrationConfigurationError(
                "INTEGRATION_ACTIVE_ROUND_STATUSES must match the parent round status values."
            )


class FixtureIntegrationRepository:
    """In-memory fixture with the same fields used from the parent VIEWs."""

    def __init__(self, *, users=(), memberships=(), active_statuses=()):
        normalized_users = tuple(self._to_parent_user(user) for user in users)
        self.users = {user.user_id: user for user in normalized_users}
        self.memberships = tuple(self._to_round_membership(row) for row in memberships)
        self.active_statuses = frozenset(active_statuses)

    def get_user(self, user_id: int) -> ParentUser | None:
        return self.users.get(user_id)

    def get_membership(self, user_id: int, round_id: int) -> RoundMembership | None:
        matches = [
            row for row in self.memberships if row.user_id == user_id and row.round_id == round_id
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise IntegrationDataIntegrityError(
                "Multiple team memberships exist for the requested user and round."
            )
        return matches[0]

    def get_active_membership(self, user_id: int, round_id: int) -> RoundMembership | None:
        if not self.active_statuses:
            raise IntegrationConfigurationError("Fixture active statuses are required.")
        membership = self.get_membership(user_id, round_id)
        if membership is None or membership.round_status not in self.active_statuses:
            return None
        return membership

    def list_active_memberships(self, user_id: int) -> tuple[RoundMembership, ...]:
        if not self.active_statuses:
            raise IntegrationConfigurationError("Fixture active statuses are required.")
        matches = tuple(
            row
            for row in self.memberships
            if row.user_id == user_id and row.round_status in self.active_statuses
        )
        if len({row.round_id for row in matches}) != len(matches):
            raise IntegrationDataIntegrityError(
                "Multiple team memberships exist in an active round."
            )
        return matches

    @staticmethod
    def _to_parent_user(row) -> ParentUser:
        if isinstance(row, ParentUser):
            return row
        return ParentUser(
            user_id=row["user_id"],
            parent_role=row.get("role"),
            is_active=row["is_active"],
            is_staff=row["is_staff"],
            is_superuser=row["is_superuser"],
        )

    @staticmethod
    def _to_round_membership(row) -> RoundMembership:
        if isinstance(row, RoundMembership):
            return row
        return RoundMembership(
            user_id=row["user_id"],
            round_id=row["round_id"],
            round_title=row["round_title"],
            round_status=row["round_status"],
            participant_id=row["participant_id"],
            team_id=row["team_id"],
            team_name=row["team_name"],
        )
