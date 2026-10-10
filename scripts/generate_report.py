#!/usr/bin/env python3
"""Generate a Markdown status report for a project."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MISSING = "\u2014 (not available)"


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _load_state(project_dir: str) -> dict | None:
    path = os.path.join(project_dir, "state.json")
    if not os.path.isfile(path):
        logger.error("state.json not found in %s", project_dir)
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error("state.json contains invalid JSON: %s", exc)
        return None
    except OSError as exc:
        logger.error("Could not read state.json: %s", exc)
        return None


def _fmt(value, default=MISSING) -> str:
    """Format a value, returning the placeholder for None/empty."""
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return str(value)


def _scan_artifacts(state: dict, project_dir: str) -> list[dict]:
    """Scan artifacts from state and verify file existence."""
    artifacts = state.get("artifacts", {})
    if not artifacts:
        return []
    results = []
    for name, info in artifacts.items():
        entry = {"name": name}
        path = info.get("path", "")
        if path:
            abs_path = path if os.path.isabs(path) else os.path.join(project_dir, path)
            entry["path"] = path
            entry["exists"] = os.path.isfile(abs_path)
        else:
            entry["path"] = ""
            entry["exists"] = False
        entry["hash"] = info.get("hash", "")
        entry["created_at"] = info.get("created_at", "")
        entry["stage"] = info.get("stage", "")
        results.append(entry)
    return results


def _scan_stage_results(project_dir: str) -> list[dict]:
    """Look for stage-result JSON files in the project directory."""
    results = []
    for fname in sorted(os.listdir(project_dir)):
        if fname.endswith("-result.json") or fname.startswith("stage-result"):
            fpath = os.path.join(project_dir, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    results.append(data)
                except (json.JSONDecodeError, OSError):
                    pass
    return results


def _load_audit_logs(project_dir: str, state: dict) -> list[dict]:
    """Combine audit log from state.json with any files in audit/ directory."""
    entries = list(state.get("audit_log", []))

    audit_dir = os.path.join(project_dir, "audit")
    if os.path.isdir(audit_dir):
        for fname in sorted(os.listdir(audit_dir)):
            if fname.endswith(".json"):
                fpath = os.path.join(audit_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        entries.append(json.load(fh))
                except (json.JSONDecodeError, OSError):
                    pass

    # Sort by timestamp descending, take last 10
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries[:10]


def generate_report(project_dir: str) -> str:
    """Generate the full Markdown report. Returns the report string."""
    state = _load_state(project_dir)
    if state is None:
        return "# Error\n\nCould not load project state.\n"

    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # --- Project Overview ---
    lines.append("# Project Status Report")
    lines.append("")
    lines.append(f"*Generated: {now}*")
    lines.append("")
    lines.append("## Project Overview")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Project ID | {_fmt(state.get('project_id'))} |")
    lines.append(f"| Name | {_fmt(state.get('name'))} |")
    lines.append(f"| Description | {_fmt(state.get('description'))} |")
    lines.append(f"| Status | {_fmt(state.get('status'))} |")
    lines.append(f"| Created | {_fmt(state.get('created_at'))} |")
    lines.append(f"| Updated | {_fmt(state.get('updated_at'))} |")
    lines.append("")

    # --- Current Stage ---
    lines.append("## Current Stage")
    lines.append("")
    stage = state.get("stage")
    if stage:
        lines.append(f"**{_fmt(stage)}**")
    else:
        lines.append(f"**{MISSING}**")
    lines.append("")
    next_action = state.get("next_action")
    if next_action:
        lines.append(f"**Next action:** {next_action}")
    else:
        lines.append(f"**Next action:** {MISSING}")
    lines.append("")

    # --- Approved Stages ---
    lines.append("## Approved Stages")
    lines.append("")
    approved = state.get("approved_stages", [])
    if approved:
        lines.append("| Stage | Approved At | Approval ID |")
        lines.append("|-------|-------------|-------------|")
        for entry in approved:
            lines.append(
                f"| {_fmt(entry.get('stage'))} "
                f"| {_fmt(entry.get('approved_at'))} "
                f"| {_fmt(entry.get('approval_id'))} |"
            )
    else:
        lines.append(f"*{MISSING}*")
    lines.append("")

    # --- Artifacts ---
    lines.append("## Artifacts")
    lines.append("")
    artifacts = _scan_artifacts(state, project_dir)
    if artifacts:
        lines.append("| Name | Path | Exists | Stage | Created |")
        lines.append("|------|------|--------|-------|---------|")
        for a in artifacts:
            exists_str = "Yes" if a["exists"] else "**No**"
            lines.append(
                f"| {_fmt(a['name'])} "
                f"| `{_fmt(a['path'], '—')}` "
                f"| {exists_str} "
                f"| {_fmt(a.get('stage'), '—')} "
                f"| {_fmt(a.get('created_at'), '—')} |"
            )
    else:
        lines.append(f"*{MISSING}*")
    lines.append("")

    # --- Evidence Summary ---
    lines.append("## Evidence Summary")
    lines.append("")
    stage_results = _scan_stage_results(project_dir)
    if stage_results:
        for sr in stage_results:
            evidence_list = sr.get("evidence", [])
            if evidence_list:
                lines.append(f"### Stage: {_fmt(sr.get('stage', 'unknown'))}")
                lines.append("")
                lines.append("| Claim | Type | Confidence | Source |")
                lines.append("|-------|------|------------|--------|")
                for ev in evidence_list:
                    lines.append(
                        f"| {_fmt(ev.get('claim'))} "
                        f"| {_fmt(ev.get('evidence_type'))} "
                        f"| {_fmt(ev.get('confidence'))} "
                        f"| {_fmt(ev.get('source_type'))} |"
                    )
                lines.append("")
    else:
        lines.append(f"*{MISSING} — no stage results found*")
    lines.append("")

    # --- Risks ---
    lines.append("## Risks")
    lines.append("")
    all_risks = []
    for sr in stage_results:
        all_risks.extend(sr.get("risks", []))
    if all_risks:
        lines.append("| Description | Severity | Mitigation |")
        lines.append("|-------------|----------|------------|")
        for r in all_risks:
            lines.append(
                f"| {_fmt(r.get('description'))} "
                f"| {_fmt(r.get('severity'))} "
                f"| {_fmt(r.get('mitigation'), '—')} |"
            )
    else:
        lines.append(f"*{MISSING}*")
    lines.append("")

    # --- Next Actions ---
    lines.append("## Next Actions")
    lines.append("")
    all_actions = []
    for sr in stage_results:
        all_actions.extend(sr.get("next_actions", []))
    if all_actions:
        lines.append("| Action | Priority | Blocked By |")
        lines.append("|--------|----------|------------|")
        for a in all_actions:
            lines.append(
                f"| {_fmt(a.get('action'))} "
                f"| {_fmt(a.get('priority'))} "
                f"| {_fmt(a.get('blocked_by'), '—')} |"
            )
    else:
        na = state.get("next_action")
        if na:
            lines.append(f"- {na}")
        else:
            lines.append(f"*{MISSING}*")
    lines.append("")

    # --- Blocked Items ---
    lines.append("## Blocked Items")
    lines.append("")
    blocked_actions = [a for a in all_actions if a.get("blocked_by")]
    if blocked_actions:
        for a in blocked_actions:
            lines.append(f"- **{_fmt(a.get('action'))}** — blocked by: {_fmt(a.get('blocked_by'))}")
    elif state.get("status") == "blocked":
        lines.append(f"*Project status is **blocked** — see next action above.*")
    else:
        lines.append("*None*")
    lines.append("")

    # --- Audit Log ---
    lines.append("## Audit Log (last 10)")
    lines.append("")
    audit_entries = _load_audit_logs(project_dir, state)
    if audit_entries:
        lines.append("| Timestamp | Action | Actor | Details |")
        lines.append("|-----------|--------|-------|---------|")
        for entry in audit_entries:
            details = entry.get("details", "")
            from_s = entry.get("from_stage")
            to_s = entry.get("to_stage")
            if from_s and to_s:
                details = f"{from_s} -> {to_s}" + (f" — {details}" if details else "")
            lines.append(
                f"| {_fmt(entry.get('timestamp'))} "
                f"| {_fmt(entry.get('action'))} "
                f"| {_fmt(entry.get('actor'))} "
                f"| {_fmt(details, '—')} |"
            )
    else:
        lines.append(f"*{MISSING}*")
    lines.append("")

    # --- Data Provenance ---
    lines.append("---")
    lines.append("")
    lines.append("*Data provenance: Facts from state.json and artifact files. "
                  "Inferences and assumptions from stage results. "
                  "Items marked with \"\u2014 (not available)\" indicate missing or unavailable data.*")
    lines.append("")

    return "\n".join(lines)


def main(argv=None):
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Generate a Markdown status report for a project.",
    )
    parser.add_argument(
        "--project-dir", required=True, help="Path to the project directory."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path. Defaults to stdout.",
    )

    args = parser.parse_args(argv)

    if not os.path.isdir(args.project_dir):
        logger.error("Project directory does not exist: %s", args.project_dir)
        sys.exit(2)

    report = generate_report(args.project_dir)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(report)
            logger.info("Report written to %s", args.output)
        except OSError as exc:
            logger.error("Could not write output file %s: %s", args.output, exc)
            sys.exit(1)
    else:
        print(report)

    sys.exit(0)


if __name__ == "__main__":
    main()
