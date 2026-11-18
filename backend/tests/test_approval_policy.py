import uuid

import pytest

from app.approvals.policy import (
    PolicyError,
    is_complete,
    open_slot_for,
    parse_policy,
    satisfied_slots,
    slots_for,
)

OWNER = "project_owner"
REVIEWER = "internal_reviewer"


def _slots(raw):
    return slots_for(parse_policy(raw))


@pytest.mark.parametrize(
    ("raw", "expected_slots"),
    [
        ({"type": "single", "role": OWNER}, 1),
        ({"type": "any_of", "roles": [OWNER, REVIEWER]}, 1),
        ({"type": "all_of", "roles": [OWNER, REVIEWER]}, 2),
        ({"type": "role_based", "roles": [OWNER, REVIEWER], "min_approvers": 2}, 1),
        ({"type": "sequential", "steps": [{"role": REVIEWER}, {"role": OWNER}]}, 2),
    ],
)
def test_each_supported_policy_type_produces_slots(raw, expected_slots):
    assert len(_slots(raw)) == expected_slots


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "single", "role": "wizard"},
        {"type": "any_of", "roles": []},
        {"type": "all_of", "roles": [OWNER]},
        {"type": "all_of", "roles": [OWNER, OWNER]},
        {"type": "role_based", "roles": [OWNER], "min_approvers": 0},
        {"type": "role_based", "roles": [OWNER], "min_approvers": 11},
        {"type": "sequential", "steps": [{"role": OWNER}]},
        {"type": "single", "role": OWNER, "extra": 1},
        {"type": "conditional", "role": OWNER},
    ],
)
def test_invalid_policies_are_refused(raw):
    with pytest.raises(PolicyError):
        parse_policy(raw)


def test_single_is_satisfied_by_one_owner_approval():
    slots = _slots({"type": "single", "role": OWNER})
    approver = uuid.uuid4()
    assert not is_complete(slots, {})
    assert is_complete(slots, {"s1": {approver}})


def test_any_of_needs_one_approval_from_any_listed_role():
    slots = _slots({"type": "any_of", "roles": [OWNER, REVIEWER]})
    assert open_slot_for(slots, REVIEWER, {}, uuid.uuid4()) is not None
    assert open_slot_for(slots, "viewer", {}, uuid.uuid4()) is None


def test_all_of_needs_every_role_and_distinct_people():
    slots = _slots({"type": "all_of", "roles": [OWNER, REVIEWER]})
    owner, reviewer = uuid.uuid4(), uuid.uuid4()
    approvals = {"s1": {owner}}
    assert not is_complete(slots, approvals)
    # The same person cannot fill the second slot.
    assert open_slot_for(slots, REVIEWER, approvals, owner) is None
    assert open_slot_for(slots, REVIEWER, approvals, reviewer).id == "s2"
    assert is_complete(slots, {"s1": {owner}, "s2": {reviewer}})


def test_role_based_counts_distinct_approvers():
    slots = _slots({"type": "role_based", "roles": [OWNER, REVIEWER], "min_approvers": 2})
    a, b = uuid.uuid4(), uuid.uuid4()
    assert not is_complete(slots, {"s1": {a}})
    assert is_complete(slots, {"s1": {a, b}})


def test_sequential_opens_steps_in_order():
    slots = _slots({"type": "sequential", "steps": [{"role": REVIEWER}, {"role": OWNER}]})
    owner, reviewer = uuid.uuid4(), uuid.uuid4()
    # Owner is the second step: refused until the reviewer has approved.
    assert open_slot_for(slots, OWNER, {}, owner) is None
    assert open_slot_for(slots, REVIEWER, {}, reviewer).id == "s1"
    approvals = {"s1": {reviewer}}
    assert open_slot_for(slots, OWNER, approvals, owner).id == "s2"
    # The reviewer cannot take the owner's step.
    assert open_slot_for(slots, REVIEWER, approvals, uuid.uuid4()) is None
    assert is_complete(slots, {"s1": {reviewer}, "s2": {owner}})


def test_a_person_fills_at_most_one_slot_per_version():
    slots = _slots({"type": "any_of", "roles": [OWNER, REVIEWER]})
    person = uuid.uuid4()
    assert open_slot_for(slots, OWNER, {"s1": {person}}, person) is None


def test_satisfied_slots_reports_only_complete_slots():
    slots = _slots({"type": "all_of", "roles": [OWNER, REVIEWER]})
    assert satisfied_slots(slots, {"s2": {uuid.uuid4()}}) == {"s2"}
