"""The Codebase Explorer. The real parsers (Python's ast, the TypeScript compiler) and the real resolver run on real file
contents, including this platform's own backend code; only the hand-off to the executor's container is simulated (the
container path is demonstrated on the test stack). Covers discovery and exclusions, imports of every kind, circular
dependencies, unresolved and external imports, deletion and rename, incremental indexing, permissions, paths outside
the index, predecessors versus successors, impact and chains, and a large repository."""

import hashlib
import json
import os
import pathlib
import sys
import time
import types
import uuid

import pytest

from app.codebase import analysis
from app.codebase import service as codebase
from app.core.errors import AppError
from app.execution import service as execution
from tests.test_devai import _team, checks, git  # noqa: F401  (fixtures)
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sandbox"))
import codeindex

TS = ROOT / "frontend" / "node_modules" / "typescript"
TS_SCRIPT = str(ROOT / "sandbox" / "tsimports.js")
needs_ts = pytest.mark.skipif(not TS.exists(), reason="the TypeScript compiler is not installed locally")


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class Repo:
    """A repository's content at a branch; the executor's git.index job is simulated over it with the real analysis."""

    def __init__(self, files: dict[str, str]):
        self.files, self.parsed_counts = dict(files), []

    def index_result(self, payload: dict) -> dict:
        entries = [{"path": p, "sha": _sha(c), "size": len(c.encode())} for p, c in sorted(self.files.items())]
        blobs = {_sha(c): c.encode() for c in self.files.values()}
        os.environ.setdefault("AIDLC_TS_PATH", str(TS))
        result = codeindex.analyse(entries, blobs.__getitem__, payload.get("known") or {},
                                   codeindex.DEFAULT_EXCLUDE, TS_SCRIPT)
        self.parsed_counts.append(len(result["parsed"]))
        return {"status": "completed", "ref": payload["ref"], "commit": _sha(json.dumps(self.files, sort_keys=True))
                .ljust(40, "0")[:40], **result}


@pytest.fixture
def repo(monkeypatch):
    holder = Repo({})

    def wait(factory, job_id, timeout, poll=0.5):
        from app.execution.models import ExecutionJob

        with factory() as db:
            job = db.get(ExecutionJob, job_id)
            payload = dict(job.payload)
        assert job.kind == "git.index"
        return types.SimpleNamespace(id=job_id, status="succeeded", result=holder.index_result(payload), failure="")

    monkeypatch.setattr(execution, "wait", wait)
    return holder


SMALL = {
    "app/__init__.py": "",
    "app/main.py": "from app.auth import service\nfrom app import db\nimport os\nimport fastapi\n",
    "app/db.py": "from .auth.models import User\n",
    "app/auth/__init__.py": "",
    "app/auth/service.py": "from . import models\nfrom ..db import *\nimport app.missing\n",
    "app/auth/models.py": "import importlib\nplugin = importlib.import_module(name)\n",
    "tests/test_service.py": "from app.auth.service import x\n",
    "tests/test_db.py": "def test_db(): pass\n",
    "web/src/main.tsx": "import { App } from './App';\nimport React from 'react';\nexport * from './api';\n",
    "web/src/App.tsx": "import { api } from './api.js';\nconst page = import(`./pages/${name}`);\n",
    "web/src/api.ts": "export const api = 1; import type { X } from './types';\n",
    "web/src/App.test.tsx": "import { describe } from 'vitest';\n",
    "web/node_modules/react/index.js": "module.exports = 1;\n",
    ".env": "API_KEY=sk-never-read-this-value-123456\n",
    "README.md": "# Demo\n",
    "web/package.json": "{}\n",
}


def _index(client, headers, base, branch="main"):
    started = client.post(f"{base}/codebase/index", headers=headers, json={"branch": branch})
    assert started.status_code == 202, started.text
    return client.get(f"{base}/codebase/status", params={"branch": branch}).json()


# The parsers -------------------------------------------------------------------------------------------------------

def test_python_parser_reads_every_kind_of_import():
    found = codeindex.python_imports(
        "import a.b as c\nfrom .x import y, z\nfrom ... import w\nimport importlib\n"
        "m = importlib.import_module('pkg.mod')\nn = __import__(name)\n")
    assert [(i["spec"], i["level"], i["kind"], i.get("dynamic", False)) for i in found] == [
        ("a.b", 0, "import", False), ("x", 1, "import", False), ("", 3, "import", False),
        ("importlib", 0, "import", False), ("pkg.mod", 0, "dynamic_import", False), ("", 0, "dynamic_import", True)]
    with pytest.raises(SyntaxError):
        codeindex.python_imports("def broken(:\n")


