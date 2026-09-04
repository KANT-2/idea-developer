from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from apps.jobs.cleanup import CleanupResult
from apps.jobs.runners import PeriodicCleanupRunner


class PeriodicCleanupRunnerTests(SimpleTestCase):
    def test_empty_cleanup_is_successful_and_waits_until_next_interval(self):
        service = Mock()
        service.run.return_value = CleanupResult()
        times = iter([100.0, 101.0, 160.0])
        runner = PeriodicCleanupRunner(
            service=service,
            clock=lambda: next(times),
            interval_seconds=60,
        )

        self.assertTrue(runner.run_if_due())
        self.assertFalse(runner.run_if_due())
        self.assertTrue(runner.run_if_due())
        self.assertEqual(service.run.call_count, 2)

    def test_cleanup_failure_does_not_stop_worker(self):
        service = Mock()
        service.run.side_effect = RuntimeError("temporary cleanup failure")
        runner = PeriodicCleanupRunner(
            service=service,
            clock=lambda: 100.0,
            interval_seconds=60,
        )

        with self.assertLogs("apps.jobs.runners", level="ERROR"):
            self.assertFalse(runner.run_if_due())


class JobWorkerCommandTests(SimpleTestCase):
    @override_settings(JOB_RUNNER_CLASS="apps.jobs.runners.NoopJobRunner")
    @patch(
        "apps.jobs.management.commands.run_job_worker."
        "PeriodicCleanupRunner.run_if_due",
        return_value=True,
    )
    @patch("apps.jobs.runners.NoopJobRunner.run_once", return_value=False)
    def test_once_runs_cleanup_and_a_single_job_iteration(self, run_once, cleanup):
        call_command("run_job_worker", once=True, stdout=StringIO())

        cleanup.assert_called_once_with()
        run_once.assert_called_once_with()
