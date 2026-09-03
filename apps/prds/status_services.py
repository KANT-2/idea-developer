from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import ParticipantAction, role_permission_policy

from .detail import PrdAccess
from .models import (
    Prd,
    PrdChangeHistory,
    PrdContributionStatus,
    PrdParticipantRole,
    PrdStatus,
    PrdStatusAuditAction,
    PrdStatusAuditLog,
)


class PrdStatusConflict(Exception):
    def __init__(self, *, current_status: str):
        self.current_status = current_status
        super().__init__(current_status)


class PrdStatusService:
    @transaction.atomic
    def complete(
        self,
        *,
        access: PrdAccess,
        actor_user_id: int,
        confirm_incomplete: bool = False,
    ) -> Prd:
        prd = Prd.objects.select_for_update().get(pk=access.prd.pk)
        if prd.status != PrdStatus.IN_PROGRESS:
            raise PrdStatusConflict(current_status=prd.status)
        if access.role != PrdParticipantRole.OWNER:
            raise PermissionDenied("Only the PRD owner can complete it.")
        role_permission_policy.enforce(access.role, ParticipantAction.COMPLETE)
        has_incomplete_questions = prd.sections.filter(
            is_deleted=False,
            questions__is_deleted=False,
            questions__is_completed=False,
        ).exists()
        if has_incomplete_questions and confirm_incomplete is not True:
            raise ValidationError(
                {
                    "confirm_incomplete": (
                        "미완료 질문이 있습니다. 완료하려면 명시적으로 확인해 주세요."
                    )
                }
            )

        completed_at = timezone.now()
        previous_status = prd.status
        prd.status = PrdStatus.COMPLETED
        prd.completed_at = completed_at
        prd.contribution_status = PrdContributionStatus.PENDING
        prd.save(update_fields=["status", "completed_at", "contribution_status", "updated_at"])
        audit = self._record(
            prd=prd,
            actor_user_id=actor_user_id,
            action=PrdStatusAuditAction.COMPLETED,
            previous_status=previous_status,
            new_status=prd.status,
            reason="",
            previous_completed_at=None,
        )
        transaction.on_commit(
            lambda: self._schedule_contribution(
                prd_id=prd.pk,
                completion_audit_id=audit.pk,
                actor_user_id=actor_user_id,
            )
        )
        return prd

    @transaction.atomic
    def reopen(self, *, access: PrdAccess, actor_user_id: int, reason: str) -> Prd:
        normalized_reason = self._validate_reason(reason)
        prd = Prd.objects.select_for_update().get(pk=access.prd.pk)
        if prd.status != PrdStatus.COMPLETED:
            raise PrdStatusConflict(current_status=prd.status)
        if access.role != PrdParticipantRole.OWNER and not access.is_admin:
            raise PermissionDenied("Only the PRD owner or an administrator can reopen it.")

        previous_status = prd.status
        previous_completed_at = prd.completed_at
        prd.status = PrdStatus.IN_PROGRESS
        prd.completed_at = None
        prd.contribution_status = PrdContributionStatus.NOT_STARTED
        prd.save(update_fields=["status", "completed_at", "contribution_status", "updated_at"])
        self._record(
            prd=prd,
            actor_user_id=actor_user_id,
            action=PrdStatusAuditAction.REOPENED,
            previous_status=previous_status,
            new_status=prd.status,
            reason=normalized_reason,
            previous_completed_at=previous_completed_at,
        )
        return prd

    @staticmethod
    def _validate_reason(reason) -> str:
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError({"reason": "재개 이유를 입력해 주세요."})
        normalized = reason.strip()
        if len(normalized) > 2000:
            raise ValidationError({"reason": "재개 이유는 2000자 이하여야 합니다."})
        return normalized

    @staticmethod
    def _record(
        *,
        prd,
        actor_user_id,
        action,
        previous_status,
        new_status,
        reason,
        previous_completed_at,
    ):
        audit = PrdStatusAuditLog.objects.create(
            prd=prd,
            actor_user_id=actor_user_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
            previous_completed_at=previous_completed_at,
        )
        PrdChangeHistory.objects.create(
            prd=prd,
            actor_user_id=actor_user_id,
            event_type=f"prd_{action}",
            before_data={
                "status": previous_status,
                "completed_at": (
                    previous_completed_at.isoformat() if previous_completed_at else None
                ),
            },
            after_data={
                "status": new_status,
                "reason": reason,
            },
        )
        return audit

    @staticmethod
    def _schedule_contribution(*, prd_id, completion_audit_id, actor_user_id):
        from apps.ai.contribution import ContributionEvaluationService

        ContributionEvaluationService().schedule_for_completion(
            prd_id=prd_id,
            completion_audit_id=completion_audit_id,
            actor_user_id=actor_user_id,
        )
