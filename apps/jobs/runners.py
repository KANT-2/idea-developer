import logging
import time

from django.conf import settings

from .cleanup import BackgroundDataCleanupService

logger = logging.getLogger(__name__)


class PeriodicCleanupRunner:
    """Runs cleanup at most once per configured interval in a worker process."""

    def __init__(self, *, service=None, clock=None, interval_seconds=None):
        self.service = service or BackgroundDataCleanupService()
        self.clock = clock or time.monotonic
        self.interval_seconds = (
            settings.BACKGROUND_CLEANUP_INTERVAL_SECONDS
            if interval_seconds is None
            else interval_seconds
        )
        self.next_run_at = None

    def run_if_due(self) -> bool:
        now = self.clock()
        if self.next_run_at is not None and now < self.next_run_at:
            return False
        self.next_run_at = now + self.interval_seconds
        try:
            result = self.service.run()
        except Exception:
            logger.exception("Periodic background cleanup failed")
            return False
        logger.info(
            "Periodic background cleanup completed",
            extra={
                "prds": result.prds,
                "nodes": result.nodes,
                "connections": result.connections,
                "ai_previews": result.ai_previews,
            },
        )
        return True


class NoopJobRunner:
    """Worker seam used until the background-job state contract is approved."""

    def run_once(self) -> bool:
        logger.info("No background job handlers are registered yet")
        return False
