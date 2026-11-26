"""Codebase Explorer: turning parsed imports into a dependency graph. Pure and deterministic: no database, no model.

Resolution is done against the whole list of the commit's files, so an import that could not resolve becomes
confirmed as soon as its file exists. Statuses:
- confirmed: resolved to exactly one file of the repository;
- partial: resolved, but not certainly (several candidate files, a path alias, or a test matched by its name only);
- unresolved: looks internal (a relative import, or a top-level name the repository has) but no file matches;
- external: a package from outside the repository (standard library or a dependency);
- dynamic: the target is computed at run time and cannot be read statically.
Only confirmed and partial relationships with a target file appear as edges between files.

Directions: for a file, its successors are the files it depends on (outgoing); its predecessors are the files that
depend on it (incoming).
"""

import posixpath
import sys
from collections import defaultdict, deque
from dataclasses import dataclass

PY_EXT = (".py",)
TS_EXT = (".ts", ".tsx", ".mts", ".cts", ".d.ts", ".js", ".jsx", ".mjs", ".cjs")
CONFIG_NAMES = {"pyproject.toml", "package.json", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", "dockerfile",
                "docker-compose.yml", "docker-compose.yaml", "makefile", "requirements.txt", ".gitignore",
                ".editorconfig", "alembic.ini", "ruff.toml", ".dockerignore", "eslint.config.js", ".eslintrc.json",
                ".prettierrc", "babel.config.js", "jest.config.js", "jest.config.ts"}
CONFIG_EXT = (".toml", ".ini", ".cfg", ".yml", ".yaml", ".json", ".env.example", ".conf")
DOC_EXT = (".md", ".rst", ".txt", ".adoc")
ENTRY_NAMES = {"main.py", "__main__.py", "manage.py", "wsgi.py", "asgi.py", "main.ts", "main.tsx", "index.ts",
               "index.tsx", "index.js", "main.js", "server.js", "server.ts", "app.py"}
STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))


def classify(path: str) -> dict[str, str]:
    """file_type: test, config, docs, entry, source or other; language; extension."""
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""
    language = "python" if lower.endswith(PY_EXT) else "typescript" if lower.endswith((".ts", ".tsx", ".mts", ".cts")) \
        else "javascript" if lower.endswith((".js", ".jsx", ".mjs", ".cjs")) else ""
    parts = path.lower().split("/")
    code = bool(language)
    if code and (lower.startswith("test_") or lower.endswith("_test.py") or ".test." in lower or ".spec." in lower
                 or "tests" in parts[:-1] or "__tests__" in parts[:-1] or lower == "conftest.py"):
        kind = "test"
    elif lower in CONFIG_NAMES or lower.startswith(("tsconfig", "vite.config", "vitest.config", "playwright.config")) \
            or lower.endswith("dockerfile") or (not code and lower.endswith(CONFIG_EXT)):
        kind = "config"
    elif lower.endswith(DOC_EXT) or (parts[0] == "docs" and not code):
        kind = "docs"
    elif code and lower in ENTRY_NAMES:
        kind = "entry"
    elif code:
        kind = "source"
    else:
        kind = "other"
    return {"file_type": kind, "language": language, "extension": ext[:32]}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str | None
    spec: str
    relationship: str
    method: str
    status: str
    confidence: float
    line: int | None


