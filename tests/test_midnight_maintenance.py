from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.prds.models import Prd, PrdStatus, PrdType


class MidnightMaintenanceCommandTests(TestCase):
    def make_prd(self, *, title, deadline, status=PrdStatus.IN_PROGRESS, is_deleted=False):
        prd = Prd.objects.create(
            title=title,
            description="자정 유지보수 테스트",
            deadline=deadline,
            prd_type=PrdType.NEW_PRODUCT,
            status=status,
            creator_user_id=7,
            creation_idempotency_key=f"midnight-{title}",
            is_deleted=is_deleted,
            deleted_at=timezone.now() - timedelta(days=31) if is_deleted else None,
        )
        return prd

    def test_command_completes_elapsed_prds_and_purges_30_day_deletes(self):
        today = timezone.localdate()
        overdue = self.make_prd(title="기한 경과", deadline=today - timedelta(days=1))
        due_today = self.make_prd(title="오늘 마감", deadline=today)
        dropped = self.make_prd(
            title="드랍 유지",
            deadline=today - timedelta(days=2),
            status=PrdStatus.DROPPED,
        )
        deleted = self.make_prd(
            title="보관기간 경과",
            deadline=None,
            is_deleted=True,
        )
        output = StringIO()

        call_command("run_midnight_maintenance", stdout=output)

        overdue.refresh_from_db()
        due_today.refresh_from_db()
        dropped.refresh_from_db()
        self.assertEqual(overdue.status, PrdStatus.COMPLETED)
        self.assertEqual(overdue.version, 2)
        self.assertEqual(due_today.status, PrdStatus.IN_PROGRESS)
        self.assertEqual(dropped.status, PrdStatus.DROPPED)
        self.assertFalse(Prd.objects.filter(pk=deleted.pk).exists())
        self.assertIn("prds_completed=1", output.getvalue())
        self.assertIn("prds_purged=1", output.getvalue())

    def test_command_succeeds_when_there_is_nothing_to_process(self):
        output = StringIO()

        call_command("run_midnight_maintenance", stdout=output)

        self.assertIn("prds_completed=0", output.getvalue())
        self.assertIn("prds_purged=0", output.getvalue())
