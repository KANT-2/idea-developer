from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from apps.jobs.runners import PeriodicCleanupRunner


class Command(BaseCommand):
    help = "Run the PostgreSQL-backed AI job worker in a separate process."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        runner = import_string(settings.JOB_RUNNER_CLASS)()
        cleanup = PeriodicCleanupRunner()
        if options["once"]:
            cleanup.run_if_due()
            runner.run_once()
            return

        self.stdout.write("Job worker started. Press Ctrl+C to stop.")
        try:
            while True:
                cleanup.run_if_due()
                processed = runner.run_once()
                if not processed:
                    time.sleep(settings.JOB_WORKER_POLL_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("Job worker stopped.")
