"""Tests for the local orchestrator (scripts/orchestrator.py)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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
    orch.grant_approval(state, State.PLANNING, "before_design", "tester")

    entry = state["approved_stages"][0]
    assert entry["stage"] == "planning"
    assert entry["approved_by"] == "tester"
    assert entry["gate"] == "before_design"

    allowed, reasons = orch.sm.check_transition(
        State.VALIDATION_APPROVED, State.PLANNING, state
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
    # all four gates on the canonical path were approved locally
    approved = {e["stage"] for e in state["approved_stages"]}
    assert approved == {
        "planning",          # before_design
        "plan_approved",     # before_mvp_commit
        "release_pending",   # before_code_merge
        "launched",          # before_production_release
    }


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

    # research and validation ran unattended; the run stopped at the first gate
    state = orch.load_state(project)
    assert state["stage"] == "validation_approved"
    assert set(state["artifacts"]) == {"research_result", "validation_result"}
    assert state["approved_stages"] == []


def test_run_rejection_leaves_stage_and_audits(project, config, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    result = orch.run(project, config=config)

    assert result.completed is False
    state = orch.load_state(project)
    assert state["stage"] == "validation_approved"
    assert state["approved_stages"] == []
    assert any(e["action"] == "approval_rejected" for e in state["audit_log"])


def test_run_approval_via_input(project, config, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    result = orch.run(project, target=State.PLANNING, config=config)
    assert result.reached == "planning"
    state = orch.load_state(project)
    assert any(e["action"] == "approval_granted" for e in state["audit_log"])


#: Gates in the order a project meets them.
GATE_ORDER = ["planning", "plan_approved", "release_pending", "launched"]

#: gate target stage -> the stage the run should be sitting on when declined
HAPPY_PATH_GATES = {
    "planning": "validation_approved",         # before_design
    "plan_approved": "planning",               # before_mvp_commit
    "release_pending": "testing",              # before_code_merge
    "launched": "release_pending",             # before_production_release
}

assert set(GATE_ORDER) == set(HAPPY_PATH_GATES)


@pytest.mark.parametrize("declined,expected_stage", sorted(HAPPY_PATH_GATES.items()))
def test_every_gate_can_stop_the_run(project, config, monkeypatch, declined, expected_stage):
    """Pre-approve four gates, decline the fifth: the run must stop there."""
    state = orch.load_state(project)
    for stage in HAPPY_PATH_GATES:
        if stage != declined:
            orch.grant_approval(state, State(stage), None, "tester")
    orch.save_state(project, state)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    result = orch.run(project, config=config)

    assert result.completed is False
    final = orch.load_state(project)
    assert final["stage"] == expected_stage
    assert declined not in {e["stage"] for e in final["approved_stages"]}
    assert any(
        e["action"] == "approval_rejected" and e["stage"] == declined
        for e in final["audit_log"]
    )


@pytest.mark.parametrize("target", GATE_ORDER)
def test_gates_up_to_a_target_can_all_be_pre_approved(project, config, monkeypatch, target):
    """Pre-approving the gates on the way must suppress every prompt.

    stdin is forced non-interactive, so any gate that still asked would raise
    instead of silently succeeding.
    """
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    state = orch.load_state(project)
    for stage in GATE_ORDER[: GATE_ORDER.index(target) + 1]:
        orch.grant_approval(state, State(stage), None, "tester")
    orch.save_state(project, state)

    result = orch.run(project, target=State(target), config=config)

    assert result.completed is True
    assert result.reached == target
    # and the approvals were recognised, not duplicated
    final = orch.load_state(project)
    assert len(final["approved_stages"]) == GATE_ORDER.index(target) + 1


def test_reaching_a_gate_target_still_runs_that_stage(project, config):
    """`run --to release_pending` must execute the release stage, not just enter it."""
    state = orch.load_state(project)
    for stage in GATE_ORDER[: GATE_ORDER.index("release_pending") + 1]:
        orch.grant_approval(state, State(stage), None, "tester")
    orch.save_state(project, state)

    orch.run(project, target=State.RELEASE_PENDING, config=config)

    final = orch.load_state(project)
    assert final["stage"] == "release_pending"
    assert "test_result" in final["artifacts"]
    assert "release_result" in final["artifacts"]


def test_declining_a_gate_does_not_consume_later_stages(project, config, monkeypatch):
    """A refusal must leave the project before the gate, not past it."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    orch.run(project, config=config)

    final = orch.load_state(project)
    assert final["stage"] == "validation_approved"
    # research and validation ran, nothing downstream did
    assert set(final["artifacts"]) == {"research_result", "validation_result"}
    assert final["approved_stages"] == []


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


# ---------------------------------------------------------------------------
# 9. Stages that must produce real code
# ---------------------------------------------------------------------------


class FakeLiveAdapter:
    """An adapter that reports success, optionally writing code like a real agent."""

    def __init__(self, payload, writes=None):
        self.payload = payload
        self.writes = writes or {}
        self.requests = []

    def name(self):
        return "fake-live"

    def health_check(self):
        return True

    def execute(self, request):
        from adapters.adapter_interface import AgentResponse

        self.requests.append(request)
        if request.code_dir:
            for relative, content in self.writes.items():
                target = Path(request.code_dir) / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
        return AgentResponse(
            status="success",
            stage_result=self.payload,
            raw_output="",
            mode="live",
            is_real_data=True,
        )


