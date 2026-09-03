from django.core.management.base import BaseCommand

from apps.jobs.cleanup import BackgroundDataCleanupService


class Command(BaseCommand):
    help = "Purge expired brainstorm soft deletes and temporary AI preview payloads."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        result = BackgroundDataCleanupService().run(dry_run=options["dry_run"])
        prefix = "Would clean" if options["dry_run"] else "Cleaned"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}: nodes={result.nodes}, connections={result.connections}, "
                f"ai_previews={result.ai_previews}"
            )
        )
