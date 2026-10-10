#!/usr/bin/env python3
"""Create GitHub Issues for task tracking with idempotency support."""

import argparse
import json
import logging
import os
import re
import subprocess
import sys

logger = logging.getLogger(__name__)


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


_LABEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


def _validate_labels(labels_str: str) -> list[str]:
    """Validate labels are safe (alphanumeric + hyphens only)."""
    if not labels_str:
        return []
    labels = [lbl.strip() for lbl in labels_str.split(",") if lbl.strip()]
    bad = [lbl for lbl in labels if not _LABEL_RE.match(lbl)]
    if bad:
        logger.error("Invalid label(s) — only alphanumeric and hyphens allowed: %s", bad)
        return None  # sentinel
    return labels


def _load_idempotency_file(project_dir: str) -> dict:
    """Load the .issue-keys.json marker file."""
    path = os.path.join(project_dir, ".issue-keys.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read .issue-keys.json: %s", exc)
        return {}


def _save_idempotency_file(project_dir: str, data: dict):
    """Save the .issue-keys.json marker file."""
    path = os.path.join(project_dir, ".issue-keys.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError as exc:
        logger.error("Could not write .issue-keys.json: %s", exc)


def _check_gh_available() -> bool:
    """Check that gh CLI is available and authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except FileNotFoundError:
        logger.error("'gh' CLI not found. Install it from https://cli.github.com/")
        return False
    except subprocess.TimeoutExpired:
        logger.error("'gh auth status' timed out")
        return False
    except OSError as exc:
        logger.error("Could not run 'gh': %s", exc)
        return False


def create_issue(
    title: str,
    body: str,
    project_id: str,
    stage: str,
    labels: list[str],
    dry_run: bool,
    idempotency_key: str | None,
    project_dir: str | None,
) -> int:
    """Create a GitHub issue. Returns exit code."""
    # Build payload
    payload = {
        "title": title,
        "body": body,
        "labels": labels,
    }

    # Add metadata to body if project context given
    if project_id or stage:
        meta = f"\n\n---\nProject: `{project_id or 'N/A'}` | Stage: `{stage or 'N/A'}`"
        payload["body"] = body + meta

    # Idempotency check
    if idempotency_key and project_dir:
        keys = _load_idempotency_file(project_dir)
        if idempotency_key in keys:
            existing = keys[idempotency_key]
            logger.info(
                "Issue already exists for key '%s': %s", idempotency_key, existing
            )
            print(f"IDEMPOTENT: issue already exists — {existing}")
            return 0

    # Dry-run mode
    if dry_run:
        output = {
            "title": payload["title"],
            "body": payload["body"],
            "labels": payload["labels"],
            "project_id": project_id,
            "stage": stage,
            "idempotency_key": idempotency_key,
        }
        print(json.dumps(output, indent=2))
        return 0

    # Live mode — check gh CLI
    if not _check_gh_available():
        logger.error("GitHub CLI is not available or not authenticated. Cannot create issue.")
        return 2

    # Build gh command
    cmd = ["gh", "issue", "create", "--title", title, "--body", payload["body"]]
    for lbl in labels:
        cmd.extend(["--label", lbl])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.error("'gh issue create' timed out")
        return 1
    except OSError as exc:
        logger.error("Could not run 'gh issue create': %s", exc)
        return 1

    if result.returncode != 0:
        logger.error("gh issue create failed (exit %d): %s", result.returncode, result.stderr.strip())
        return 1

    issue_url = result.stdout.strip()
    logger.info("Issue created: %s", issue_url)

    # Record idempotency key
    if idempotency_key and project_dir:
        keys = _load_idempotency_file(project_dir)
        keys[idempotency_key] = issue_url
        _save_idempotency_file(project_dir, keys)

    print(issue_url)
    return 0


def main(argv=None):
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Create GitHub Issues for task tracking.",
    )
    parser.add_argument("--title", required=True, help="Issue title.")
    parser.add_argument("--body", default="", help="Issue body text.")
    parser.add_argument(
        "--body-file", default=None, help="Read issue body from a file instead of --body."
    )
    parser.add_argument("--project-id", default=None, help="Project identifier.")
    parser.add_argument("--stage", default=None, help="Current pipeline stage.")
    parser.add_argument(
        "--labels", default="", help="Comma-separated list of labels (alphanumeric + hyphens)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the issue payload as JSON instead of creating."
    )
    parser.add_argument(
        "--idempotency-key",
        default=None,
        help="Unique key to prevent duplicate issues. Checked against .issue-keys.json.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory (used for idempotency marker file).",
    )

    args = parser.parse_args(argv)

    # Validate labels
    labels = _validate_labels(args.labels)
    if labels is None:
        sys.exit(2)

    # Resolve body
    body = args.body
    if args.body_file:
        if not os.path.isfile(args.body_file):
            logger.error("Body file not found: %s", args.body_file)
            sys.exit(2)
        try:
            with open(args.body_file, "r", encoding="utf-8") as fh:
                body = fh.read()
        except OSError as exc:
            logger.error("Could not read body file %s: %s", args.body_file, exc)
            sys.exit(2)

    # Idempotency requires project-dir
    if args.idempotency_key and not args.project_dir:
        logger.error("--project-dir is required when using --idempotency-key")
        sys.exit(2)

    sys.exit(
        create_issue(
            title=args.title,
            body=body,
            project_id=args.project_id,
            stage=args.stage,
            labels=labels,
            dry_run=args.dry_run,
            idempotency_key=args.idempotency_key,
            project_dir=args.project_dir,
        )
    )


if __name__ == "__main__":
    main()
