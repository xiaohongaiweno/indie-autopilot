"""Tests for security properties (test_security.py)."""

import json
import os
import subprocess
import sys
import tempfile

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adapters.adapter_interface import StageRequest, validate_response
from adapters.mock_agent import MockAgent

SCHEMA_PATH = os.path.join(ROOT, "schemas", "stage-result.schema.json")
ALL_STAGES = ["discovery", "research", "validation", "planning",
              "building", "testing", "release", "growth"]


# ---- 1. Mock agent never sets is_real_data=true ----------------------------

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_mock_agent_never_sets_is_real_data_true(stage):
    agent = MockAgent()
    request = StageRequest(
        project_id="test-product",
        stage=stage,
        task_description="security test",
        allowed_read_paths=[],
        expected_output_schema=SCHEMA_PATH,
    )
    response = agent.execute(request)
    assert response.is_real_data is False
    assert response.stage_result.get("is_real_data") is False


def test_mock_agent_failure_modes_never_set_real_data():
    for mode in ["invalid_schema", "empty"]:
        agent = MockAgent(failure_mode=mode)
        request = StageRequest(
            project_id="test-product",
            stage="discovery",
            task_description="security test",
            allowed_read_paths=[],
            expected_output_schema=SCHEMA_PATH,
        )
        response = agent.execute(request)
        assert response.is_real_data is False


# ---- 2. Approval schema requires source_event ------------------------------

# ---- 2. Production release blocked by default ------------------------------

def test_production_release_blocked_by_default():
    """workflow-policy.yml has production_allowed: false for release stage."""
    policy_path = os.path.join(ROOT, "config", "workflow-policy.yml")
    with open(policy_path) as f:
        policy = yaml.safe_load(f)

    release_stage = policy["stages"]["release"]
    assert release_stage.get("production_allowed") is False

    # Also check the approval gate
    gate = policy["approval_gates"]["before_production_release"]
    assert gate.get("production_allowed") is False


# ---- 4. validate_environment doesn't print token values --------------------

def test_validate_environment_hides_token_values():
    """validate_environment should never print actual token values."""
    scripts_dir = os.path.join(ROOT, "scripts")
    env = os.environ.copy()
    secret = "super-secret-token-xyz123"
    env["SERPAPI_KEY"] = secret

    result = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "validate_environment.py")],
        capture_output=True, text=True, env=env,
    )
    # The secret must never appear in output
    assert secret not in result.stdout
    assert secret not in result.stderr
    # It should say "set (value hidden)" instead
    assert "value hidden" in result.stdout


# ---- 5. State machine prevents skipping approval gates ---------------------


def test_state_machine_prevents_skipping_approval():
    """Cannot move from validation into planning without approval."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from state_machine import check_transition

    state_data = {
        "artifacts": {},
        "approved_stages": [],  # No approval!
    }
    allowed, reasons = check_transition("validation_approved", "planning", state_data)
    assert not allowed
    assert any("Approval required" in r for r in reasons)


def test_state_machine_prevents_skipping_plan_approval():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from state_machine import check_transition

    state_data = {
        "artifacts": {"plan_result": {"path": "dummy"}},
        "approved_stages": [],  # No approval!
    }
    allowed, reasons = check_transition("planning", "plan_approved", state_data)
    assert not allowed
    assert any("Approval required" in r for r in reasons)


def test_state_machine_prevents_skipping_release_approval():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from state_machine import check_transition, requires_approval

    # The release_pending -> launched transition requires approval
    assert requires_approval("release_pending", "launched") is True

    state_data = {
        "artifacts": {},
        "approved_stages": [],
    }
    allowed, reasons = check_transition("release_pending", "launched", state_data)
    assert not allowed
    assert any("Approval required" in r for r in reasons)
