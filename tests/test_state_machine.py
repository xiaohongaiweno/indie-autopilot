"""Tests for state machine logic (test_state_machine.py)."""

import copy
import sys
import os

import pytest

# Ensure scripts/ is importable
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from state_machine import (
    State,
    TRANSITIONS,
    HAPPY_PATH,
    check_transition,
    apply_transition,
    get_valid_transitions,
    requires_approval,
    get_recovery_options,
    is_terminal_state,
)


def _make_state_data(
    stage="discovered",
    artifacts=None,
    approved_stages=None,
    audit_log=None,
):
    """Helper to build a minimal state_data dict."""
    return {
        "project_id": "test-product",
        "stage": stage,
        "status": "active",
        "artifacts": artifacts or {},
        "approved_stages": approved_stages or [],
        "audit_log": audit_log or [],
    }


# ---- 1. Valid forward transitions ------------------------------------------

ALL_STAGES = [
    (State.DISCOVERED, State.RESEARCHING),
    (State.RESEARCHING, State.VALIDATION_PENDING),
    (State.VALIDATION_PENDING, State.VALIDATING),
    (State.VALIDATING, State.VALIDATION_APPROVED),
    (State.VALIDATION_APPROVED, State.PLANNING),
    (State.PLANNING, State.PLAN_APPROVED),
    (State.PLAN_APPROVED, State.BUILDING),
    (State.BUILDING, State.TESTING),
    (State.TESTING, State.RELEASE_PENDING),
    (State.RELEASE_PENDING, State.LAUNCHED),
    (State.LAUNCHED, State.GROWING),
    (State.GROWING, State.ITERATING),
    (State.ITERATING, State.GROWING),
]

# Shortcuts were removed on purpose so that approval gates cannot be skipped.
# `autopilot move --force` is the audited escape hatch.
REMOVED_SHORTCUTS = [
    (State.DISCOVERED, State.VALIDATING),
    (State.DISCOVERED, State.PLANNING),
    (State.VALIDATING, State.PLANNING),
    (State.VALIDATING, State.BUILDING),
]


@pytest.mark.parametrize("from_s,to_s", REMOVED_SHORTCUTS)
def test_shortcut_transitions_are_gone(from_s, to_s):
    assert (from_s, to_s) not in TRANSITIONS


def test_happy_path_is_a_linear_chain():
    """HAPPY_PATH must follow real transitions and be strictly linear."""
    for src, dst in zip(HAPPY_PATH, HAPPY_PATH[1:]):
        assert (src, dst) in TRANSITIONS
        assert get_valid_transitions(src) == [dst] or src == State.GROWING



@pytest.mark.parametrize("from_s,to_s", ALL_STAGES)
def test_valid_forward_transition_exists(from_s, to_s):
    """Every documented happy-path transition is defined in TRANSITIONS."""
    assert (from_s, to_s) in TRANSITIONS


@pytest.mark.parametrize("from_s,to_s", ALL_STAGES)
def test_valid_forward_transition_check_passes(from_s, to_s):
    """check_transition returns allowed=True when artifacts and approvals are present."""
    config = TRANSITIONS[(from_s, to_s)]
    artifacts = {k: {"path": "dummy"} for k in config.required_artifacts}
    approved_stages = []
    if config.approval_required:
        approved_stages = [{"stage": to_s.value}]
    sd = _make_state_data(stage=from_s.value, artifacts=artifacts, approved_stages=approved_stages)
    allowed, reasons = check_transition(from_s, to_s, sd)
    assert allowed, f"Expected allowed=True but got reasons: {reasons}"


# ---- 2. Invalid transitions are rejected -----------------------------------

INVALID_TRANSITIONS = [
    (State.DISCOVERED, State.BUILDING),
    (State.RESEARCHING, State.LAUNCHED),
    (State.PLANNING, State.LAUNCHED),
    (State.BUILDING, State.DISCOVERED),
]


@pytest.mark.parametrize("from_s,to_s", INVALID_TRANSITIONS)
def test_invalid_transition_rejected(from_s, to_s):
    sd = _make_state_data(stage=from_s.value)
    allowed, reasons = check_transition(from_s, to_s, sd)
    assert not allowed
    assert len(reasons) > 0
    assert any("No transition defined" in r for r in reasons)


