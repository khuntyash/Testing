from __future__ import annotations

import logging
import os
import socket
import time
import uuid

from history_store import init_history_db
from task_queue import init_task_queue_db, run_worker_once


# Errors that indicate a transient infrastructure issue (DNS hiccup, Redis
# proxy reconnect, network blip). We log and back off instead of letting the
# process crash, because Docker restart-cycles between every task hurt
# throughput and lose in-flight state.
_TRANSIENT_ERROR_NAMES = {
    "ConnectionError",
    "TimeoutError",
    "BusyLoadingError",
    "gaierror",
    "DNSError",
    "OSError",
}


def _is_transient(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in _TRANSIENT_ERROR_NAMES:
        return True
    msg = str(exc).lower()
    if (
        "name resolution" in msg
        or "temporary failure" in msg
        or "connection reset" in msg
        or "timed out" in msg
        or "broken pipe" in msg
    ):
        return True
    return False


def main() -> None:
    logging.basicConfig(level=os.getenv("WORKER_LOG_LEVEL", "INFO"))
    log = logging.getLogger("labelhub.worker")
    init_history_db()
    init_task_queue_db()
    worker_id = f"{socket.gethostname()}-worker-{uuid.uuid4().hex[:8]}"
    idle_sleep = max(0.1, float(os.getenv("WORKER_IDLE_SLEEP_SEC", "0.4")))
    transient_backoff_min = max(1.0, float(os.getenv("WORKER_TRANSIENT_BACKOFF_MIN_SEC", "2") or 2))
    transient_backoff_max = max(transient_backoff_min, float(os.getenv("WORKER_TRANSIENT_BACKOFF_MAX_SEC", "30") or 30))
    log.info(
        "Worker started id=%s queue_backend=%s storage_backend=%s",
        worker_id,
        os.getenv("QUEUE_BACKEND", "sqlite"),
        os.getenv("STORAGE_BACKEND", "local"),
    )
    transient_failures = 0
    while True:
        try:
            had_work = run_worker_once(worker_id)
            transient_failures = 0
            if had_work:
                log.info("Worker %s completed one queue iteration", worker_id)
            if not had_work:
                time.sleep(idle_sleep)
        except KeyboardInterrupt:
            log.info("Worker %s received interrupt; exiting", worker_id)
            break
        except Exception as exc:  # noqa: BLE001 - we deliberately keep the loop alive
            if _is_transient(exc):
                transient_failures += 1
                wait = min(
                    transient_backoff_max,
                    transient_backoff_min * (2 ** min(transient_failures - 1, 5)),
                )
                log.warning(
                    "Worker %s transient error (#%s, backoff=%.1fs): %s: %s",
                    worker_id,
                    transient_failures,
                    wait,
                    type(exc).__name__,
                    exc,
                )
                time.sleep(wait)
                continue
            # Non-transient: log full traceback, sleep briefly, then keep going
            # so a single bad task doesn't kill the worker process.
            log.exception("Worker %s unexpected error; continuing", worker_id)
            time.sleep(max(idle_sleep, 1.0))


if __name__ == "__main__":
    main()

