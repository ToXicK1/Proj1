"""Codebase Explorer service: indexing a branch and answering questions about its dependency graph.

Indexing (a worker job): the executor lists the commit's files and parses the imports of files whose blob changed
since the last index (`git.index`, in a locked-down container with no network). Here the results are stored: files
that no longer exist are removed (with their relationships), changed files are updated, unchanged files kept, and every
import is resolved again against the full file list. Only the project's Software Developers may index or read it, and
every path asked about must be a file of the index: a request can never reach outside the repository.
Nothing here runs code or changes the repository, and no source code is sent to any AI service.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.codebase import analysis
from app.codebase.models import CodeIndex, FileDependency, RepositoryFile
from app.core.db import uuid7
from app.core.errors import AppError

INDEX_WAIT = 330
STALE_INDEXING = timedelta(minutes=15)
MAX_NODES = 300
EDGE_STATUSES = ("confirmed", "partial")
DEVELOPER = "software_developer"


def _access(db: Session, user: User, project_id: uuid.UUID, branch: str) -> tuple[Any, Any]:
    from app.collab.service import scope_for
    from app.execution.service import _allowed
    from app.repos.service import BRANCH, _repo

    project = _allowed(db, user, project_id)
    _, scope = scope_for(db, user, project_id)
    if scope.kind != "professional" or DEVELOPER not in scope.profiles:  # a Developer tool: not admins, not other roles
        raise AppError(403, "not_permitted", "The Codebase Explorer is for the project's Software Developers")
    repo = _repo(db, project.id)
    if not BRANCH.match(branch):
        raise AppError(422, "invalid_branch", "Choose a branch of the repository")
    return project, repo


def _index(db: Session, repo_id: uuid.UUID, branch: str) -> CodeIndex | None:
    return db.execute(select(CodeIndex).where(CodeIndex.repository_id == repo_id, CodeIndex.branch == branch)
                      ).scalar_one_or_none()


def status_out(row: CodeIndex | None) -> dict[str, Any]:
    if row is None:
        return {"status": "not_indexed"}
    return {"status": row.status, "branch": row.branch, "commit": row.commit, "counts": row.counts,
            "failure": row.failure, "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None}


def status(db: Session, user: User, project_id: uuid.UUID, branch: str) -> dict[str, Any]:
    _, repo = _access(db, user, project_id, branch)
    return status_out(_index(db, repo.id, branch))


def request_index(db: Session, user: User, project_id: uuid.UUID, branch: str) -> CodeIndex:
    """Marks the branch as indexing. One index at a time per branch; a run stuck for 15 minutes may be restarted."""
    from app.events.service import publish

    project, repo = _access(db, user, project_id, branch)
    row = db.execute(select(CodeIndex).where(CodeIndex.repository_id == repo.id, CodeIndex.branch == branch)
                     .with_for_update()).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is not None and row.status == "indexing" and now - row.started_at < STALE_INDEXING:
        raise AppError(409, "indexing", "This branch is being analysed already")
    if row is None:
        row = CodeIndex(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                        repository_id=repo.id, branch=branch, counts={})
        db.add(row)
    row.status, row.failure, row.requested_by_user_id, row.started_at, row.finished_at = \
        "indexing", "", user.id, now, None
    append_event(db, chain_key=org_chain(project.organization_id), event_type="codebase.index_requested",
                 actor_type="human", actor_id=str(user.id), organization_id=project.organization_id,
                 project_id=project.id, payload={"branch": branch})
    publish(db, organization_id=project.organization_id, project_id=project.id, kind="codebase.indexing",
            subject=branch, actor=f"user:{user.id}", data={"branch": branch})
    db.commit()
    return row


def _store(db: Session, row: CodeIndex, result: dict[str, Any]) -> dict[str, int]:
    """Applies one analysis result: removes deleted files, updates changed ones, and resolves every import again."""
    commit, branch = result["commit"], row.branch
    listed = {f["path"]: f for f in result["files"]}
    parsed: dict[str, dict] = result.get("parsed") or {}
    existing = {f.relative_path: f for f in db.execute(select(RepositoryFile).where(
        RepositoryFile.repository_id == row.repository_id, RepositoryFile.branch == branch)).scalars()}
    removed = [f for p, f in existing.items() if p not in listed]
    for f in removed:
        db.delete(f)  # its relationships go with it (ON DELETE CASCADE)
    db.flush()
    reused = 0
    files: dict[str, RepositoryFile] = {}
    for path, entry in listed.items():
        f = existing.get(path)
        kind = analysis.classify(path)
        if f is None:
            f = RepositoryFile(id=uuid7(), project_id=row.project_id, repository_id=row.repository_id, branch=branch,
                               relative_path=path, file_name=path.rsplit("/", 1)[-1][:255], content_hash=entry["sha"],
                               last_indexed_commit=commit, imports=[])
            db.add(f)
        if path in parsed:
            info = parsed[path]
            f.imports = info.get("imports") or []
            f.analysis_status = str(info.get("status") or "parsed")[:24]
            f.analysis_error = str(info.get("error") or "")[:200]
        elif f.content_hash == entry["sha"] and path in existing:
            reused += 1
        else:
            f.imports, f.analysis_status, f.analysis_error = [], "not_parsed", ""
        f.content_hash, f.size, f.last_indexed_commit = entry["sha"], int(entry.get("size") or 0), commit
        f.extension, f.file_type, f.language = kind["extension"], kind["file_type"], kind["language"]
        f.indexed_at = datetime.now(UTC)
        files[path] = f
    db.flush()

    db.execute(delete(FileDependency).where(FileDependency.repository_id == row.repository_id,
                                            FileDependency.branch == branch))
    resolver = analysis.Resolver(list(files))
    edges: list[analysis.Edge] = []
    for path, f in files.items():
        if f.imports:
            edges += resolver.resolve(path, f.imports)
    linked = {(e.source, e.target) for e in edges if e.target}
    edges += resolver.tests_by_name([p for p, f in files.items() if f.file_type == "test"], linked)
    for e in edges:
        db.add(FileDependency(id=uuid7(), repository_id=row.repository_id, branch=branch,
                              source_file_id=files[e.source].id,
                              target_file_id=files[e.target].id if e.target else None, target_spec=e.spec[:300],
                              relationship_type=e.relationship, discovery_method=e.method,
                              resolution_status=e.status, confidence=e.confidence, line=e.line,
                              last_indexed_commit=commit))
    by_status = Counter(e.status for e in edges)
    errors = sum(1 for f in files.values() if f.analysis_status == "parse_error")
    return {"files": len(files), "parsed": len(parsed), "reused": reused, "removed": len(removed),
            "relationships": len(edges), "confirmed": by_status["confirmed"], "partial": by_status["partial"],
            "unresolved": by_status["unresolved"], "external": by_status["external"],
            "dynamic": by_status["dynamic"], "parse_errors": errors,
            "excluded": int((result.get("skipped") or {}).get("excluded", 0)),
            "secret_files_skipped": int((result.get("skipped") or {}).get("secret", 0)),
            "over_file_limit": bool(result.get("partial"))}


def run_index(factory: sessionmaker[Session], index_id: uuid.UUID, finish=None) -> None:
    """The worker's job: ask the executor for the analysis, then store it. A failure is recorded plainly."""
    from app.events.service import publish
    from app.execution import service as execution

    with factory() as db:
        row = db.get(CodeIndex, index_id)
        if row is None or row.status != "indexing":
            if finish:
                finish(db)
            db.commit()
            return
        known = dict(db.execute(select(RepositoryFile.relative_path, RepositoryFile.content_hash).where(
            RepositoryFile.repository_id == row.repository_id, RepositoryFile.branch == row.branch,
            RepositoryFile.analysis_status != "not_parsed")).all())
        job = execution.submit(db, organization_id=row.organization_id, project_id=row.project_id, kind="git.index",
                               payload={"ref": row.branch, "known": known}, user_id=row.requested_by_user_id)
        db.commit()
        done = execution.wait(factory, job.id, INDEX_WAIT)
        db.refresh(row)
        try:
            if done is None:
                raise AppError(503, "execution_unavailable", "The execution service did not answer")
            if done.status != "succeeded" or (done.result or {}).get("status") != "completed":
                raise AppError(502, "index_failed", str((done.result or {}).get("error") or done.failure
                                                        or done.status)[:250])
            counts = _store(db, row, done.result)
            row.counts, row.commit = counts, done.result["commit"]
            row.status = "partial" if counts["over_file_limit"] or counts["parse_errors"] else "up_to_date"
        except AppError as exc:
            db.rollback()
            row = db.get(CodeIndex, index_id)
            row.status, row.failure = "failed", exc.message[:300]
        row.finished_at = datetime.now(UTC)
        publish(db, organization_id=row.organization_id, project_id=row.project_id, kind="codebase.indexed",
                subject=row.branch, actor="worker", data={"branch": row.branch, "status": row.status})
        if finish:
            finish(db)
        db.commit()


