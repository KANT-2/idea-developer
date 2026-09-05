from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.common.slack_notifications import send_prd_participant_added
from apps.integration.repository import IntegrationRepository, get_default_integration_repository

from .models import (
    Prd,
    PrdChangeHistory,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
    PrdTemplate,
    PrdType,
)


@dataclass(frozen=True, slots=True)
class CreatePrdCommand:
    title: str
    description: str
    deadline: date | None
    prd_type: str
    round_id: int | None
    team_id: int | None
    creator_user_id: int
    idempotency_key: str
    participant_user_ids: tuple[int, ...] = ()


class PrdParticipantService:
    """Validates immediate participants against the parent VIEW boundary."""

    def __init__(self, repository: IntegrationRepository | None = None):
        self.repository = repository or get_default_integration_repository()

    def validate_memberships(self, *, user_ids: tuple[int, ...], round_id: int | None):
        unique_user_ids = tuple(dict.fromkeys(user_ids))
        if round_id is None:
            memberships = tuple(
                user
                for user_id in unique_user_ids
                if (user := self.repository.get_user(user_id)) is not None
                and user.is_active
                and user.approval_status == settings.INTEGRATION_APPROVED_USER_STATUS
            )
        else:
            memberships = self.repository.get_eligible_memberships(
                user_ids=unique_user_ids,
                round_id=round_id,
            )
        memberships_by_user_id = {membership.user_id: membership for membership in memberships}
        invalid_user_ids = [
            user_id for user_id in unique_user_ids if user_id not in memberships_by_user_id
        ]
        if invalid_user_ids:
            eligibility_scope = (
                "활성·승인된 부모 사용자가 아닌 사용자가 포함되어 있습니다: "
                if round_id is None
                else "현재 회차의 활성 참여자가 아닌 사용자가 포함되어 있습니다: "
            )
            raise ValidationError(
                {
                    "participant_user_ids": (
                        eligibility_scope + ", ".join(str(user_id) for user_id in invalid_user_ids)
                    )
                }
            )
        return tuple(memberships_by_user_id[user_id] for user_id in unique_user_ids)

    def add_editors(self, *, prd: Prd, user_ids: tuple[int, ...]):
        memberships = self.validate_memberships(user_ids=user_ids, round_id=prd.round_id)
        existing_user_ids = set(
            prd.participants.filter(user_id__in=user_ids).values_list("user_id", flat=True)
        )
        participants = [
            PrdParticipant(
                prd=prd,
                user_id=membership.user_id,
                participant_id=getattr(membership, "participant_id", None),
                role=PrdParticipantRole.EDITOR,
            )
            for membership in memberships
            if membership.user_id != prd.creator_user_id
            and membership.user_id not in existing_user_ids
        ]
        PrdParticipant.objects.bulk_create(participants)
        return tuple(participants)

    @staticmethod
    def _validate_role(role: str) -> str:
        if role not in {
            PrdParticipantRole.EDITOR,
            PrdParticipantRole.TUTOR,
            PrdParticipantRole.VIEWER,
        }:
            raise ValidationError({"role": "추가 가능한 역할은 editor, tutor, viewer입니다."})
        return role

    @transaction.atomic
    def add_participant(self, *, prd: Prd, user_id: int, role: str, actor_user_id: int):
        role = self._validate_role(role)
        memberships = self.validate_memberships(user_ids=(user_id,), round_id=prd.round_id)
        membership = memberships[0]
        participant, created = PrdParticipant.objects.get_or_create(
            prd=prd,
            user_id=user_id,
            defaults={
                "participant_id": getattr(membership, "participant_id", None),
                "role": role,
            },
        )
        if created:
            self._record_change(
                prd=prd,
                actor_user_id=actor_user_id,
                event_type="participant_added",
                before={},
                after={
                    "user_id": user_id,
                    "participant_id": getattr(membership, "participant_id", None),
                    "role": role,
                },
            )
            transaction.on_commit(
                lambda: send_prd_participant_added(
                    prd_id=prd.pk,
                    prd_title=prd.title,
                    user_ids=(user_id,),
                )
            )
        return participant, created

    @transaction.atomic
    def update_role(
        self,
        *,
        participant: PrdParticipant,
        role: str,
        actor_user_id: int,
        expected_version: int,
    ):
        participant = (
            PrdParticipant.objects.select_for_update().select_related("prd").get(pk=participant.pk)
        )
        if participant.version != expected_version:
            raise PrdParticipantVersionConflict(participant)
        self.validate_memberships(
            user_ids=(participant.user_id,),
            round_id=participant.prd.round_id,
        )
        role = self._validate_role(role)
        if participant.role == PrdParticipantRole.OWNER:
            raise ValidationError({"participant": "owner 역할은 변경할 수 없습니다."})
        before_role = participant.role
        if before_role != role:
            participant.role = role
            participant.version += 1
            participant.save(update_fields=["role", "version"])
            self._record_change(
                prd=participant.prd,
                actor_user_id=actor_user_id,
                event_type="participant_role_changed",
                before={"user_id": participant.user_id, "role": before_role},
                after={"user_id": participant.user_id, "role": role},
            )
        return participant

    @transaction.atomic
    def remove_participant(
        self, *, participant: PrdParticipant, actor_user_id: int, expected_version: int
    ):
        from apps.brainstorm.models import (
            AuditLog,
            BrainstormChangeTarget,
            BrainstormNode,
            BrainstormNodeType,
        )

        participant = PrdParticipant.objects.select_for_update().get(pk=participant.pk)
        if participant.version != expected_version:
            raise PrdParticipantVersionConflict(participant)
        if participant.role == PrdParticipantRole.OWNER:
            raise ValidationError({"participant": "owner는 PRD 참여자에서 제거할 수 없습니다."})
        nodes = list(
            BrainstormNode.objects.select_for_update().filter(
                canvas__prd=participant.prd,
                node_type=BrainstormNodeType.NOTE,
                assignee_id=participant.user_id,
                is_deleted=False,
            )
        )
        for node in nodes:
            BrainstormNode.objects.filter(pk=node.pk).update(
                assignee_id=F("author_id"),
                version=F("version") + 1,
                updated_at=timezone.now(),
            )
            AuditLog.objects.create(
                canvas=node.canvas,
                actor_user_id=actor_user_id,
                action="assignee_restored_to_author",
                target_type=BrainstormChangeTarget.NODE,
                target_id=str(node.pk),
                reason="participant_removed",
                details={
                    "removed_user_id": participant.user_id,
                    "author_id": node.author_id,
                },
            )
        removed = {
            "user_id": participant.user_id,
            "participant_id": participant.participant_id,
            "role": participant.role,
        }
        prd = participant.prd
        participant.delete()
        self._record_change(
            prd=prd,
            actor_user_id=actor_user_id,
            event_type="participant_removed",
            before=removed,
            after={"reassigned_node_ids": [str(node.pk) for node in nodes]},
        )
        return nodes

    @staticmethod
    def _record_change(*, prd, actor_user_id, event_type, before, after):
        PrdChangeHistory.objects.create(
            prd=prd,
            actor_user_id=actor_user_id,
            event_type=event_type,
            before_data=before,
            after_data=after,
        )


