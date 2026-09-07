from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class NoopJobRunner:
    def run_once(self):
        return False


class JobWorkerCommandTests(SimpleTestCase):
    @override_settings(JOB_RUNNER_CLASS="tests.test_worker.NoopJobRunner")
    @patch("tests.test_worker.NoopJobRunner.run_once", return_value=False)
    def test_once_runs_a_single_job_iteration(self, run_once):
        call_command("run_job_worker", once=True, stdout=StringIO())

        run_once.assert_called_once_with()
