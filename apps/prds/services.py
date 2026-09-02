from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.integration.repository import DjangoViewIntegrationRepository, IntegrationRepository

from .models import (
    Prd,
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
    round_id: int
    team_id: int | None
    creator_user_id: int
    idempotency_key: str
    participant_user_ids: tuple[int, ...] = ()


class PrdParticipantService:
    """Validates immediate participants against the parent VIEW boundary."""

    def __init__(self, repository: IntegrationRepository | None = None):
        self.repository = repository or DjangoViewIntegrationRepository()

    def validate_memberships(self, *, user_ids: tuple[int, ...], round_id: int):
        unique_user_ids = tuple(dict.fromkeys(user_ids))
        memberships = self.repository.get_eligible_memberships(
            user_ids=unique_user_ids,
            round_id=round_id,
        )
        memberships_by_user_id = {membership.user_id: membership for membership in memberships}
        invalid_user_ids = [
            user_id for user_id in unique_user_ids if user_id not in memberships_by_user_id
        ]
        if invalid_user_ids:
            raise ValidationError(
                {
                    "participant_user_ids": (
                        "현재 회차의 활성 참여자가 아닌 사용자가 포함되어 있습니다: "
                        + ", ".join(str(user_id) for user_id in invalid_user_ids)
                    )
                }
            )
        return tuple(memberships_by_user_id[user_id] for user_id in unique_user_ids)

    def add_editors(self, *, prd: Prd, user_ids: tuple[int, ...]):
        memberships = self.validate_memberships(user_ids=user_ids, round_id=prd.round_id)
        existing_user_ids = set(
            prd.participants.filter(user_id__in=user_ids).values_list("user_id", flat=True)
        )
        PrdParticipant.objects.bulk_create(
            [
                PrdParticipant(
                    prd=prd,
                    user_id=membership.user_id,
                    participant_id=membership.participant_id,
                    role=PrdParticipantRole.EDITOR,
                )
                for membership in memberships
                if membership.user_id != prd.creator_user_id
                and membership.user_id not in existing_user_ids
            ]
        )


class PrdCreationService:
    def __init__(self, repository: IntegrationRepository | None = None):
        self.repository = repository or DjangoViewIntegrationRepository()

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
            participant_id=membership.participant_id,
            role=PrdParticipantRole.OWNER,
        )
        participant_service.add_editors(prd=prd, user_ids=participant_user_ids)
        self._copy_template(prd=prd, template=template)
        return prd, True

    @staticmethod
    def _validate_command(command: CreatePrdCommand):
        errors = {}
        if not command.title.strip():
            errors["title"] = "Title is required."
        if command.prd_type not in PrdType.values:
            errors["prd_type"] = "Unknown PRD type."
        if command.round_id <= 0:
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
