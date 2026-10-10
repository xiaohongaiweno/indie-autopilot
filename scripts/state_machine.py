"""
Core state machine for the indie developer automation pipeline.

Defines all valid states, transitions, recovery paths, and the functions
needed to query, validate, and apply state transitions with full audit logging.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class State(str, Enum):
    """All valid pipeline states."""

    DISCOVERED = "discovered"
    RESEARCHING = "researching"
    VALIDATION_PENDING = "validation_pending"
    VALIDATING = "validating"
    VALIDATION_APPROVED = "validation_approved"
    PLANNING = "planning"
    PLAN_APPROVED = "plan_approved"
    BUILDING = "building"
    TESTING = "testing"
    RELEASE_PENDING = "release_pending"
    LAUNCHED = "launched"
    GROWING = "growing"
    ITERATING = "iterating"
    BLOCKED = "blocked"
    FAILED = "failed"
    PAUSED = "paused"
    REJECTED = "rejected"


# Convenience alias so callers can write  State.DISCOVERED  or  "discovered".
S = State


# ---------------------------------------------------------------------------
# Transition configuration
# ---------------------------------------------------------------------------

class TransitionConfig:
    """Immutable descriptor for a single state transition."""

    __slots__ = (
        "required_artifacts",
        "approval_required",
        "auto",
        "failure_action",
        "gate",
    )

    def __init__(
        self,
        *,
        required_artifacts: list[str] | None = None,
        approval_required: bool = False,
        auto: bool = False,
        failure_action: str = "fail",
        gate: str | None = None,
    ) -> None:
        self.required_artifacts = required_artifacts or []
        self.approval_required = approval_required
        self.auto = auto
        self.failure_action = failure_action  # "block" | "fail" | "pause"
        self.gate = gate  # optional gate identifier

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TransitionConfig(artifacts={self.required_artifacts}, "
            f"approval={self.approval_required}, auto={self.auto}, "
            f"failure={self.failure_action}, gate={self.gate})"
        )


def _tc(**kwargs: Any) -> TransitionConfig:
    """Shorthand factory to keep the TRANSITIONS table readable."""
    return TransitionConfig(**kwargs)


# ---------------------------------------------------------------------------
# TRANSITIONS  –  (from_state, to_state) -> TransitionConfig
# ---------------------------------------------------------------------------

TRANSITIONS: dict[tuple[State, State], TransitionConfig] = {
    # --- Happy path --------------------------------------------------------
    (S.DISCOVERED, S.RESEARCHING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.DISCOVERED, S.VALIDATING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.DISCOVERED, S.PLANNING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.VALIDATING, S.PLANNING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.VALIDATING, S.BUILDING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.RESEARCHING, S.VALIDATION_PENDING): _tc(
        required_artifacts=["research_result"],
        failure_action="block",
    ),
    (S.VALIDATION_PENDING, S.VALIDATING): _tc(
        approval_required=True,
        gate="before_deep_validation",
        failure_action="block",
    ),
    (S.VALIDATING, S.VALIDATION_APPROVED): _tc(
        required_artifacts=["validation_result"],
        failure_action="fail",
    ),
    (S.VALIDATION_APPROVED, S.PLANNING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.PLANNING, S.PLAN_APPROVED): _tc(
        required_artifacts=["plan_result"],
        approval_required=True,
        gate="before_mvp_commit",
        failure_action="block",
    ),
    (S.PLAN_APPROVED, S.BUILDING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.BUILDING, S.TESTING): _tc(
        required_artifacts=["build_result"],
        failure_action="fail",
    ),
    (S.TESTING, S.RELEASE_PENDING): _tc(
        required_artifacts=["test_result"],
        failure_action="fail",
    ),
    (S.RELEASE_PENDING, S.LAUNCHED): _tc(
        approval_required=True,
        gate="before_production_release",
        failure_action="block",
    ),
    (S.LAUNCHED, S.GROWING): _tc(
        auto=True,
        failure_action="block",
    ),
    (S.GROWING, S.ITERATING): _tc(
        required_artifacts=["growth_review"],
        failure_action="pause",
    ),
    (S.ITERATING, S.GROWING): _tc(
        auto=True,
        failure_action="block",
    ),

    # --- Recovery: blocked -------------------------------------------------
    (S.BLOCKED, S.RESEARCHING): _tc(
        auto=True,
        failure_action="fail",
    ),
    (S.BLOCKED, S.VALIDATING): _tc(
        auto=True,
        failure_action="fail",
    ),
    (S.BLOCKED, S.BUILDING): _tc(
        auto=True,
        failure_action="fail",
    ),

    # --- Recovery: failed --------------------------------------------------
    (S.FAILED, S.DISCOVERED): _tc(
        approval_required=True,
        failure_action="fail",
    ),
    (S.FAILED, S.RESEARCHING): _tc(
        auto=True,
        failure_action="fail",
    ),

    # --- Recovery: paused --------------------------------------------------
    (S.PAUSED, S.DISCOVERED): _tc(
        auto=True,
        failure_action="fail",
    ),
    (S.PAUSED, S.RESEARCHING): _tc(
        auto=True,
        failure_action="fail",
    ),

    # --- Recovery: rejected ------------------------------------------------
    (S.REJECTED, S.DISCOVERED): _tc(
        auto=True,
        failure_action="fail",
    ),
}


# States from which no forward progress is possible without external action.
_TERMINAL_STATES: frozenset[State] = frozenset({S.FAILED, S.REJECTED})

# States considered "recovery" states (not part of the happy path).
_RECOVERY_STATES: frozenset[State] = frozenset({S.BLOCKED, S.FAILED, S.PAUSED, S.REJECTED})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_valid_transitions(from_state: State | str) -> list[State]:
    """Return every state reachable from *from_state* in a single step.

    Parameters
    ----------
    from_state:
        The current pipeline state.

    Returns
    -------
    list[State]
        Target states that have a defined transition from *from_state*.
    """
    from_state = State(from_state)
    return [
        to_state
        for (src, to_state) in TRANSITIONS
        if src == from_state
    ]


def check_transition(
    from_state: State | str,
    to_state: State | str,
    state_data: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate whether a transition is allowed given the current state data.

    Parameters
    ----------
    from_state:
        Current pipeline state.
    to_state:
        Desired target state.
    state_data:
        Mutable pipeline state dictionary.  Must contain at least:
        ``artifacts`` (dict), ``approved_stages`` (list).

    Returns
    -------
    tuple[bool, list[str]]
        ``(allowed, reasons)`` where *allowed* is ``True`` when the
        transition may proceed and *reasons* collects every violation
        found (empty when *allowed* is ``True``).
    """
    from_state = State(from_state)
    to_state = State(to_state)
    reasons: list[str] = []

    # 1. Transition must exist.
    config = TRANSITIONS.get((from_state, to_state))
    if config is None:
        reasons.append(
            f"No transition defined from '{from_state.value}' to '{to_state.value}'."
        )
        return False, reasons

    artifacts: dict[str, Any] = state_data.get("artifacts", {})
    approved_stages: list[dict[str, Any]] = state_data.get("approved_stages", [])

    # 2. Required artifacts must be present.
    for artifact_key in config.required_artifacts:
        if artifact_key not in artifacts:
            reasons.append(
                f"Missing required artifact: '{artifact_key}'."
            )

    # 3. Approval gate.
    if config.approval_required:
        target_stage = to_state.value
        has_approval = any(
            entry.get("stage") == target_stage for entry in approved_stages
        )
        if not has_approval:
            reasons.append(
                f"Approval required for stage '{target_stage}' but no matching "
                f"entry found in approved_stages."
            )

    allowed = len(reasons) == 0
    return allowed, reasons


