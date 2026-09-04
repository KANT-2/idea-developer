from django.core.management.base import BaseCommand

from apps.jobs.cleanup import BackgroundDataCleanupService
from apps.prds.status_services import PrdStatusService


class Command(BaseCommand):
    help = "Complete overdue PRDs and purge expired recoverable data. Safe to run repeatedly."

    def handle(self, *args, **options):
        completed_ids = PrdStatusService().complete_overdue()
        cleanup = BackgroundDataCleanupService().run()
        self.stdout.write(
            self.style.SUCCESS(
                "Midnight maintenance completed: "
                f"prds_completed={len(completed_ids)}, "
                f"prds_purged={cleanup.prds}, nodes={cleanup.nodes}, "
                f"connections={cleanup.connections}, ai_previews={cleanup.ai_previews}"
            )
        )
