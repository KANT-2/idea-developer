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
from apps.prds.models import Prd, PrdAnswer, PrdComment, PrdParticipant


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

        self.assertIn("생성 5개", first_output)
        self.assertEqual(Prd.objects.count(), 5)
        self.assertEqual(PrdParticipant.objects.count(), 16)
        self.assertEqual(PrdAnswer.objects.count(), 16)
        self.assertEqual(PrdComment.objects.count(), 11)
        self.assertEqual(BrainstormCanvas.objects.count(), 5)
        self.assertEqual(BrainstormNode.objects.count(), 21)
        self.assertEqual(BrainstormConnection.objects.count(), 5)
        self.assertEqual(
            set(Prd.objects.values_list("status", flat=True)),
            {"in_progress", "completed", "held", "dropped"},
        )

        second_output = self.run_seed()

        self.assertIn("기존 유지 5개", second_output)
        self.assertEqual(Prd.objects.count(), 5)
        self.assertEqual(BrainstormNode.objects.count(), 21)
