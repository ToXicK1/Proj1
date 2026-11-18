import pytest

from app.workflows.state_machine import (
    EDGES,
    TERMINAL,
    ActorType,
    InvalidTransition,
    StageStatus,
    check_transition,
    is_legal,
)

S = StageStatus
A = ActorType


@pytest.mark.parametrize(("edge", "allowed"), sorted(EDGES.items(), key=lambda kv: (kv[0][0], kv[0][1])))
def test_every_defined_edge_is_legal_only_for_its_actors(edge, allowed):
    frm, to = edge
    for actor in A:
        assert is_legal(frm, to, actor) == (actor in allowed), (frm, to, actor)


@pytest.mark.parametrize("actor", [A.AI_AGENT, A.PROVIDER])
def test_ai_actors_never_move_a_stage(actor):
    for (frm, to), allowed in EDGES.items():
        assert actor not in allowed, f"{actor} is allowed {frm} -> {to}"
        with pytest.raises(InvalidTransition):
            check_transition(frm, to, actor)


def test_only_humans_can_approve_reject_or_request_changes():
    for to in (S.APPROVED, S.REJECTED, S.CHANGES_REQUESTED):
        assert EDGES[(S.AWAITING_HUMAN_REVIEW, to)] == frozenset({A.HUMAN})


def test_system_cannot_approve():
    with pytest.raises(InvalidTransition, match="may not take"):
        check_transition(S.AWAITING_HUMAN_REVIEW, S.APPROVED, A.SYSTEM)


def test_undefined_edges_are_refused():
    for frm, to in [(S.READY, S.AWAITING_HUMAN_REVIEW), (S.NOT_STARTED, S.RUNNING), (S.SKIPPED, S.READY)]:
        with pytest.raises(InvalidTransition, match="not defined"):
            check_transition(frm, to, A.SYSTEM)


def test_terminal_states_have_no_outgoing_edges():
    for frm in TERMINAL:
        assert not [to for (f, to) in EDGES if f == frm]


def test_every_status_is_reachable_from_not_started():
    seen = {S.NOT_STARTED}
    frontier = [S.NOT_STARTED]
    while frontier:
        node = frontier.pop()
        for (frm, to) in EDGES:
            if frm == node and to not in seen:
                seen.add(to)
                frontier.append(to)
    # APPROVED is reachable only through a human, but it is still reachable in the graph.
    assert seen == set(StageStatus), set(StageStatus) - seen
