"""Tests for the local orchestrator (scripts/orchestrator.py)."""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for _p in (SCRIPTS_DIR, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import orchestrator as orch  # noqa: E402
from state_machine import State  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_project(tmp_path, project_id="proj-test", stage="discovered"):
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "project_id": project_id,
        "name": "Test Product",
        "stage": stage,
        "status": "active",
        "created_at": orch.utc_now(),
        "updated_at": orch.utc_now(),
        "approved_stages": [],
        "artifacts": {},
        "audit_log": [],
    }
    (project_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n")
    return project_dir


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path)


@pytest.fixture
def config():
    return orch.load_config()


# ---------------------------------------------------------------------------
# 1. Config loading
# ---------------------------------------------------------------------------


def test_config_loads_all_stage_specs(config):
    for stage in (
        State.RESEARCHING,
        State.VALIDATING,
        State.PLANNING,
        State.BUILDING,
        State.TESTING,
        State.RELEASE_PENDING,
        State.GROWING,
    ):
        assert config.spec_for(stage) is not None


def test_config_declares_mock_adapter(config):
    assert "mock" in config.adapters


def test_config_default_target_is_growing(config):
    assert config.default_target == State.GROWING


def test_config_rejects_unknown_stage(tmp_path):
    bad = tmp_path / "pipeline.yaml"
    bad.write_text("stages:\n  not-a-stage:\n    agent_stage: research\n")
    with pytest.raises(orch.PipelineError, match="unknown stage"):
        orch.load_config(bad)


def test_config_requires_agent_stage(tmp_path):
    bad = tmp_path / "pipeline.yaml"
    bad.write_text("stages:\n  researching:\n    output_dir: research\n")
    with pytest.raises(orch.PipelineError, match="agent_stage"):
        orch.load_config(bad)


