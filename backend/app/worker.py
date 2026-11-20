"""The worker process: `python -m app.worker`. Runs AI and system work from the job queue (RD-4).

The API never runs this work itself, so restarting the API does not interrupt it. Stopping the worker
(SIGTERM) lets the current job finish; a killed worker's job is taken back once its lease runs out.
"""

import logging
import os
import signal
import socket
import threading
import time

from app import models  # noqa: F401  (registers every table)
from app.core import correlation
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.jobs import service as jobs

log = logging.getLogger("aidlc.worker")


def main() -> None:
    correlation.configure_logging()
    settings = get_settings()
    settings.assert_safe_for_environment()
    factory = make_session_factory(make_engine(settings.database_url))
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stopping = threading.Event()

    def stop(signum: int, _frame: object) -> None:
        log.info("signal %s: finishing the current job, then stopping", signum)
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("worker %s started (lease %ss)", worker_id, settings.job_lease_seconds)

    next_sweep = 0.0
    while not stopping.is_set():
        try:
            if time.monotonic() >= next_sweep:
                with factory() as db:
                    jobs.sweep(db, settings)
                next_sweep = time.monotonic() + settings.job_sweep_interval_seconds
            if not jobs.run_one(factory, settings, None, worker_id):
                stopping.wait(settings.job_poll_seconds)
        except Exception:
            log.exception("worker loop error; retrying shortly")
            stopping.wait(5)
    log.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    main()
