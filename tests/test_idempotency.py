"""Tests for idempotency properties (test_idempotency.py)."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
ADAPTERS_DIR = os.path.join(ROOT, "adapters")


# ---- 1. MockAgent determinism -----------------------------------------------

def test_mock_agent_same_params_same_output():
    """Running mock_agent twice with same params produces the same stage_result."""
    # Import directly for determinism check
    sys.path.insert(0, ROOT)
    from adapters.adapter_interface import StageRequest
    from adapters.mock_agent import MockAgent

    agent = MockAgent()
    request = StageRequest(
        project_id="test-product",
        stage="discovery",
        task_description="test",
        allowed_read_paths=[],
        expected_output_schema="schemas/stage-result.schema.json",
    )

    resp1 = agent.execute(request)
    resp2 = agent.execute(request)

    # Compare stage_result (excluding generated_at which has timestamps)
    r1 = {k: v for k, v in resp1.stage_result.items() if k != "generated_at"}
    r2 = {k: v for k, v in resp2.stage_result.items() if k != "generated_at"}
    assert r1 == r2


# ---- 3. validate_artifact determinism --------------------------------------

def test_validate_artifact_deterministic():
    """validate_artifact produces same output for same input."""
    schema_path = os.path.join(ROOT, "schemas", "project.schema.json")
    artifact_path = os.path.join(ROOT, "tests", "fixtures", "valid_project.json")

    result1 = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "validate_artifact.py"),
         "--schema", schema_path, "--artifact", artifact_path],
        capture_output=True, text=True,
    )
    result2 = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "validate_artifact.py"),
         "--schema", schema_path, "--artifact", artifact_path],
        capture_output=True, text=True,
    )

    assert result1.returncode == 0
    assert result2.returncode == 0
    assert result1.stdout.strip() == result2.stdout.strip()


# ---- 3. check_transition determinism ---------------------------------------

def test_check_transition_deterministic():
    """check_transition CLI produces same output for same input."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a minimal project dir with state.json
        state = {
            "project_id": "test-product",
            "stage": "discovered",
            "status": "active",
            "artifacts": {},
            "approved_stages": [],
            "audit_log": [],
        }
        state_path = os.path.join(tmpdir, "state.json")
        with open(state_path, "w") as f:
            json.dump(state, f)

        result1 = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "check_transition.py"),
             "--project-dir", tmpdir, "--to-stage", "researching"],
            capture_output=True, text=True,
        )
        result2 = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "check_transition.py"),
             "--project-dir", tmpdir, "--to-stage", "researching"],
            capture_output=True, text=True,
        )

        assert result1.returncode == 0
        assert result2.returncode == 0
        assert result1.stdout.strip() == result2.stdout.strip()
