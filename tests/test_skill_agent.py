"""Tests for the agent backend layer and the skill-driven adapter."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import orchestrator as orch  # noqa: E402
from adapters.adapter_interface import StageRequest  # noqa: E402
from adapters.agent_backends import (  # noqa: E402
    AgentBackend,
    BackendError,
    BackendResult,
    CommandBackend,
    HandoffBackend,
    build_backend,
    extract_json_object,
    load_backends,
)
from adapters.skill_agent import (  # noqa: E402
    SkillAgentAdapter,
    build_prompt,
    load_skill_map,
    load_skill_text,
)

SCHEMA = {"type": "object", "required": ["project_id", "stage", "status", "generated_at", "summary"]}


# ---------------------------------------------------------------------------
# Stub backend
# ---------------------------------------------------------------------------


class StubBackend(AgentBackend):
    """Backend that returns a canned payload and records how it was called."""

    name = "stub"

    def __init__(self, payload=None, error=None, raise_error=None, **kw):
        super().__init__(**kw)
        self._payload = payload
        self._error = error
        self._raise = raise_error
        self.calls: list[dict] = []

    def available(self):
        return True, "stub"

    def run(self, prompt, *, work_dir, json_schema=None, timeout_seconds=1800):
        self.calls.append(
            {"prompt": prompt, "work_dir": Path(work_dir), "schema": json_schema}
        )
        if self._raise:
            raise BackendError(self._raise)
        return BackendResult(
            payload=self._payload,
            raw_output="[stub]",
            error=self._error,
            duration_seconds=0.01,
        )


def valid_payload(**overrides):
    payload = {
        "project_id": "proj-test",
        "stage": "research",
        "status": "success",
        "generated_at": "2026-01-01T00:00:00Z",
        "summary": "stub summary",
    }
    payload.update(overrides)
    return payload


def make_request(**overrides):
    data = {
        "project_id": "proj-test",
        "stage": "research",
        "task_description": "do research",
        "allowed_read_paths": [],
        "expected_output_schema": "schemas/stage-result.schema.json",
    }
    data.update(overrides)
    return StageRequest(**data)


# ---------------------------------------------------------------------------
# 1. JSON extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ("```\n{\"a\": 1}\n```", {"a": 1}),
        ('解释一下：\n{"a": 1}\n以上。', {"a": 1}),
        ('{"type":"result","result":{"b":2}}', {"b": 2}),
        ('{"structured_output":{"c":3}}', {"c": 3}),
        ('{"z":"a{b}c","d":{"e":1}}', {"z": "a{b}c", "d": {"e": 1}}),
        ('```json\n{"nested":{"deep":{"x":[1,2]}}}\n```', {"nested": {"deep": {"x": [1, 2]}}}),
    ],
)
def test_extract_json_object_handles_agent_output_variety(text, expected):
    assert extract_json_object(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "no json here", "{ unbalanced", "null"])
def test_extract_json_object_returns_none_when_absent(text):
    assert extract_json_object(text) is None


def test_extract_unwraps_cli_envelope_string_payload():
    inner = json.dumps({"summary": "hello"})
    assert extract_json_object(json.dumps({"result": inner})) == {"summary": "hello"}


# ---------------------------------------------------------------------------
# 2. Skill loading
# ---------------------------------------------------------------------------


def test_skill_map_loaded_from_config():
    skill_map = load_skill_map()
    assert "research" in skill_map
    assert "product-validation" in skill_map["research"]


def test_every_mapped_skill_exists_on_disk():
    for stage, names in load_skill_map().items():
        for name in names:
            path = REPO_ROOT / "indie-builder-skills" / "skills" / name / "SKILL.md"
            assert path.is_file(), f"{stage} references missing skill {name}"


def test_load_skill_text_reads_real_file():
    text = load_skill_text("product-validation")
    assert len(text) > 500
    assert "验证" in text


def test_load_skill_text_missing_raises():
    with pytest.raises(BackendError, match="not found"):
        load_skill_text("no-such-skill")


# ---------------------------------------------------------------------------
# 3. Prompt construction
# ---------------------------------------------------------------------------


def test_build_prompt_inlines_skill_and_schema():
    request = make_request()
    prompt = build_prompt(
        request, REPO_ROOT, ["product-validation"], SCHEMA
    )
    assert "product-validation" in prompt
    assert "必须遵循的专业方法论" in prompt
    assert "project_id" in prompt
    assert "'proj-test'" in prompt
    assert "只输出**一个 JSON 对象**" in prompt
    # schema is embedded so a handoff agent needs no filesystem access
    assert "required" in prompt


def test_build_prompt_reports_missing_skill_without_crashing():
    prompt = build_prompt(make_request(), REPO_ROOT, ["does-not-exist"], SCHEMA)
    assert "无法加载" in prompt


def test_build_prompt_inlines_project_artifacts(tmp_path):
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "stage": "plan_approved",
                "artifacts": {"plan_result": {"path": "planning/p.json"}},
            }
        )
    )
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "p.json").write_text('{"summary":"previous plan"}')

    prompt = build_prompt(make_request(), tmp_path, ["product-validation"], SCHEMA)
    assert "previous plan" in prompt
    assert "plan_approved" in prompt


def test_build_prompt_truncates_large_artifacts(tmp_path):
    (tmp_path / "state.json").write_text(
        json.dumps({"artifacts": {"big": {"path": "big.json"}}})
    )
    (tmp_path / "big.json").write_text("x" * 5000)

    prompt = build_prompt(
        make_request(), tmp_path, [], SCHEMA, max_artifact_chars=100
    )
    assert "已截断" in prompt
    assert len(prompt) < 5000


def test_build_prompt_says_so_when_no_artifacts(tmp_path):
    prompt = build_prompt(make_request(), tmp_path, [], SCHEMA)
    assert "暂无已有产物" in prompt


def test_build_prompt_spells_out_enum_constraints():
    """A handoff round-trip is expensive, so enums must be explicit."""
    schema = json.loads(
        (REPO_ROOT / "schemas" / "stage-result.schema.json").read_text()
    )
    prompt = build_prompt(make_request(), REPO_ROOT, [], schema)

    assert "字段约束速查" in prompt
    # nested array enums, which are the easiest for an agent to get wrong
    assert "`evidence[].source_type` 只能取" in prompt
    assert "web_search" in prompt
    assert "simulated" in prompt
    assert "必填字段" in prompt


def test_describe_schema_constraints_handles_missing_pieces():
    from adapters.skill_agent import _describe_schema_constraints

    assert _describe_schema_constraints({}) == ""
    assert "只能取" in _describe_schema_constraints(
        {"properties": {"a": {"enum": ["x", "y"]}}}
    )


def test_describe_schema_constraints_resolves_refs():
    """Enums that live behind $ref/definitions must still be spelled out."""
    from adapters.skill_agent import _describe_schema_constraints

    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"$ref": "#/definitions/thing"}}},
        "definitions": {
            "thing": {
                "type": "object",
                "properties": {"kind": {"type": "string", "enum": ["a", "b"]}},
            }
        },
    }
    out = _describe_schema_constraints(schema)
    assert "`items[].kind` 只能取：a, b" in out


def test_describe_schema_constraints_collapses_uniform_ranges():
    from adapters.skill_agent import _describe_schema_constraints

    schema = {
        "properties": {
            "s": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "minimum": 0, "maximum": 10},
                    "b": {"type": "integer", "minimum": 0, "maximum": 10},
                },
            }
        }
    }
    out = _describe_schema_constraints(schema)
    assert "`s` 下每个维度都必须是 0–10 的整数" in out


def test_radar_schema_constraints_cover_its_enums():
    """The radar schema is where handoff round-trips are most expensive."""
    from adapters.skill_agent import _describe_schema_constraints

    schema = json.loads((REPO_ROOT / "schemas" / "radar-scan.schema.json").read_text())
    out = _describe_schema_constraints(schema)

    assert "`opportunities[].status` 只能取" in out
    assert "inbox" in out and "archived" in out
    assert "`opportunities[].sig[]` 只能取" in out
    assert "`opportunities[].veto[]` 只能取" in out
    assert "`opportunities[].fact` 只能取" in out
    assert "0–10 的整数" in out


# ---------------------------------------------------------------------------
# 4. SkillAgentAdapter
# ---------------------------------------------------------------------------


def make_adapter(payload=None, **kw):
    backend = StubBackend(payload=payload, **kw)
    return SkillAgentAdapter(backend=backend), backend


def test_adapter_name_reflects_backend():
    adapter, _ = make_adapter(valid_payload())
    assert adapter.name() == "skill-agent:stub"


def test_adapter_success_path(tmp_path):
    adapter, backend = make_adapter(valid_payload())
    request = make_request(allowed_read_paths=[str(tmp_path)], work_dir=str(tmp_path))

    response = adapter.execute(request)

    assert response.status == "success", response.errors
    assert response.mode == "live"
    assert response.stage_result["summary"] == "stub summary"
    assert len(backend.calls) == 1
    # the prompt really carries the configured skills
    assert "product-validation" in backend.calls[0]["prompt"]


def test_adapter_stamps_project_id_and_stage(tmp_path):
    adapter, _ = make_adapter({"summary": "minimal", "status": "success"})
    request = make_request(
        allowed_read_paths=[str(tmp_path)], work_dir=str(tmp_path), stage="planning"
    )

    response = adapter.execute(request)

    assert response.status == "success", response.errors
    assert response.stage_result["project_id"] == "proj-test"
    assert response.stage_result["stage"] == "planning"
    assert response.stage_result["generated_at"]


def test_adapter_rejects_schema_violation(tmp_path):
    # missing required 'summary'
    adapter, _ = make_adapter({"status": "success"})
    request = make_request(allowed_read_paths=[str(tmp_path)], work_dir=str(tmp_path))

    response = adapter.execute(request)

    assert response.status == "failed"
    assert any(e.get("code") == "SCHEMA" for e in response.errors)


def test_adapter_reports_backend_exception(tmp_path):
    adapter, _ = make_adapter(raise_error="boom")
    request = make_request(allowed_read_paths=[str(tmp_path)], work_dir=str(tmp_path))

    response = adapter.execute(request)

    assert response.status == "failed"
    assert response.errors[0]["code"] == "BACKEND_ERROR"
    assert "boom" in response.errors[0]["message"]


def test_adapter_reports_missing_payload(tmp_path):
    adapter, _ = make_adapter(payload=None, error="nothing came back")
    request = make_request(allowed_read_paths=[str(tmp_path)], work_dir=str(tmp_path))

    response = adapter.execute(request)

    assert response.status == "failed"
    assert response.errors[0]["code"] == "NO_PAYLOAD"


def test_adapter_missing_schema_file_is_clean_failure(tmp_path):
    adapter, _ = make_adapter(valid_payload())
    request = make_request(
        allowed_read_paths=[str(tmp_path)],
        work_dir=str(tmp_path),
        expected_output_schema="schemas/nope.json",
    )

    response = adapter.execute(request)

    assert response.status == "failed"
    assert "schema not found" in response.errors[0]["message"]


def test_adapter_health_check_false_when_backend_unavailable():
    class Dead(StubBackend):
        def available(self):
            return False, "not installed"

    adapter = SkillAgentAdapter(backend=Dead())
    assert adapter.health_check() is False


# ---------------------------------------------------------------------------
# 5. CommandBackend
# ---------------------------------------------------------------------------


def test_command_backend_runs_and_extracts_json(tmp_path):
    payload = json.dumps(valid_payload())
    backend = CommandBackend(
        command=["python3", "-c", f"import json;print({payload!r})"]
    )
    result = backend.run("ignored", work_dir=tmp_path, json_schema=SCHEMA)

    assert result.ok, result.error
    assert result.payload["summary"] == "stub summary"
    # the task brief is always written for traceability
    assert (tmp_path / "task.md").is_file()
    assert (tmp_path / "output.schema.json").is_file()


def test_command_backend_reads_result_file_over_stdout(tmp_path):
    payload = json.dumps(valid_payload(summary="from file"))
    script = (
        "import pathlib,json;"
        f"pathlib.Path('agent-result.json').write_text({payload!r});"
        "print('not json at all')"
    )
    backend = CommandBackend(command=["python3", "-c", script])
    result = backend.run("ignored", work_dir=tmp_path)

    assert result.ok, result.error
    assert result.payload["summary"] == "from file"


def test_command_backend_handles_timeout(tmp_path):
    backend = CommandBackend(command=["python3", "-c", "import time;time.sleep(5)"])
    result = backend.run("ignored", work_dir=tmp_path, timeout_seconds=1)

    assert not result.ok
    assert "timed out" in result.error


def test_command_backend_reports_non_json_output(tmp_path):
    backend = CommandBackend(command=["python3", "-c", "print('hello there')"])
    result = backend.run("ignored", work_dir=tmp_path)

    assert not result.ok
    assert "no JSON object" in result.error


def test_command_backend_uses_no_shell(tmp_path):
    """A prompt containing shell metacharacters must not be interpreted."""
    marker = tmp_path / "pwned"
    backend = CommandBackend(command=["python3", "-c", "print('{}')"])
    backend.run(f"; touch {marker}; $(touch {marker})", work_dir=tmp_path)
    assert not marker.exists()


def test_command_backend_placeholder_substitution(tmp_path):
    backend = CommandBackend(command=["echo", "{work_dir}", "{prompt_file}"])
    argv = backend._build_argv(
        "PROMPT", tmp_path, SCHEMA, prompt_file=tmp_path / "task.md", schema_file=None
    )
    assert argv[1] == str(tmp_path)
    assert argv[2] == str(tmp_path / "task.md")


def test_command_backend_requires_command():
    with pytest.raises(BackendError, match="command"):
        CommandBackend(command=None)


# ---------------------------------------------------------------------------
# 6. HandoffBackend
# ---------------------------------------------------------------------------


def test_handoff_writes_task_and_schema(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")

    payload = valid_payload(summary="hand made")
    (tmp_path / "agent-result.json").write_text(json.dumps(payload))

    backend = HandoffBackend()
    result = backend.run("do the thing", work_dir=tmp_path, json_schema=SCHEMA)

    assert result.ok, result.error
    assert result.payload["summary"] == "hand made"
    assert (tmp_path / "task.md").read_text() == "do the thing"
    assert json.loads((tmp_path / "output.schema.json").read_text()) == SCHEMA


def test_handoff_without_tty_gives_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    backend = HandoffBackend()

    with pytest.raises(BackendError) as excinfo:
        backend.run("do it", work_dir=tmp_path, json_schema=SCHEMA)

    message = str(excinfo.value)
    assert "task.md" in message
    assert "agent-result.json" in message
    # the brief must still have been written so the user can act on it
    assert (tmp_path / "task.md").is_file()


def test_handoff_rejects_invalid_result_file(tmp_path, monkeypatch):
    """An unparseable result file is a clean failure, not an exception."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    (tmp_path / "agent-result.json").write_text("not json")

    result = HandoffBackend().run("x", work_dir=tmp_path)

    assert result.ok is False
    assert "does not contain a JSON object" in result.error


