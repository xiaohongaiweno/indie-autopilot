#!/usr/bin/env python3
"""Validate a JSON artifact against a JSON Schema."""

import argparse
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _load_json(path: str, label: str) -> dict:
    """Load a JSON file, returning None on error and logging clearly."""
    if not os.path.isfile(path):
        logger.error("%s file not found: %s", label, path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error("%s file contains invalid JSON: %s — %s", label, path, exc)
        return None
    except OSError as exc:
        logger.error("Could not read %s file %s: %s", label, path, exc)
        return None


def _check_path_fields(schema: dict, artifact: dict, base_dir: str) -> list[str]:
    """If --strict, walk the artifact looking for 'path' fields and verify they exist."""
    errors: list[str] = []

    def _walk(obj, path_prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "path" and isinstance(value, str):
                    resolved = value if os.path.isabs(value) else os.path.join(base_dir, value)
                    if not os.path.isfile(resolved):
                        errors.append(
                            f"Path not found at '{path_prefix}.{key}': {value}"
                        )
                else:
                    _walk(value, f"{path_prefix}.{key}")
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                _walk(item, f"{path_prefix}[{idx}]")

    _walk(artifact)
    return errors


def validate(schema_path: str, artifact_path: str, strict: bool = False) -> int:
    """Run validation. Returns exit code."""
    try:
        import jsonschema
    except ImportError:
        logger.error("jsonschema library is not installed. Install it with: pip install jsonschema")
        return 2

    schema = _load_json(schema_path, "Schema")
    if schema is None:
        return 2

    artifact = _load_json(artifact_path, "Artifact")
    if artifact is None:
        return 2

    # Validate against schema
    validator_cls = jsonschema.Draft7Validator
    validator = validator_cls(schema)
    validation_errors = sorted(validator.iter_errors(artifact), key=lambda e: list(e.path))

    if validation_errors:
        for err in validation_errors:
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            logger.error("Validation error at %s: %s", path, err.message)
        return 1

    # Strict mode: check path fields
    if strict:
        base_dir = os.path.dirname(os.path.abspath(artifact_path))
        path_errors = _check_path_fields(schema, artifact, base_dir)
        if path_errors:
            for err in path_errors:
                logger.error("Strict check: %s", err)
            return 1

    print("VALID")
    return 0


def main(argv=None):
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Validate a JSON artifact against a JSON Schema.",
    )
    parser.add_argument(
        "--schema", required=True, help="Path to the JSON Schema file."
    )
    parser.add_argument(
        "--artifact", required=True, help="Path to the JSON artifact to validate."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also check that any 'path' field values point to existing files.",
    )

    args = parser.parse_args(argv)
    sys.exit(validate(args.schema, args.artifact, args.strict))


if __name__ == "__main__":
    main()
