from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormConnection,
    BrainstormNode,
)
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdComment,
    PrdParticipant,
    PrdParticipantRole,
)


def parent_user(user_id):
    return {
        "user_id": user_id,
        "user_email": f"user{user_id}@example.test",
        "primary_email": f"user{user_id}@example.test",
        "first_name": "데모",
        "last_name": str(user_id),
        "role": "tutor" if user_id == 2 else "student",
        "approval_status": "fixture-approved",
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
    }


class DemoWorkspaceSeedTests(TestCase):
    def setUp(self):
        self.repository = FixtureIntegrationRepository(
            users=[parent_user(user_id) for user_id in (2, *range(21, 31))],
            memberships=[],
            active_statuses={"fixture-running"},
        )

    def run_seed(self):
        output = StringIO()
        with patch(
            "apps.prds.management.commands.seed_demo_workspace.get_default_integration_repository",
            return_value=self.repository,
        ):
            call_command("seed_demo_workspace", stdout=output)
        return output.getvalue()

    def test_seed_creates_complete_shared_demo_and_is_idempotent(self):
        first_output = self.run_seed()

        self.assertIn("생성 14개", first_output)
        self.assertEqual(Prd.objects.count(), 14)
        self.assertEqual(PrdParticipant.objects.count(), 53)
        self.assertEqual(PrdAnswer.objects.count(), 251)
        self.assertEqual(PrdComment.objects.count(), 24)
        self.assertEqual(BrainstormCanvas.objects.count(), 14)
        self.assertEqual(BrainstormNode.objects.count(), 47)
        self.assertEqual(BrainstormConnection.objects.count(), 11)
        self.assertEqual(
            set(Prd.objects.values_list("status", flat=True)),
            {"in_progress", "completed", "held", "dropped"},
        )

        progress_prds = Prd.objects.filter(
            creation_idempotency_key__startswith="roundless-demo-v1:progress-"
        ).with_completion_rate()
        self.assertEqual(
            sorted(progress_prds.values_list("completion_rate", flat=True)),
            [24, 32, 46, 54, 66, 73, 85, 93],
        )
        messi_roles = set(
            PrdParticipant.objects.filter(
                prd__in=progress_prds,
                user_id=24,
            ).values_list("role", flat=True)
        )
        self.assertEqual(
            messi_roles,
            {PrdParticipantRole.EDITOR, PrdParticipantRole.VIEWER},
        )

        second_output = self.run_seed()

        self.assertIn("기존 유지 14개", second_output)
        self.assertEqual(Prd.objects.count(), 14)
        self.assertEqual(BrainstormNode.objects.count(), 47)
