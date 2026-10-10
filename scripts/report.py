#!/usr/bin/env python3
"""Human-readable reports over the pipeline's own state.

Everything the pipeline produces is already on disk, but reading it meant
opening `state.json` and several artifact files. This turns that into one view,
and it is deliberately opinionated about what to surface first:

* **what is waiting for you** -- a project sitting at an ungranted approval gate
  is the single most actionable fact, and nothing used to say so;
* **real versus mock** -- an artifact produced by the mock adapter is not
  evidence, and a report that blurs the two is worse than none;
* **the real numbers** -- GSC/GA4 metrics, the test run, the deployment URL.

Two views: one project in full, or every project at a glance.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
for _p in (str(_HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import state_machine as sm  # noqa: E402

logger = logging.getLogger(__name__)

MISSING = "—"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_state(project_dir: Path | str) -> dict[str, Any]:
    return _read_json(Path(project_dir) / "state.json")


def discover_projects(projects_dir: Path | None = None) -> list[Path]:
    projects_dir = projects_dir or (REPO_ROOT / "projects")
    if not projects_dir.is_dir():
        return []
    return sorted(
        p for p in projects_dir.iterdir() if (p / "state.json").is_file()
    )


# ---------------------------------------------------------------------------
# Derived facts
# ---------------------------------------------------------------------------


def pending_gate(state: dict[str, Any]) -> dict[str, Any] | None:
    """The approval a project is sitting on, if any.

    This is the answer to "why is nothing happening", and it had no home before.
    """
    stage = state.get("stage")
    if not stage:
        return None
    try:
        current = sm.State(stage)
    except ValueError:
        return None

    approved = {e.get("stage") for e in (state.get("approved_stages") or [])}
    for nxt in sm.get_valid_transitions(current):
        cfg = sm.TRANSITIONS[(current, nxt)]
        if cfg.approval_required and nxt.value not in approved:
            return {
                "from": current.value,
                "to": nxt.value,
                "gate": cfg.gate,
                "required_artifacts": list(cfg.required_artifacts),
            }
    return None


def _artifact_rows(project_dir: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, entry in (state.get("artifacts") or {}).items():
        exists = (project_dir / entry.get("path", "")).is_file()
        rows.append(
            {
                "key": key,
                "path": entry.get("path"),
                "exists": exists,
                "mode": entry.get("mode") or MISSING,
                "is_real_data": entry.get("is_real_data"),
                "generated_at": entry.get("generated_at") or MISSING,
                "code": entry.get("code"),
            }
        )
    return rows


def _real_data(project_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Pull the genuinely-real numbers out of the artifact files."""
    out: dict[str, Any] = {}

    metrics_entry = (state.get("artifacts") or {}).get("metrics")
    if metrics_entry and (project_dir / metrics_entry["path"]).is_file():
        report = _read_json(project_dir / metrics_entry["path"])
        gsc = ((report.get("sources") or {}).get("search_console") or {})
        ga4 = ((report.get("sources") or {}).get("analytics") or {})
        out["metrics"] = {
            "mode": report.get("mode"),
            "fetched_at": report.get("fetched_at"),
            "search_console": gsc.get("totals"),
            "delta": gsc.get("delta"),
            "opportunities": gsc.get("opportunities") or [],
            "analytics": ga4.get("totals"),
            "unavailable": report.get("unavailable") or [],
        }

    deploy_entry = (state.get("artifacts") or {}).get("deployment")
    if deploy_entry and (project_dir / deploy_entry["path"]).is_file():
        record = _read_json(project_dir / deploy_entry["path"])
        out["deployment"] = {
            "url": record.get("url"),
            "kind": record.get("kind"),
            "environment": record.get("environment"),
            "deployed_at": record.get("deployed_at"),
            "custom_domain": record.get("custom_domain"),
        }

    test_entry = (state.get("artifacts") or {}).get("test_run")
    if test_entry and (project_dir / test_entry["path"]).is_file():
        run = _read_json(project_dir / test_entry["path"])
        out["tests"] = {
            "status": run.get("status"),
            "command": run.get("command"),
            "exit_code": run.get("exit_code"),
            "duration_seconds": run.get("duration_seconds"),
        }

    return out


