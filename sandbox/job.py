"""One job per container (Phase 1, RD-30): reads the job from /job/job.json and prints its result.

The executor starts a fresh container from the runner image for each job: no network, a read-only root, dropped
capabilities, CPU, memory and process limits, and a temporary /work. This entry point reuses the sandbox runner's
vetted checks: generated code still runs as a separate unprivileged user with a clean environment. The result is
printed on one line after a marker, so nothing the code prints can be mistaken for it.
"""

import json
import sys
import time

import runner

MARKER = "@@AIDLC-RESULT@@"
MAX_INPUT = 4_000_000


def main() -> None:
    started = time.monotonic()
    with open("/job/job.json", "rb") as handle:  # put there by the executor before the container started
        raw = handle.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        result = {"status": "rejected", "error": "the job is too large"}
    else:
        try:
            job = json.loads(raw.decode("utf-8"))
            kind = job.get("kind") if isinstance(job, dict) else None
            if kind != "checks":
                result = {"status": "rejected", "error": "unknown job kind"}
            else:
                result = runner.execute(job)
        except Exception as exc:  # noqa: BLE001 - a broken job reports, never crashes silently
            result = {"status": "error", "error": type(exc).__name__}
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    sys.stdout.write("\n" + MARKER + json.dumps(result) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