class Resolver:
    """Resolves import specifiers of one commit's files."""

    def __init__(self, paths: list[str]):
        self.paths = set(paths)
        self.modules: dict[str, list[str]] = defaultdict(list)  # dotted module name -> files (at every root)
        self.top_level: set[str] = set()
        for path in paths:
            if not path.endswith(".py"):
                continue
            parts = path[:-3].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for start in range(len(parts)):  # every ancestor folder could be a source root
                name = ".".join(parts[start:])
                if name:
                    self.modules[name].append(path)
            if parts:
                self.top_level.update(parts)

    # Python -------------------------------------------------------------------------------------------------------

    def _pick(self, importer: str, candidates: list[str]) -> tuple[str | None, str]:
        if not candidates:
            return None, "unresolved"
        if len(candidates) == 1:
            return candidates[0], "confirmed"
        # Several roots define it: prefer the one nearest the importing file; it is then only partly certain.
        def shared(path: str) -> int:
            return len(posixpath.commonprefix([importer.split("/"), path.split("/")]))
        ranked = sorted(candidates, key=lambda p: (-shared(p), len(p)))
        if shared(ranked[0]) > shared(ranked[1]):
            return ranked[0], "confirmed"
        return ranked[0], "partial"

    def _relative_module(self, importer: str, level: int, module: str) -> str | None:
        base = importer.split("/")[:-1]
        if level - 1 > len(base):
            return None
        base = base[: len(base) - (level - 1)]
        rel = "/".join([*base, *module.split(".")]) if module else "/".join(base)
        for candidate in (rel + ".py", rel + "/__init__.py"):
            if candidate in self.paths:
                return candidate
        return None

    def python(self, importer: str, imp: dict) -> list[Edge]:
        spec, level, names = imp.get("spec", ""), int(imp.get("level") or 0), imp.get("names") or []
        line, kind = imp.get("line"), imp.get("kind", "import")
        rel = "dynamic_import" if kind == "dynamic_import" else "imports"
        if imp.get("dynamic"):
            return [Edge(importer, None, "", rel, "python_ast", "dynamic", 0.0, line)]
        written = "." * level + spec
        if level:
            out = []
            if names and names != ["*"]:  # `from . import x`: x may be a module of the package
                for name in names:
                    sub = self._relative_module(importer, level, f"{spec}.{name}" if spec else name)
                    if sub:
                        out.append(Edge(importer, sub, f"{written}.{name}" if spec else written + name, rel,
                                        "python_ast", "confirmed", 1.0, line))
            if not out:
                target = self._relative_module(importer, level, spec)
                out.append(Edge(importer, target, written, rel, "python_ast", "confirmed" if target else "unresolved",
                                1.0 if target else 0.0, line))
            return out
        top = spec.split(".")[0]
        if not spec:
            return []
        out = []
        for name in names if names and names != ["*"] else []:  # `from pkg import module`
            target, status = self._pick(importer, self.modules.get(f"{spec}.{name}", []))
            if target:
                out.append(Edge(importer, target, f"{spec}.{name}", rel, "python_ast", status,
                                1.0 if status == "confirmed" else 0.6, line))
        if out:
            return out
        target, status = self._pick(importer, self.modules.get(spec, []))
        if target:
            return [Edge(importer, target, spec, rel, "python_ast", status, 1.0 if status == "confirmed" else 0.6,
                         line)]
        if top in STDLIB or top not in self.top_level:
            return [Edge(importer, None, spec, rel, "python_ast", "external", 1.0, line)]
        return [Edge(importer, None, spec, rel, "python_ast", "unresolved", 0.0, line)]

    # TypeScript / JavaScript ----------------------------------------------------------------------------------------

    def _ts_file(self, base: str) -> str | None:
        base = posixpath.normpath(base)
        if base.startswith("../") or base == "..":
            return None
        stems = [base]
        if base.endswith((".js", ".jsx", ".mjs", ".cjs")):  # ESM-style ".js" written for a ".ts" source
            stems.append(base.rsplit(".", 1)[0])
        for stem in stems:
            if stem in self.paths:
                return stem
            for ext in TS_EXT:
                if stem + ext in self.paths:
                    return stem + ext
            for ext in TS_EXT:
                if f"{stem}/index{ext}" in self.paths:
                    return f"{stem}/index{ext}"
        return None

    def typescript(self, importer: str, imp: dict) -> list[Edge]:
        kind = imp.get("kind", "import")
        rel = {"import": "imports", "re_export": "re_exports", "require": "requires"}.get(kind, "dynamic_import")
        line = imp.get("line")
        if imp.get("dynamic"):
            return [Edge(importer, None, "", rel, "typescript_parser", "dynamic", 0.0, line)]
        spec = str(imp.get("spec") or "").split("?", 1)[0]  # bundler suffixes such as ?worker
        written = str(imp.get("spec") or "")
        if spec.startswith((".", "/")):
            base = posixpath.join(posixpath.dirname(importer), spec) if spec.startswith(".") else spec.lstrip("/")
            target = self._ts_file(base)
            return [Edge(importer, target, written, rel, "typescript_parser", "confirmed" if target else "unresolved",
                         1.0 if target else 0.0, line)]
        if spec.startswith(("@/", "~/")):  # a path alias: try the nearest src/ folder; only partly certain
            parts = importer.split("/")
            for cut in range(len(parts) - 1, -1, -1):
                if parts[cut] == "src":
                    target = self._ts_file("/".join(parts[: cut + 1]) + "/" + spec[2:])
                    if target:
                        return [Edge(importer, target, written, rel, "typescript_parser", "partial", 0.6, line)]
            return [Edge(importer, None, written, rel, "typescript_parser", "unresolved", 0.0, line)]
        return [Edge(importer, None, written, rel, "typescript_parser", "external", 1.0, line)]

    def resolve(self, importer: str, imports: list[dict]) -> list[Edge]:
        out: list[Edge] = []
        python = importer.endswith(".py")
        for imp in imports:
            out += self.python(importer, imp) if python else self.typescript(importer, imp)
        return out

    # Tests matched by name ------------------------------------------------------------------------------------------

    def tests_by_name(self, tests: list[str], linked: set[tuple[str, str]]) -> list[Edge]:
        """test_x.py / x_test.py -> x.py, and x.test.ts / x.spec.tsx -> x.ts(x): nearest file of that name. Only where
        the test does not already import it; marked partial (a match by name, not by code)."""
        by_name: dict[str, list[str]] = defaultdict(list)
        for path in self.paths:
            by_name[path.rsplit("/", 1)[-1]].append(path)
        out = []
        for test in tests:
            name = test.rsplit("/", 1)[-1]
            wanted: list[str] = []
            if name.startswith("test_") and name.endswith(".py"):
                wanted = [name[5:]]
            elif name.endswith("_test.py"):
                wanted = [name[:-8] + ".py"]
            else:
                for marker in (".test.", ".spec."):
                    if marker in name:
                        stem = name.split(marker)[0]
                        wanted = [stem + ext for ext in (".ts", ".tsx", ".js", ".jsx")]
            candidates = [p for w in wanted for p in by_name.get(w, []) if p != test]
            if not candidates:
                continue
            target = min(candidates, key=lambda p: (-len(posixpath.commonprefix([test.split("/"), p.split("/")])),
                                                        len(p)))
            if (test, target) not in linked:
                out.append(Edge(test, target, target.rsplit("/", 1)[-1], "tests", "naming", "partial", 0.5, None))
        return out