def test_config_missing_file_raises(tmp_path):
    with pytest.raises(orch.PipelineError):
        orch.load_config(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# 2. Routing
# ---------------------------------------------------------------------------


def test_plan_route_happy_path():
    route = orch.plan_route(State.DISCOVERED, State.GROWING)
    assert route is not None
    assert route[0] == State.RESEARCHING
    assert route[-1] == State.GROWING
    # every hop must be a legal transition
    prev = State.DISCOVERED
    for step in route:
        assert step in orch.sm.get_valid_transitions(prev)
        prev = step


def test_plan_route_same_stage_is_empty():
    assert orch.plan_route(State.BUILDING, State.BUILDING) == []


def test_plan_route_has_no_backwards_path():
    assert orch.plan_route(State.BUILDING, State.PLANNING) is None


def test_plan_route_from_recovery_state():
    route = orch.plan_route(State.BLOCKED, State.BUILDING)
    assert route == [State.BUILDING]


# ---------------------------------------------------------------------------
# 3. Artifact handling
# ---------------------------------------------------------------------------


def test_artifact_is_current_false_when_missing(project, config):
    state = orch.load_state(project)
    spec = config.spec_for(State.RESEARCHING)
    assert orch.artifact_is_current(project, state, spec) is False


def test_execute_stage_registers_artifact(project, config):
    state = orch.load_state(project)
    spec = config.spec_for(State.RESEARCHING)
    adapter = orch.load_adapter(config, "mock")

    rel = orch.execute_stage(project, state, spec, adapter, config)

    assert rel == "research/mock-research-result.json"
    assert (project / rel).is_file()
    assert state["artifacts"]["research_result"]["path"] == rel
    assert state["artifacts"]["research_result"]["mode"] == "mock"
    # the produced payload must be schema-conformant
    payload = json.loads((project / rel).read_text())
    assert payload["project_id"] == "proj-test"
    assert payload["is_real_data"] is False


def test_artifact_is_current_true_after_run(project, config):
    state = orch.load_state(project)
    spec = config.spec_for(State.RESEARCHING)
    orch.execute_stage(project, state, spec, orch.load_adapter(config, "mock"), config)
    assert orch.artifact_is_current(project, state, spec) is True


# ---------------------------------------------------------------------------
# 4. Approvals
# ---------------------------------------------------------------------------


def test_grant_approval_shape_matches_check_transition():
    state = {"artifacts": {}, "approved_stages": []}
    orch.grant_approval(state, State.VALIDATING, "before_deep_validation", "tester")

    entry = state["approved_stages"][0]
    assert entry["stage"] == "validating"
    assert entry["approved_by"] == "tester"
    assert entry["gate"] == "before_deep_validation"

    allowed, reasons = orch.sm.check_transition(
        State.VALIDATION_PENDING, State.VALIDATING, state
    )
    assert allowed, reasons


def test_already_approved_detects_target():
    state = {"approved_stages": [{"stage": "launched"}]}
    assert orch._already_approved(state, State.LAUNCHED) is True
    assert orch._already_approved(state, State.PLAN_APPROVED) is False


# ---------------------------------------------------------------------------
# 5. Full run
# ---------------------------------------------------------------------------


def test_run_reaches_default_target(project, config):
    result = orch.run(project, config=config, assume_yes=True)

    assert result.completed is True
    assert result.reached == "growing"

    state = orch.load_state(project)
    assert state["stage"] == "growing"
    # every stage's artifact is registered and present on disk
    for key, entry in state["artifacts"].items():
        assert (project / entry["path"]).is_file(), key
    # the three gates were approved locally
    approved = {e["stage"] for e in state["approved_stages"]}
    assert approved == {"validating", "plan_approved", "launched"}


def test_run_registers_artifact_required_by_next_transition(project, config):
    orch.run(project, config=config, assume_yes=True)
    state = orch.load_state(project)

    # building -> testing requires build_result, which the build stage produced
    allowed, reasons = orch.sm.check_transition(
        State.BUILDING, State.TESTING, state
    )
    assert allowed, reasons


def test_run_is_idempotent(project, config):
    orch.run(project, config=config, assume_yes=True)
    first = orch.load_state(project)

    result = orch.run(project, config=config, assume_yes=True)
    second = orch.load_state(project)

    assert result.completed is True
    assert second["stage"] == first["stage"]
    # nothing new was executed or approved
    assert len(second["audit_log"]) == len(first["audit_log"])
    assert len(second["approved_stages"]) == len(first["approved_stages"])


def test_run_to_intermediate_target(project, config):
    result = orch.run(project, target=State.BUILDING, config=config, assume_yes=True)
    assert result.reached == "building"
    state = orch.load_state(project)
    assert state["stage"] == "building"
    # the target stage itself is fulfilled, not just entered
    assert "build_result" in state["artifacts"]


def test_run_stops_at_gate_without_tty(project, config, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(orch.PipelineError, match="not a TTY"):
        orch.run(project, config=config)

    # state is left at the pending stage and no approval was invented
    state = orch.load_state(project)
    assert state["stage"] == "validation_pending"
    assert state["approved_stages"] == []


def test_run_rejection_leaves_stage_and_audits(project, config, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    result = orch.run(project, config=config)

    assert result.completed is False
    state = orch.load_state(project)
    assert state["stage"] == "validation_pending"
    assert state["approved_stages"] == []
    assert any(e["action"] == "approval_rejected" for e in state["audit_log"])


def test_run_approval_via_input(project, config, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    result = orch.run(project, target=State.VALIDATING, config=config)
    assert result.reached == "validating"
    state = orch.load_state(project)
    assert any(e["action"] == "approval_granted" for e in state["audit_log"])


def test_run_self_heals_missing_artifact(project, config):
    orch.run(project, target=State.BUILDING, config=config, assume_yes=True)
    state = orch.load_state(project)

    victim = project / state["artifacts"]["build_result"]["path"]
    assert victim.is_file()
    victim.unlink()

    # re-running the same target regenerates the deleted artifact
    orch.run(project, target=State.BUILDING, config=config, assume_yes=True)
    assert victim.is_file(), "orchestrator should regenerate a missing artifact"


def test_run_missing_project_raises(tmp_path, config):
    with pytest.raises(orch.PipelineError, match="does not exist"):
        orch.run(tmp_path / "nope", config=config)


def test_run_unreachable_target_suggests_force(project, config):
    orch.run(project, target=State.GROWING, config=config, assume_yes=True)
    with pytest.raises(orch.PipelineError, match="--force"):
        orch.run(project, target=State.RESEARCHING, config=config, assume_yes=True)


def test_run_refuses_archived_project(project, config):
    state = orch.load_state(project)
    state["status"] = "archived"
    orch.save_state(project, state)
    with pytest.raises(orch.PipelineError, match="archived"):
        orch.run(project, config=config, assume_yes=True)


# ---------------------------------------------------------------------------
# 5b. Generated state must stay schema-valid
# ---------------------------------------------------------------------------


def assert_state_is_schema_valid(project):
    """Regression guard: every audit entry needs timestamp/action/actor."""
    import jsonschema

    schema_path = os.path.join(REPO_ROOT, "schemas", "project.schema.json")
    schema = json.loads(open(schema_path, encoding="utf-8").read())
    state = orch.load_state(project)
    jsonschema.Draft7Validator(schema).validate(state)


def test_full_run_keeps_state_schema_valid(project, config):
    orch.run(project, config=config, assume_yes=True)
    assert_state_is_schema_valid(project)


def test_every_audit_entry_has_actor(project, config):
    orch.run(project, config=config, assume_yes=True)
    state = orch.load_state(project)
    assert state["audit_log"], "expected audit entries"
    for entry in state["audit_log"]:
        assert entry.get("actor"), f"missing actor: {entry}"
        assert entry.get("timestamp") and entry.get("action")


def test_approve_keeps_state_schema_valid(project, config):
    state = orch.load_state(project)
    orch.grant_approval(state, State.PLAN_APPROVED, "before_mvp_commit", "tester")
    orch.save_state(project, state)
    assert_state_is_schema_valid(project)


def test_force_move_keeps_state_schema_valid(project):
    orch.force_move(project, State.TESTING, reason="skip")
    assert_state_is_schema_valid(project)


# ---------------------------------------------------------------------------
# 6. --force escape hatch
# ---------------------------------------------------------------------------


def test_force_move_bypasses_gates_and_audits(project):
    state = orch.force_move(
        project, State.BUILDING, reason="hotfix", actor="tester"
    )
    assert state["stage"] == "building"

    entry = state["audit_log"][-1]
    assert entry["action"] == "forced_transition"
    assert entry["from_stage"] == "discovered"
    assert entry["to_stage"] == "building"
    assert entry["reason"] == "hotfix"
    assert entry["actor"] == "tester"


def test_force_move_records_that_gates_were_bypassed(project):
    state = orch.force_move(project, State.LAUNCHED, reason="emergency")
    assert "bypassed" in state["audit_log"][-1]["warning"]


def test_force_move_same_stage_is_rejected(project):
    with pytest.raises(orch.PipelineError, match="already in"):
        orch.force_move(project, State.DISCOVERED, reason="noop")


def test_force_move_persists(project):
    orch.force_move(project, State.TESTING, reason="skip ahead")
    assert orch.load_state(project)["stage"] == "testing"


# ---------------------------------------------------------------------------
# 7. Reporting
# ---------------------------------------------------------------------------


def test_describe_status_shows_stage_and_requirements(project, config):
    text = orch.describe_status(project, config)
    assert "stage      : discovered" in text
    assert "-> researching" in text


def test_describe_status_marks_satisfied_requirements(project, config):
    orch.run(project, config=config, assume_yes=True)
    state = orch.load_state(project)
    state["stage"] = "growing"
    orch.save_state(project, state)

    text = orch.describe_status(project, config)
    assert "✅ growth_review" in text


def test_describe_history_lists_actions(project, config):
    orch.run(project, target=State.BUILDING, config=config, assume_yes=True)
    text = orch.describe_history(project)
    assert "stage_executed" in text
    assert "approval_granted" in text
    assert "transition" in text


def test_describe_history_respects_limit(project, config):
    orch.run(project, config=config, assume_yes=True)
    assert len(orch.describe_history(project, limit=2).splitlines()) == 2


def test_describe_history_empty(project):
    assert orch.describe_history(project) == "(no audit entries)"


# ---------------------------------------------------------------------------
# 8. Adapter registry
# ---------------------------------------------------------------------------


def test_load_adapter_unknown_name(config):
    with pytest.raises(orch.PipelineError, match="Unknown adapter"):
        orch.load_adapter(config, "does-not-exist")


def test_load_adapter_mock(config):
    adapter = orch.load_adapter(config, "mock")
    assert adapter.name() == "mock-agent"
    assert adapter.health_check() is True
