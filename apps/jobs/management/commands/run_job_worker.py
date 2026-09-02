from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string


class Command(BaseCommand):
    help = "Run the PostgreSQL-backed background job worker seam."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        runner = import_string(settings.JOB_RUNNER_CLASS)()
        if options["once"]:
            runner.run_once()
            return

        self.stdout.write("Job worker started. Press Ctrl+C to stop.")
        try:
            while True:
                processed = runner.run_once()
                if not processed:
                    time.sleep(settings.JOB_WORKER_POLL_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("Job worker stopped.")