# Graph walks -------------------------------------------------------------------------------------------------------

def neighbours(edges: list[tuple[str, str]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """successors (what a file depends on) and predecessors (what depends on it)."""
    succ: dict[str, set[str]] = defaultdict(set)
    pred: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        if a != b:
            succ[a].add(b)
            pred[b].add(a)
    return succ, pred


def reach(start: str, step: dict[str, set[str]], depth: int | None = None) -> dict[str, int]:
    """Every file reachable from start (not start itself), with its distance. Safe with cycles."""
    seen: dict[str, int] = {}
    queue = deque([(start, 0)])
    while queue:
        node, d = queue.popleft()
        if depth is not None and d >= depth:
            continue
        for nxt in sorted(step.get(node, ())):
            if nxt != start and nxt not in seen:
                seen[nxt] = d + 1
                queue.append((nxt, d + 1))
    return seen


def chain(start: str, goal: str, step: dict[str, set[str]]) -> list[str]:
    """A shortest dependency chain from start to goal along step, or [] if there is none."""
    parent: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            out = []
            while node is not None:
                out.append(node)
                node = parent[node]
            return out[::-1]
        for nxt in sorted(step.get(node, ())):
            if nxt not in parent:
                parent[nxt] = node
                queue.append(nxt)
    return []


def in_cycle(start: str, succ: dict[str, set[str]]) -> bool:
    """Whether start depends, directly or not, on itself (self-edges are dropped by neighbours())."""
    return any(start in succ.get(n, ()) for n in reach(start, succ))
