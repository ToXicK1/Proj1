"""Record kinds: which department owns each, its key prefix, and the fields of its body.

Fields are checked on every version. Kinds for the other departments are added with their workspaces (7.2 to 7.5).
"""

from dataclasses import dataclass, field
from typing import Any

TEXT_MAX = 20_000


@dataclass(frozen=True)
class Field:
    name: str
    type: str  # text, enum, list (of strings), int, json
    required: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Kind:
    key: str
    department: str
    prefix: str
    label: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


PRIORITY = ("must", "should", "could", "wont")
BA = "business_analyst"

KINDS: dict[str, Kind] = {k.key: k for k in (
    Kind("requirement", BA, "REQ", "Requirement", (
        Field("description", "text", required=True),
        Field("type", "enum", required=True, choices=("business", "functional", "non_functional", "constraint")),
        Field("priority", "enum", choices=PRIORITY),
        Field("justification", "text"),
        Field("source", "text"),
        Field("acceptance_criteria", "list"),
    )),
    Kind("user_story", BA, "US", "User story", (
        Field("role", "text", required=True),
        Field("want", "text", required=True),
        Field("so_that", "text"),
        Field("epic", "text"),
        Field("acceptance_criteria", "list"),
        Field("priority", "enum", choices=PRIORITY),
        Field("estimate", "int"),
    )),
    Kind("stakeholder", BA, "SH", "Stakeholder", (
        Field("role", "text", required=True), Field("interests", "text"), Field("influence", "enum",
                                                                                 choices=("high", "medium", "low")),
    )),
    Kind("assumption", BA, "AS", "Assumption", (Field("description", "text", required=True),
                                                Field("impact_if_wrong", "text"))),
    Kind("risk", BA, "RK", "Risk", (
        Field("description", "text", required=True),
        Field("likelihood", "enum", choices=("high", "medium", "low")),
        Field("impact", "enum", choices=("high", "medium", "low")),
        Field("mitigation", "text"),
    )),
    Kind("discovery_question", BA, "Q", "Discovery question", (
        Field("question", "text", required=True), Field("answer", "text"), Field("asked_to", "text"),
    )),
    Kind("document", BA, "DOC", "Document", (
        Field("doc_type", "enum", required=True, choices=(
            "project_brief", "brd", "srs", "functional_requirements", "non_functional_requirements", "scope",
            "stakeholders", "assumptions_constraints", "risk_register", "other")),
        Field("sections", "json", required=True),  # [{"heading": str, "content": str}]
    )),
    Kind("review_finding", BA, "RF", "Review finding", (
        Field("finding", "text", required=True),
        Field("severity", "enum", required=True, choices=("blocking", "major", "minor")),
        Field("affects", "text"),  # the record keys or step concerned
        Field("recommendation", "text"),
    )),
    Kind("process_flow", BA, "PF", "Process flow", (
        Field("flow_type", "enum", required=True, choices=("as_is", "to_be", "user_workflow", "decision")),
        Field("diagram", "json", required=True),  # {"nodes": [...], "edges": [...]} as the editor saves it
    )),
)}


class InvalidBody(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def validate(kind: Kind, body: dict[str, Any]) -> dict[str, Any]:
    """The body with unknown fields refused, types checked and required fields present."""
    if not isinstance(body, dict):
        raise InvalidBody(["the body must be an object"])
    known = {f.name: f for f in kind.fields}
    problems = [f"unknown field '{name}'" for name in body if name not in known]
    out: dict[str, Any] = {}
    for f in kind.fields:
        value = body.get(f.name)
        if value is None or value == "" or value == []:
            if f.required:
                problems.append(f"'{f.name}' is required")
            continue
        if f.type == "text" and not (isinstance(value, str) and len(value) <= TEXT_MAX):
            problems.append(f"'{f.name}' must be text of at most {TEXT_MAX} characters")
        elif f.type == "enum" and value not in f.choices:
            problems.append(f"'{f.name}' must be one of {', '.join(f.choices)}")
        elif f.type == "list" and not (isinstance(value, list) and len(value) <= 100
                                       and all(isinstance(v, str) and len(v) <= 2000 for v in value)):
            problems.append(f"'{f.name}' must be a list of up to 100 texts")
        elif f.type == "int" and not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000):
            problems.append(f"'{f.name}' must be a whole number")
        elif f.type == "json" and len(str(value)) > 500_000:
            problems.append(f"'{f.name}' is too large")
        out[f.name] = value
    if problems:
        raise InvalidBody(problems)
    return out


def example(kind: Kind) -> dict[str, Any]:
    """The shape of one entry, with placeholders, for the AI: small models follow an example far better than a list
    of field names. Placeholders are in angle brackets so they are never mistaken for real content."""
    out: dict[str, Any] = {"title": "<short title>"}
    for f in kind.fields:
        if f.type == "enum":
            out[f.name] = f.choices[0] if f.required else f"<one of {'/'.join(f.choices)}>"
        elif f.type == "list":
            out[f.name] = [f"<{f.name.replace('_', ' ')}>"]
        elif f.type == "int":
            out[f.name] = 1
        elif f.type == "text":
            out[f.name] = f"<{f.name.replace('_', ' ')}>"
    return out


def describe() -> list[dict[str, Any]]:
    return [{"key": k.key, "department": k.department, "prefix": k.prefix, "label": k.label,
             "fields": [{"name": f.name, "type": f.type, "required": f.required, "choices": list(f.choices)}
                        for f in k.fields]} for k in KINDS.values()]
