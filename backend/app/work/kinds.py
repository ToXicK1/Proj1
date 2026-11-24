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
LEVEL = ("high", "medium", "low")
PM = "project_manager"
BA = "business_analyst"
SA = "solution_architect"
UX = "ui_ux_designer"

KINDS: dict[str, Kind] = {k.key: k for k in (
    # Project Manager (P2): client meetings held in person, and the structured intake the PM validates (RD-21) ---
    Kind("meeting", PM, "MTG", "Client meeting", (
        Field("held_at", "text", required=True),  # date and time as the PM writes it, e.g. 2026-11-24 10:00
        Field("status", "enum", required=True, choices=("planned", "held", "follow_up_needed", "closed")),
        Field("participants", "list"), Field("objectives", "list"),
        Field("raw_notes", "text"),  # what was said, in the PM's own words
        Field("summary", "text"),
        Field("decisions", "list"), Field("assumptions", "list"), Field("constraints", "list"),
        Field("risks", "list"), Field("open_questions", "list"), Field("follow_ups", "list"),
        Field("references", "list"),  # links and document names
    )),
    Kind("meeting_analysis", PM, "MA", "Meeting analysis", (
        Field("summary", "text", required=True),
        Field("objectives", "list"), Field("features", "list"), Field("stakeholders", "list"),
        Field("decisions", "list"), Field("assumptions", "list"), Field("risks", "list"),
        Field("missing_information", "list"), Field("contradictions", "list"), Field("follow_up_questions", "list"),
    )),
    Kind("project_intake", PM, "INT", "Project intake", (
        Field("business_problem", "text", required=True),
        Field("validation", "enum", required=True, choices=("draft", "validated")),
        Field("objectives", "list"), Field("proposed_solution", "text"),
        Field("stakeholders", "list"), Field("target_users", "list"),
        Field("features_discussed", "list"), Field("functional_expectations", "list"),
        Field("non_functional_expectations", "list"), Field("technical_constraints", "list"),
        Field("budget_timeline", "text"), Field("integrations", "list"), Field("dependencies", "list"),
        Field("assumptions", "list"), Field("risks", "list"), Field("decisions", "list"),
        Field("open_questions", "list"),
    )),
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
    # Solution Architect ------------------------------------------------------------------------------------------
    Kind("architecture_driver", SA, "AD", "Architecture driver", (
        Field("description", "text", required=True),
        Field("type", "enum", required=True, choices=("quality_attribute", "constraint", "functional")),
        Field("source", "text"),
        Field("related_requirements", "text"),
    )),
    Kind("component", SA, "CMP", "Component", (
        Field("responsibility", "text", required=True),
        Field("type", "enum", required=True, choices=("service", "frontend", "database", "queue", "external",
                                                      "library")),
        Field("interfaces", "text"),
        Field("related_requirements", "text"),
    )),
    Kind("architecture_diagram", SA, "AR", "Architecture diagram", (
        Field("diagram_type", "enum", required=True, choices=("system_context", "high_level", "component",
                                                              "deployment", "data_flow", "integration",
                                                              "service_interaction")),
        Field("diagram", "json", required=True),
        Field("notes", "text"),
    )),
    Kind("data_entity", SA, "ENT", "Data entity", (
        Field("description", "text", required=True),
        Field("attributes", "json", required=True),  # [{"name", "type", "key": pk/fk/none, "nullable", "references"}]
        Field("relationships", "text"),
        Field("indexes", "list"),
        Field("rationale", "text"),
    )),
    Kind("api_endpoint", SA, "API", "API endpoint", (
        Field("method", "enum", required=True, choices=("GET", "POST", "PUT", "PATCH", "DELETE")),
        Field("path", "text", required=True),
        Field("purpose", "text", required=True),
        Field("request_schema", "json"),
        Field("response_schema", "json"),
        Field("auth", "text"),
        Field("errors", "list"),
        Field("rate_limit", "text"),
        Field("related_requirements", "text"),
    )),
    Kind("adr", SA, "ADR", "Architecture decision", (
        Field("context", "text", required=True),
        Field("decision", "text", required=True),
        Field("alternatives", "list"),
        Field("consequences", "text"),
        Field("status", "enum", choices=("proposed", "accepted", "superseded")),
    )),
    Kind("security_control", SA, "SEC", "Security control", (
        Field("area", "enum", required=True, choices=("authentication", "authorization", "trust_boundary",
                                                      "data_classification", "encryption", "network", "secrets",
                                                      "audit")),
        Field("description", "text", required=True),
        Field("related_requirements", "text"),
    )),
    Kind("infra_resource", SA, "INF", "Infrastructure resource (proposed)", (
        Field("type", "enum", required=True, choices=("compute", "database", "storage", "network", "container",
                                                      "load_balancer", "monitoring", "external")),
        Field("purpose", "text", required=True),
        Field("environment", "text"),
    )),
    Kind("tech_risk", SA, "TR", "Technical risk", (
        Field("description", "text", required=True),
        Field("likelihood", "enum", choices=LEVEL), Field("impact", "enum", choices=LEVEL),
        Field("mitigation", "text"),
    )),
    Kind("architecture_document", SA, "SAD", "Architecture document", (
        Field("sections", "json", required=True),
    )),
    Kind("architecture_finding", SA, "AF", "Architecture review finding", (
        Field("finding", "text", required=True),
        Field("severity", "enum", required=True, choices=("blocking", "major", "minor")),
        Field("affects", "text"), Field("recommendation", "text"),
    )),
    # UI/UX Designer ----------------------------------------------------------------------------------------------
    Kind("persona", UX, "PER", "Persona", (
        Field("description", "text", required=True), Field("goals", "list"), Field("pain_points", "list"),
    )),
    Kind("research_note", UX, "RN", "Research note", (
        Field("finding", "text", required=True), Field("source", "text"),
    )),
    Kind("ia_node", UX, "IA", "Site map entry", (
        Field("purpose", "text", required=True), Field("parent", "text"), Field("audience", "text"),
    )),
    Kind("user_journey", UX, "UJ", "User journey", (
        Field("persona", "text", required=True), Field("steps", "list", required=True),
        Field("pain_points", "list"), Field("related_requirements", "text"),
    )),
    Kind("screen", UX, "SCR", "Screen", (
        Field("purpose", "text", required=True),
        Field("user_role", "text"), Field("journey", "text"), Field("related_requirements", "text"),
        Field("sections", "list"),  # what the screen shows, top to bottom (wireframe level)
        Field("states", "list"),  # loading, empty, error and the like
        Field("layout", "json"),  # the design canvas's element tree (step 7.2c)
        Field("responsive", "text"),
    )),
    Kind("design_token", UX, "TOK", "Design token", (
        Field("category", "enum", required=True, choices=("color", "typography", "spacing", "radius", "shadow",
                                                          "grid")),
        Field("value", "text", required=True), Field("usage", "text"),
    )),
    Kind("ui_component", UX, "UIC", "UI component", (
        Field("purpose", "text", required=True), Field("variants", "list"), Field("states", "list"),
        Field("accessibility", "text"),
    )),
    Kind("prototype_flow", UX, "PRO", "Prototype interaction", (
        Field("from_screen", "text", required=True), Field("to_screen", "text", required=True),
        Field("trigger", "text", required=True), Field("notes", "text"),
    )),
    Kind("design_finding", UX, "DF", "Design review finding", (
        Field("finding", "text", required=True),
        Field("severity", "enum", required=True, choices=("blocking", "major", "minor")),
        Field("affects", "text"), Field("recommendation", "text"),
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
        elif f.type == "json" and f.name in JSON_EXAMPLES:
            out[f.name] = JSON_EXAMPLES[f.name]
    return out


# The shape of each structured field, for the AI's instructions (only fields the AI is expected to write).
JSON_EXAMPLES: dict[str, Any] = {
    "attributes": [{"name": "<attribute>", "type": "<text/number/date/boolean>", "key": "<pk/fk/none>",
                    "nullable": False, "references": "<entity, for a foreign key>"}],
    "sections": [{"heading": "<section heading>", "content": "<section text>"}],
    "request_schema": {"<field>": "<type>"},
    "response_schema": {"<field>": "<type>"},
}


def describe() -> list[dict[str, Any]]:
    return [{"key": k.key, "department": k.department, "prefix": k.prefix, "label": k.label,
             "fields": [{"name": f.name, "type": f.type, "required": f.required, "choices": list(f.choices)}
                        for f in k.fields]} for k in KINDS.values()]
