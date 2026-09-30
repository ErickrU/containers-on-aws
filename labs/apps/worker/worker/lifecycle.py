"""Process lifecycle shared by both entrypoints (labs/CONTRACT.md §7).

Start:  validate config -> connect DB (retry up to 30 s) -> start HTTP -> start the consumer loop.
Stop:   SIGTERM/SIGINT sets a stop flag; the loop stops taking new work after the current message
        batch; the main thread waits at most ``SHUTDOWN_TIMEOUT_SECONDS`` (default 20), then
        flushes telemetry, closes the pool and exits 0. Work still in flight at the deadline is
        abandoned on purpose: SQS redelivers after the visibility timeout and Kafka re-reads from
        the last committed offset, and both handlers tolerate redelivery.

The consumer loop runs in its own (daemon) thread so that a blocking call, such as a 20-second SQS
long poll, cannot push the process past its shutdown budget. ``SHUTDOWN_TIMEOUT_SECONDS`` must be
below the platform's grace period (ECS ``stopTimeout`` 30, Kubernetes
``terminationGracePeriodSeconds`` 30), otherwise the platform sends SIGKILL first.

Exit codes: 0 clean, 1 runtime error, 2 configuration error.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_CONFIG_ERROR = 2

_SIGNAL_NAMES = {signal.SIGTERM: "SIGTERM", signal.SIGINT: "SIGINT"}


class Lifecycle:
    def __init__(self, shutdown_timeout_seconds: float) -> None:
        self.stop = threading.Event()
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.signal_name: str | None = None

    def install_signal_handlers(self) -> None:
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, self._on_signal)

    def _on_signal(self, signum: int, _frame) -> None:
        # Only set a flag here: signal handlers run between bytecodes on the main thread and must
        # not do real work. The main loop notices the flag within half a second.
        self.signal_name = _SIGNAL_NAMES.get(signum, str(signum))
        self.stop.set()

    def supervise(self, loop: Callable[[], None], *, name: str) -> tuple[int, float]:
        """Run ``loop`` in a thread until the stop flag is set or the loop dies.

        Returns ``(exit_code, remaining_shutdown_budget_seconds)``.
        """
        thread = threading.Thread(target=self._guard(loop), name=name, daemon=True)
        thread.start()
        exit_code = EXIT_OK
        while not self.stop.is_set():
            if not thread.is_alive():
                log.error("consumer loop exited unexpectedly; shutting down with exit code 1")
                exit_code = EXIT_RUNTIME_ERROR
                self.stop.set()
                break
            self.stop.wait(0.5)

        if self.signal_name:
            log.info("shutdown signal received", extra={"signal": self.signal_name})
        deadline = time.monotonic() + self.shutdown_timeout_seconds
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            log.warning(
                "shutdown deadline reached with work in flight; exiting anyway (messages will be redelivered)",
                extra={"shutdown_timeout_seconds": self.shutdown_timeout_seconds},
            )
        else:
            log.info("consumer loop stopped")
        return exit_code, max(0.5, deadline - time.monotonic())

    def _guard(self, loop: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                loop()
            except Exception:  # noqa: BLE001 - logged here, turned into exit code 1 by supervise()
                log.exception("consumer loop crashed")

        return run