# Reading the graph -------------------------------------------------------------------------------------------------

class Graph:
    """One branch's index, loaded for answering a question."""

    def __init__(self, db: Session, repo_id: uuid.UUID, branch: str):
        self.files = {f.id: f for f in db.execute(select(RepositoryFile).where(
            RepositoryFile.repository_id == repo_id, RepositoryFile.branch == branch)).scalars()}
        self.by_path = {f.relative_path: f for f in self.files.values()}
        self.deps = list(db.execute(select(FileDependency).where(FileDependency.repository_id == repo_id,
                                                                 FileDependency.branch == branch)).scalars())
        pairs = [(self.files[d.source_file_id].relative_path, self.files[d.target_file_id].relative_path)
                 for d in self.deps if d.target_file_id and d.resolution_status in EDGE_STATUSES]
        self.succ, self.pred = analysis.neighbours(pairs)

    def file(self, path: str) -> RepositoryFile:
        f = self.by_path.get(path)
        if f is None:
            raise AppError(404, "file_not_indexed", "This file is not in the analysis of this branch: it may have been "
                                                    "moved or deleted. Refresh the analysis.")
        return f


def _graph(db: Session, user: User, project_id: uuid.UUID, branch: str) -> tuple[Graph, CodeIndex]:
    _, repo = _access(db, user, project_id, branch)
    row = _index(db, repo.id, branch)
    if row is None or not row.commit:
        raise AppError(409, "not_indexed", "This branch has not been analysed yet")
    return Graph(db, repo.id, branch), row


