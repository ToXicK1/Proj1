import copy

import pytest

from app.workflows.compiler import CompileError, compile_workflow
from app.workflows.work import WORK_FUNCTIONS

KNOWN = set(WORK_FUNCTIONS)


def _base() -> dict:
    return {
        "key": "demo-flow",
        "name": "Demo flow",
        "execution": "sequential",
        "stages": [
            {"id": "intake", "name": "Intake", "depends_on": [], "work": "intake_summary",
             "output_required_keys": ["project_name"]},
            {"id": "outline", "name": "Outline", "depends_on": ["intake"], "protected": True,
             "approval_policy": {"type": "single"}, "work": "requirements_outline",
             "output_required_keys": ["sections"]},
        ],
    }


def test_valid_definition_compiles_with_order_roots_and_stable_hash():
    compiled = compile_workflow(_base(), KNOWN)
    assert compiled.order == ["intake", "outline"]
    assert compiled.roots == ["intake"]
    assert compile_workflow(_base(), KNOWN).sha256 == compiled.sha256


def test_hash_changes_when_the_definition_changes():
    changed = _base()
    changed["stages"][0]["name"] = "Intake v2"
    assert compile_workflow(changed, KNOWN).sha256 != compile_workflow(_base(), KNOWN).sha256


def _problems(raw: dict) -> list[str]:
    with pytest.raises(CompileError) as exc:
        compile_workflow(raw, KNOWN)
    return exc.value.problems


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d["stages"].append(copy.deepcopy(d["stages"][0])), "duplicate stage id 'intake'"),
        (lambda d: d["stages"][1].update(depends_on=["missing"]), "unknown stage 'missing'"),
        (lambda d: d["stages"][0].update(depends_on=["intake"]), "depends on itself"),
        (lambda d: d["stages"][0].update(depends_on=["outline"]), "circular dependency"),
        (lambda d: d["stages"][0].update(work="does_not_exist"), "unknown work function"),
        (lambda d: d["stages"][1].update(approval_policy=None), "needs an approval policy"),
        (lambda d: d["stages"][0].update(condition="x > 1"), "conditional execution is not supported"),
        (lambda d: d.update(execution="parallel"), "'parallel' is not supported"),
        (lambda d: d["stages"][0].update(id="Bad-ID"), "must be lowercase snake_case"),
        (lambda d: d.update(stages=[]), "stages"),
        (lambda d: d.update(surprise=True), "surprise"),
        (lambda d: d["stages"][0].update(unknown_field=1), "unknown_field"),
    ],
)
def test_each_invalid_definition_is_refused_with_a_clear_reason(mutate, fragment):
    raw = _base()
    mutate(raw)
    problems = _problems(raw)
    assert any(fragment in p for p in problems), problems


def test_all_problems_are_reported_together():
    raw = _base()
    raw["stages"][0].update(work="nope", condition="x")
    raw["stages"][1].update(depends_on=["ghost"])
    problems = _problems(raw)
    assert len(problems) >= 3, problems


def test_cycle_path_is_reported():
    raw = {
        "key": "loop",
        "name": "Loop",
        "stages": [
            {"id": "a", "name": "A", "depends_on": ["c"], "work": "intake_summary"},
            {"id": "b", "name": "B", "depends_on": ["a"], "work": "intake_summary"},
            {"id": "c", "name": "C", "depends_on": ["b"], "work": "intake_summary"},
        ],
    }
    (problem,) = [p for p in _problems(raw) if "circular" in p]
    assert "->" in problem
