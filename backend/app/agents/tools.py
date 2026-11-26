"""Tool registry and permission classes (SECURITY_ARCHITECTURE.md section 3, AGENT_ARCHITECTURE.md section 8).

Only tools in this catalogue can be granted, and only at the classes the current milestone allows.
Granting never widens what a human may do: an agent holds exactly the grants on its version.
READ tools run in the model loop (app/agents/tool_runtime.py); executor WRITE/EXECUTE tools are run by the platform
for the Developer AI (app/devai/service.py), never by the model directly.
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

# Classes that may be granted. READ tools may be granted to any agent whose department they are authorised for.
# WRITE and EXECUTE are grantable only for tools that run through the executor (a locked-down container per call),
# to a department named in the tool's definition (Phase 2e: the Developer AI). The platform runs those tools on the
# agent's behalf, only on the agent's own work branch; the model never calls them directly. ADMINISTRATIVE and
# EXTERNAL_SIDE_EFFECT tools are never grantable.
GRANTABLE_THIS_MILESTONE: frozenset[PermissionClass] = frozenset({PermissionClass.READ})
EXECUTOR_GRANTABLE: frozenset[PermissionClass] = frozenset({PermissionClass.WRITE, PermissionClass.EXECUTE})


def grantable(name: str) -> bool:
    """Whether the tool's class and environment allow granting at all (department checks come on top)."""
    if name not in TOOL_CATALOG or not DEFINITIONS[name].departments:
        return False
    cls = TOOL_CATALOG[name]
    return cls in GRANTABLE_THIS_MILESTONE or (cls in EXECUTOR_GRANTABLE and DEFINITIONS[name].environment == "executor")


def grant_problems(tools: list[str], profile: str | None = None, disabled: frozenset[str] = frozenset()) -> list[str]:
    """Why these grants are not allowed. With a profile, also checks each tool is authorised for that department;
    `disabled` are tools an administrator has switched off in the registry. Creating or versioning an agent always
    checks with its department (agents.service._check_registry). The model loop runs only in-process READ tools
    (tool_runtime.RUNNABLE): executor tools are run by the platform for the Developer AI, never by the model."""
    problems: list[str] = []
    for name in tools:
        if name not in TOOL_CATALOG:
            problems.append(f"unknown tool '{name}'")
        elif not grantable(name):
            problems.append(f"tool '{name}' is {TOOL_CATALOG[name]}; that tool cannot be granted to an agent")
        elif profile is not None and "*" not in DEFINITIONS[name].departments                 and profile not in DEFINITIONS[name].departments:
            problems.append(f"tool '{name}' is not authorised for the {profile.replace('_', ' ')} department")
        elif name in disabled:
            problems.append(f"tool '{name}' is disabled in the tool registry")
    if len(set(tools)) != len(tools):
        problems.append("tools must be unique")
    return problems
