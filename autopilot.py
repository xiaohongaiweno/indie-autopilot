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
import deploy  # noqa: E402
import metrics  # noqa: E402
import verify  # noqa: E402
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


DEPLOYABLE_STAGES = (State.RELEASE_PENDING, State.LAUNCHED)


def cmd_deploy(args: argparse.Namespace) -> int:
    """Deploy to Cloudflare, then (only on success) record `launched`."""
    project_dir = _resolve_project(args.project)
    state = orch.load_state(project_dir)
    stage = State(state["stage"])

    if stage not in DEPLOYABLE_STAGES:
        raise orch.PipelineError(
            f"项目处于 '{stage.value}'，不能部署。\n"
            "  只有 release_pending（首次部署）或 launched（重新部署）可以部署。"
        )

    if args.dry_run:
        result = deploy.deploy(
            project_dir, environment=args.environment, dry_run=True
        )
        print("将执行： " + " ".join(result.command))
        print("（dry-run：不部署、不校验凭据、不改状态）")
        return 0

    if stage == State.LAUNCHED:
        # Already launched: redeploy in place, no transition to record.
        result = deploy.deploy_before_launch(
            project_dir,
            state,
            assume_yes=args.yes,
            environment=args.environment,
        )
        orch.save_state(project_dir, state)
        return 0 if result.ok else 1

    # release_pending: the registered pre-transition action deploys between the
    # gate and the transition, so `launched` is only ever recorded on success.
    run_result = orch.run(
        project_dir, target=State.LAUNCHED, assume_yes=args.yes
    )
    return 0 if run_result.completed else 1


def cmd_domain(args: argparse.Namespace) -> int:
    """Record the custom domain you attached by hand after deploying."""
    project_dir = _resolve_project(args.project)
    actor = orch.current_actor()
    deploy.record_domain(project_dir, args.domain, actor=actor)

    state = orch.load_state(project_dir)
    state.setdefault("audit_log", []).append(
        {
            "timestamp": deploy.utc_now(),
            "action": "domain_attached",
            "actor": actor,
            "domain": args.domain,
        }
    )
    orch.save_state(project_dir, state)

    print(f"✅ 已记录自定义域名：{args.domain}")
    print(f"   状态不变（仍是 {state['stage']}）——挂域名是部署后的手动步骤。")
    return 0


def cmd_deploy_status(args: argparse.Namespace) -> int:
    project_dir = _resolve_project(args.project)
    record = deploy.load_deployment(project_dir)
    if not record:
        print("(还没有部署记录)")
        return 1
    print(f"provider   : {record.get('provider')}")
    print(f"类型       : {record.get('kind')}")
    print(f"环境       : {record.get('environment')}")
    print(f"URL        : {record.get('url') or '(未解析到)'}")
    print(f"部署时间   : {record.get('deployed_at')}")
    domain = record.get("custom_domain")
    print(f"自定义域名 : {domain if domain else '（尚未挂）'}")
    if not domain:
        print()
        print(deploy.domain_instructions(record.get("project_name") or project_dir.name))
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    """Fetch real Search Console / GA4 data and register it for the growth stage."""
    project_dir = _resolve_project(args.project)

    if args.dry_run:
        print(metrics.describe_config(project_dir))
        print("\n（dry-run：未调用任何 API）")
        return 0

    report = metrics.collect(project_dir, days=args.days)
    print()
    print(metrics.describe_report(report))

    state = orch.load_state(project_dir)
    latest = metrics.record_metrics(project_dir, state, report)
    orch.save_state(project_dir, state)

    print(f"\n已登记为产物：{latest.relative_to(project_dir)}")
    if report.get("is_real_data"):
        print("下游 growth 阶段的任务书会自动带上这些真实数据。")
        print(f"  下一步：./autopilot.py run {project_dir.name} --adapter skill")
        return 0

    print(
        "\n没有取到任何真实数据，因此没有被当作真实反馈。\n"
        "  检查配置：./autopilot.py metrics <project> --dry-run"
    )
    return 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Run the project's own tests, without touching pipeline state."""
    project_dir = _resolve_project(args.project)
    config = orch.load_config()
    spec = config.spec_for(orch.sm.State.TESTING) or config.spec_for(
        orch.sm.State.BUILDING
    )
    code_dir = project_dir / (spec.code_dir if spec and spec.code_dir else "app")

    if args.dry_run:
        detected = verify.detect_command(code_dir)
        if detected is None:
            print(f"没有检测到测试命令（{code_dir}）")
            print("  支持：package.json 的 scripts.test / pytest 配置 / Makefile 的 test 目标")
            return 1
        print("将执行： " + " ".join(detected.argv))
        print(f"  来源：{detected.source}")
        if detected.install:
            print(f"  依赖安装： {' '.join(detected.install)}")
        return 0

    result = verify.run_verification(project_dir, code_dir=code_dir)
    print(verify.describe(result))
    if result.output_tail:
        print()
        print(result.output_tail)
    return 0 if result.status == "passed" else 1


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

    p_deploy = sub.add_parser(
        "deploy", help="deploy to Cloudflare (records `launched` only on success)"
    )
    p_deploy.add_argument("project")
    p_deploy.add_argument(
        "--environment", default="production", choices=["production", "preview"]
    )
    p_deploy.add_argument(
        "--dry-run", action="store_true", help="print the command without deploying"
    )
    p_deploy.add_argument("--yes", action="store_true", help="auto-approve the gate")
    p_deploy.set_defaults(func=cmd_deploy)

    p_domain = sub.add_parser(
        "domain", help="record the custom domain you attached by hand"
    )
    p_domain.add_argument("project")
    p_domain.add_argument("--domain", required=True)
    p_domain.set_defaults(func=cmd_domain)

    p_dstatus = sub.add_parser("deploy-status", help="show deployment info")
    p_dstatus.add_argument("project")
    p_dstatus.set_defaults(func=cmd_deploy_status)

    p_metrics = sub.add_parser(
        "metrics", help="fetch real Search Console / GA4 data (closes the loop)"
    )
    p_metrics.add_argument("project")
    p_metrics.add_argument(
        "--days", type=int, default=None, help="lookback window (default from config)"
    )
    p_metrics.add_argument(
        "--dry-run", action="store_true", help="show what is configured, call no APIs"
    )
    p_metrics.set_defaults(func=cmd_metrics)

    p_verify = sub.add_parser(
        "verify", help="run the project's own tests (no state changes)"
    )
    p_verify.add_argument("project")
    p_verify.add_argument(
        "--dry-run", action="store_true", help="show the detected command only"
    )
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    # Deployment is a pre-transition action, so `run` (and `deploy`) can never
    # record `launched` without the deploy having actually succeeded.
    orch.register_pre_transition_action(
        State.RELEASE_PENDING, State.LAUNCHED, deploy.deploy_before_launch
    )

    try:
        return args.func(args)
    except (orch.PipelineError, radar.RadarError, metrics.MetricsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中断。state.json 已保存，可直接重跑续上。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
