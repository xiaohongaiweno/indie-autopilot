"""Integration tests (test_integration.py)."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from state_machine import (
    State,
    check_transition,
    apply_transition,
    requires_approval,
)


def _make_state_data(stage="discovered", artifacts=None, approved_stages=None, audit_log=None):
    return {
        "project_id": "test-product",
        "stage": stage,
        "status": "active",
        "artifacts": artifacts or {},
        "approved_stages": approved_stages or [],
        "audit_log": audit_log or [],
    }


# ---- 1. Full happy path ----------------------------------------------------

def test_happy_path_discovered_to_planning():
    """Walk through: discovered -> researching -> validation_pending ->
    validating -> validation_approved -> planning"""

    # Step 1: discovered -> researching (auto, no artifacts needed)
    sd = _make_state_data(stage="discovered")
    allowed, reasons = check_transition("discovered", "researching", sd)
    assert allowed, f"discovered->researching blocked: {reasons}"
    sd = apply_transition("discovered", "researching", sd)
    assert sd["stage"] == "researching"

    # Step 2: researching -> validation_pending (needs research_result artifact)
    sd["artifacts"]["research_result"] = {"path": "research/result.json"}
    allowed, reasons = check_transition("researching", "validation_pending", sd)
    assert allowed, f"researching->validation_pending blocked: {reasons}"
    sd = apply_transition("researching", "validation_pending", sd)
    assert sd["stage"] == "validation_pending"

    # Step 3: validation_pending -> validating (ungated: the opportunity
    # approval already authorised spending validation effort)
    allowed, reasons = check_transition("validation_pending", "validating", sd)
    assert allowed, f"validation_pending->validating blocked: {reasons}"
    sd = apply_transition("validation_pending", "validating", sd)
    assert sd["stage"] == "validating"

    # Step 4: validating -> validation_approved (needs validation_result artifact)
    sd["artifacts"]["validation_result"] = {"path": "research/validation.json"}
    allowed, reasons = check_transition("validating", "validation_approved", sd)
    assert allowed, f"validating->validation_approved blocked: {reasons}"
    sd = apply_transition("validating", "validation_approved", sd)
    assert sd["stage"] == "validation_approved"

    # Step 5: validation_approved -> planning (HUMAN GATE: before_design)
    allowed, reasons = check_transition("validation_approved", "planning", sd)
    assert not allowed, "validation_approved->planning should need approval"
    assert "Approval required" in " ".join(reasons)

    sd["approved_stages"].append({"stage": "planning"})
    allowed, reasons = check_transition("validation_approved", "planning", sd)
    assert allowed, f"validation_approved->planning blocked: {reasons}"
    sd = apply_transition("validation_approved", "planning", sd)
    assert sd["stage"] == "planning"

    # Verify audit log has all transitions
    assert len(sd["audit_log"]) == 5
    transitions = [(e["from_stage"], e["to_stage"]) for e in sd["audit_log"]]
    assert ("discovered", "researching") in transitions
    assert ("researching", "validation_pending") in transitions
    assert ("validation_pending", "validating") in transitions
    assert ("validating", "validation_approved") in transitions
    assert ("validation_approved", "planning") in transitions


# ---- 2. Recovery path: blocked -> researching ------------------------------

def test_recovery_path_blocked_to_researching():
    """blocked -> researching works."""
    sd = _make_state_data(stage="blocked")
    allowed, reasons = check_transition("blocked", "researching", sd)
    assert allowed, f"blocked->researching blocked: {reasons}"
    sd = apply_transition("blocked", "researching", sd)
    assert sd["stage"] == "researching"


def test_recovery_path_failed_to_researching():
    """failed -> researching works."""
    sd = _make_state_data(stage="failed")
    allowed, reasons = check_transition("failed", "researching", sd)
    assert allowed, f"failed->researching blocked: {reasons}"
    sd = apply_transition("failed", "researching", sd)
    assert sd["stage"] == "researching"


def test_recovery_path_rejected_to_discovered():
    """rejected -> discovered works."""
    sd = _make_state_data(stage="rejected")
    allowed, reasons = check_transition("rejected", "discovered", sd)
    assert allowed, f"rejected->discovered blocked: {reasons}"
    sd = apply_transition("rejected", "discovered", sd)
    assert sd["stage"] == "discovered"


# ---- 3. Failed transition leaves state unchanged ---------------------------

def test_failed_transition_leaves_state_unchanged():
    """An invalid transition raises ValueError and does not change state."""
    import copy
    sd = _make_state_data(stage="discovered")
    original = copy.deepcopy(sd)

    with pytest.raises(ValueError):
        apply_transition("discovered", "launched", sd)

    # State must be unchanged
    assert sd == original


def test_blocked_check_does_not_mutate():
    """check_transition that fails does not mutate state_data."""
    import copy
    sd = _make_state_data(stage="discovered", artifacts={})
    original = copy.deepcopy(sd)
    allowed, _ = check_transition("discovered", "validation_pending", sd)
    assert not allowed
    assert sd == original


# ---- 4. report works on example project ------------------------------------

def test_report_on_example_project():
    project_dir = os.path.join(ROOT, "projects", "example-product")
    if not os.path.isdir(project_dir):
        pytest.skip("example-product project not found")

    scripts_dir = os.path.join(ROOT, "scripts")
    result = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "report.py"),
         "--project-dir", project_dir],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    text = result.stdout
    assert "example-product" in text
    assert "discovered" in text


def test_report_output_file():
    project_dir = os.path.join(ROOT, "projects", "example-product")
    if not os.path.isdir(project_dir):
        pytest.skip("example-product project not found")

    scripts_dir = os.path.join(ROOT, "scripts")
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w") as f:
        output_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, os.path.join(scripts_dir, "report.py"),
             "--project-dir", project_dir, "--output", output_path],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        with open(output_path) as f:
            assert "example-product" in f.read()
    finally:
        if os.path.isfile(output_path):
            os.unlink(output_path)


# ---- 5. validate_environment succeeds on this project ----------------------

def test_validate_environment_succeeds():
    scripts_dir = os.path.join(ROOT, "scripts")
    result = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "validate_environment.py"),
         "--json"],
        capture_output=True, text=True,
        cwd=ROOT,
    )
    # Parse JSON output
    assert result.returncode == 0 or result.returncode == 1  # may have warnings
    data = json.loads(result.stdout)
    assert "checks" in data
    assert "summary" in data
    assert "ok" in data
    # At least some checks should pass
    assert data["summary"]["pass"] > 0


def test_validate_environment_python_version_passes():
    scripts_dir = os.path.join(ROOT, "scripts")
    result = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "validate_environment.py"),
         "--json"],
        capture_output=True, text=True,
        cwd=ROOT,
    )
    data = json.loads(result.stdout)
    python_check = [c for c in data["checks"] if "Python version" in c["name"]]
    assert len(python_check) == 1
    assert python_check[0]["status"] == "PASS"


# ---- Bonus: validate_artifact on fixtures ----------------------------------

def test_validate_artifact_valid_project():
    scripts_dir = os.path.join(ROOT, "scripts")
    result = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "validate_artifact.py"),
         "--schema", os.path.join(ROOT, "schemas", "project.schema.json"),
         "--artifact", os.path.join(ROOT, "tests", "fixtures", "valid_project.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "VALID" in result.stdout


def test_validate_artifact_invalid_project():
    scripts_dir = os.path.join(ROOT, "scripts")
    result = subprocess.run(
        [sys.executable, os.path.join(scripts_dir, "validate_artifact.py"),
         "--schema", os.path.join(ROOT, "schemas", "project.schema.json"),
         "--artifact", os.path.join(ROOT, "tests", "fixtures", "invalid_project.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
