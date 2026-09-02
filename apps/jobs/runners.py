import logging

logger = logging.getLogger(__name__)


class NoopJobRunner:
    """Worker seam used until the background-job state contract is approved."""

    def run_once(self) -> bool:
        logger.info("No background job handlers are registered yet")
        return False
