"""Runs generated code, one job at a time, inside the locked-down sandbox container.

The container has no network. Jobs arrive as files on a volume only this process can read. Generated code runs as
a separate unprivileged user, in a private temporary directory, with a clean environment and hard limits. The
commands are fixed here: nothing in a job can choose what is executed besides the project's own code and tests.
"""

import json
import os
import pathlib
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
import uuid

JOBS = pathlib.Path(os.environ.get("SANDBOX_JOBS", "/jobs"))
WORK = pathlib.Path(os.environ.get("SANDBOX_WORK", "/work"))
CODE_UID = 2000
COMMAND_SECONDS = 60
MAX_FILES = 100
MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 2_000_000
OUTPUT_BYTES = 8_000
SAFE_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")
ALLOWED_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".json", ".md", ".txt", ".html", ".css", ".toml", ".yaml", ".yml",
                    ".cfg", ".ini", ".svg"}


def problems_in(files) -> list[str]:
    if not isinstance(files, list) or not files:
        return ["no files were generated"]
    if len(files) > MAX_FILES:
        return [f"more than {MAX_FILES} files"]
    problems, seen, total = [], set(), 0
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or \
                not isinstance(item.get("content"), str):
            problems.append("each file needs a path and text content")
            continue
        path, size = item["path"], len(item["content"].encode())
        total += size
        if not SAFE_PATH.match(path) or ".." in path.split("/") or len(path) > 200:
            problems.append(f"unsafe file path: {path[:80]}")
        elif pathlib.PurePosixPath(path).suffix.lower() not in ALLOWED_SUFFIXES:
            problems.append(f"file type is not allowed: {path[:80]}")
        elif path.lower() in seen:
            problems.append(f"duplicate file: {path[:80]}")
        elif size > MAX_FILE_BYTES:
            problems.append(f"file is too large: {path[:80]}")
        seen.add(path.lower())
    if total > MAX_TOTAL_BYTES:
        problems.append("the project is too large")
    return problems


def _limit_child(cwd: pathlib.Path) -> None:
    os.setsid()
    os.setgroups([])
    os.setgid(CODE_UID)
    os.setuid(CODE_UID)
    os.chdir(cwd)  # only the unprivileged user can enter its workspace
    os.umask(0o077)
    for name, value in ((resource.RLIMIT_CPU, COMMAND_SECONDS), (resource.RLIMIT_FSIZE, 10_000_000),
                        (resource.RLIMIT_NOFILE, 256), (resource.RLIMIT_NPROC, 64), (resource.RLIMIT_CORE, 0)):
        resource.setrlimit(name, (value, value))


def _stop_all_code() -> None:
    """Removes anything the generated code left running, including processes that detached themselves."""
    pid = os.fork()
    if pid == 0:
        try:
            os.setgid(CODE_UID)
            os.setuid(CODE_UID)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.kill(-1, signal.SIGKILL)
        finally:
            os._exit(0)
    os.waitpid(pid, 0)


def _wipe(cwd: pathlib.Path) -> None:
    """Deletes the workspace as its owner, including anything the code made unreadable."""
    pid = os.fork()
    if pid == 0:
        try:
            os.setgid(CODE_UID)
            os.setuid(CODE_UID)
            for root, folders, _ in os.walk(cwd):
                os.chmod(root, 0o700)
                for name in folders:
                    os.chmod(os.path.join(root, name), 0o700)
            for entry in cwd.iterdir():
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
        finally:
            os._exit(0)
    os.waitpid(pid, 0)
    os.rmdir(cwd)


def run(command: list[str], cwd: pathlib.Path) -> tuple[int | None, str]:
    log = WORK / f".log-{uuid.uuid4().hex}"
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(cwd), "TMPDIR": "/tmp", "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "NODE_NO_WARNINGS": "1"}
    with log.open("wb") as out:
        os.chmod(log, 0o600)
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                   preexec_fn=lambda: _limit_child(cwd), close_fds=True)
        try:
            code: int | None = process.wait(timeout=COMMAND_SECONDS)
        except subprocess.TimeoutExpired:
            code = None
            _stop_all_code()  # the runner may signal the code only as the same user
            process.wait()
    _stop_all_code()
    with log.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - OUTPUT_BYTES))
        text = handle.read().decode("utf-8", "replace")
    log.unlink()
    return code, text.replace(str(cwd), ".")


