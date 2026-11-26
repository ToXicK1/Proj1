"""Source analysis for the Codebase Explorer, run inside a locked-down job container (no network, read-only copy of
the repository, unprivileged user). Deterministic: the language's own parser, never a model.

- Python: the standard library's `ast`. Records `import a.b`, `from .x import y` (with its level), and literal
  `importlib.import_module("x")` / `__import__("x")`. A dynamic import whose target is not a literal is recorded as
  dynamic, with no target.
- TypeScript / JavaScript: the TypeScript compiler's parser (tsimports.js). Records import and export-from
  declarations, `import x = require("y")`, `require("y")` and `import("y")`.

The job lists the files of a commit, skips excluded paths (dependencies, build output, caches and anything that may
hold secrets, which are never read), and parses only files whose blob changed since the last index. It returns import
specifiers exactly as written; resolving them to files is done by the platform against the whole file list.
"""

import ast
import fnmatch
import json
import subprocess

PY = (".py",)
TS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
MAX_PARSE_BYTES = 400_000
MAX_FILES = 5000
DEFAULT_EXCLUDE = (
    ".git/*", "*/.git/*", "node_modules/*", "*/node_modules/*", ".venv/*", "*/.venv/*", "venv/*", "*/venv/*",
    "dist/*", "*/dist/*", "build/*", "*/build/*", "__pycache__/*", "*/__pycache__/*", "coverage/*", "*/coverage/*",
    ".pytest_cache/*", "*/.pytest_cache/*", ".mypy_cache/*", "*/.mypy_cache/*", ".ruff_cache/*", "*/.ruff_cache/*",
    "*.min.js", "*.map", "*.lock", "package-lock.json", "*/package-lock.json", "*.pyc",
)
# Never listed, read or described: anything that may hold credentials.
# Data files only: source code that handles secrets (secrets.py, credentials.ts) is code and is analysed.
SECRET = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*",
          "*credentials*.json", "secrets.json", "secrets.yaml", "secrets.yml", "secrets.toml", "*.secrets",
          ".secrets", "*.keystore", "*.jks", ".npmrc", ".pypirc", ".netrc")


def excluded(path: str, patterns: tuple[str, ...]) -> str | None:
    """'secret', 'excluded' or None."""
    name = path.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, p) for p in SECRET) and not name.endswith((".example", ".sample", ".template")):
        return "secret"
    if any(fnmatch.fnmatch(path, p) for p in patterns):
        return "excluded"
    return None


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def python_imports(text: str) -> list[dict]:
    """Import statements of one Python file, as written. Raises SyntaxError for a file that does not parse."""
    tree = ast.parse(text)
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append({"spec": alias.name, "level": 0, "names": [], "kind": "import", "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            out.append({"spec": node.module or "", "level": node.level, "names": [a.name for a in node.names],
                        "kind": "import", "line": node.lineno})
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            owner = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else ""
            if (name == "import_module" and owner in ("importlib", "")) or name == "__import__":
                target = _literal(node.args[0]) if node.args else None
                out.append({"spec": target or "", "level": 0, "names": [], "kind": "dynamic_import",
                            "line": node.lineno, "dynamic": target is None})
    return sorted(out, key=lambda i: (i["line"], i["spec"]))


def ts_imports(files: dict[str, str], script: str = "/opt/runner/tsimports.js") -> dict[str, dict]:
    """Imports of TypeScript/JavaScript files, through the TypeScript compiler's parser, in one Node process."""
    if not files:
        return {}
    run = subprocess.run(["node", script], input=json.dumps(files).encode(), capture_output=True, timeout=300,
                         check=False)
    if run.returncode != 0:
        raise RuntimeError("the TypeScript parser failed: " + run.stderr.decode("utf-8", "replace")[-300:])
    return json.loads(run.stdout)


def analyse(entries: list[dict], read, known: dict[str, str], patterns: tuple[str, ...],
            ts_script: str = "/opt/runner/tsimports.js") -> dict:
    """entries: [{path, sha, size}] of the commit. read(sha) returns a blob's bytes. known: path -> sha already
    indexed (unchanged files are not read again). Returns the listed files, what was excluded, and the imports of the
    files that changed."""
    files, skipped = [], {"excluded": 0, "secret": 0}
    for entry in entries:
        why = excluded(entry["path"], patterns)
        if why:
            skipped[why] += 1
            continue
        files.append(entry)
    partial = len(files) > MAX_FILES
    files = files[:MAX_FILES]
    parsed: dict[str, dict] = {}
    ts_sources: dict[str, str] = {}
    for entry in files:
        path = entry["path"]
        if known.get(path) == entry["sha"] or not path.endswith(PY + TS):
            continue
        if entry["size"] > MAX_PARSE_BYTES:
            parsed[path] = {"status": "too_large", "imports": []}
            continue
        raw = read(entry["sha"])
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            parsed[path] = {"status": "not_text", "imports": []}
            continue
        if path.endswith(PY):
            try:
                parsed[path] = {"status": "parsed", "imports": python_imports(text)}
            except (SyntaxError, ValueError, RecursionError) as exc:
                parsed[path] = {"status": "parse_error", "imports": [],
                                "error": f"line {getattr(exc, 'lineno', '?')}: {str(exc)[:120]}"}
        else:
            ts_sources[path] = text
    for path, result in ts_imports(ts_sources, ts_script).items():
        parsed[path] = result
    return {"files": files, "skipped": skipped, "partial": partial, "parsed": parsed}