# ---- 3. check_transition returns specific reasons --------------------------

def test_check_transition_missing_artifact_reason():
    sd = _make_state_data(
        stage="researching",
        artifacts={},  # missing research_result
    )
    allowed, reasons = check_transition("researching", "validation_pending", sd)
    assert not allowed
    assert any("research_result" in r for r in reasons)


def test_check_transition_missing_approval_reason():
    sd = _make_state_data(
        stage="validation_pending",
        artifacts={},
        approved_stages=[],  # no approval for validating
    )
    allowed, reasons = check_transition("validation_pending", "validating", sd)
    assert not allowed
    assert any("Approval required" in r for r in reasons)


# ---- 4. Missing required artifacts block transition ------------------------

def test_missing_required_artifacts_block():
    sd = _make_state_data(stage="researching", artifacts={})
    allowed, reasons = check_transition("researching", "validation_pending", sd)
    assert not allowed
    assert any("research_result" in r for r in reasons)


def test_present_artifacts_allow():
    sd = _make_state_data(
        stage="researching",
        artifacts={"research_result": {"path": "some/path.json"}},
    )
    allowed, reasons = check_transition("researching", "validation_pending", sd)
    assert allowed, f"Expected allowed but got: {reasons}"


# ---- 5. Missing approval blocks transition ---------------------------------

def test_missing_approval_blocks():
    sd = _make_state_data(
        stage="validation_pending",
        artifacts={},
        approved_stages=[],
    )
    allowed, reasons = check_transition("validation_pending", "validating", sd)
    assert not allowed
    assert any("Approval required" in r for r in reasons)


def test_present_approval_allows():
    sd = _make_state_data(
        stage="validation_pending",
        artifacts={},
        approved_stages=[{"stage": "validating"}],
    )
    allowed, reasons = check_transition("validation_pending", "validating", sd)
    assert allowed, f"Expected allowed but got: {reasons}"


# ---- 6. apply_transition updates audit_log ---------------------------------

def test_apply_transition_updates_audit_log():
    sd = _make_state_data(stage="discovered", audit_log=[])
    new_data = apply_transition("discovered", "researching", sd)
    assert len(new_data["audit_log"]) == 1
    entry = new_data["audit_log"][0]
    assert entry["action"] == "transition"
    assert entry["from_stage"] == "discovered"
    assert entry["to_stage"] == "researching"
    assert entry["actor"] == "system"
    assert "timestamp" in entry


def test_apply_transition_updates_stage():
    sd = _make_state_data(stage="discovered")
    new_data = apply_transition("discovered", "researching", sd)
    assert new_data["stage"] == "researching"


def test_apply_transition_updates_timestamp():
    sd = _make_state_data(stage="discovered")
    new_data = apply_transition("discovered", "researching", sd)
    assert "updated_at" in new_data
    assert new_data["updated_at"] != sd.get("updated_at", "")


# ---- 7. apply_transition does not mutate input state -----------------------

def test_apply_transition_does_not_mutate_input():
    sd = _make_state_data(stage="discovered", audit_log=[])
    original = copy.deepcopy(sd)
    _ = apply_transition("discovered", "researching", sd)
    assert sd == original, "Input state_data was mutated!"


def test_apply_transition_raises_on_invalid():
    sd = _make_state_data(stage="discovered")
    with pytest.raises(ValueError, match="not allowed"):
        apply_transition("discovered", "launched", sd)


# ---- 8. Recovery transitions -----------------------------------------------

RECOVERY_TRANSITIONS = [
    (State.BLOCKED, State.RESEARCHING),
    (State.BLOCKED, State.VALIDATING),
    (State.BLOCKED, State.BUILDING),
    (State.FAILED, State.DISCOVERED),
    (State.FAILED, State.RESEARCHING),
    (State.PAUSED, State.DISCOVERED),
    (State.PAUSED, State.RESEARCHING),
    (State.REJECTED, State.DISCOVERED),
]


@pytest.mark.parametrize("from_s,to_s", RECOVERY_TRANSITIONS)
def test_recovery_transitions_exist(from_s, to_s):
    assert (from_s, to_s) in TRANSITIONS