def _trailing_audit(state: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    return (state.get("audit_log") or [])[-limit:]


def _audit_line(entry: dict[str, Any]) -> str:
    action = entry.get("action", "?")
    bits = []
    for key in ("from_stage", "to_stage", "stage", "status", "gate", "url", "domain", "mode"):
        if entry.get(key) not in (None, ""):
            bits.append(f"{key}={entry[key]}")
    if entry.get("exit_code") is not None:
        bits.append(f"exit={entry['exit_code']}")
    detail = " ".join(bits)
    return f"| {entry.get('timestamp', MISSING)} | `{action}` | {detail or MISSING} |"


# ---------------------------------------------------------------------------
# Project report
# ---------------------------------------------------------------------------


def project_report(project_dir: Path | str) -> str:
    project_dir = Path(project_dir)
    state = load_state(project_dir)
    if not state:
        return f"# 错误\n\n无法读取 {project_dir / 'state.json'}\n"

    lines: list[str] = []
    name = state.get("name") or project_dir.name
    lines.append(f"# {name}")
    lines.append("")
    lines.append(f"*生成于 {utc_now()}*")
    lines.append("")

    # --- Overview ---
    lines.append("## 概览")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    for label, key in (
        ("项目 ID", "project_id"),
        ("名称", "name"),
        ("阶段", "stage"),
        ("状态", "status"),
        ("创建", "created_at"),
        ("更新", "updated_at"),
    ):
        lines.append(f"| {label} | {state.get(key) or MISSING} |")
    lines.append("")

    # --- What is waiting for you, first ---
    gate = pending_gate(state)
    lines.append("## 待办")
    lines.append("")
    if gate:
        lines.append(f"⏸ **等待你批准**：`{gate['gate']}`（{gate['from']} → {gate['to']}）")
        lines.append("")
        lines.append(f"批准：`./autopilot.py approve {project_dir.name} --stage {gate['to']}`")
        lines.append("")
        lines.append(f"或运行：`./autopilot.py run {project_dir.name}`")
    else:
        lines.append("没有待批准的审批门。")
    lines.append("")

    nexts = sm.get_valid_transitions(state.get("stage")) if state.get("stage") in {s.value for s in sm.State} else []
    if nexts:
        approved = {e.get("stage") for e in (state.get("approved_stages") or [])}
        lines.append("下一步可选：")
        lines.append("")
        for nxt in nexts:
            cfg = sm.TRANSITIONS[(sm.State(state["stage"]), nxt)]
            marks = []
            for key in cfg.required_artifacts:
                have = key in (state.get("artifacts") or {})
                marks.append(f"{'✅' if have else '❌'} {key}")
            if cfg.approval_required:
                marks.append(
                    f"{'✅' if nxt.value in approved else '❌'} 审批({nxt.value})"
                )
            suffix = f"  [{', '.join(marks)}]" if marks else "  [可直接进入]"
            lines.append(f"- `{nxt.value}`{suffix}")
        lines.append("")

    # --- Artifacts ---
    rows = _artifact_rows(project_dir, state)
    lines.append("## 产物")
    lines.append("")
    if rows:
        lines.append("| 键 | 路径 | 文件 | 来源 | 真实数据 | 生成时间 |")
        lines.append("|---|---|---|---|---|---|")
        for row in rows:
            real = {True: "✅", False: "❌", None: MISSING}.get(row["is_real_data"])
            lines.append(
                f"| `{row['key']}` | {row['path']} | {'✅' if row['exists'] else '❌'} "
                f"| {row['mode']} | {real} | {row['generated_at']} |"
            )
        lines.append("")
        lines.append("> `mock` 来源的产物不是证据，只是流程占位。")
    else:
        lines.append(f"*{MISSING}*")
    lines.append("")

    # --- Real data ---
    real = _real_data(project_dir, state)
    if real:
        lines.append("## 真实数据")
        lines.append("")
        if "metrics" in real:
            m = real["metrics"]
            lines.append(f"### 流量（mode: {m['mode']}，拉取于 {m['fetched_at']}）")
            lines.append("")
            if m.get("search_console"):
                sc = m["search_console"]
                lines.append(
                    "Search Console："
                    + "，".join(f"{k}={v}" for k, v in sc.items())
                )
            if m.get("delta"):
                parts = [
                    f"{k} {'+' if (v or 0) >= 0 else ''}{round((v or 0) * 100, 1)}%"
                    for k, v in m["delta"].items()
                    if v is not None
                ]
                if parts:
                    lines.append("")
                    lines.append("环比：" + "，".join(parts))
            if m.get("analytics"):
                lines.append("")
                lines.append(
                    "GA4：" + "，".join(f"{k}={v}" for k, v in m["analytics"].items())
                )
            if m.get("opportunities"):
                lines.append("")
                lines.append("SEO 机会：")
                lines.append("")
                lines.append("| 类型 | 查询 | 展示 | 点击 | 排名 | 动作 |")
                lines.append("|---|---|---|---|---|---|")
                for opp in m["opportunities"][:8]:
                    lines.append(
                        f"| {opp.get('type')} | {opp.get('query')} | {opp.get('impressions')} "
                        f"| {opp.get('clicks')} | {opp.get('position')} | {opp.get('action')} |"
                    )
            if m.get("unavailable"):
                lines.append("")
                lines.append("不可用：" + "；".join(m["unavailable"]))
            lines.append("")
        if "tests" in real:
            t = real["tests"]
            icon = {"passed": "✅", "failed": "❌"}.get(t.get("status"), "⚠️")
            lines.append(f"### 测试 {icon} {t.get('status')}")
            lines.append("")
            if t.get("command"):
                lines.append(f"`{' '.join(t['command'])}`")
            if t.get("exit_code") is not None:
                lines.append(f"退出码 {t['exit_code']}，用时 {t.get('duration_seconds')}s")
            lines.append("")
        if "deployment" in real:
            d = real["deployment"]
            lines.append("### 部署")
            lines.append("")
            lines.append(f"- URL：{d.get('url') or MISSING}")
            lines.append(f"- 类型：{d.get('kind')}（{d.get('environment')}）")
            lines.append(f"- 时间：{d.get('deployed_at')}")
            lines.append(f"- 自定义域名：{d.get('custom_domain') or '（尚未挂）'}")
            lines.append("")

    # --- Code manifest ---
    code_artifacts = [r for r in rows if r.get("code")]
    if code_artifacts:
        lines.append("## 代码")
        lines.append("")
        for row in code_artifacts:
            code = row["code"]
            lines.append(
                f"{code.get('file_count')} 个文件，{code.get('bytes')} 字节（`{row['key']}`）"
            )
            lines.append("")
            for path in (code.get("files") or [])[:20]:
                lines.append(f"- `{path}`")
            lines.append("")

    # --- Approvals ---
    lines.append("## 批准记录")
    lines.append("")
    approvals = state.get("approved_stages") or []
    if approvals:
        lines.append("| 目标阶段 | 门 | 批准人 | 时间 |")
        lines.append("|---|---|---|---|")
        for entry in approvals:
            lines.append(
                f"| `{entry.get('stage')}` | {entry.get('gate') or MISSING} "
                f"| {entry.get('approved_by') or MISSING} | {entry.get('approved_at') or MISSING} |"
            )
    else:
        lines.append(f"*{MISSING}*")
    lines.append("")

    # --- Timeline ---
    lines.append("## 最近动态")
    lines.append("")
    audit = _trailing_audit(state)
    if audit:
        lines.append("| 时间 | 动作 | 详情 |")
        lines.append("|---|---|---|")
        for entry in audit:
            lines.append(_audit_line(entry))
    else:
        lines.append(f"*{MISSING}*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Portfolio report
# ---------------------------------------------------------------------------


def portfolio_report(project_dirs: list[Path] | None = None) -> str:
    dirs = project_dirs if project_dirs is not None else discover_projects()
    lines = ["# 所有项目", "", f"*生成于 {utc_now()}*", ""]
    if not dirs:
        lines.append("(projects/ 下没有可识别的项目)")
        return "\n".join(lines)

    lines.append("| 项目 | 阶段 | 待办 | 真实数据 | 最近更新 |")
    lines.append("|---|---|---|---|---|")
    waiting: list[tuple[str, dict[str, Any]]] = []
    for project_dir in dirs:
        state = load_state(project_dir)
        gate = pending_gate(state)
        real_count = sum(
            1
            for entry in (state.get("artifacts") or {}).values()
            if entry.get("is_real_data")
        )
        marker = f"⏸ {gate['gate']}" if gate else "—"
        lines.append(
            f"| `{project_dir.name}` | {state.get('stage') or MISSING} | {marker} "
            f"| {real_count} 项 | {state.get('updated_at') or MISSING} |"
        )
        if gate:
            waiting.append((project_dir.name, gate))

    if waiting:
        lines.append("")
        lines.append("## 等待你处理")
        lines.append("")
        for name, gate in waiting:
            lines.append(
                f"- **{name}**：`{gate['gate']}`（{gate['from']} → {gate['to']}）"
                f" → `./autopilot.py run {name}`"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(description="Report on pipeline state.")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--all", action="store_true", help="every project at a glance")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    if args.all or not args.project_dir:
        text = portfolio_report()
    else:
        text = project_report(args.project_dir)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"已写入 {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
