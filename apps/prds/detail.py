from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.integration.context import IntegrationContext

from .models import Prd, PrdParticipant, PrdParticipantRole, PrdStatus


class PrdNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PrdAccess:
    prd: Prd
    role: str | None


class PrdAccessService:
    """Single permission boundary shared by every PRD detail endpoint."""

    def get(self, *, prd_id: int, context: IntegrationContext) -> PrdAccess:
        try:
            prd = Prd.objects.with_completion_rate().get(pk=prd_id, is_deleted=False)
        except Prd.DoesNotExist as exc:
            raise PrdNotFound from exc
        if prd.round_id != context.round_id:
            raise PermissionDenied("The PRD belongs to another round.")

        participant = PrdParticipant.objects.filter(
            prd=prd,
            user_id=context.user_id,
        ).first()
        role = participant.role if participant else None
        if role is None and prd.creator_user_id == context.user_id:
            role = PrdParticipantRole.OWNER

        has_team_access = prd.is_team_shared and prd.team_id == context.team_id
        if role is None and not has_team_access:
            raise PermissionDenied("The user cannot access this PRD.")
        return PrdAccess(prd=prd, role=role)


class PrdPermissionPresenter:
    """Role permissions now; completion-lock rules can be layered here later."""

    def describe(self, access: PrdAccess):
        role = access.role
        return {
            "role": role,
            "can_view": True,
            "can_edit": self._allows(role, ParticipantAction.EDIT),
            "can_comment": self._allows(role, ParticipantAction.COMMENT),
            "can_manage_participants": self._allows(role, ParticipantAction.MANAGE_PARTICIPANTS),
            "can_complete": self._allows(role, ParticipantAction.COMPLETE),
            "can_reopen": self._allows(role, ParticipantAction.REOPEN),
            "can_request_ai": self._allows(role, ParticipantAction.REQUEST_AI),
            "can_apply_ai": self._allows(role, ParticipantAction.APPLY_AI),
            "is_completed": access.prd.status == PrdStatus.COMPLETED,
        }

    @staticmethod
    def _allows(role, action):
        return bool(role and role_permission_policy.allows(role, action, is_completed=False))
