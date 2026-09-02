from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class JobWorkerCommandTests(SimpleTestCase):
    @patch("apps.jobs.runners.NoopJobRunner.run_once", return_value=False)
    def test_once_runs_a_single_iteration(self, run_once):
        call_command("run_job_worker", once=True, stdout=StringIO())

        run_once.assert_called_once_with()