def build_payload():
    return {
        "project_id": "proj-test",
        "stage": "building",
        "status": "success",
        "generated_at": "2026-01-01T00:00:00Z",
        "summary": "实现了 MVP",
    }


def building_spec(config):
    return config.spec_for(orch.sm.State.BUILDING)


def test_pipeline_config_declares_a_code_dir_for_building(config):
    spec = building_spec(config)
    assert spec.code_dir == "app"
    # must not be the artifact directory, which deploy used to mistake for a site
    assert spec.code_dir != spec.output_dir


def test_live_build_without_code_is_a_failure(project, config):
    """The guard that matters: a confident summary is not a product."""
    adapter = FakeLiveAdapter(build_payload(), writes={})
    spec = building_spec(config)
    state = orch.load_state(project)

    with pytest.raises(orch.PipelineError) as excinfo:
        orch.execute_stage(project, state, spec, adapter, config)

    message = str(excinfo.value)
    assert "没有在 app/ 写出任何文件" in message
    assert "只有 JSON 摘要不算完成" in message
    # nothing was registered
    assert "build_result" not in state.get("artifacts", {})


def test_live_build_with_code_succeeds_and_records_it(project, config):
    adapter = FakeLiveAdapter(
        build_payload(),
        writes={"wrangler.toml": 'name = "x"\n', "src/index.js": "export default {}"},
    )
    spec = building_spec(config)
    state = orch.load_state(project)

    rel = orch.execute_stage(project, state, spec, adapter, config)

    assert rel == "build/building-result.json"
    code = state["artifacts"]["build_result"]["code"]
    assert code["file_count"] == 2
    assert code["bytes"] > 0
    assert "src/index.js" in code["files"]
    assert (project / "app" / "src" / "index.js").is_file()


def test_code_dir_is_passed_to_the_adapter(project, config):
    adapter = FakeLiveAdapter(build_payload(), writes={"index.js": "x"})
    spec = building_spec(config)
    state = orch.load_state(project)

    orch.execute_stage(project, state, spec, adapter, config)

    request = adapter.requests[0]
    assert request.code_dir == str(project / "app")
    assert request.work_dir == str(project / "build")
    assert request.code_dir != request.work_dir


def test_mock_build_needs_no_code(project, config):
    """The mock adapter is explicitly fake; demanding files from it is meaningless."""
    spec = building_spec(config)
    state = orch.load_state(project)
    adapter = orch.load_adapter(config, "mock")

    rel = orch.execute_stage(project, state, spec, adapter, config)

    assert rel.endswith("mock-building-result.json")
    assert not (project / "app").exists()
    assert "code" not in state["artifacts"]["build_result"]


def test_stage_without_code_dir_is_unaffected(project, config):
    spec = config.spec_for(orch.sm.State.RESEARCHING)
    assert spec.code_dir is None
    adapter = FakeLiveAdapter(
        {
            "project_id": "proj-test",
            "stage": "research",
            "status": "success",
            "generated_at": "2026-01-01T00:00:00Z",
            "summary": "研究完成",
        }
    )
    state = orch.load_state(project)
    orch.execute_stage(project, state, spec, adapter, config)
    assert "research_result" in state["artifacts"]


# --- inspect_code_dir -------------------------------------------------------


def test_inspect_code_dir_missing(tmp_path):
    report = orch.inspect_code_dir(tmp_path / "nope")
    assert report == {
        "path": str(tmp_path / "nope"),
        "exists": False,
        "file_count": 0,
        "bytes": 0,
        "files": [],
    }


def test_inspect_code_dir_empty(tmp_path):
    (tmp_path / "app").mkdir()
    assert orch.inspect_code_dir(tmp_path / "app")["file_count"] == 0


def test_inspect_code_dir_counts_nested_files(tmp_path):
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "a.js").write_text("aaa")
    (tmp_path / "src" / "deep").mkdir()
    (tmp_path / "src" / "deep" / "b.js").write_text("bbbbb")

    report = orch.inspect_code_dir(tmp_path)
    assert report["file_count"] == 2
    assert report["bytes"] == 8
    assert report["files"] == ["src/a.js", "src/deep/b.js"]


def test_inspect_code_dir_ignores_pipeline_and_noise_files(tmp_path):
    (tmp_path / "task.md").write_text("brief")
    (tmp_path / "agent-result.json").write_text("{}")
    (tmp_path / ".DS_Store").write_text("junk")
    (tmp_path / "real.js").write_text("code")

    report = orch.inspect_code_dir(tmp_path)
    assert report["files"] == ["real.js"]


def test_inspect_code_dir_caps_the_listing_but_not_the_count(tmp_path):
    for i in range(40):
        (tmp_path / f"f{i}.js").write_text("x")
    report = orch.inspect_code_dir(tmp_path)
    assert report["file_count"] == 40
    assert len(report["files"]) == 30
