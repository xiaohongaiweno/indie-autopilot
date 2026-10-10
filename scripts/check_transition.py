#!/usr/bin/env python3
"""Check if a state transition is valid for a project."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _load_json(path: str, label: str) -> dict | None:
    if not os.path.isfile(path):
        logger.error("%s not found: %s", label, path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error("%s contains invalid JSON: %s — %s", label, path, exc)
        return None
    except OSError as exc:
        logger.error("Could not read %s %s: %s", label, path, exc)
        return None


def _import_state_machine(project_dir: str):
    """Import the state_machine module from the scripts directory."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import state_machine
        return state_machine
    except ImportError as exc:
        logger.error("Could not import state_machine module: %s", exc)
        return None


def _validate_approval_file(approval_path: str, project_id: str, stage: str) -> list[str]:
    """Validate an approval file against the schema and check project/stage match."""
    errors = []

    # Find the schema
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(repo_root, "schemas", "approval.schema.json")
    if not os.path.isfile(schema_path):
        errors.append(f"Approval schema not found at {schema_path}")
        return errors

    try:
        import jsonschema
    except ImportError:
        errors.append("jsonschema library is not installed")
        return errors

    schema = _load_json(schema_path, "Approval schema")
    if schema is None:
        errors.append("Could not load approval schema")
        return errors

    approval = _load_json(approval_path, "Approval file")
    if approval is None:
        errors.append("Could not load approval file")
        return errors

    validator = jsonschema.Draft7Validator(schema)
    for err in sorted(validator.iter_errors(approval), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"Approval schema error at {path}: {err.message}")

    if not errors:
        if approval.get("project_id") != project_id:
            errors.append(
                f"Approval project_id mismatch: "
                f"expected '{project_id}', got '{approval.get('project_id')}'"
            )
        if approval.get("stage") != stage:
            errors.append(
                f"Approval stage mismatch: "
                f"expected '{stage}', got '{approval.get('stage')}'"
            )
        if approval.get("decision") != "approved":
            errors.append(
                f"Approval decision is '{approval.get('decision')}', expected 'approved'"
            )

    return errors


def _write_audit_record(project_dir: str, from_stage: str, to_stage: str, project_id: str):
    """Write a transition record to the audit directory."""
    audit_dir = os.path.join(project_dir, "audit")
    os.makedirs(audit_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}-{from_stage}-{to_stage}.json"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "action": "transition_check",
        "actor": "check_transition.py",
    }

    filepath = os.path.join(audit_dir, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        logger.info("Audit record written to %s", filepath)
    except OSError as exc:
        logger.warning("Could not write audit record: %s", exc)


def check_transition(project_dir: str, to_stage: str, approval_file: str | None = None) -> int:
    """Run the transition check. Returns exit code."""
    sm = _import_state_machine(project_dir)
    if sm is None:
        return 2

    # Load state.json
    state_path = os.path.join(project_dir, "state.json")
    state = _load_json(state_path, "State file")
    if state is None:
        return 2

    current_stage = state.get("stage")
    project_id = state.get("project_id", "unknown")

    if not current_stage:
        logger.error("state.json missing 'stage' field")
        return 2

    # Validate that both stages are known
    try:
        sm.State(current_stage)
    except ValueError:
        logger.error("Unknown current stage in state.json: '%s'", current_stage)
        return 2

    try:
        sm.State(to_stage)
    except ValueError:
        allowed = [s.value for s in sm.get_valid_transitions(current_stage)]
        logger.error(
            "Unknown target stage '%s'. Valid transitions from '%s': %s",
            to_stage, current_stage, allowed if allowed else "none",
        )
        return 2

    reasons: list[str] = []

    # 1. Use state_machine.check_transition for structural validation
    allowed, sm_reasons = sm.check_transition(current_stage, to_stage, state)
    if not allowed:
        reasons.extend(sm_reasons)

    # 2. If approval is required by the transition config, check approval file
    if sm.requires_approval(current_stage, to_stage):
        if approval_file is None:
            reasons.append(
                f"Transition '{current_stage}' -> '{to_stage}' requires approval "
                f"but no --approval-file was provided"
            )
        else:
            approval_errors = _validate_approval_file(approval_file, project_id, to_stage)
            reasons.extend(approval_errors)

    # 3. Verify artifact files referenced in state actually exist on disk
    artifacts = state.get("artifacts", {})
    for artifact_name, artifact_info in artifacts.items():
        path = artifact_info.get("path", "")
        if path:
            abs_path = path if os.path.isabs(path) else os.path.join(project_dir, path)
            if not os.path.isfile(abs_path):
                reasons.append(f"Artifact '{artifact_name}' file not found: {path}")

    # Output result
    if reasons:
        reason_text = "; ".join(reasons)
        print(f"TRANSITION BLOCKED: {reason_text}")
        return 1
    else:
        print(f"TRANSITION OK: {current_stage} -> {to_stage}")
        _write_audit_record(project_dir, current_stage, to_stage, project_id)
        return 0


def main(argv=None):
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Check if a state transition is valid for a project.",
    )
    parser.add_argument(
        "--project-dir", required=True, help="Path to the project directory containing state.json."
    )
    parser.add_argument(
        "--to-stage", required=True, help="Target stage name to transition to."
    )
    parser.add_argument(
        "--approval-file",
        default=None,
        help="Optional path to an approval JSON file (required for some transitions).",
    )

    args = parser.parse_args(argv)

    if not os.path.isdir(args.project_dir):
        logger.error("Project directory does not exist: %s", args.project_dir)
        sys.exit(2)

    sys.exit(check_transition(args.project_dir, args.to_stage, args.approval_file))


if __name__ == "__main__":
    main()
