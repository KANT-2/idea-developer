from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.db import DatabaseError, connections
from django.db.models import Q

from .exceptions import (
    IntegrationConfigurationError,
    IntegrationDataIntegrityError,
    IntegrationUnavailableError,
)
from .models import AxUserTeamLoginView, UserRoundTeamView

logger = logging.getLogger(__name__)


def escape_like_pattern(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


@dataclass(frozen=True, slots=True)
class ParentUser:
    user_id: int
    parent_role: str | None
    approval_status: str | None
    is_active: bool
    is_staff: bool
    is_superuser: bool
    user_email: str | None
    primary_email: str | None


@dataclass(frozen=True, slots=True)
class LoginIdentity:
    user_id: int
    email: str


@dataclass(frozen=True, slots=True)
class UserSearchResult:
    user_id: int
    participant_id: int | None
    display_name: str
    email: str | None
    team_id: int | None
    team_name: str | None
    has_duplicate_name: bool


@dataclass(frozen=True, slots=True)
class RoundUserSummary:
    user_id: int
    participant_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class SearchPage:
    results: tuple
    page: int
    page_size: int
    has_next: bool


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

    def find_login_identity(self, normalized_email: str) -> LoginIdentity | None: ...

    def get_login_identity(self, user_id: int) -> LoginIdentity | None: ...

    def search_round_users(
        self, *, query: str, round_id: int, team_id: int | None, page: int, page_size: int
    ) -> SearchPage: ...

    def search_login_users(self, *, query: str, page: int, page_size: int) -> SearchPage: ...

    def list_team_users(self, *, round_id: int, team_id: int) -> tuple[UserSearchResult, ...]: ...

    def get_eligible_memberships(
        self, *, user_ids: tuple[int, ...], round_id: int
    ) -> tuple[RoundMembership, ...]: ...

    def get_round_user_summaries(
        self, *, user_ids: tuple[int, ...], round_id: int
    ) -> dict[int, RoundUserSummary]: ...


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
                .values(
                    "user_id",
                    "role",
                    "approval_status",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "user_email",
                    "primary_email",
                )
                .first()
            )
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        if row is None:
            return None
        return ParentUser(
            user_id=row["user_id"],
            parent_role=row["role"],
            approval_status=row["approval_status"],
            is_active=row["is_active"],
            is_staff=row["is_staff"],
            is_superuser=row["is_superuser"],
            user_email=row["user_email"],
            primary_email=row["primary_email"],
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

    def find_login_identity(self, normalized_email: str) -> LoginIdentity | None:
        try:
            rows = list(
                AxUserTeamLoginView.objects.using(self.database_alias)
                .filter(
                    Q(user_email__iexact=normalized_email)
                    | Q(primary_email__iexact=normalized_email),
                    is_active=True,
                    approval_status=settings.INTEGRATION_APPROVED_USER_STATUS,
                )
                .values("user_id", "user_email", "primary_email")[:2]
            )
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        if not rows:
            return None
        if len(rows) != 1:
            raise IntegrationDataIntegrityError("The login email maps to multiple users.")
        return self._to_login_identity(rows[0], fallback_email=normalized_email)

    def get_login_identity(self, user_id: int) -> LoginIdentity | None:
        try:
            row = (
                AxUserTeamLoginView.objects.using(self.database_alias)
                .filter(
                    user_id=user_id,
                    is_active=True,
                    approval_status=settings.INTEGRATION_APPROVED_USER_STATUS,
                )
                .values("user_id", "user_email", "primary_email")
                .first()
            )
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        if row is None:
            return None
        return self._to_login_identity(row)

    def search_round_users(
        self,
        *,
        query: str,
        round_id: int,
        team_id: int | None,
        page: int,
        page_size: int,
    ) -> SearchPage:
        offset = (page - 1) * page_size
        effective_name = """
            COALESCE(
                NULLIF(BTRIM(urt.display_name_snapshot), ''),
                NULLIF(BTRIM(CONCAT_WS(' ', aut.first_name, aut.last_name)), ''),
                aut.primary_email,
                aut.user_email
            )
        """
        team_clause = "AND urt.team_id = %s" if team_id is not None else ""
        sql = f"""
            WITH candidates AS (
                SELECT
                    urt.user_id,
                    urt.participant_id,
                    {effective_name} AS display_name,
                    COALESCE(aut.primary_email, aut.user_email) AS email,
                    urt.team_id,
                    urt.team_name,
                    COUNT(*) OVER (
                        PARTITION BY LOWER({effective_name})
                    ) AS duplicate_name_count
                FROM public.user_round_team_view AS urt
                INNER JOIN public.ax_user_team_login_view AS aut
                    ON aut.user_id = urt.user_id
                WHERE urt.round_id = %s
                  {team_clause}
                  AND aut.is_active = TRUE
                  AND aut.approval_status = %s
                  AND {effective_name} ILIKE %s ESCAPE '!'
            )
            SELECT
                user_id,
                participant_id,
                display_name,
                email,
                team_id,
                team_name,
                duplicate_name_count
            FROM candidates
            ORDER BY LOWER(display_name), user_id
            LIMIT %s OFFSET %s
        """
        params = [round_id]
        if team_id is not None:
            params.append(team_id)
        params.extend(
            [
                settings.INTEGRATION_APPROVED_USER_STATUS,
                f"%{escape_like_pattern(query)}%",
                page_size + 1,
                offset,
            ]
        )
        try:
            with connections[self.database_alias].cursor() as cursor:
                cursor.execute(sql, params)
                columns = [column[0] for column in cursor.description]
                rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        except DatabaseError as exc:
            self._raise_unavailable(exc)

        has_next = len(rows) > page_size
        results = tuple(
            UserSearchResult(
                user_id=row["user_id"],
                participant_id=row["participant_id"],
                display_name=row["display_name"],
                email=row["email"],
                team_id=row["team_id"],
                team_name=row["team_name"],
                has_duplicate_name=row["duplicate_name_count"] > 1,
            )
            for row in rows[:page_size]
        )
        return SearchPage(results=results, page=page, page_size=page_size, has_next=has_next)

    def search_login_users(self, *, query: str, page: int, page_size: int) -> SearchPage:
        offset = (page - 1) * page_size
        effective_name = """
            COALESCE(
                NULLIF(BTRIM(aut.display_name_snapshot), ''),
                NULLIF(BTRIM(CONCAT_WS(' ', aut.first_name, aut.last_name)), ''),
                aut.primary_email,
                aut.user_email
            )
        """
        sql = f"""
            WITH candidates AS (
                SELECT
                    aut.user_id,
                    {effective_name} AS display_name,
                    COALESCE(aut.primary_email, aut.user_email) AS email,
                    COUNT(*) OVER (PARTITION BY LOWER({effective_name})) AS duplicate_name_count
                FROM public.ax_user_team_login_view AS aut
                WHERE aut.is_active = TRUE
                  AND aut.approval_status = %s
                  AND {effective_name} ILIKE %s ESCAPE '!'
            )
            SELECT user_id, display_name, email, duplicate_name_count
            FROM candidates
            ORDER BY LOWER(display_name), user_id
            LIMIT %s OFFSET %s
        """
        try:
            with connections[self.database_alias].cursor() as cursor:
                cursor.execute(
                    sql,
                    [
                        settings.INTEGRATION_APPROVED_USER_STATUS,
                        f"%{escape_like_pattern(query)}%",
                        page_size + 1,
                        offset,
                    ],
                )
                columns = [column[0] for column in cursor.description]
                rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        return SearchPage(
            results=tuple(
                UserSearchResult(
                    user_id=row["user_id"],
                    participant_id=None,
                    display_name=row["display_name"],
                    email=row["email"],
                    team_id=None,
                    team_name=None,
                    has_duplicate_name=row["duplicate_name_count"] > 1,
                )
                for row in rows[:page_size]
            ),
            page=page,
            page_size=page_size,
            has_next=len(rows) > page_size,
        )

    def list_team_users(self, *, round_id: int, team_id: int) -> tuple[UserSearchResult, ...]:
        effective_name = """
            COALESCE(
                NULLIF(BTRIM(urt.display_name_snapshot), ''),
                NULLIF(BTRIM(CONCAT_WS(' ', aut.first_name, aut.last_name)), ''),
                aut.primary_email,
                aut.user_email
            )
        """
        sql = f"""
            WITH candidates AS (
                SELECT
                    urt.user_id,
                    urt.participant_id,
                    {effective_name} AS display_name,
                    COALESCE(aut.primary_email, aut.user_email) AS email,
                    urt.team_id,
                    urt.team_name,
                    COUNT(*) OVER (
                        PARTITION BY LOWER({effective_name})
                    ) AS duplicate_name_count
                FROM public.user_round_team_view AS urt
                INNER JOIN public.ax_user_team_login_view AS aut
                    ON aut.user_id = urt.user_id
                WHERE urt.round_id = %s
                  AND urt.team_id = %s
                  AND aut.is_active = TRUE
                  AND aut.approval_status = %s
            )
            SELECT
                user_id,
                participant_id,
                display_name,
                email,
                team_id,
                team_name,
                duplicate_name_count
            FROM candidates
            ORDER BY LOWER(display_name), user_id
        """
        try:
            with connections[self.database_alias].cursor() as cursor:
                cursor.execute(
                    sql,
                    [round_id, team_id, settings.INTEGRATION_APPROVED_USER_STATUS],
                )
                columns = [column[0] for column in cursor.description]
                rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        return tuple(
            UserSearchResult(
                user_id=row["user_id"],
                participant_id=row["participant_id"],
                display_name=row["display_name"],
                email=row["email"],
                team_id=row["team_id"],
                team_name=row["team_name"],
                has_duplicate_name=row["duplicate_name_count"] > 1,
            )
            for row in rows
        )

    def get_eligible_memberships(
        self, *, user_ids: tuple[int, ...], round_id: int
    ) -> tuple[RoundMembership, ...]:
        self._require_active_statuses()
        if not user_ids:
            return ()
        try:
            active_user_ids = set(
                AxUserTeamLoginView.objects.using(self.database_alias)
                .filter(
                    user_id__in=user_ids,
                    is_active=True,
                    approval_status=settings.INTEGRATION_APPROVED_USER_STATUS,
                )
                .values_list("user_id", flat=True)
            )
            rows = list(
                UserRoundTeamView.objects.using(self.database_alias)
                .filter(
                    user_id__in=active_user_ids,
                    round_id=round_id,
                    round_status__in=self.active_statuses,
                )
                .values(*self._membership_fields())
            )
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        memberships = tuple(self._to_membership(row) for row in rows)
        found_user_ids = [membership.user_id for membership in memberships]
        found_participant_ids = [membership.participant_id for membership in memberships]
        if len(found_user_ids) != len(set(found_user_ids)) or len(found_participant_ids) != len(
            set(found_participant_ids)
        ):
            raise IntegrationDataIntegrityError(
                "Duplicate user or participant memberships exist in the selected round."
            )
        return memberships

    def get_round_user_summaries(
        self, *, user_ids: tuple[int, ...], round_id: int
    ) -> dict[int, RoundUserSummary]:
        if not user_ids:
            return {}
        try:
            membership_rows = list(
                UserRoundTeamView.objects.using(self.database_alias)
                .filter(user_id__in=user_ids, round_id=round_id)
                .values(
                    "user_id",
                    "participant_id",
                    "display_name_snapshot",
                    "email",
                )
            )
            user_rows = {
                row["user_id"]: row
                for row in AxUserTeamLoginView.objects.using(self.database_alias)
                .filter(user_id__in=user_ids)
                .values(
                    "user_id",
                    "first_name",
                    "last_name",
                    "primary_email",
                    "user_email",
                )
            }
        except DatabaseError as exc:
            self._raise_unavailable(exc)
        if len({row["user_id"] for row in membership_rows}) != len(membership_rows):
            raise IntegrationDataIntegrityError(
                "Multiple memberships exist for a card participant in the selected round."
            )
        summaries = {}
        for membership in membership_rows:
            user = user_rows.get(membership["user_id"], {})
            full_name = " ".join(
                part for part in (user.get("first_name"), user.get("last_name")) if part
            )
            display_name = (
                membership.get("display_name_snapshot")
                or full_name
                or user.get("primary_email")
                or membership.get("email")
                or user.get("user_email")
                or f"사용자 {membership['user_id']}"
            )
            summaries[membership["user_id"]] = RoundUserSummary(
                user_id=membership["user_id"],
                participant_id=membership["participant_id"],
                display_name=display_name,
            )
        return summaries

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
    def _to_login_identity(row, fallback_email="") -> LoginIdentity:
        return LoginIdentity(
            user_id=row["user_id"],
            email=row.get("primary_email") or row.get("user_email") or fallback_email,
        )

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
        self.user_rows = tuple(dict(user) if isinstance(user, dict) else user for user in users)
        self.membership_rows = tuple(
            dict(row) if isinstance(row, dict) else row for row in memberships
        )
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

    def find_login_identity(self, normalized_email: str) -> LoginIdentity | None:
        matches = [
            row
            for row in self.user_rows
            if isinstance(row, dict)
            and row["is_active"]
            and row.get("approval_status") == settings.INTEGRATION_APPROVED_USER_STATUS
            and normalized_email
            in {
                (row.get("user_email") or "").lower(),
                (row.get("primary_email") or "").lower(),
            }
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise IntegrationDataIntegrityError("The login email maps to multiple users.")
        return self._to_login_identity(matches[0], fallback_email=normalized_email)

    def get_login_identity(self, user_id: int) -> LoginIdentity | None:
        for row in self.user_rows:
            if (
                isinstance(row, dict)
                and row["user_id"] == user_id
                and row["is_active"]
                and row.get("approval_status") == settings.INTEGRATION_APPROVED_USER_STATUS
            ):
                return self._to_login_identity(row)
        return None

    def search_round_users(
        self,
        *,
        query: str,
        round_id: int,
        team_id: int | None,
        page: int,
        page_size: int,
    ) -> SearchPage:
        users_by_id = {
            row["user_id"]: row
            for row in self.user_rows
            if isinstance(row, dict)
            and row["is_active"]
            and row.get("approval_status") == settings.INTEGRATION_APPROVED_USER_STATUS
        }
        candidates = []
        for row in self.membership_rows:
            if not isinstance(row, dict) or row["round_id"] != round_id:
                continue
            if team_id is not None and row["team_id"] != team_id:
                continue
            user = users_by_id.get(row["user_id"])
            if user is None:
                continue
            full_name = " ".join(
                part for part in (user.get("first_name"), user.get("last_name")) if part
            )
            display_name = (
                row.get("display_name_snapshot")
                or full_name
                or user.get("primary_email")
                or user.get("user_email")
            )
            if query.casefold() not in display_name.casefold():
                continue
            candidates.append((row, user, display_name))

        name_counts = {}
        for _, _, display_name in candidates:
            key = display_name.casefold()
            name_counts[key] = name_counts.get(key, 0) + 1
        candidates.sort(key=lambda item: (item[2].casefold(), item[0]["user_id"]))
        offset = (page - 1) * page_size
        page_rows = candidates[offset : offset + page_size + 1]
        return SearchPage(
            results=tuple(
                UserSearchResult(
                    user_id=row["user_id"],
                    participant_id=row["participant_id"],
                    display_name=display_name,
                    email=user.get("primary_email") or user.get("user_email"),
                    team_id=row["team_id"],
                    team_name=row["team_name"],
                    has_duplicate_name=name_counts[display_name.casefold()] > 1,
                )
                for row, user, display_name in page_rows[:page_size]
            ),
            page=page,
            page_size=page_size,
            has_next=len(page_rows) > page_size,
        )

    def search_login_users(self, *, query: str, page: int, page_size: int) -> SearchPage:
        matching = []
        for row in self.user_rows:
            if not isinstance(row, dict):
                continue
            if not row["is_active"] or (
                row.get("approval_status") != settings.INTEGRATION_APPROVED_USER_STATUS
            ):
                continue
            searchable = " ".join(
                str(row.get(field) or "")
                for field in (
                    "user_email",
                    "primary_email",
                    "first_name",
                    "last_name",
                    "display_name_snapshot",
                )
            )
            if query.casefold() in searchable.casefold():
                matching.append(row)
        candidates = []
        for row in matching:
            full_name = " ".join(
                part for part in (row.get("first_name"), row.get("last_name")) if part
            )
            display_name = (
                row.get("display_name_snapshot")
                or full_name
                or row.get("primary_email")
                or row.get("user_email")
            )
            candidates.append((row, display_name))
        name_counts = {}
        for _, display_name in candidates:
            key = display_name.casefold()
            name_counts[key] = name_counts.get(key, 0) + 1
        candidates.sort(key=lambda item: (item[1].casefold(), item[0]["user_id"]))
        offset = (page - 1) * page_size
        page_rows = candidates[offset : offset + page_size + 1]
        return SearchPage(
            results=tuple(
                UserSearchResult(
                    user_id=row["user_id"],
                    participant_id=None,
                    display_name=display_name,
                    email=row.get("primary_email") or row.get("user_email"),
                    team_id=None,
                    team_name=None,
                    has_duplicate_name=name_counts[display_name.casefold()] > 1,
                )
                for row, display_name in page_rows[:page_size]
            ),
            page=page,
            page_size=page_size,
            has_next=len(page_rows) > page_size,
        )

    def list_team_users(self, *, round_id: int, team_id: int) -> tuple[UserSearchResult, ...]:
        users_by_id = {
            row["user_id"]: row
            for row in self.user_rows
            if isinstance(row, dict)
            and row["is_active"]
            and row.get("approval_status") == settings.INTEGRATION_APPROVED_USER_STATUS
        }
        candidates = []
        for row in self.membership_rows:
            if (
                not isinstance(row, dict)
                or row["round_id"] != round_id
                or row["team_id"] != team_id
            ):
                continue
            user = users_by_id.get(row["user_id"])
            if user is None:
                continue
            full_name = " ".join(
                part for part in (user.get("first_name"), user.get("last_name")) if part
            )
            display_name = (
                row.get("display_name_snapshot")
                or full_name
                or user.get("primary_email")
                or user.get("user_email")
            )
            candidates.append((row, user, display_name))
        name_counts = {}
        for _, _, display_name in candidates:
            key = display_name.casefold()
            name_counts[key] = name_counts.get(key, 0) + 1
        candidates.sort(key=lambda item: (item[2].casefold(), item[0]["user_id"]))
        return tuple(
            UserSearchResult(
                user_id=row["user_id"],
                participant_id=row["participant_id"],
                display_name=display_name,
                email=user.get("primary_email") or user.get("user_email"),
                team_id=row["team_id"],
                team_name=row["team_name"],
                has_duplicate_name=name_counts[display_name.casefold()] > 1,
            )
            for row, user, display_name in candidates
        )

    def get_eligible_memberships(
        self, *, user_ids: tuple[int, ...], round_id: int
    ) -> tuple[RoundMembership, ...]:
        if not self.active_statuses:
            raise IntegrationConfigurationError("Fixture active statuses are required.")
        eligible_users = {
            user_id
            for user_id in user_ids
            if (user := self.users.get(user_id)) is not None
            and user.is_active
            and user.approval_status == settings.INTEGRATION_APPROVED_USER_STATUS
        }
        memberships = tuple(
            row
            for row in self.memberships
            if row.user_id in eligible_users
            and row.round_id == round_id
            and row.round_status in self.active_statuses
        )
        found_user_ids = [membership.user_id for membership in memberships]
        found_participant_ids = [membership.participant_id for membership in memberships]
        if len(found_user_ids) != len(set(found_user_ids)) or len(found_participant_ids) != len(
            set(found_participant_ids)
        ):
            raise IntegrationDataIntegrityError(
                "Duplicate user or participant memberships exist in the selected round."
            )
        return memberships

    def get_round_user_summaries(
        self, *, user_ids: tuple[int, ...], round_id: int
    ) -> dict[int, RoundUserSummary]:
        requested_user_ids = set(user_ids)
        users_by_id = {row["user_id"]: row for row in self.user_rows if isinstance(row, dict)}
        matching_rows = [
            row
            for row in self.membership_rows
            if isinstance(row, dict)
            and row["user_id"] in requested_user_ids
            and row["round_id"] == round_id
        ]
        if len({row["user_id"] for row in matching_rows}) != len(matching_rows):
            raise IntegrationDataIntegrityError(
                "Multiple memberships exist for a card participant in the selected round."
            )
        summaries = {}
        for membership in matching_rows:
            user = users_by_id.get(membership["user_id"], {})
            full_name = " ".join(
                part for part in (user.get("first_name"), user.get("last_name")) if part
            )
            display_name = (
                membership.get("display_name_snapshot")
                or full_name
                or user.get("primary_email")
                or membership.get("email")
                or user.get("user_email")
                or f"사용자 {membership['user_id']}"
            )
            summaries[membership["user_id"]] = RoundUserSummary(
                user_id=membership["user_id"],
                participant_id=membership["participant_id"],
                display_name=display_name,
            )
        return summaries

    @staticmethod
    def _to_parent_user(row) -> ParentUser:
        if isinstance(row, ParentUser):
            return row
        return ParentUser(
            user_id=row["user_id"],
            parent_role=row.get("role"),
            approval_status=row.get("approval_status"),
            is_active=row["is_active"],
            is_staff=row["is_staff"],
            is_superuser=row["is_superuser"],
            user_email=row.get("user_email"),
            primary_email=row.get("primary_email"),
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

    @staticmethod
    def _to_login_identity(row, fallback_email="") -> LoginIdentity:
        return LoginIdentity(
            user_id=row["user_id"],
            email=row.get("primary_email") or row.get("user_email") or fallback_email,
        )
