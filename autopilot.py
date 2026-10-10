#!/usr/bin/env python3
"""autopilot — local driver for the indie-autopilot pipeline.

Replaces the GitHub Actions workflows with a single local command that walks a
project through the state machine, pausing at approval gates.

    ./autopilot.py run opp-25              # run until the next refusal
    ./autopilot.py run opp-25 --to testing # stop once testing is reached
    ./autopilot.py run opp-25 --yes        # auto-approve every gate
    ./autopilot.py status opp-25
    ./autopilot.py history opp-25
    ./autopilot.py approve opp-25 --stage plan_approved
    ./autopilot.py move opp-25 --to testing --force --reason "hotfix"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import orchestrator as orch  # noqa: E402
import radar  # noqa: E402
from state_machine import State  # noqa: E402

PROJECTS_DIR = REPO_ROOT / "projects"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _resolve_project(value: str) -> Path:
    """Accept either a bare project id or a path to a project directory."""
    candidate = Path(value).expanduser()
    if candidate.is_dir() and (candidate / "state.json").is_file():
        return candidate.resolve()
    by_id = PROJECTS_DIR / value
    if by_id.is_dir():
        return by_id
    raise orch.PipelineError(
        f"No project '{value}'. Looked for {candidate} and {by_id}."
    )


def _project_ids() -> list[str]:
    if not PROJECTS_DIR.is_dir():
        return []
    return sorted(
        p.name for p in PROJECTS_DIR.iterdir() if (p / "state.json").is_file()
    )


def _stage(value: str) -> State:
    try:
        return State(value)
    except ValueError:
        valid = ", ".join(s.value for s in State)
        raise argparse.ArgumentTypeError(
            f"unknown stage '{value}'. Valid stages: {valid}"
        ) from None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    project_dir = _resolve_project(args.project)
    result = orch.run(
        project_dir,
        target=args.to,
        adapter_name=args.adapter,
        assume_yes=args.yes,
        rerun=args.rerun,
    )
    print()
    print(f"结果: reached={result.reached} completed={result.completed}")
    if not result.completed:
        print(f"      停止原因: {result.stopped_reason}")
    return 0 if result.completed else 1


def cmd_status(args: argparse.Namespace) -> int:
    print(orch.describe_status(_resolve_project(args.project)))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    print(orch.describe_history(_resolve_project(args.project), limit=args.limit))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Pre-grant an approval so a later `run` sails through that gate."""
    project_dir = _resolve_project(args.project)
    config = orch.load_config()
    state = orch.load_state(project_dir)
    target = args.stage

    gate_id = None
    for (src, dst), cfg in orch.sm.TRANSITIONS.items():
        if dst == target and cfg.approval_required:
            gate_id = cfg.gate
            break

    orch.grant_approval(state, target, gate_id, args.by or orch.current_actor())
    orch.save_state(project_dir, state)
    print(f"✅ 已批准 '{target.value}'" + (f" (gate {gate_id})" if gate_id else ""))
    if gate_id is None:
        print("   注意: 没有任何受审批保护的转换以该 stage 为目标。")
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    if not args.force:
        raise orch.PipelineError(
            "`move` bypasses the state machine, so it requires --force."
        )
    if not args.reason:
        raise orch.PipelineError("`move --force` requires --reason (it is audited).")
    state = orch.force_move(
        _resolve_project(args.project), args.to, reason=args.reason
    )
    print(f"⚠️  已强制移到 '{state['stage']}'（已记入 audit_log）")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    ids = _project_ids()
    if not ids:
        print("(projects/ 下没有可识别的项目)")
        return 0
    for pid in ids:
        try:
            state = orch.load_state(PROJECTS_DIR / pid)
            print(f"{pid:16} {state.get('stage')}")
        except orch.PipelineError as exc:
            print(f"{pid:16} <unreadable: {exc}>")
    return 0


def cmd_radar(args: argparse.Namespace) -> int:
    """Find new opportunities, then create a project for the ones you pick."""
    result = radar.run_scan(
        scan_id=args.scan_id,
        from_file=Path(args.from_file) if args.from_file else None,
    )

    print()
    print(radar.describe_scan(result, max_cards=args.top))

    if result.validation_errors:
        return 1

    picks = radar.choose_opportunities(result, assume_yes=args.yes)
    if not picks:
        print(f"\n本轮不立项。报告保留在 {result.scan_dir}")
        return 0

    print()
    created: list[Path] = []
    for index, opp in enumerate(picks, start=1):
        try:
            project_dir = radar.create_project(opp, result, index=index)
        except radar.RadarError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            continue
        created.append(project_dir)
        print(f"✅ 已立项：{project_dir.name}  （{opp.get('name')}）")

    if created:
        print("\n下一步：")
        for project_dir in created:
            print(f"  ./autopilot.py run {project_dir.name} --adapter skill")
    return 0


def cmd_radar_list(args: argparse.Namespace) -> int:
    scans = radar.SCANS_DIR
    if not scans.is_dir():
        print("(还没有扫描记录)")
        return 0
    for path in sorted(scans.iterdir(), reverse=True):
        if path.is_dir():
            marker = "✅" if (path / "agent-result.json").is_file() else "…"
            print(f"{marker} {path.name}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="Local driver for the indie-autopilot pipeline.",
    )
    parser.add_argument("--verbose", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="advance a project along the pipeline")
    p_run.add_argument("project")
    p_run.add_argument("--to", type=_stage, default=None, help="stop at this stage")
    p_run.add_argument("--adapter", default="mock", help="adapter name (default: mock)")
    p_run.add_argument(
        "--yes", action="store_true", help="auto-approve all approval gates"
    )
    p_run.add_argument(
        "--rerun", action="store_true", help="re-run stages whose artifact already exists"
    )
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="show a project's state")
    p_status.add_argument("project")
    p_status.set_defaults(func=cmd_status)

    p_hist = sub.add_parser("history", help="show a project's audit log")
    p_hist.add_argument("project")
    p_hist.add_argument("--limit", type=int, default=None)
    p_hist.set_defaults(func=cmd_history)

    p_approve = sub.add_parser("approve", help="pre-grant an approval gate")
    p_approve.add_argument("project")
    p_approve.add_argument("--stage", type=_stage, required=True, help="stage to approve")
    p_approve.add_argument("--by", default=None, help="approver name")
    p_approve.set_defaults(func=cmd_approve)

    p_move = sub.add_parser("move", help="force a stage change (bypasses gates)")
    p_move.add_argument("project")
    p_move.add_argument("--to", type=_stage, required=True)
    p_move.add_argument("--force", action="store_true", required=True)
    p_move.add_argument("--reason", required=True, help="why the override is needed")
    p_move.set_defaults(func=cmd_move)

    p_list = sub.add_parser("list", help="list known projects")
    p_list.set_defaults(func=cmd_list)

    p_radar = sub.add_parser(
        "radar", help="scan for new product opportunities (step 1: 找需求)"
    )
    p_radar.add_argument("--scan-id", default=None, help="scan identifier")
    p_radar.add_argument("--top", type=int, default=5, help="how many cards to show")
    p_radar.add_argument(
        "--yes", action="store_true", help="auto-pick the top opportunity"
    )
    p_radar.add_argument(
        "--from-file",
        default=None,
        help="use an existing scan JSON instead of running an agent",
    )
    p_radar.set_defaults(func=cmd_radar)

    p_radar_list = sub.add_parser("radar-list", help="list previous radar scans")
    p_radar_list.set_defaults(func=cmd_radar_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except (orch.PipelineError, radar.RadarError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中断。state.json 已保存，可直接重跑续上。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
