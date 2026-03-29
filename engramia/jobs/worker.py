# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""In-process background worker for async job execution.

Runs as a daemon thread alongside the FastAPI process. Polls the job queue
at a configurable interval and executes claimed jobs in a bounded thread pool.

This avoids introducing Celery/Redis infrastructure on small deployments.
Extract to a separate process when independent scaling is needed.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from engramia.jobs.service import JobService

_log = logging.getLogger(__name__)


class JobWorker:
    """Background thread that polls and executes pending jobs.

    Args:
        service: JobService instance for queue operations.
        poll_interval: Seconds between poll cycles (default: 2.0).
        max_concurrent: Maximum concurrent job executions (default: 3).
            Controls backpressure on LLM/embedding calls.
    """

    def __init__(
        self,
        service: JobService,
        poll_interval: float = 2.0,
        max_concurrent: int = 3,
    ) -> None:
        self._service = service
        self._poll_interval = poll_interval
        self._max_concurrent = max_concurrent
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the worker loop in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            _log.warning("JobWorker already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="engramia-job-worker",
            daemon=True,
        )
        self._thread.start()
        _log.info(
            "JobWorker started: poll_interval=%.1fs, max_concurrent=%d",
            self._poll_interval,
            self._max_concurrent,
        )

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the worker to stop and wait for it to finish.

        Args:
            timeout: Maximum seconds to wait for the thread to join.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                _log.warning("JobWorker did not stop within %.1fs timeout.", timeout)
            else:
                _log.info("JobWorker stopped.")
        self._executor.shutdown(wait=False)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        """Main poll loop. Runs until stop() is called."""
        _log.debug("JobWorker loop started.")
        reap_counter = 0

        while not self._stop_event.is_set():
            try:
                executed = self._service.poll_and_execute(batch_size=self._max_concurrent)
                if executed > 0:
                    _log.debug("Executed %d job(s).", executed)

                # Reap expired jobs every 30 cycles (~60s at 2s interval)
                reap_counter += 1
                if reap_counter >= 30:
                    reaped = self._service.reap_expired()
                    if reaped > 0:
                        _log.info("Reaped %d expired job(s).", reaped)
                    reap_counter = 0

            except Exception:
                _log.exception("Error in job worker poll cycle.")

            self._stop_event.wait(timeout=self._poll_interval)

        _log.debug("JobWorker loop exiting.")
