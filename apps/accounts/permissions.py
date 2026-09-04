from __future__ import annotations

from enum import StrEnum

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied


class ParticipantRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    TUTOR = "tutor"
    VIEWER = "viewer"


class ParticipantAction(StrEnum):
    VIEW = "view"
    MANAGE_PARTICIPANTS = "manage_participants"
    COMPLETE = "complete"
    REOPEN = "reopen"
    EDIT = "edit"
    REQUEST_AI = "request_ai"
    APPLY_AI = "apply_ai"
    COMMENT = "comment"
    REVIEW_COMMENT = "review_comment"
    BRAINSTORM_CREATE_NOTE = "brainstorm_create_note"


ROLE_ACTIONS = {
    ParticipantRole.OWNER: frozenset(
        action for action in ParticipantAction if action != ParticipantAction.REVIEW_COMMENT
    ),
    ParticipantRole.EDITOR: frozenset(
        {
            ParticipantAction.VIEW,
            ParticipantAction.EDIT,
            ParticipantAction.REQUEST_AI,
            ParticipantAction.APPLY_AI,
            ParticipantAction.COMMENT,
            ParticipantAction.BRAINSTORM_CREATE_NOTE,
        }
    ),
    ParticipantRole.TUTOR: frozenset(
        {
            ParticipantAction.VIEW,
            ParticipantAction.COMMENT,
            ParticipantAction.REVIEW_COMMENT,
            ParticipantAction.BRAINSTORM_CREATE_NOTE,
        }
    ),
    ParticipantRole.VIEWER: frozenset({ParticipantAction.VIEW}),
}

COMPLETED_ROLE_ACTIONS = {
    ParticipantRole.OWNER: frozenset({ParticipantAction.VIEW, ParticipantAction.REOPEN}),
    ParticipantRole.EDITOR: frozenset({ParticipantAction.VIEW}),
    ParticipantRole.TUTOR: frozenset({ParticipantAction.VIEW, ParticipantAction.REVIEW_COMMENT}),
    ParticipantRole.VIEWER: frozenset({ParticipantAction.VIEW}),
}


class RolePermissionPolicy:
    def allows(
        self,
        role: ParticipantRole | str,
        action: ParticipantAction | str,
        *,
        is_completed: bool = False,
    ) -> bool:
        try:
            normalized_role = ParticipantRole(role)
            normalized_action = ParticipantAction(action)
        except ValueError:
            return False
        allowed_actions = (
            COMPLETED_ROLE_ACTIONS[normalized_role]
            if is_completed
            else ROLE_ACTIONS[normalized_role]
        )
        return normalized_action in allowed_actions

    def enforce(
        self,
        role: ParticipantRole | str,
        action: ParticipantAction | str,
        *,
        is_completed: bool = False,
    ):
        if not self.allows(role, action, is_completed=is_completed):
            raise PermissionDenied("The participant role does not allow this action.")


class ParentRoleMappingPolicy:
    """Single configurable boundary for unresolved parent-to-child role mapping."""

    def resolve(self, *, parent_role, is_staff, is_superuser) -> ParticipantRole | None:
        configured_role = None
        if is_superuser and settings.PARENT_SUPERUSER_PARTICIPANT_ROLE:
            configured_role = settings.PARENT_SUPERUSER_PARTICIPANT_ROLE
        elif is_staff and settings.PARENT_STAFF_PARTICIPANT_ROLE:
            configured_role = settings.PARENT_STAFF_PARTICIPANT_ROLE
        elif parent_role:
            configured_role = settings.PARENT_ROLE_PARTICIPANT_MAP.get(parent_role)

        if not configured_role:
            return None
        try:
            return ParticipantRole(configured_role)
        except ValueError as exc:
            raise ImproperlyConfigured(
                f"Invalid configured participant role: {configured_role}"
            ) from exc


role_permission_policy = RolePermissionPolicy()
parent_role_mapping_policy = ParentRoleMappingPolicy()