@needs_ts
def test_typescript_parser_reads_imports_exports_requires_and_dynamic_imports(monkeypatch):
    monkeypatch.setenv("AIDLC_TS_PATH", str(TS))
    out = codeindex.ts_imports({"a.tsx": "import x from './x';\nimport type { T } from './t';\nexport { y } from './y';\n"
                                         "const z = require('./z');\nimport('./lazy');\nimport(name);\n"
                                         "import fs = require('fs');\n"}, TS_SCRIPT)["a.tsx"]
    assert out["status"] == "parsed"
    assert [(i["spec"], i["kind"], i.get("dynamic", False)) for i in out["imports"]] == [
        ("./x", "import", False), ("./t", "import", False), ("./y", "re_export", False), ("./z", "require", False),
        ("./lazy", "dynamic_import", False), ("", "dynamic_import", True), ("fs", "require", False)]
    assert out["imports"][1]["type_only"] is True


def test_discovery_skips_dependencies_build_output_and_never_reads_secrets():
    read = []
    entries = [{"path": p, "sha": _sha(c), "size": len(c)} for p, c in SMALL.items() if p.endswith(".py") or "/" not in p
               or p.startswith("web/node_modules")]
    result = codeindex.analyse(entries, lambda sha: read.append(sha) or next(
        c.encode() for c in SMALL.values() if _sha(c) == sha), {}, codeindex.DEFAULT_EXCLUDE, TS_SCRIPT)
    listed = {f["path"] for f in result["files"]}
    assert ".env" not in listed and "web/node_modules/react/index.js" not in listed
    assert result["skipped"] == {"excluded": 1, "secret": 1}
    assert _sha(SMALL[".env"]) not in read  # the secret file was never even read


# The resolver ------------------------------------------------------------------------------------------------------

def test_resolution_distinguishes_confirmed_unresolved_external_and_dynamic():
    r = analysis.Resolver(list(SMALL))
    got = {(e.source, e.spec): (e.target, e.status) for path in SMALL if path.endswith(".py")
           for e in r.resolve(path, codeindex.python_imports(SMALL[path]))}
    assert got[("app/main.py", "app.auth.service")] == ("app/auth/service.py", "confirmed")
    assert got[("app/main.py", "app.db")] == ("app/db.py", "confirmed")
    assert got[("app/main.py", "os")] == (None, "external") and got[("app/main.py", "fastapi")] == (None, "external")
    assert got[("app/db.py", ".auth.models")] == ("app/auth/models.py", "confirmed")
    assert got[("app/auth/service.py", ".models")] == ("app/auth/models.py", "confirmed")
    assert got[("app/auth/service.py", "..db")] == ("app/db.py", "confirmed")
    assert got[("app/auth/service.py", "app.missing")] == (None, "unresolved")  # looks internal, no such file
    assert got[("app/auth/models.py", "")] == (None, "dynamic")
    named = r.tests_by_name(["tests/test_db.py", "tests/test_service.py"], {("tests/test_service.py",
                                                                           "app/auth/service.py")})
    assert [(e.source, e.target, e.status, e.method) for e in named] == [
        ("tests/test_db.py", "app/db.py", "partial", "naming")]  # test_service already imports its source


def test_cycles_and_walks_are_safe():
    succ, pred = analysis.neighbours([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("d", "d")])
    assert analysis.in_cycle("a", succ) and not analysis.in_cycle("d", succ)  # a self-reference is dropped
    assert analysis.reach("a", succ) == {"b": 1, "c": 2, "d": 3}
    assert analysis.reach("d", pred) == {"c": 1, "b": 2, "a": 3}
    assert analysis.chain("a", "d", succ) == ["a", "b", "c", "d"] and analysis.chain("d", "a", succ) == []


# Indexing, through the API ---------------------------------------------------------------------------------------------

