"""Tool registry and permission classes (SECURITY_ARCHITECTURE.md section 3, AGENT_ARCHITECTURE.md section 8).

Only tools in this catalogue can be granted, and only at the classes the current milestone allows.
Granting never widens what a human may do: an agent holds exactly the grants on its version.
The READ tools run (app/agents/tool_runtime.py); the other classes stay ungrantable until their policies exist.
"""

from enum import StrEnum

from app.tools.definitions import DEFINITIONS


class PermissionClass(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


# Derived from the reviewed definitions (app/tools/definitions.py), the single source of what each tool is.
TOOL_CATALOG: dict[str, PermissionClass] = {key: PermissionClass(d.permission_class) for key, d in DEFINITIONS.items()}

# Classes that may be granted in this milestone. Everything else is refused until its policy exists.
GRANTABLE_THIS_MILESTONE: frozenset[PermissionClass] = frozenset({PermissionClass.READ})


def grant_problems(tools: list[str], profile: str | None = None, disabled: frozenset[str] = frozenset()) -> list[str]:
    """Why these grants are not allowed. With a profile, also checks each tool is authorised for that department;
    `disabled` are tools an administrator has switched off in the registry."""
    problems: list[str] = []
    for name in tools:
        if name not in TOOL_CATALOG:
            problems.append(f"unknown tool '{name}'")
        elif TOOL_CATALOG[name] not in GRANTABLE_THIS_MILESTONE:
            problems.append(f"tool '{name}' is {TOOL_CATALOG[name]}; that class cannot be granted yet")
        elif DEFINITIONS[name].environment == "executor":
            problems.append(f"tool '{name}' runs through the executor; agents get it with the Developer IDE")
        elif profile is not None and "*" not in DEFINITIONS[name].departments                 and profile not in DEFINITIONS[name].departments:
            problems.append(f"tool '{name}' is not authorised for the {profile.replace('_', ' ')} department")
        elif name in disabled:
            problems.append(f"tool '{name}' is disabled in the tool registry")
    if len(set(tools)) != len(tools):
        problems.append("tools must be unique")
    return problems
