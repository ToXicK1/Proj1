"""Hands generated projects to the isolated sandbox and reads back what really happened.

The API and the sandbox share only a job folder. If the sandbox is missing or slow there is no result, no evidence
is recorded, and the mandatory checks stay unsatisfied: failure to verify never counts as success.
"""

import json
import pathlib
import re
import time
import uuid
from typing import Any, Protocol

SAFE_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")


def project_files(content: dict[str, Any]) -> list[dict[str, str]]:
    """The generated files in a deliverable. Models sometimes return a path-to-text mapping; both forms work."""
    raw = content.get("source_files")
    if isinstance(raw, dict):
        raw = [{"path": k, "content": v} for k, v in raw.items()]
    if not isinstance(raw, list):
        return []
    return [{"path": f["path"], "content": f["content"]} for f in raw if isinstance(f, dict)
            and isinstance(f.get("path"), str) and isinstance(f.get("content"), str)]


class SandboxUnavailable(Exception):
    pass


class Sandbox(Protocol):
    def run(self, files: list[dict[str, Any]]) -> dict[str, Any]: ...


class FolderSandbox:
    def __init__(self, folder: str, timeout_seconds: float) -> None:
        self.root = pathlib.Path(folder)
        self.timeout = timeout_seconds

    def _alive(self) -> bool:
        try:
            return time.time() - float((self.root / "heartbeat").read_text()) < 15
        except (OSError, ValueError):
            return False

    def run(self, files: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._alive():
            raise SandboxUnavailable("the sandbox is not running")
        job_id = uuid.uuid4().hex
        temporary = self.root / "tmp" / f"{job_id}.job"
        temporary.write_text(json.dumps({"files": files}), encoding="utf-8")
        temporary.replace(self.root / "in" / f"{job_id}.json")
        result = self.root / "out" / f"{job_id}.json"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if result.exists():
                data = json.loads(result.read_text(encoding="utf-8"))
                result.unlink(missing_ok=True)
                return data
            time.sleep(0.2)
        (self.root / "in" / f"{job_id}.json").unlink(missing_ok=True)
        raise SandboxUnavailable("the sandbox did not answer in time")


def sandbox_for(settings: Any) -> Sandbox:
    if not settings.sandbox_dir:
        raise SandboxUnavailable("no sandbox is configured")
    return FolderSandbox(settings.sandbox_dir, settings.sandbox_timeout_seconds)
