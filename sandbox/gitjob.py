"""Git operations for one project repository (Phase 1b), run inside a fresh, locked-down job container.

The executor copies the project's bare repository to /repo (a throwaway volume), puts the job in /job/job.json, and,
only for operations that write, copies /repo back afterwards. The commands are fixed here: a job chooses an operation
and its validated arguments (branch names, file paths and contents, a message), never git flags or commands. Hooks are
disabled, system and global configuration are ignored, and nothing is fetched from or pushed to anywhere.

Operations: init, commit (files onto a branch), read (tree and files at a ref), diff (two refs), log, merge (a
branch into the default branch; the API only asks for this after the change set was approved at that exact commit).
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

MARKER = "@@AIDLC-RESULT@@"
REPO = pathlib.Path("/repo/project.git")
REF = re.compile(r"^(?!.*\.\.)(?!.*//)(?!/)(?!.*\.lock$)[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")
MAX_FILES, MAX_FILE_BYTES, MAX_READ_BYTES = 200, 400_000, 2_000_000
DEFAULT_BRANCH = "main"
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
        "-c", "safe.directory=*", "-c", "init.defaultBranch=main", "-c", "commit.gpgSign=false"]


class JobError(Exception):
    pass


def git(*args: str, cwd: pathlib.Path | None = None, repo: bool = True, input_bytes: bytes | None = None,
        check: bool = True) -> str:
    command = ["git", *SAFE, *([f"--git-dir={REPO}"] if repo else []), *args]
    done = subprocess.run(command, cwd=cwd, env=ENV, input=input_bytes, capture_output=True, timeout=60)
    if check and done.returncode != 0:
        raise JobError(done.stderr.decode("utf-8", "replace").strip()[:500] or f"git {args[0]} failed")
    return done.stdout.decode("utf-8", "replace")


def ref_ok(name: str) -> str:
    if not isinstance(name, str) or not (REF.match(name) or SHA.match(name)):
        raise JobError(f"invalid ref: {str(name)[:60]}")
    return name


def exists(ref: str) -> bool:
    return subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          env=ENV, capture_output=True).returncode == 0


def author_env(author: dict) -> dict:
    name = str(author.get("name") or "AI-DLC")[:80].replace("\n", " ")
    email = str(author.get("email") or "noreply@aidlc.local")[:120].replace("\n", " ")
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": "AI-DLC platform",
            "GIT_COMMITTER_EMAIL": "platform@aidlc.local"}


def op_init(job: dict) -> dict:
    if (REPO / "HEAD").exists():
        raise JobError("the repository already exists")
    REPO.mkdir(parents=True, exist_ok=True)  # the executor provides the empty folder, owned by this user
    git("init", "--bare", "--initial-branch", DEFAULT_BRANCH, str(REPO), repo=False)
    readme = job.get("readme") or "# Project repository\n"
    return op_commit({"branch": DEFAULT_BRANCH, "files": [{"path": "README.md", "content": str(readme)[:20000]}],
                      "message": "Initial commit", "author": job.get("author") or {}}, initial=True)


def op_commit(job: dict, initial: bool = False) -> dict:
    branch = ref_ok(job.get("branch", ""))
    if branch == DEFAULT_BRANCH and not initial and not job.get("allow_default"):
        raise JobError("commit to a work branch; the default branch changes only through an approved merge")
    files = job.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise JobError(f"a commit needs 1 to {MAX_FILES} files")
    message = str(job.get("message") or "").strip()[:2000]
    if not message:
        raise JobError("a commit needs a message")
    work = pathlib.Path(tempfile.mkdtemp(dir="/work"))
    index = work / "index"
    env = {**ENV, "GIT_INDEX_FILE": str(index), **author_env(job.get("author") or {})}
    parent = None
    branch_existed = exists(branch)
    if branch_existed:
        parent = git("rev-parse", f"{branch}^{{commit}}").strip()
    elif not initial:
        base = ref_ok(job.get("base") or DEFAULT_BRANCH)
        if not exists(base):
            raise JobError(f"the base {base} does not exist")
        parent = git("rev-parse", f"{base}^{{commit}}").strip()
    if parent:
        subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "read-tree", parent], env=env, check=True,
                       capture_output=True)
    changed = []
    for item in files:
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, str) or not SAFE_PATH.match(path) or ".." in path.split("/") or len(path) > 200:
            raise JobError(f"unsafe path: {str(path)[:60]}")
        if item.get("delete"):
            subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "update-index", "--force-remove", path], env=env,
                           check=True, capture_output=True)
        else:
            content = item.get("content")
            if not isinstance(content, str) or len(content.encode()) > MAX_FILE_BYTES:
                raise JobError(f"file content missing or too large: {path[:60]}")
            blob = subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "hash-object", "-w", "--stdin"], env=env,
                                  input=content.encode(), capture_output=True, check=True).stdout.decode().strip()
            subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "update-index", "--add", "--cacheinfo",
                            f"100644,{blob},{path}"], env=env, check=True, capture_output=True)
        changed.append(path)
    tree = subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "write-tree"], env=env, capture_output=True,
                          check=True).stdout.decode().strip()
    if parent and git("rev-parse", f"{parent}^{{tree}}").strip() == tree:
        raise JobError("nothing changed")
    args = ["git", *SAFE, f"--git-dir={REPO}", "commit-tree", tree, *(["-p", parent] if parent else []), "-m", message]
    commit = subprocess.run(args, env=env, capture_output=True, check=True).stdout.decode().strip()
    # The old value guards against a concurrent change: the branch's last commit, or "must not exist yet".
    git("update-ref", f"refs/heads/{branch}", commit, parent if branch_existed else "0" * 40)
    shutil.rmtree(work, ignore_errors=True)
    return {"branch": branch, "commit": commit, "parent": parent, "changed": changed}


def op_read(job: dict) -> dict:
    ref = ref_ok(job.get("ref") or DEFAULT_BRANCH)
    if not exists(ref):
        raise JobError(f"{ref} does not exist")
    commit = git("rev-parse", f"{ref}^{{commit}}").strip()
    entries = []
    for line in git("ls-tree", "-r", "-l", "--full-tree", commit).splitlines():
        meta, path = line.split("\t", 1)
        _, kind, sha, size = meta.split()
        if kind == "blob":
            entries.append({"path": path, "sha": sha, "size": int(size) if size.isdigit() else 0})
    wanted = job.get("paths")
    files, budget = [], MAX_READ_BYTES
    if isinstance(wanted, list):
        by_path = {e["path"]: e for e in entries}
        for path in wanted[:50]:
            entry = by_path.get(path) if isinstance(path, str) else None
            if entry is None or entry["size"] > budget:
                files.append({"path": str(path)[:200], "missing": entry is None, "too_large": entry is not None})
                continue
            content = git("cat-file", "blob", entry["sha"])
            budget -= entry["size"]
            files.append({"path": path, "content": content})
    return {"ref": ref, "commit": commit, "tree": entries[:5000], "files": files}


def op_diff(job: dict) -> dict:
    base, head = ref_ok(job.get("base") or DEFAULT_BRANCH), ref_ok(job.get("head") or "")
    for ref in (base, head):
        if not exists(ref):
            raise JobError(f"{ref} does not exist")
    merge_base = git("merge-base", base, head, check=False).strip() or base
    stat = git("diff", "--numstat", merge_base, head)
    files = []
    for line in stat.splitlines():
        added, removed, path = line.split("\t", 2)
        files.append({"path": path, "added": int(added) if added.isdigit() else None,
                      "removed": int(removed) if removed.isdigit() else None})
    patch = git("diff", "--no-color", "--no-ext-diff", "-U3", merge_base, head)
    return {"base": base, "head": head, "merge_base": merge_base, "head_commit": git("rev-parse", head).strip(),
            "files": files, "patch": patch[:400_000], "truncated": len(patch) > 400_000}


def op_log(job: dict) -> dict:
    ref = ref_ok(job.get("ref") or DEFAULT_BRANCH)
    limit = max(1, min(int(job.get("limit") or 50), 200))
    if not exists(ref):
        raise JobError(f"{ref} does not exist")
    path = job.get("path")
    if path is not None and (not isinstance(path, str) or not SAFE_PATH.match(path) or ".." in path.split("/")):
        raise JobError("invalid path")
    raw = git("log", f"--max-count={limit}", "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s%x1e", ref,
              *(["--", path] if path else []))
    commits = []
    for record in raw.split("\x1e"):
        parts = record.strip().split("\x1f")
        if len(parts) == 5:
            commits.append(dict(zip(("commit", "author", "email", "date", "subject"), parts, strict=True)))
    branches = [b for b in git("for-each-ref", "--format=%(refname:short)", "refs/heads").split() if b]
    return {"ref": ref, "commits": commits, "branches": branches}


def op_merge(job: dict) -> dict:
    """Merges an approved branch into the default branch at the approved commit, and nothing else."""
    branch, expected = ref_ok(job.get("branch", "")), job.get("expected_head", "")
    if not isinstance(expected, str) or not SHA.match(expected):
        raise JobError("the approved commit is required")
    if git("rev-parse", f"{branch}^{{commit}}").strip() != expected:
        raise JobError("the branch moved after it was approved")
    main = git("rev-parse", f"{DEFAULT_BRANCH}^{{commit}}").strip()
    work = pathlib.Path(tempfile.mkdtemp(dir="/work"))
    env = {**ENV, "GIT_INDEX_FILE": str(work / "index"), **author_env(job.get("author") or {})}
    fast_forward = subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "merge-base", "--is-ancestor", main, expected],
                                  env=ENV, capture_output=True).returncode == 0
    if fast_forward:
        git("update-ref", f"refs/heads/{DEFAULT_BRANCH}", expected, main)
        return {"merged": expected, "fast_forward": True, "default_branch": DEFAULT_BRANCH}
    tree = subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "merge-tree", "--write-tree", main, expected], env=env,
                          capture_output=True)
    if tree.returncode != 0:
        raise JobError("the branch conflicts with the default branch; update it first")
    message = str(job.get("message") or f"Merge {branch}")[:2000]
    commit = subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "commit-tree", tree.stdout.decode().split()[0],
                             "-p", main, "-p", expected, "-m", message], env=env, capture_output=True,
                            check=True).stdout.decode().strip()
    git("update-ref", f"refs/heads/{DEFAULT_BRANCH}", commit, main)
    return {"merged": commit, "fast_forward": False, "default_branch": DEFAULT_BRANCH}


PATTERN = re.compile(r"^[A-Za-z0-9_.*/\-]{1,100}$")


def op_index(job: dict) -> dict:
    """Codebase Explorer: list the files of a commit and parse the imports of those that changed (codeindex.py)."""
    import codeindex

    ref = ref_ok(job.get("ref") or DEFAULT_BRANCH)
    if not exists(ref):
        raise JobError(f"{ref} does not exist")
    known = job.get("known") or {}
    if not isinstance(known, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not SHA.match(v)
                                          for k, v in known.items()):
        raise JobError("invalid index state")
    patterns = job.get("exclude") or list(codeindex.DEFAULT_EXCLUDE)
    if not isinstance(patterns, list) or len(patterns) > 100 or any(
            not isinstance(p, str) or not PATTERN.match(p) for p in patterns):
        raise JobError("invalid exclusion patterns")
    commit = git("rev-parse", f"{ref}^{{commit}}").strip()
    entries = []
    for line in git("ls-tree", "-r", "-l", "--full-tree", commit).splitlines():
        meta, path = line.split("\t", 1)
        _, kind, sha, size = meta.split()
        if kind == "blob" and len(path) <= 500:
            entries.append({"path": path, "sha": sha, "size": int(size) if size.isdigit() else 0})

    def read(sha: str) -> bytes:
        done = subprocess.run(["git", *SAFE, f"--git-dir={REPO}", "cat-file", "blob", sha], env=ENV,
                              capture_output=True, timeout=60, check=True)
        return done.stdout

    try:
        result = codeindex.analyse(entries, read, known, tuple(patterns))
    except RuntimeError as exc:
        raise JobError(str(exc)) from exc
    return {"ref": ref, "commit": commit, **result}


OPERATIONS = {"git.index": op_index, "git.init": op_init, "git.commit": op_commit, "git.read": op_read, "git.diff": op_diff,
              "git.log": op_log, "git.merge": op_merge}


CODE_UID = 2000


def drop_privileges() -> None:
    """Starts as root with only CHOWN, SETUID and SETGID: hands /repo and /work to the unprivileged user, then becomes
    it for good. No git command ever runs as root."""
    if os.getuid() != 0:
        return
    for root, folders, files in os.walk("/repo"):
        for name in [*folders, *files]:
            os.lchown(os.path.join(root, name), CODE_UID, CODE_UID)
        os.lchown(root, CODE_UID, CODE_UID)
    os.chown("/work", CODE_UID, CODE_UID)  # its private scratch space (a fresh tmpfs)
    os.setgroups([])
    os.setgid(CODE_UID)
    os.setuid(CODE_UID)
    if os.getuid() != CODE_UID or os.geteuid() != CODE_UID:
        raise SystemExit("could not drop privileges")


def main() -> None:
    started = time.monotonic()
    drop_privileges()
    try:
        job = json.loads(pathlib.Path("/job/job.json").read_text(encoding="utf-8"))
        operation = OPERATIONS.get(job.get("kind")) if isinstance(job, dict) else None
        if operation is None:
            result = {"status": "rejected", "error": "unknown git operation"}
        else:
            if job["kind"] != "git.init" and not (REPO / "HEAD").exists():
                raise JobError("the project has no repository yet")
            result = {"status": "completed", **operation(job)}
    except JobError as exc:
        result = {"status": "failed", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": type(exc).__name__}
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    os.sync()
    sys.stdout.write("\n" + MARKER + json.dumps(result) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
