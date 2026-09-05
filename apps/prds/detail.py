from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.integration.context import IntegrationContext, is_admin_context

from .models import Prd, PrdParticipant, PrdParticipantRole, PrdStatus


class PrdNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PrdAccess:
    prd: Prd
    role: str | None
    is_admin: bool = False


class PrdAccessService:
    """Single permission boundary shared by every PRD detail endpoint."""

    def get(self, *, prd_id: int, context: IntegrationContext) -> PrdAccess:
        # Import locally because the status service also uses PrdAccess as its
        # permission input for explicit completion/reopen operations.
        from .status_services import PrdStatusService

        PrdStatusService().complete_overdue(prd_ids=[prd_id])
        try:
            prd = Prd.objects.with_completion_rate().get(pk=prd_id, is_deleted=False)
        except Prd.DoesNotExist as exc:
            raise PrdNotFound from exc
        participant = PrdParticipant.objects.filter(
            prd=prd,
            user_id=context.user_id,
        ).first()
        role = participant.role if participant else None
        if role is None and prd.creator_user_id == context.user_id:
            role = PrdParticipantRole.OWNER

        if prd.round_id is not None and prd.round_id != context.round_id and role is None:
            raise PermissionDenied("The PRD belongs to another round.")

        if prd.round_id is None and role is None:
            raise PermissionDenied("Only an explicit participant can access this personal PRD.")

        has_team_access = (
            prd.round_id is not None and prd.is_team_shared and prd.team_id == context.team_id
        )
        is_admin = is_admin_context(context)
        if role is None and not has_team_access and not is_admin:
            raise PermissionDenied("The user cannot access this PRD.")
        return PrdAccess(prd=prd, role=role, is_admin=is_admin)


class PrdPermissionPresenter:
    """Role permissions now; completion-lock rules can be layered here later."""

    def describe(self, access: PrdAccess):
        role = access.role
        can_edit_completed_deadline = access.prd.status == PrdStatus.COMPLETED and bool(
            access.is_admin or role == PrdParticipantRole.OWNER
        )
        return {
            "role": role,
            "can_view": True,
            "can_edit": self._allows(access, ParticipantAction.EDIT),
            "can_edit_deadline": self._allows(access, ParticipantAction.EDIT)
            or can_edit_completed_deadline,
            "can_change_status": bool(access.is_admin or access.role == PrdParticipantRole.OWNER),
            "can_comment": self._allows(access, ParticipantAction.COMMENT),
            "can_review_comment": self._allows(access, ParticipantAction.REVIEW_COMMENT),
            "can_manage_participants": self._allows(access, ParticipantAction.MANAGE_PARTICIPANTS),
            "can_complete": self._allows(access, ParticipantAction.COMPLETE),
            "can_reopen": self._allows(access, ParticipantAction.REOPEN),
            "can_request_ai": self._allows(access, ParticipantAction.REQUEST_AI),
            "can_apply_ai": self._allows(access, ParticipantAction.APPLY_AI),
            "can_view_contributions": access.is_admin,
            "can_delete": bool(access.is_admin or role == PrdParticipantRole.OWNER),
            "is_completed": access.prd.status == PrdStatus.COMPLETED,
        }

    @staticmethod
    def _allows(access, action):
        if (
            action == ParticipantAction.REOPEN
            and access.is_admin
            and access.prd.status == PrdStatus.COMPLETED
        ):
            return True
        return bool(
            access.role
            and role_permission_policy.allows(
                access.role,
                action,
                is_completed=access.prd.status == PrdStatus.COMPLETED,
            )
        )
