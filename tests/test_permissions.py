from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, override_settings

from apps.accounts.permissions import (
    ParentRoleMappingPolicy,
    ParticipantAction,
    ParticipantRole,
    RolePermissionPolicy,
)


class RolePermissionPolicyTests(SimpleTestCase):
    def setUp(self):
        self.policy = RolePermissionPolicy()

    def test_owner_has_management_actions_but_not_tutor_review_action(self):
        self.assertTrue(
            all(
                self.policy.allows(ParticipantRole.OWNER, action)
                for action in ParticipantAction
                if action != ParticipantAction.REVIEW_COMMENT
            )
        )
        self.assertFalse(
            self.policy.allows(ParticipantRole.OWNER, ParticipantAction.REVIEW_COMMENT)
        )

    def test_editor_permissions_match_contract(self):
        for action in (
            ParticipantAction.VIEW,
            ParticipantAction.EDIT,
            ParticipantAction.REQUEST_AI,
            ParticipantAction.APPLY_AI,
            ParticipantAction.COMMENT,
        ):
            self.assertTrue(self.policy.allows(ParticipantRole.EDITOR, action))
        self.assertFalse(self.policy.allows(ParticipantRole.EDITOR, ParticipantAction.COMPLETE))

    def test_tutor_and_viewer_permissions_match_contract(self):
        self.assertTrue(self.policy.allows(ParticipantRole.TUTOR, ParticipantAction.REVIEW_COMMENT))
        self.assertFalse(self.policy.allows(ParticipantRole.TUTOR, ParticipantAction.EDIT))
        self.assertTrue(self.policy.allows(ParticipantRole.VIEWER, ParticipantAction.VIEW))
        self.assertFalse(self.policy.allows(ParticipantRole.VIEWER, ParticipantAction.COMMENT))

    def test_server_enforcement_denies_unknown_or_disallowed_role(self):
        with self.assertRaises(PermissionDenied):
            self.policy.enforce(ParticipantRole.VIEWER, ParticipantAction.EDIT)
        with self.assertRaises(PermissionDenied):
            self.policy.enforce("unknown", ParticipantAction.VIEW)

    def test_completed_state_is_locked_except_owner_reopen_and_tutor_review(self):
        self.assertTrue(
            self.policy.allows(
                ParticipantRole.OWNER,
                ParticipantAction.REOPEN,
                is_completed=True,
            )
        )
        self.assertTrue(
            self.policy.allows(
                ParticipantRole.TUTOR,
                ParticipantAction.REVIEW_COMMENT,
                is_completed=True,
            )
        )
        self.assertFalse(
            self.policy.allows(
                ParticipantRole.EDITOR,
                ParticipantAction.EDIT,
                is_completed=True,
            )
        )


class ParentRoleMappingPolicyTests(SimpleTestCase):
    def setUp(self):
        self.policy = ParentRoleMappingPolicy()

    @override_settings(
        PARENT_ROLE_PARTICIPANT_MAP={},
        PARENT_STAFF_PARTICIPANT_ROLE="",
        PARENT_SUPERUSER_PARTICIPANT_ROLE="",
    )
    def test_unconfirmed_mapping_does_not_guess(self):
        self.assertIsNone(
            self.policy.resolve(parent_role="student", is_staff=False, is_superuser=False)
        )

    @override_settings(
        PARENT_ROLE_PARTICIPANT_MAP={"fixture-parent-role": "editor"},
        PARENT_STAFF_PARTICIPANT_ROLE="tutor",
        PARENT_SUPERUSER_PARTICIPANT_ROLE="owner",
    )
    def test_mapping_is_centralized_in_settings_policy(self):
        self.assertEqual(
            self.policy.resolve(
                parent_role="fixture-parent-role",
                is_staff=False,
                is_superuser=False,
            ),
            ParticipantRole.EDITOR,
        )
        self.assertEqual(
            self.policy.resolve(parent_role=None, is_staff=True, is_superuser=False),
            ParticipantRole.TUTOR,
        )
        self.assertEqual(
            self.policy.resolve(parent_role=None, is_staff=True, is_superuser=True),
            ParticipantRole.OWNER,
        )