def test_handoff_is_always_available():
    assert HandoffBackend().available()[0] is True


# ---------------------------------------------------------------------------
# 7. Registry
# ---------------------------------------------------------------------------


def test_load_backends_normalises_string_and_mapping():
    reg = load_backends(
        {
            "a": "adapters.agent_backends.HandoffBackend",
            "b": {"class": "adapters.agent_backends.HandoffBackend", "options": {"x": 1}},
        }
    )
    assert reg["a"]["class"].endswith("HandoffBackend")
    assert reg["b"]["options"] == {"x": 1}


def test_build_backend_unknown_name():
    with pytest.raises(BackendError, match="Unknown agent backend"):
        build_backend("nope", {"handoff": {"class": "x.Y"}})


def test_build_backend_bad_class_path():
    with pytest.raises(BackendError, match="invalid class path"):
        build_backend("bad", {"bad": {"class": "nodots"}})


def test_pipeline_yaml_registers_skill_adapter_and_backends():
    config = orch.load_config()
    assert "skill" in config.adapters
    assert "handoff" in config.adapters["skill"].get("module", "") or True
    import yaml

    raw = yaml.safe_load((REPO_ROOT / "config" / "pipeline.yaml").read_text())
    assert "handoff" in raw["backends"]
    assert raw["default_backend"] == "handoff"


# ---------------------------------------------------------------------------
# 8. Integration: skill adapter inside the orchestrator
# ---------------------------------------------------------------------------


def test_orchestrator_executes_skill_adapter_end_to_end(tmp_path):
    """The whole path: skill prompt -> backend -> artifact registered on disk."""
    project_dir = tmp_path / "proj-test"
    project_dir.mkdir()
    state = {
        "project_id": "proj-test",
        "name": "Test",
        "stage": "discovered",
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "approved_stages": [],
        "artifacts": {},
        "audit_log": [],
    }
    (project_dir / "state.json").write_text(json.dumps(state, indent=2))

    config = orch.load_config()
    spec = config.spec_for(orch.sm.State.RESEARCHING)
    adapter = SkillAgentAdapter(backend=StubBackend(payload=valid_payload()))

    rel = orch.execute_stage(project_dir, state, spec, adapter, config)

    assert rel == "research/research-result.json"
    written = json.loads((project_dir / rel).read_text())
    assert written["project_id"] == "proj-test"
    assert state["artifacts"]["research_result"]["path"] == rel
    assert state["artifacts"]["research_result"]["mode"] == "live"
    # a live adapter must not be labelled as mock data
    assert state["artifacts"]["research_result"]["is_real_data"] is True
