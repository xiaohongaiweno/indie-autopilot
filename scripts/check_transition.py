#!/usr/bin/env python3
"""Check whether a state transition would be valid for a project.

Read-only: it never writes state, and it never creates audit files. Approval is
read from ``state.json``'s ``approved_stages`` -- the same single source the
orchestrator writes -- so this tool and the pipeline can never disagree about
what an approval is.
"""

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


def check_transition(project_dir: str, to_stage: str) -> int:
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

    # 2. Approval needs no separate handling: sm.check_transition above already
    #    reads state.json's approved_stages, which is the single source the
    #    orchestrator writes. The old --approval-file path validated a richer
    #    format that nothing ever produced.

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
    args = parser.parse_args(argv)

    if not os.path.isdir(args.project_dir):
        logger.error("Project directory does not exist: %s", args.project_dir)
        sys.exit(2)

    sys.exit(check_transition(args.project_dir, args.to_stage))


if __name__ == "__main__":
    main()