class PrdParticipantVersionConflict(Exception):
    def __init__(self, participant):
        self.participant = participant


class PrdCreationService:
    def __init__(self, repository: IntegrationRepository | None = None):
        self.repository = repository or get_default_integration_repository()

    @transaction.atomic
    def create(self, command: CreatePrdCommand) -> tuple[Prd, bool]:
        self._validate_command(command)

        parent_user = self.repository.get_user(command.creator_user_id)
        if (
            parent_user is None
            or not parent_user.is_active
            or parent_user.approval_status != settings.INTEGRATION_APPROVED_USER_STATUS
        ):
            raise PermissionDenied("The creator is not an active approved parent user.")

        membership = None
        if command.round_id is None:
            if command.team_id is not None:
                raise ValidationError({"team_id": "A PRD without a round cannot have a team."})
        else:
            membership = self.repository.get_active_membership(
                command.creator_user_id, command.round_id
            )
            if membership is None:
                raise PermissionDenied("The creator does not participate in the requested round.")
            if command.team_id is not None and command.team_id != membership.team_id:
                raise PermissionDenied("The team does not match the creator's current-round team.")

        normalized_key = command.idempotency_key.strip()
        existing = Prd.objects.filter(
            creator_user_id=command.creator_user_id,
            round_id=command.round_id,
            creation_idempotency_key=normalized_key,
        ).first()
        if existing is not None:
            return existing, False

        participant_user_ids = tuple(
            user_id
            for user_id in dict.fromkeys(command.participant_user_ids)
            if user_id != command.creator_user_id
        )
        participant_service = PrdParticipantService(self.repository)

        try:
            template = PrdTemplate.objects.prefetch_related("sections__questions").get(
                prd_type=command.prd_type
            )
        except PrdTemplate.DoesNotExist as exc:
            raise ValidationError(
                {"prd_type": "A template for this PRD type has not been configured."}
            ) from exc

        prd, created = Prd.objects.get_or_create(
            round_id=command.round_id,
            creator_user_id=command.creator_user_id,
            creation_idempotency_key=normalized_key,
            defaults={
                "title": command.title.strip(),
                "description": command.description.strip(),
                "deadline": command.deadline,
                "prd_type": command.prd_type,
                "status": PrdStatus.IN_PROGRESS,
                "team_id": command.team_id,
            },
        )
        if not created:
            return prd, False
        PrdParticipant.objects.create(
            prd=prd,
            user_id=command.creator_user_id,
            participant_id=membership.participant_id if membership else None,
            role=PrdParticipantRole.OWNER,
        )
        added_participants = participant_service.add_editors(
            prd=prd,
            user_ids=participant_user_ids,
        )
        self._copy_template(prd=prd, template=template)
        PrdChangeHistory.objects.create(
            prd=prd,
            actor_user_id=command.creator_user_id,
            event_type="prd_created",
            before_data={},
            after_data={
                "participant_user_ids": [row.user_id for row in added_participants],
            },
        )
        added_user_ids = tuple(row.user_id for row in added_participants)
        if added_user_ids:
            transaction.on_commit(
                lambda: send_prd_participant_added(
                    prd_id=prd.pk,
                    prd_title=prd.title,
                    user_ids=added_user_ids,
                )
            )
        return prd, True

    @staticmethod
    def _validate_command(command: CreatePrdCommand):
        errors = {}
        if not command.title.strip():
            errors["title"] = "Title is required."
        if command.prd_type not in PrdType.values:
            errors["prd_type"] = "Unknown PRD type."
        if command.round_id is not None and command.round_id <= 0:
            errors["round_id"] = "round_id must be positive."
        if command.creator_user_id <= 0:
            errors["creator_user_id"] = "creator_user_id must be positive."
        if command.team_id is not None and command.team_id <= 0:
            errors["team_id"] = "team_id must be positive."
        if not command.idempotency_key.strip():
            errors["idempotency_key"] = "Idempotency key is required."
        if len(command.idempotency_key.strip()) > 128:
            errors["idempotency_key"] = "Idempotency key is too long."
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _copy_template(*, prd: Prd, template: PrdTemplate):
        for source_section in template.sections.all():
            section = PrdSection.objects.create(
                prd=prd,
                title=source_section.title,
                guide=source_section.guide,
                position=source_section.position,
            )
            PrdQuestion.objects.bulk_create(
                [
                    PrdQuestion(
                        section=section,
                        prompt=source_question.prompt,
                        position=source_question.position,
                    )
                    for source_question in source_section.questions.all()
                ]
            )