def apply_transition(
    from_state: State | str,
    to_state: State | str,
    state_data: dict[str, Any],
) -> dict[str, Any]:
    """Apply a validated transition and return the updated state data.

    The input *state_data* is **never** mutated; a deep copy is returned.

    Parameters
    ----------
    from_state:
        Current pipeline state.
    to_state:
        Desired target state.
    state_data:
        Current pipeline state dictionary.

    Returns
    -------
    dict[str, Any]
        A new state_data dictionary with ``stage``, ``updated_at``, and
        ``audit_log`` updated to reflect the transition.

    Raises
    ------
    ValueError
        If ``check_transition`` reports the transition is not allowed.
    """
    from_state = State(from_state)
    to_state = State(to_state)

    allowed, reasons = check_transition(from_state, to_state, state_data)
    if not allowed:
        raise ValueError(
            f"Transition from '{from_state.value}' to '{to_state.value}' is not "
            f"allowed. Reasons: {'; '.join(reasons)}"
        )

    new_data: dict[str, Any] = copy.deepcopy(state_data)
    now = datetime.now(timezone.utc).isoformat()

    new_data["stage"] = to_state.value
    new_data["updated_at"] = now

    new_data.setdefault("audit_log", []).append(
        {
            "timestamp": now,
            "action": "transition",
            "actor": "system",
            "from_stage": from_state.value,
            "to_stage": to_state.value,
        }
    )

    return new_data


def is_terminal_state(state: State | str) -> bool:
    """Return ``True`` if *state* has no outgoing transitions at all.

    A terminal state means the pipeline cannot advance without external
    intervention (e.g. a full reset or manual override).

    Parameters
    ----------
    state:
        The pipeline state to check.
    """
    state = State(state)
    return state in _TERMINAL_STATES


def requires_approval(from_state: State | str, to_state: State | str) -> bool:
    """Return ``True`` if the transition requires an approval gate.

    Parameters
    ----------
    from_state:
        Source state.
    to_state:
        Target state.
    """
    from_state = State(from_state)
    to_state = State(to_state)
    config = TRANSITIONS.get((from_state, to_state))
    if config is None:
        return False
    return config.approval_required


def get_recovery_options(state: State | str) -> list[State]:
    """Return the states reachable from a recovery state.

    If *state* is not a recovery state (blocked / failed / paused / rejected)
    the returned list is empty.

    Parameters
    ----------
    state:
        The current pipeline state.
    """
    state = State(state)
    if state not in _RECOVERY_STATES:
        return []
    return get_valid_transitions(state)