@needs_ts
def test_index_graph_inspector_and_impact(managed, engine, git, repo):  # noqa: F811
    t = _team(managed, engine)
    (d, dh), (client, ch), (analyst, ah) = t["dev"], t["client"], t["analyst"]
    base = t["base"]
    assert d.get(f"{base}/codebase/status").json() == {"status": "not_indexed"}
    assert d.get(f"{base}/codebase/tree").json()["code"] == "not_indexed"
    repo.files = dict(SMALL)
    status = _index(d, dh, base)
    assert status["status"] == "up_to_date", status
    counts = status["counts"]
    assert counts["files"] == len(SMALL) - 2 and counts["secret_files_skipped"] == 1 and counts["excluded"] == 1
    assert counts["unresolved"] >= 1 and counts["dynamic"] == 2 and counts["external"] >= 3

    tree = {f["path"]: f for f in d.get(f"{base}/codebase/tree").json()["files"]}
    assert ".env" not in tree and tree["app/main.py"]["type"] == "entry" and tree["tests/test_db.py"]["type"] == "test"
    assert tree["web/package.json"]["type"] == "config" and tree["README.md"]["type"] == "docs"

    info = d.get(f"{base}/codebase/file", params={"path": "app/auth/service.py"}).json()
    successors = {(r["path"], r["status"]) for r in info["successors"]}
    assert ("app/auth/models.py", "confirmed") in successors and ("app/db.py", "confirmed") in successors
    assert (None, "unresolved") in successors  # shown, but never as a file dependency
    assert {r["path"] for r in info["predecessors"]} == {"app/main.py", "tests/test_service.py"}
    assert {r["direction"] for r in info["predecessors"]} == {"incoming"}
    assert info["tests"] == ["tests/test_service.py"] and info["in_cycle"] is False

    ts_info = d.get(f"{base}/codebase/file", params={"path": "web/src/App.tsx"}).json()
    assert {(r["path"], r["status"]) for r in ts_info["successors"]} == {("web/src/api.ts", "confirmed"), (None, "dynamic")}
    assert {(r["path"], r["type"], r["status"]) for r in ts_info["predecessors"]} == {
        ("web/src/main.tsx", "imports", "confirmed"), ("web/src/App.test.tsx", "tests", "partial")}  # by name only

    graph = d.get(f"{base}/codebase/graph", params={"focus": "app/db.py", "depth": 1}).json()
    assert {n["path"] for n in graph["nodes"]} == {"app/db.py", "app/main.py", "app/auth/models.py", "app/auth/service.py",
                                                  "tests/test_db.py"}
    whole = d.get(f"{base}/codebase/graph", params={"focus": "app/db.py", "transitive": True}).json()
    assert "tests/test_service.py" in {n["path"] for n in whole["nodes"]}
    ext = d.get(f"{base}/codebase/graph", params={"external": True, "types": ["entry"]}).json()
    assert {e["name"] for e in ext["external"]} == {"os", "fastapi", "react"}

    impact = d.get(f"{base}/codebase/impact", params={"paths": ["app/auth/models.py"]}).json()
    assert impact["direct"] == ["app/auth/service.py", "app/db.py"]
    # test_db.py is tied to db.py by its name, and db.py imports models.py: it may be affected too.
    assert {i["path"] for i in impact["indirect"]} == {"app/main.py", "tests/test_service.py", "tests/test_db.py"}
    assert impact["tests"] == ["tests/test_db.py", "tests/test_service.py"]
    assert "does not mean they will break" in impact["note"]
    chain = d.get(f"{base}/codebase/chain", params={"source": "app/main.py", "target": "app/auth/models.py"}).json()
    assert chain == {"chain": ["app/main.py", "app/auth/service.py", "app/auth/models.py"], "direction": "depends_on"}

    # Paths must be files of the index: nothing outside the repository can be asked about.
    for bad in ("../../etc/passwd", "/etc/passwd", ".env", "app/nothere.py"):
        r = d.get(f"{base}/codebase/file", params={"path": bad})
        assert r.status_code == 404 and r.json()["code"] == "file_not_indexed", bad
    assert d.get(f"{base}/codebase/tree", params={"branch": "../main"}).status_code == 422
    # Only the project's engineers and administrators.
    assert client.get(f"{base}/codebase/tree").status_code in (403, 404)
    assert client.post(f"{base}/codebase/index", headers=ch, json={"branch": "main"}).status_code in (403, 404)
    assert analyst.get(f"{base}/codebase/tree").status_code == 403  # a Developer tool: not for the BA
    admin, h = t["admin"]
    assert admin.get(f"{base}/codebase/tree").status_code == 403  # nor for administrators
    assert admin.post(f"{base}/codebase/index", headers=h, json={"branch": "main"}).status_code == 403
    assert d.post(f"{base}/codebase/index", json={"branch": "main"}).status_code == 403  # CSRF
    assert ah


@needs_ts
def test_incremental_indexing_deletion_and_rename(managed, engine, git, repo):  # noqa: F811
    t = _team(managed, engine)
    (d, dh), base = t["dev"], t["base"]
    repo.files = dict(SMALL)
    _index(d, dh, base)
    first = repo.parsed_counts[-1]
    status = _index(d, dh, base)  # nothing changed: nothing is parsed again
    assert first == 12 and repo.parsed_counts[-1] == 0  # the 12 code files, parsed once
    assert status["counts"]["reused"] == status["counts"]["files"] == 14  # every file kept as it was
    repo.files["app/db.py"] = "from .auth import models\n"  # one change
    _index(d, dh, base)
    assert repo.parsed_counts[-1] == 1
    # Rename app/auth/models.py -> app/auth/entities.py: the old file and its relationships go; imports re-resolve.
    repo.files["app/auth/entities.py"] = repo.files.pop("app/auth/models.py")
    status = _index(d, dh, base)
    assert status["counts"]["removed"] == 1 and repo.parsed_counts[-1] == 1
    tree = {f["path"] for f in d.get(f"{base}/codebase/tree").json()["files"]}
    assert "app/auth/models.py" not in tree and "app/auth/entities.py" in tree
    info = d.get(f"{base}/codebase/file", params={"path": "app/auth/service.py"}).json()
    after = {(r["path"], r["spec"]) for r in info["successors"]}
    assert not any(p == "app/auth/models.py" for p, _ in after)  # the deleted file is gone from its successors
    assert ("app/auth/__init__.py", ".") in after  # `from . import models` now only reaches the package itself
    gone = d.get(f"{base}/codebase/file", params={"path": "app/auth/models.py"})
    assert gone.status_code == 404 and "moved or deleted" in gone.json()["title"]
    # Adding the missing file resolves the import without re-parsing the importer.
    repo.files["app/missing.py"] = "x = 1\n"
    _index(d, dh, base)
    info = d.get(f"{base}/codebase/file", params={"path": "app/auth/service.py"}).json()
    assert ("app/missing.py", "confirmed") in {(r["path"], r["status"]) for r in info["successors"]}
    assert repo.parsed_counts[-1] == 1  # only the new file


