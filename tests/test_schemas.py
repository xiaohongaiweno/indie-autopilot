"""Tests for JSON schema validation (test_schemas.py).

Validates project, stage-result, and approval schemas against the
canonical schema files in schemas/.
"""

import json
import os

import jsonschema
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(ROOT, "schemas")
FIXTURES_DIR = os.path.join(ROOT, "tests", "fixtures")


def _load_schema(name: str) -> dict:
    with open(os.path.join(SCHEMAS_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _validate(schema_name: str, data: dict) -> list[str]:
    """Return list of validation error messages (empty = valid)."""
    schema = _load_schema(schema_name)
    validator = jsonschema.Draft7Validator(schema)
    return [err.message for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path))]


# ---- project.schema.json ---------------------------------------------------

def test_valid_project_passes():
    data = _load_fixture("valid_project.json")
    errors = _validate("project.schema.json", data)
    assert errors == [], f"Unexpected errors: {errors}"


def test_invalid_stage_enum_fails():
    data = _load_fixture("valid_project.json")
    data["stage"] = "nonexistent_stage"
    errors = _validate("project.schema.json", data)
    assert len(errors) > 0
    assert any("nonexistent_stage" in e or "enum" in e.lower() for e in errors)


def test_missing_required_fields_fail():
    data = _load_fixture("invalid_project.json")
    errors = _validate("project.schema.json", data)
    assert len(errors) > 0
    # Should complain about missing 'stage', 'status', 'created_at', 'updated_at'
    missing_fields = {"stage", "status", "created_at", "updated_at"}
    error_text = " ".join(errors)
    for field in missing_fields:
        assert field in error_text, f"Expected error about missing '{field}'"


def test_extra_properties_rejected():
    data = _load_fixture("valid_project.json")
    data["totally_bogus_field"] = "should not be here"
    errors = _validate("project.schema.json", data)
    assert len(errors) > 0
    assert any("additional" in e.lower() or "bogus" in e.lower() for e in errors)


# ---- stage-result.schema.json ----------------------------------------------

def test_valid_stage_result_passes():
    data = _load_fixture("valid_stage_result.json")
    errors = _validate("stage-result.schema.json", data)
    assert errors == [], f"Unexpected errors: {errors}"


def test_stage_result_invalid_evidence_type_fails():
    data = _load_fixture("valid_stage_result.json")
    data["evidence"][0]["evidence_type"] = "totally_made_up"
    errors = _validate("stage-result.schema.json", data)
    assert len(errors) > 0
    assert any("made_up" in e or "enum" in e.lower() for e in errors)


# ---- approval.schema.json --------------------------------------------------

def test_valid_approval_passes():
    data = _load_fixture("valid_approval.json")
    errors = _validate("approval.schema.json", data)
    assert errors == [], f"Unexpected errors: {errors}"


def test_approval_invalid_decision_fails():
    data = _load_fixture("valid_approval.json")
    data["decision"] = "maybe_later"
    errors = _validate("approval.schema.json", data)
    assert len(errors) > 0
    assert any("maybe_later" in e or "enum" in e.lower() for e in errors)


def test_approval_extra_properties_rejected():
    data = _load_fixture("valid_approval.json")
    data["injected_field"] = "evil"
    errors = _validate("approval.schema.json", data)
    assert len(errors) > 0
    assert any("additional" in e.lower() or "injected" in e.lower() for e in errors)
