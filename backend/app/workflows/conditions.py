"""Stage conditions: deterministic, structured, never model text and never code.

A condition is JSON, built from:
    {"all": [c, ...]}   {"any": [c, ...]}   {"not": c}
    {"fact": NAME, OP}                         facts about the project, fixed when delivery starts
    {"artifact": STAGE, "field": KEY, OP}      a field of an earlier stage's approved deliverable
with OP one of {"equals": v}, {"in": [v, ...]}, {"present": true|false}.

Facts: project_type, scope, and intake.<field> (the owner's confirmed brief).
A stage whose condition is false when its dependencies are satisfied is SKIPPED, which counts as satisfied for
the stages after it. Nothing is evaluated by `eval`; unknown shapes are refused when the workflow is compiled.
"""

import re
from collections.abc import Callable
from typing import Any

FACTS = re.compile(r"^(project_type|scope|intake\.[a-z][a-z0-9_]{0,63})$")
OPS = ("equals", "in", "present")
MAX_NODES = 30
MAX_DEPTH = 5
Lookup = Callable[[str, str], tuple[bool, Any]]  # (stage, field) -> (found, value)


def problems(condition: Any, upstream: set[str], path: str = "condition") -> list[str]:
    out: list[str] = []
    count = [0]

    def walk(node: Any, where: str, depth: int) -> None:
        count[0] += 1
        if count[0] > MAX_NODES:
            if count[0] == MAX_NODES + 1:
                out.append(f"{path}: more than {MAX_NODES} parts")
            return
        if depth > MAX_DEPTH:
            out.append(f"{where}: nested more than {MAX_DEPTH} levels")
            return
        if not isinstance(node, dict) or not node:
            out.append(f"{where}: must be an object")
            return
        if set(node) == {"all"} or set(node) == {"any"}:
            items = next(iter(node.values()))
            if not isinstance(items, list) or not items:
                out.append(f"{where}: needs a non-empty list")
                return
            for i, item in enumerate(items):
                walk(item, f"{where}.{next(iter(node))}[{i}]", depth + 1)
            return
        if set(node) == {"not"}:
            walk(node["not"], f"{where}.not", depth + 1)
            return
        ops = [k for k in node if k in OPS]
        if len(ops) != 1:
            out.append(f"{where}: needs exactly one of {', '.join(OPS)}")
            return
        op = ops[0]
        if "fact" in node:
            if set(node) != {"fact", op}:
                out.append(f"{where}: a fact test has only 'fact' and '{op}'")
            elif not isinstance(node["fact"], str) or not FACTS.match(node["fact"]):
                out.append(f"{where}.fact: unknown fact {node['fact']!r} (project_type, scope, intake.<field>)")
        elif "artifact" in node:
            if set(node) != {"artifact", "field", op}:
                out.append(f"{where}: an artifact test has only 'artifact', 'field' and '{op}'")
            elif node["artifact"] not in upstream:
                out.append(f"{where}.artifact: stage {node['artifact']!r} is not upstream, so its work cannot exist yet")
            elif not isinstance(node["field"], str) or not node["field"]:
                out.append(f"{where}.field: must name a field")
        else:
            out.append(f"{where}: needs 'fact' or 'artifact'")
            return
        value = node[op]
        if op == "in" and (not isinstance(value, list) or not value):
            out.append(f"{where}.in: needs a non-empty list")
        if op == "present" and not isinstance(value, bool):
            out.append(f"{where}.present: must be true or false")
        if op in ("equals", "in") and not _plain(value):
            out.append(f"{where}.{op}: only text, numbers and true/false can be compared")

    walk(condition, path, 1)
    return out


def _plain(value: Any) -> bool:
    if isinstance(value, list):
        return all(_plain(v) for v in value)
    return isinstance(value, str | int | float | bool)


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def evaluate(condition: dict[str, Any], facts: dict[str, Any], artifact: Lookup) -> tuple[bool, str]:
    """Returns the result and a plain-language reason, for the stage's transition log."""
    if "all" in condition:
        results = [evaluate(c, facts, artifact) for c in condition["all"]]
        failed = next((r for ok, r in results if not ok), None)
        return (failed is None, failed or "all conditions met")
    if "any" in condition:
        results = [evaluate(c, facts, artifact) for c in condition["any"]]
        passed = next((r for ok, r in results if ok), None)
        return (passed is not None, passed or "none of the conditions met")
    if "not" in condition:
        ok, reason = evaluate(condition["not"], facts, artifact)
        return (not ok, f"not ({reason})")
    if "fact" in condition:
        name = condition["fact"]
        if name.startswith("intake."):
            found, value = name[7:] in facts.get("intake", {}), facts.get("intake", {}).get(name[7:])
        else:
            found, value = name in facts, facts.get(name)
        label = name
    else:
        found, value = artifact(condition["artifact"], condition["field"])
        label = f"{condition['artifact']}.{condition['field']}"
    if "present" in condition:
        ok = (found and _present(value)) == condition["present"]
        return ok, f"{label} is {'present' if found and _present(value) else 'missing'}"
    if "equals" in condition:
        ok = found and _norm(value) == _norm(condition["equals"])
        return ok, f"{label} is {value!r}"
    ok = found and _norm(value) in [_norm(v) for v in condition["in"]]
    return ok, f"{label} is {value!r}"


def _norm(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value