def check(passed: bool, summary: str, output: str = "") -> dict:
    return {"passed": passed, "summary": summary, "output": output}


def _python(cwd: pathlib.Path) -> dict:
    code, out = run([sys.executable, "-m", "compileall", "-q", "."], cwd)
    build = check(code == 0, "Python files compile" if code == 0 else "Python files do not compile", out)
    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", "."], cwd)
    counts = re.findall(r"(\d+) (passed|failed|error|errors)", out)
    text = ", ".join(f"{n} {w}" for n, w in counts) or "no result"
    if code is None:
        return {"build": build, "unit_tests": check(False, "Tests timed out", out)}
    if code == 5:
        return {"build": build, "unit_tests": check(False, "No tests were found", out)}
    return {"build": build, "unit_tests": check(code == 0, f"Tests: {text}", out)}


def _node(cwd: pathlib.Path, scripts: list[str]) -> dict:
    failed, output = [], ""
    for script in scripts:
        code, out = run(["node", "--check", script], cwd)
        if code != 0:
            failed.append(script)
            output += out
    build = check(not failed, "JavaScript files parse" if not failed else "JavaScript files do not parse", output)
    code, out = run(["node", "--test", "."], cwd)
    passed = re.search(r"# pass (\d+)", out)
    failures = re.search(r"# fail (\d+)", out)
    if code is None:
        return {"build": build, "unit_tests": check(False, "Tests timed out", out)}
    if not passed or int(passed.group(1)) == 0:
        return {"build": build, "unit_tests": check(False, "No passing tests were found", out)}
    return {"build": build, "unit_tests": check(code == 0, f"Tests: {passed.group(1)} passed, "
                                                           f"{failures.group(1) if failures else 0} failed", out)}


def execute(job: dict) -> dict:
    files = job.get("files")
    problems = problems_in(files)
    if problems:
        message = "; ".join(problems)[:500]
        return {"status": "completed", "language": None, "checks": {
            "build": check(False, message), "unit_tests": check(False, "Tests were not run")}}
    cwd = WORK / uuid.uuid4().hex
    cwd.mkdir(mode=0o700)
    try:
        for item in files:
            target = cwd / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item["content"], encoding="utf-8")
        for path in [*sorted(cwd.rglob("*"), reverse=True), cwd]:  # children first: the owner changes last
            os.chown(path, CODE_UID, CODE_UID)
        names = [f["path"] for f in files]
        scripts = [n for n in names if n.endswith((".js", ".mjs", ".cjs"))]
        if any(n.endswith(".py") for n in names):
            return {"status": "completed", "language": "python", "checks": _python(cwd)}
        if scripts:
            return {"status": "completed", "language": "javascript", "checks": _node(cwd, scripts)}
        return {"status": "completed", "language": None, "checks": {
            "build": check(False, "No Python or JavaScript source was generated"),
            "unit_tests": check(False, "Tests were not run")}}
    finally:
        _stop_all_code()
        _wipe(cwd)


def _publish(job_id: str, result: dict) -> None:
    temporary = JOBS / "tmp" / f"{job_id}.result"
    temporary.write_text(json.dumps(result), encoding="utf-8")
    temporary.replace(JOBS / "out" / f"{job_id}.json")


def main() -> None:
    for name in ("in", "out", "tmp"):
        (JOBS / name).mkdir(parents=True, exist_ok=True)
    JOBS.chmod(0o700)
    while True:
        (JOBS / "tmp" / "heartbeat").write_text(str(time.time()))
        (JOBS / "tmp" / "heartbeat").replace(JOBS / "heartbeat")
        pending = sorted((JOBS / "in").glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not pending:
            time.sleep(0.25)
            continue
        path = pending[0]
        started = time.monotonic()
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            result = execute(job)
        except Exception as exc:  # noqa: BLE001 - a broken job must never stop the runner
            result = {"status": "error", "error": type(exc).__name__, "checks": {}}
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        path.unlink(missing_ok=True)
        _publish(path.stem, result)


if __name__ == "__main__":
    main()