def node_out(g: Graph, f: RepositoryFile) -> dict[str, Any]:
    path = f.relative_path
    return {"path": path, "name": f.file_name, "type": f.file_type, "language": f.language, "size": f.size,
            "status": f.analysis_status, "successors": len(g.succ.get(path, ())),
            "predecessors": len(g.pred.get(path, ()))}


def tree(db: Session, user: User, project_id: uuid.UUID, branch: str) -> dict[str, Any]:
    g, row = _graph(db, user, project_id, branch)
    return {"index": status_out(row), "files": sorted((node_out(g, f) for f in g.files.values()),
                                                     key=lambda n: n["path"])}


def graph(db: Session, user: User, project_id: uuid.UUID, branch: str, *, focus: str | None, depth: int,
          transitive: bool, types: list[str], relations: list[str], external: bool) -> dict[str, Any]:
    """The graph to draw: around a focused file (to a depth, or everything reachable), or the whole branch up to
    MAX_NODES files (the most connected first)."""
    g, row = _graph(db, user, project_id, branch)
    limit = None if transitive else max(1, min(depth, 6))
    if focus:
        g.file(focus)
        chosen = {focus, *analysis.reach(focus, g.succ, limit), *analysis.reach(focus, g.pred, limit)}
    else:
        chosen = set(g.by_path)
    if types:
        chosen = {p for p in chosen if g.by_path[p].file_type in types or p == focus}
    truncated = len(chosen) > MAX_NODES
    if truncated:
        degree = {p: len(g.succ.get(p, ())) + len(g.pred.get(p, ())) for p in chosen}
        chosen = set(sorted(chosen, key=lambda p: (p != focus, -degree[p], p))[:MAX_NODES])
    edges, ext_nodes = [], {}
    for d in g.deps:
        if relations and d.relationship_type not in relations:
            continue
        source = g.files[d.source_file_id].relative_path
        if source not in chosen:
            continue
        if d.target_file_id and d.resolution_status in EDGE_STATUSES:
            target = g.files[d.target_file_id].relative_path
            if target in chosen:
                edges.append({"source": source, "target": target, "type": d.relationship_type,
                              "status": d.resolution_status, "method": d.discovery_method})
        elif external and d.resolution_status == "external" and d.target_spec:
            name = d.target_spec.split("/")[0] if not d.target_spec.startswith("@") \
                else "/".join(d.target_spec.split("/")[:2])
            name = name.split(".")[0] if source.endswith(".py") else name
            ext_nodes[name] = ext_nodes.get(name, 0) + 1
            edges.append({"source": source, "target": f"external:{name}", "type": d.relationship_type,
                          "status": "external", "method": d.discovery_method})
    unique = {(e["source"], e["target"], e["type"]): e for e in edges}
    return {"index": status_out(row), "focus": focus, "truncated": truncated, "total_files": len(g.by_path),
            "nodes": [node_out(g, g.by_path[p]) for p in sorted(chosen)],
            "external": [{"name": n, "uses": c} for n, c in sorted(ext_nodes.items())],
            "edges": list(unique.values())}


def _relation(g: Graph, d: FileDependency, other: str | None, direction: str) -> dict[str, Any]:
    return {"path": other, "spec": d.target_spec, "type": d.relationship_type, "status": d.resolution_status,
            "method": d.discovery_method, "confidence": d.confidence, "line": d.line, "direction": direction}


