#!/usr/bin/env python3
"""Apply a state transition and update state.json."""

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


def _import_state_machine():
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


def apply_transition(project_dir: str, to_stage: str) -> int:
    """Apply the transition and update state.json. Returns exit code."""
    sm = _import_state_machine()
    if sm is None:
        return 2

    state_path = os.path.join(project_dir, "state.json")
    if not os.path.isfile(state_path):
        logger.error("State file not found: %s", state_path)
        return 2

    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Could not read state file: %s", exc)
        return 2

    current_stage = state.get("stage")
    if not current_stage:
        logger.error("state.json missing 'stage' field")
        return 2

    try:
        new_state = sm.apply_transition(current_stage, to_stage, state)
    except ValueError as exc:
        logger.error("Transition failed: %s", exc)
        return 1

    try:
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(new_state, fh, indent=2)
            fh.write("\n")
        logger.info("Transition applied: %s -> %s", current_stage, to_stage)
        return 0
    except OSError as exc:
        logger.error("Could not write state file: %s", exc)
        return 2


def main(argv=None):
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Apply a state transition and update state.json.",
    )
    parser.add_argument(
        "--project-dir",
        required=True,
        help="Path to the project directory containing state.json.",
    )
    parser.add_argument(
        "--to-stage",
        required=True,
        help="Target stage to transition to.",
    )

    args = parser.parse_args(argv)

    if not os.path.isdir(args.project_dir):
        logger.error("Project directory does not exist: %s", args.project_dir)
        sys.exit(2)

    sys.exit(apply_transition(args.project_dir, args.to_stage))


if __name__ == "__main__":
    main()