def test_a_failed_analysis_is_reported_plainly(managed, engine, git, monkeypatch):  # noqa: F811
    t = _team(managed, engine)
    (d, dh), base = t["dev"], t["base"]
    monkeypatch.setattr(execution, "wait", lambda *a, **k: types.SimpleNamespace(
        status="failed", result={"status": "failed", "error": "the TypeScript parser failed: boom"}, failure=""))
    status = _index(d, dh, base)
    assert status["status"] == "failed" and "TypeScript parser failed" in status["failure"]
    monkeypatch.setattr(execution, "wait", lambda *a, **k: None)
    status = _index(d, dh, base)
    assert status["status"] == "failed" and "did not answer" in status["failure"]


def test_the_platforms_own_backend_is_indexed_correctly(managed, engine, git, repo):  # noqa: F811
    """Real repository data: this platform's backend/app, as it is in this checkout."""
    t = _team(managed, engine)
    (d, dh), base = t["dev"], t["base"]
    app_dir = ROOT / "backend" / "app"
    repo.files = {f"backend/{p.relative_to(app_dir.parent).as_posix()}": p.read_text(encoding="utf-8")
                  for p in app_dir.rglob("*.py") if "__pycache__" not in p.parts}
    started = time.monotonic()
    status = _index(d, dh, base)
    took = time.monotonic() - started
    assert status["status"] == "up_to_date" and status["counts"]["files"] == len(repo.files)
    assert status["counts"]["parse_errors"] == 0 and status["counts"]["unresolved"] == 0, status["counts"]
    router = d.get(f"{base}/codebase/file", params={"path": "backend/app/devai/router.py"}).json()
    assert {"backend/app/devai/service.py", "backend/app/jobs/api.py", "backend/app/auth/deps.py"} <= \
        {r["path"] for r in router["successors"]}
    used_by = d.get(f"{base}/codebase/file", params={"path": "backend/app/devai/service.py"}).json()
    assert {"backend/app/devai/router.py", "backend/app/jobs/handlers.py"} <= {r["path"] for r in used_by["predecessors"]}
    assert took < 60, took


def test_a_large_repository_is_bounded(managed, engine, git, repo):  # noqa: F811
    t = _team(managed, engine)
    (d, dh), base = t["dev"], t["base"]
    repo.files = {"pkg/__init__.py": ""} | {f"pkg/m{i:04d}.py": f"from pkg import m{i + 1:04d}\n" for i in range(1500)}
    repo.files["pkg/m1500.py"] = "x = 1\n"
    started = time.monotonic()
    status = _index(d, dh, base)
    assert status["status"] == "up_to_date" and status["counts"]["confirmed"] == 1500
    whole = d.get(f"{base}/codebase/graph").json()
    assert whole["truncated"] is True and len(whole["nodes"]) == codebase.MAX_NODES and whole["total_files"] == 1502
    focused = d.get(f"{base}/codebase/graph", params={"focus": "pkg/m0700.py", "depth": 2}).json()
    assert {n["path"] for n in focused["nodes"]} == {"pkg/m0698.py", "pkg/m0699.py", "pkg/m0700.py", "pkg/m0701.py",
                                                    "pkg/m0702.py"}
    assert time.monotonic() - started < 120


def test_a_second_index_of_the_same_branch_waits(managed, engine, git, repo):  # noqa: F811
    t = _team(managed, engine)
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.auth.models import User

    with Session(engine) as db:
        dev = db.execute(select(User).where(User.email == "dee@example.com")).scalar_one()
        codebase.request_index(db, dev, uuid.UUID(t["project"]), "main")
        with pytest.raises(AppError) as again:
            codebase.request_index(db, dev, uuid.UUID(t["project"]), "main")
    assert again.value.code == "indexing"