def file_details(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID, branch: str,
                 path: str, history: bool) -> dict[str, Any]:
    """The inspector: incoming (predecessors) and outgoing (successors) relationships, transitive ones, related tests
    and configuration, and, on request, the file's last commit."""
    from app.repos.models import ChangeSet

    g, row = _graph(db, user, project_id, branch)
    f = g.file(path)
    outgoing, incoming = [], []
    for d in g.deps:
        if d.source_file_id == f.id:
            outgoing.append(_relation(g, d, g.files[d.target_file_id].relative_path if d.target_file_id else None,
                                      "outgoing"))
        elif d.target_file_id == f.id and d.resolution_status in EDGE_STATUSES:
            incoming.append(_relation(g, d, g.files[d.source_file_id].relative_path, "incoming"))
    succ_all, pred_all = analysis.reach(path, g.succ), analysis.reach(path, g.pred)
    tests = sorted({p for p in pred_all if g.by_path[p].file_type == "test"}
                   | {r["path"] for r in incoming if r["type"] == "tests"})
    parts = path.split("/")
    ancestors = {"/".join(parts[:i]) for i in range(len(parts))}  # "" (the root), then each parent folder
    configs = [p for p, x in g.by_path.items() if x.file_type == "config"
               and (p.rsplit("/", 1)[0] if "/" in p else "") in ancestors]
    open_sets = [{"number": cs.number, "title": cs.title, "status": cs.status, "branch": cs.branch}
                 for cs in db.execute(select(ChangeSet).where(ChangeSet.project_id == row.project_id,
                                                              ChangeSet.status.in_(("open", "in_review", "approved"))
                                                              )).scalars()
                 if any(x.get("path") == path for x in cs.files)]
    out = {"index": status_out(row), "file": node_out(g, f), "extension": f.extension, "hash": f.content_hash,
           "analysis_error": f.analysis_error, "last_indexed_commit": f.last_indexed_commit,
           "successors": sorted(outgoing, key=lambda r: (r["path"] is None, r["path"] or r["spec"])),
           "predecessors": sorted(incoming, key=lambda r: r["path"]),
           "transitive_successors": [{"path": p, "distance": d} for p, d in sorted(succ_all.items(),
                                                                                    key=lambda x: (x[1], x[0]))][:200],
           "transitive_predecessors": [{"path": p, "distance": d} for p, d in sorted(pred_all.items(),
                                                                                      key=lambda x: (x[1], x[0]))][:200],
           "in_cycle": analysis.in_cycle(path, g.succ), "tests": tests, "configs": sorted(configs)[:10],
           "change_sets": open_sets, "last_commit": None}
    if history:
        from app.repos import service as repos

        project, _ = _access(db, user, project_id, branch)
        log = repos._run(db, factory, project, user, "git.log", {"ref": branch, "limit": 1, "path": path})
        out["last_commit"] = (log.get("commits") or [None])[0]
    return out


def impact(db: Session, user: User, project_id: uuid.UUID, branch: str, paths: list[str],
           change_set_id: uuid.UUID | None) -> dict[str, Any]:
    """Files that may be affected if these files change: what depends on them, directly and indirectly, and the
    tests among them. A possibility from the dependency graph, not a certainty."""
    from app.repos.models import ChangeSet

    g, row = _graph(db, user, project_id, branch)
    changed = list(paths)
    change_set = None
    if change_set_id is not None:
        cs = db.get(ChangeSet, change_set_id)
        if cs is None or cs.project_id != row.project_id:
            raise AppError(404, "not_found", "Not found")
        change_set = {"number": cs.number, "title": cs.title, "branch": cs.branch, "status": cs.status}
        changed += [x["path"] for x in cs.files if isinstance(x.get("path"), str)]
    known = [p for p in dict.fromkeys(changed) if p in g.by_path]
    direct, indirect = set(), {}
    for p in known:
        for q, d in analysis.reach(p, g.pred).items():
            if q in known:
                continue
            if d == 1:
                direct.add(q)
            elif q not in direct:
                indirect[q] = min(d, indirect.get(q, d))
    indirect = {q: d for q, d in indirect.items() if q not in direct}
    affected = direct | set(indirect)
    tests = sorted({q for q in affected if g.by_path[q].file_type == "test"} | {
        g.files[d.source_file_id].relative_path for d in g.deps if d.relationship_type == "tests"
        and d.target_file_id and g.files[d.target_file_id].relative_path in known})
    return {"index": status_out(row), "change_set": change_set, "changed": known,
            "not_in_index": [p for p in dict.fromkeys(changed) if p not in g.by_path],
            "direct": sorted(direct), "indirect": [{"path": p, "distance": d} for p, d in sorted(
                indirect.items(), key=lambda x: (x[1], x[0]))], "tests": tests,
            "note": "Files that depend on the changed files may be affected. This comes from the dependency graph; "
                    "it does not mean they will break."}


def dependency_chain(db: Session, user: User, project_id: uuid.UUID, branch: str, source: str,
                     target: str) -> dict[str, Any]:
    g, _ = _graph(db, user, project_id, branch)
    g.file(source)
    g.file(target)
    return {"chain": analysis.chain(source, target, g.succ) or analysis.chain(target, source, g.succ),
            "direction": "depends_on" if analysis.chain(source, target, g.succ) else "depended_on_by"}