@pytest.mark.parametrize("from_s,to_s", RECOVERY_TRANSITIONS)
def test_recovery_transitions_check_passes(from_s, to_s):
    config = TRANSITIONS[(from_s, to_s)]
    artifacts = {k: {"path": "dummy"} for k in config.required_artifacts}
    approved_stages = []
    if config.approval_required:
        approved_stages = [{"stage": to_s.value}]
    sd = _make_state_data(stage=from_s.value, artifacts=artifacts, approved_stages=approved_stages)
    allowed, reasons = check_transition(from_s, to_s, sd)
    assert allowed, f"Recovery transition {from_s.value}->{to_s.value} blocked: {reasons}"


# ---- 9. is_terminal_state --------------------------------------------------

def test_is_terminal_failed():
    assert is_terminal_state(State.FAILED) is True


def test_is_terminal_rejected():
    assert is_terminal_state(State.REJECTED) is True


def test_is_terminal_discovered_is_not_terminal():
    assert is_terminal_state(State.DISCOVERED) is False


def test_is_terminal_launched_is_not_terminal():
    assert is_terminal_state(State.LAUNCHED) is False


@pytest.mark.parametrize("state", [State.BLOCKED, State.PAUSED])
def test_blocked_paused_are_not_terminal(state):
    # They have recovery transitions, so not terminal
    assert is_terminal_state(state) is False


# ---- 10. requires_approval -------------------------------------------------

APPROVAL_TRANSITIONS = [
    (State.VALIDATION_PENDING, State.VALIDATING),
    (State.PLANNING, State.PLAN_APPROVED),
    (State.RELEASE_PENDING, State.LAUNCHED),
    (State.FAILED, State.DISCOVERED),
]

NO_APPROVAL_TRANSITIONS = [
    (State.DISCOVERED, State.RESEARCHING),
    (State.RESEARCHING, State.VALIDATION_PENDING),
    (State.VALIDATING, State.VALIDATION_APPROVED),
    (State.VALIDATION_APPROVED, State.PLANNING),
    (State.PLAN_APPROVED, State.BUILDING),
    (State.BUILDING, State.TESTING),
    (State.TESTING, State.RELEASE_PENDING),
    (State.LAUNCHED, State.GROWING),
    (State.GROWING, State.ITERATING),
    (State.ITERATING, State.GROWING),
]


@pytest.mark.parametrize("from_s,to_s", APPROVAL_TRANSITIONS)
def test_requires_approval_true(from_s, to_s):
    assert requires_approval(from_s, to_s) is True


@pytest.mark.parametrize("from_s,to_s", NO_APPROVAL_TRANSITIONS)
def test_requires_approval_false(from_s, to_s):
    assert requires_approval(from_s, to_s) is False


def test_requires_approval_unknown_transition():
    assert requires_approval("discovered", "launched") is False


# ---- 11. get_recovery_options -----------------------------------------------

def test_recovery_options_blocked():
    opts = get_recovery_options(State.BLOCKED)
    assert State.RESEARCHING in opts
    assert State.VALIDATING in opts
    assert State.BUILDING in opts


def test_recovery_options_failed():
    opts = get_recovery_options(State.FAILED)
    assert State.DISCOVERED in opts
    assert State.RESEARCHING in opts


def test_recovery_options_paused():
    opts = get_recovery_options(State.PAUSED)
    assert State.DISCOVERED in opts
    assert State.RESEARCHING in opts


def test_recovery_options_rejected():
    opts = get_recovery_options(State.REJECTED)
    assert State.DISCOVERED in opts


@pytest.mark.parametrize("state", [
    State.DISCOVERED, State.RESEARCHING, State.BUILDING, State.LAUNCHED,
])
def test_recovery_options_empty_for_non_error_states(state):
    assert get_recovery_options(state) == []


# ---- get_valid_transitions -------------------------------------------------

def test_get_valid_transitions_from_discovered():
    targets = get_valid_transitions(State.DISCOVERED)
    assert State.RESEARCHING in targets


def test_get_valid_transitions_from_blocked():
    targets = get_valid_transitions(State.BLOCKED)
    assert len(targets) == 3
