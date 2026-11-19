"""Deterministic routing of owner messages. Free text selects a category and nothing else.

No text can name a tool, an internal worker or a workflow command: the only outputs are the fixed values
below, and the service still checks them before acting.
"""

import re
from dataclasses import dataclass

CLASSIFIER_VERSION = "rules-1"
INTENTS = frozenset({"ask_question", "clarify_requirement", "request_change", "report_defect", "provide_approval",
                     "reject_deliverable", "request_explanation", "submit_information", "new_scope_request",
                     "feedback_general"})
FEEDBACK_ROUTES = {
    "defect": "qa_security",
    "new_requirement": "business_analyst",
    "scope_change": "business_analyst",
    "enhancement": "business_analyst",
    "usability": "ui_ux_designer",
    "security_concern": "qa_security",
}


@dataclass(frozen=True)
class Classification:
    intent: str
    feedback_kind: str | None
    profile: str | None
    reason: str


_RULES: tuple[tuple[re.Pattern[str], str, str | None, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), intent, kind, reason) for pattern, intent, kind, reason in (
        (r"\b(vulnerab\w*|security (issue|concern|risk|hole)|data leak|exposed? (data|password)|breach)\b",
         "report_defect", "security_concern", "mentions a security risk"),
        (r"\b(bug|defect|broken|crash\w*|does ?n[o']t work|not working|fails?|failing|error)\b",
         "report_defect", "defect", "describes something not working"),
        (r"\b(i|we) (approve|accept)\b|\blooks good,? approve\b", "provide_approval", None, "reads as an approval"),
        (r"\b(i|we) (reject|refuse)\b", "reject_deliverable", None, "reads as a rejection"),
        (r"\b(new requirement|also need|additionally|new feature|add support for|out of scope|extra feature)\b",
         "new_scope_request", "new_requirement", "asks for something new"),
        (r"\b(colou?r|layout|navigation|font|hard to use|confusing|usability|dark mode|button)\b",
         "request_change", "usability", "is about how it looks or feels"),
        (r"\b(change|improve|update|modify|enhance|could you make|please make|instead)\b",
         "request_change", "enhancement", "asks for a change"),
        (r"\b(why|explain|what does .+ mean)\b", "request_explanation", None, "asks for an explanation"),
        (r"\?\s*$|^(what|how|when|who|where|can|could|do|does|is|are|will)\b", "ask_question", None, "asks a question"),
    ))


def classify(text: str) -> Classification:
    for pattern, intent, kind, reason in _RULES:
        if pattern.search(text.strip()):
            return Classification(intent, kind, FEEDBACK_ROUTES.get(kind) if kind else None, reason)
    return Classification("feedback_general", None, None, "general comment")


RESERVED_TERMS = re.compile(
    r"\b(stages?|gates?|sensors?|hooks?|agents?|audit\w*|engine|prompts?|llms?|models?|openai|anthropic|claude|"
    r"gemini|gpt\S*|ollama|qwen\S*|tokens?|orchestrat\w*|workflow commands?)\b",
    re.IGNORECASE,
)


def is_owner_safe(text: str) -> bool:
    """Owner-facing wording must not reveal how the platform works inside."""
    return RESERVED_TERMS.search(text) is None
