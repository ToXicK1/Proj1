"""Tool registry and permission classes (SECURITY_ARCHITECTURE.md section 3, AGENT_ARCHITECTURE.md section 8).

Only tools in this catalogue can be granted, and only at the classes the current milestone allows.
Granting never widens what a human may do: an agent holds exactly the grants on its version.
No tool in the catalogue executes anything yet; the catalogue fixes names and classes first.
"""

from enum import StrEnum


class PermissionClass(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


TOOL_CATALOG: dict[str, PermissionClass] = {
    "read_project": PermissionClass.READ,
    "read_artifact": PermissionClass.READ,
    "write_note": PermissionClass.WRITE,
    "run_tests": PermissionClass.EXECUTE,
    "edit_rules": PermissionClass.ADMINISTRATIVE,
    "publish_release": PermissionClass.EXTERNAL_SIDE_EFFECT,
}

# Classes that may be granted in this milestone. Everything else is refused until its policy exists.
GRANTABLE_THIS_MILESTONE: frozenset[PermissionClass] = frozenset({PermissionClass.READ})


def grant_problems(tools: list[str]) -> list[str]:
    problems: list[str] = []
    for name in tools:
        if name not in TOOL_CATALOG:
            problems.append(f"unknown tool '{name}'")
        elif TOOL_CATALOG[name] not in GRANTABLE_THIS_MILESTONE:
            problems.append(f"tool '{name}' is {TOOL_CATALOG[name]}; that class cannot be granted yet")
    if len(set(tools)) != len(tools):
        problems.append("tools must be unique")
    return problems
