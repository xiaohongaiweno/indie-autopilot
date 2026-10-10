"""Tests for mock agent (test_mock_agent.py)."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adapters.adapter_interface import (
    StageRequest,
    AgentResponse,
    validate_response,
)
from adapters.mock_agent import MockAgent

SCHEMA_PATH = os.path.join(ROOT, "schemas", "stage-result.schema.json")
ALL_STAGES = ["discovery", "research", "validation", "planning",
              "building", "testing", "release", "growth"]


def _make_request(stage: str) -> StageRequest:
    return StageRequest(
        project_id="test-product",
        stage=stage,
        task_description=f"Test {stage}",
        allowed_read_paths=[],
        expected_output_schema=SCHEMA_PATH,
    )


# ---- 1. MockAgent returns valid results for all 8 stages -------------------

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_mock_agent_returns_result_for_all_stages(stage):
    agent = MockAgent()
    request = _make_request(stage)
    response = agent.execute(request)
    assert response.status == "success"
    assert response.stage_result is not None
    assert isinstance(response.stage_result, dict)


# ---- 2. All results have mode="mock" and is_real_data=false ----------------

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_mock_agent_mode_and_real_data(stage):
    agent = MockAgent()
    response = agent.execute(_make_request(stage))
    assert response.mode == "mock"
    assert response.is_real_data is False
    # Also check the stage_result itself
    assert response.stage_result.get("mode") == "mock"
    assert response.stage_result.get("is_real_data") is False


# ---- 3. All results pass schema validation ---------------------------------

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_mock_agent_results_pass_schema_validation(stage):
    agent = MockAgent()
    response = agent.execute(_make_request(stage))
    errors = validate_response(response, SCHEMA_PATH)
    assert errors == [], f"Validation errors for {stage}: {errors}"


# ---- 4. Failure mode "invalid_schema" produces invalid output ---------------

def test_failure_mode_invalid_schema():
    agent = MockAgent(failure_mode="invalid_schema")
    response = agent.execute(_make_request("discovery"))
    assert response.status == "failed"
    assert response.stage_result is not None
    # The result should fail schema validation
    errors = validate_response(response, SCHEMA_PATH)
    assert len(errors) > 0


# ---- 5. Failure mode "timeout" raises TimeoutError -------------------------

def test_failure_mode_timeout():
    agent = MockAgent(failure_mode="timeout")
    request = _make_request("discovery")
    with pytest.raises(TimeoutError):
        agent.execute(request)


# ---- 6. Failure mode "empty" returns None stage_result ---------------------

def test_failure_mode_empty():
    agent = MockAgent(failure_mode="empty")
    response = agent.execute(_make_request("discovery"))
    assert response.status == "failed"
    assert response.stage_result is None


# ---- 7. validate_response catches invalid results --------------------------

def test_validate_response_catches_invalid():
    response = AgentResponse(
        status="failed",
        stage_result={"project_id": "bad"},  # missing required fields
        raw_output="bad",
        mode="mock",
        is_real_data=False,
    )
    errors = validate_response(response, SCHEMA_PATH)
    assert len(errors) > 0


def test_validate_response_none_stage_result():
    response = AgentResponse(
        status="failed",
        stage_result=None,
        raw_output="empty",
        mode="mock",
        is_real_data=False,
    )
    errors = validate_response(response, SCHEMA_PATH)
    assert len(errors) > 0
    assert any("None" in e for e in errors)


def test_validate_response_missing_schema_file():
    response = AgentResponse(
        status="success",
        stage_result={"project_id": "test-product"},
        raw_output="test",
        mode="mock",
        is_real_data=False,
    )
    errors = validate_response(response, "/nonexistent/schema.json")
    assert len(errors) > 0
    assert any("not found" in e.lower() for e in errors)


# ---- 8. CLI interface works ------------------------------------------------

def test_mock_agent_cli():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT, "adapters", "mock_agent.py"),
                "--stage", "discovery",
                "--project-id", "test-product",
                "--output-dir", tmpdir,
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Check output file exists (stage_result written directly)
        output_file = os.path.join(tmpdir, "mock-discovery-result.json")
        assert os.path.isfile(output_file)
        with open(output_file) as f:
            data = json.load(f)
        assert data["project_id"] == "test-product"
        assert data["stage"] == "discovery"
        # Check metadata file has response info
        meta_file = os.path.join(tmpdir, "mock-discovery-meta.json")
        assert os.path.isfile(meta_file)
        with open(meta_file) as f:
            meta = json.load(f)
        assert meta["response"]["mode"] == "mock"


def test_mock_agent_cli_failure_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT, "adapters", "mock_agent.py"),
                "--stage", "discovery",
                "--project-id", "test-product",
                "--output-dir", tmpdir,
                "--failure-mode", "timeout",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "timeout" in result.stderr.lower() or "Timeout" in result.stderr


# ---- MockAgent metadata ----------------------------------------------------

def test_mock_agent_name():
    agent = MockAgent()
    assert agent.name() == "mock-agent"


def test_mock_agent_health_check():
    agent = MockAgent()
    assert agent.health_check() is True
