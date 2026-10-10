#!/usr/bin/env python3
"""Local pipeline orchestrator for indie-autopilot.

This module is the *driver* that replaces the GitHub Actions workflows. It walks
a project along the canonical state machine path, running the stage agent for
each state, registering the artifact it produced, and pausing at every approval
gate for a local decision.

Design notes
------------
* The state machine (:mod:`state_machine`) is the single source of truth for
  what transitions exist. This module never invents transitions: it asks
  ``get_valid_transitions`` and lets ``apply_transition`` enforce the gates.
* Approvals are written into ``state.json``'s ``approved_stages`` array, which
  is exactly what ``check_transition`` already validates. Nothing else needs to
  know how an approval was obtained.
* Progress lives entirely in ``state.json``, so every run is resumable: if the
  process dies, re-running picks up from the recorded stage.
* ``force_move`` is the one deliberate escape hatch. It is always audited.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
for _p in (str(_HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import state_machine as sm  # noqa: E402
from state_machine import State  # noqa: E402

from adapters.adapter_interface import (  # noqa: E402
    AgentAdapter,
    StageRequest,
    validate_response,
)

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_CONFIG = REPO_ROOT / "config" / "pipeline.yaml"
WORKFLOW_POLICY = REPO_ROOT / "config" / "workflow-policy.yml"
STAGE_RESULT_SCHEMA = "schemas/stage-result.schema.json"


class PipelineError(Exception):
    """Raised for any user-facing pipeline failure."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageSpec:
    """How to fulfil one state-machine stage."""

    stage: State
    agent_stage: str
    output_dir: str
    artifact_key: str
    description: str = ""


@dataclass
class PipelineConfig:
    """Parsed ``config/pipeline.yaml`` plus optional ``workflow-policy.yml``."""

    stages: dict[State, StageSpec]
    adapters: dict[str, dict[str, str]]
    default_target: State
    policy: dict[str, Any]

    def spec_for(self, stage: State | str) -> StageSpec | None:
        return self.stages.get(State(stage))

    def timeout_seconds(self, agent_stage: str) -> int:
        """Stage timeout in seconds, taken from workflow-policy.yml if present."""
        entry = (self.policy.get("stages") or {}).get(agent_stage) or {}
        minutes = entry.get("timeout_minutes")
        return int(minutes) * 60 if minutes else 300

    def gate_policy(self, gate_id: str | None) -> dict[str, Any]:
        if not gate_id:
            return {}
        return (self.policy.get("approval_gates") or {}).get(gate_id) or {}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise PipelineError("PyYAML is required to read pipeline config") from exc
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - surface any parse problem clearly
        raise PipelineError(f"Could not parse {path}: {exc}") from exc


def load_config(path: Path | str = DEFAULT_PIPELINE_CONFIG) -> PipelineConfig:
    """Load and validate the pipeline configuration."""
    raw = _load_yaml(Path(path))
    if not raw:
        raise PipelineError(f"Pipeline config is missing or empty: {path}")

    stages: dict[State, StageSpec] = {}
    for stage_name, entry in (raw.get("stages") or {}).items():
        try:
            stage = State(stage_name)
        except ValueError as exc:
            raise PipelineError(
                f"pipeline.yaml declares unknown stage '{stage_name}'"
            ) from exc
        if not entry or not entry.get("agent_stage"):
            raise PipelineError(
                f"pipeline.yaml stage '{stage_name}' is missing 'agent_stage'"
            )
        stages[stage] = StageSpec(
            stage=stage,
            agent_stage=entry["agent_stage"],
            output_dir=entry.get("output_dir", entry["agent_stage"]),
            artifact_key=entry.get("artifact_key") or f"{entry['agent_stage']}_result",
            description=entry.get("description", ""),
        )

    default_target_raw = raw.get("default_target", "growing")
    try:
        default_target = State(default_target_raw)
    except ValueError as exc:
        raise PipelineError(
            f"pipeline.yaml default_target '{default_target_raw}' is not a known stage"
        ) from exc

    return PipelineConfig(
        stages=stages,
        adapters=raw.get("adapters") or {},
        default_target=default_target,
        policy=_load_yaml(WORKFLOW_POLICY),
    )


def load_adapter(config: PipelineConfig, name: str) -> AgentAdapter:
    """Instantiate the named adapter from the config registry."""
    entry = config.adapters.get(name)
    if not entry:
        known = ", ".join(sorted(config.adapters)) or "none"
        raise PipelineError(f"Unknown adapter '{name}'. Registered adapters: {known}")

    import importlib

    try:
        module = importlib.import_module(entry["module"])
        cls = getattr(module, entry["class"])
    except (ImportError, KeyError, AttributeError) as exc:
        raise PipelineError(
            f"Could not load adapter '{name}' from {entry}: {exc}"
        ) from exc

    adapter = cls()
    if not adapter.health_check():
        raise PipelineError(f"Adapter '{name}' failed its health check")
    return adapter


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(project_dir: Path | str) -> Path:
    return Path(project_dir) / "state.json"


def load_state(project_dir: Path | str) -> dict[str, Any]:
    path = state_path(project_dir)
    if not path.is_file():
        raise PipelineError(f"State file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"State file contains invalid JSON: {path} — {exc}") from exc


def save_state(project_dir: Path | str, state: dict[str, Any]) -> None:
    path = state_path(project_dir)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _append_audit(state: dict[str, Any], action: str, *, actor: str | None = None, **details: Any) -> None:
    """Append an audit entry.

    ``actor`` is required by ``schemas/project.schema.json`` on every entry, so
    it is always populated here rather than left to each call site.
    """
    entry: dict[str, Any] = {
        "timestamp": utc_now(),
        "action": action,
        "actor": actor or "orchestrator",
    }
    entry.update(details)
    state.setdefault("audit_log", []).append(entry)


def current_actor() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - very unusual environments
        return os.environ.get("USER", "unknown")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def plan_route(from_stage: State | str, to_stage: State | str) -> list[State] | None:
    """Return the shortest state sequence from *from_stage* to *to_stage*.

    ``[]`` means already there; ``None`` means no route exists (the caller
    should suggest ``--force``).
    """
    start, goal = State(from_stage), State(to_stage)
    if start == goal:
        return []

    queue: deque[tuple[State, list[State]]] = deque([(start, [])])
    seen: set[State] = {start}
    while queue:
        node, path = queue.popleft()
        for nxt in sm.get_valid_transitions(node):
            if nxt in seen:
                continue
            new_path = path + [nxt]
            if nxt == goal:
                return new_path
            seen.add(nxt)
            queue.append((nxt, new_path))
    return None


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------


def _artifact_path(project_dir: Path, spec: StageSpec, mode: str) -> tuple[Path, str]:
    """Absolute path and project-relative path for a stage result file."""
    prefix = "mock-" if mode == "mock" else ""
    out_dir = project_dir / spec.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    abs_path = out_dir / f"{prefix}{spec.agent_stage}-result.json"
    return abs_path, str(abs_path.relative_to(project_dir))


def artifact_is_current(project_dir: Path, state: dict[str, Any], spec: StageSpec) -> bool:
    """True when the artifact is registered *and* still present on disk."""
    entry = (state.get("artifacts") or {}).get(spec.artifact_key)
    if not entry or not entry.get("path"):
        return False
    return (Path(project_dir) / entry["path"]).is_file()


def execute_stage(
    project_dir: Path,
    state: dict[str, Any],
    spec: StageSpec,
    adapter: AgentAdapter,
    config: PipelineConfig,
) -> str:
    """Run the agent for *spec* and register the artifact it produced.

    Returns the project-relative artifact path. The caller persists the state.
    """
    project_dir = Path(project_dir)
    request = StageRequest(
        project_id=state["project_id"],
        stage=spec.agent_stage,  # type: ignore[arg-type]
        task_description=f"{spec.description or spec.agent_stage} for {state['project_id']}",
        allowed_read_paths=[str(project_dir)],
        expected_output_schema=STAGE_RESULT_SCHEMA,
        timeout_seconds=config.timeout_seconds(spec.agent_stage),
        work_dir=str(project_dir / spec.output_dir),
    )

    response = adapter.execute(request)
    if response.status != "success" or response.stage_result is None:
        raise PipelineError(
            f"Stage '{spec.agent_stage}' failed: status={response.status} "
            f"errors={response.errors or response.raw_output}"
        )

    schema_abs = str(REPO_ROOT / STAGE_RESULT_SCHEMA)
    errors = validate_response(response, schema_abs)
    if errors:
        raise PipelineError(
            f"Stage '{spec.agent_stage}' produced output that violates "
            f"{STAGE_RESULT_SCHEMA}: " + "; ".join(errors)
        )

    abs_path, rel_path = _artifact_path(project_dir, spec, response.mode)
    abs_path.write_text(
        json.dumps(response.stage_result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    meta_path = abs_path.with_name(abs_path.name.replace("-result.json", "-meta.json"))
    meta_path.write_text(
        json.dumps(
            {
                "response": {
                    "status": response.status,
                    "raw_output": response.raw_output,
                    "errors": response.errors,
                    "duration_seconds": response.duration_seconds,
                    "mode": response.mode,
                    "is_real_data": response.is_real_data,
                }
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    state.setdefault("artifacts", {})[spec.artifact_key] = {
        "path": rel_path,
        "stage": spec.stage.value,
        "generated_at": utc_now(),
        "mode": response.mode,
        "is_real_data": response.is_real_data,
    }
    _append_audit(
        state,
        "stage_executed",
        actor=f"adapter:{adapter.name()}",
        stage=spec.stage.value,
        agent_stage=spec.agent_stage,
        adapter=adapter.name(),
        artifact_key=spec.artifact_key,
        artifact_path=rel_path,
        mode=response.mode,
        duration_seconds=response.duration_seconds,
    )
    return rel_path


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def grant_approval(state: dict[str, Any], target: State, gate_id: str | None, by: str) -> None:
    """Record an approval for *target*, in the shape ``check_transition`` reads."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    entry = {
        "stage": target.value,
        "approved_at": utc_now(),
        "approval_id": f"appr-{target.value}-{stamp}",
        "approved_by": by,
        "mode": "local",
    }
    if gate_id:
        entry["gate"] = gate_id
    state.setdefault("approved_stages", []).append(entry)
    _append_audit(
        state,
        "approval_granted",
        actor=by,
        stage=target.value,
        gate=gate_id,
        approval_id=entry["approval_id"],
    )


def record_rejection(state: dict[str, Any], target: State, gate_id: str | None, by: str) -> None:
    _append_audit(
        state,
        "approval_rejected",
        actor=by,
        stage=target.value,
        gate=gate_id,
    )


def _describe_gate(
    config: PipelineConfig,
    state: dict[str, Any],
    src: State,
    dst: State,
    gate_id: str | None,
) -> str:
    policy = config.gate_policy(gate_id)
    lines = [
        "",
        f"  ⏸  GATE {gate_id or '(unnamed)'}" + (
            f"  risk={policy['risk_level']}" if policy.get("risk_level") else ""
        ),
        f"     {src.value} -> {dst.value}",
    ]
    if policy.get("description"):
        lines.append(f"     目的: {policy['description']}")
    if policy.get("requires"):
        lines.append(f"     需要产物: {', '.join(policy['requires'])}")
    for key, entry in (state.get("artifacts") or {}).items():
        lines.append(f"     产物 {key}: {entry.get('path')}")
    return "\n".join(lines)


def ask_gate(
    config: PipelineConfig,
    project_dir: Path,
    state: dict[str, Any],
    src: State,
    dst: State,
    gate_id: str | None,
    *,
    assume_yes: bool,
    actor: str,
) -> bool:
    """Return True when the transition is approved."""
    print(_describe_gate(config, state, src, dst, gate_id))

    if assume_yes:
        print("     --yes: 自动批准")
        return True

    if not sys.stdin.isatty():
        raise PipelineError(
            "Approval required but stdin is not a TTY. "
            "Re-run interactively or pass --yes to auto-approve."
        )

    while True:
        try:
            answer = input("     [y]批准 [n]拒绝 [q]退出 > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        if answer in ("q", "quit"):
            raise PipelineError("Aborted at gate; state left unchanged.")
        print("     请输入 y / n / q")


# ---------------------------------------------------------------------------
# The run loop
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Outcome of a :func:`run` call."""

    reached: str
    completed: bool
    stopped_reason: str


def run(
    project_dir: Path | str,
    *,
    target: State | str | None = None,
    config: PipelineConfig | None = None,
    adapter_name: str = "mock",
    assume_yes: bool = False,
    rerun: bool = False,
    actor: str | None = None,
) -> RunResult:
    """Advance a project along the canonical path until *target* or a refusal."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        raise PipelineError(f"Project directory does not exist: {project_dir}")

    config = config or load_config()
    adapter = load_adapter(config, adapter_name)
    state = load_state(project_dir)
    actor = actor or current_actor()
    goal = State(target) if target else config.default_target

    if state.get("status") == "archived":
        raise PipelineError("Project is archived; refusing to run.")

    route = plan_route(state["stage"], goal)
    if route is None:
        raise PipelineError(
            f"No valid route from '{state['stage']}' to '{goal.value}'. "
            f"Valid next steps: "
            f"{', '.join(s.value for s in sm.get_valid_transitions(state['stage'])) or 'none'}. "
            f"Use `autopilot move --force` to override deliberately."
        )

    def _ensure_stage_artifact(stage: State) -> None:
        """Run *stage*'s agent unless its artifact is already present."""
        spec = config.spec_for(stage)
        if not spec:
            return
        if rerun or not artifact_is_current(project_dir, state, spec):
            print(f"[{stage.value}] 运行 {spec.agent_stage} agent ...", flush=True)
            rel = execute_stage(project_dir, state, spec, adapter, config)
            save_state(project_dir, state)
            print(f"[{stage.value}] 产物已登记: {rel} ✅")

    # Entering a stage runs its agent. Doing this for the current stage before
    # leaving it means the artifact the outgoing transition requires always
    # exists; doing it again after each transition keeps the target stage
    # itself complete (e.g. `run --to building` really produces build_result).
    _ensure_stage_artifact(State(state["stage"]))

    for nxt in route:
        src = State(state["stage"])

        # 1. Gate, if this transition is gated.
        cfg = sm.TRANSITIONS[(src, nxt)]
        if cfg.approval_required and not _already_approved(state, nxt):
            approved = ask_gate(
                config, project_dir, state, src, nxt, cfg.gate,
                assume_yes=assume_yes, actor=actor,
            )
            if not approved:
                record_rejection(state, nxt, cfg.gate, actor)
                save_state(project_dir, state)
                return RunResult(
                    reached=state["stage"],
                    completed=False,
                    stopped_reason=f"在 {src.value} -> {nxt.value} 被拒绝",
                )
            grant_approval(state, nxt, cfg.gate, actor)

        # 2. Apply the transition (state machine re-validates everything).
        try:
            new_state = sm.apply_transition(src, nxt, state)
        except ValueError as exc:
            raise PipelineError(str(exc)) from exc
        state = new_state
        state["audit_log"][-1]["actor"] = actor
        save_state(project_dir, state)
        print(f"[{nxt.value}] ✅ 状态已更新")

        # 3. Fulfil the stage we just entered.
        _ensure_stage_artifact(nxt)

    return RunResult(
        reached=state["stage"],
        completed=State(state["stage"]) == goal,
        stopped_reason="已到达目标" if State(state["stage"]) == goal else "stopped",
    )


def _already_approved(state: dict[str, Any], target: State) -> bool:
    return any(
        entry.get("stage") == target.value
        for entry in (state.get("approved_stages") or [])
    )


def force_move(
    project_dir: Path | str,
    to_stage: State | str,
    *,
    reason: str,
    actor: str | None = None,
) -> dict[str, Any]:
    """Deliberately jump to *to_stage*, bypassing gates. Always audited."""
    project_dir = Path(project_dir)
    state = load_state(project_dir)
    target = State(to_stage)
    src = State(state["stage"])
    actor = actor or current_actor()

    if src == target:
        raise PipelineError(f"Project is already in '{target.value}'.")

    state["stage"] = target.value
    state["updated_at"] = utc_now()
    _append_audit(
        state,
        "forced_transition",
        actor=actor,
        from_stage=src.value,
        to_stage=target.value,
        reason=reason,
        warning="gates and artifact requirements were bypassed",
    )
    save_state(project_dir, state)
    return state


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def describe_status(project_dir: Path | str, config: PipelineConfig | None = None) -> str:
    project_dir = Path(project_dir)
    config = config or load_config()
    state = load_state(project_dir)
    stage = State(state["stage"])

    lines = [
        f"project_id : {state.get('project_id')}",
        f"name       : {state.get('name', '-')}",
        f"stage      : {stage.value}",
    ]
    spec = config.spec_for(stage)
    if spec:
        lines.append(f"agent      : {spec.agent_stage} ({spec.description})")

    lines.append("artifacts  :")
    artifacts = state.get("artifacts") or {}
    if not artifacts:
        lines.append("  (none)")
    for key, entry in artifacts.items():
        exists = (project_dir / entry["path"]).is_file()
        lines.append(f"  {'✅' if exists else '❌'} {key}: {entry['path']}")

    lines.append("approvals  :")
    approvals = state.get("approved_stages") or []
    if not approvals:
        lines.append("  (none)")
    for entry in approvals:
        lines.append(
            f"  ✅ {entry.get('stage')} by {entry.get('approved_by')} "
            f"at {entry.get('approved_at')}"
        )

    nexts = sm.get_valid_transitions(stage)
    lines.append("next       :")
    if not nexts:
        lines.append("  (terminal — no outgoing transitions)")
    for nxt in nexts:
        cfg = sm.TRANSITIONS[(stage, nxt)]
        marks = [
            f"{'✅' if key in (state.get('artifacts') or {}) else '❌'} {key}"
            for key in cfg.required_artifacts
        ]
        if cfg.approval_required:
            marks.append(
                f"{'✅' if _already_approved(state, nxt) else '❌'} approval({nxt.value})"
            )
        lines.append(
            f"  -> {nxt.value}  [{', '.join(marks)}]" if marks
            else f"  -> {nxt.value}  [ready]"
        )

    return "\n".join(lines)


def describe_history(project_dir: Path | str, limit: int | None = None) -> str:
    state = load_state(project_dir)
    entries = state.get("audit_log") or []
    if limit:
        entries = entries[-limit:]
    if not entries:
        return "(no audit entries)"
    lines = []
    for entry in entries:
        detail = " ".join(
            f"{k}={v}" for k, v in entry.items() if k not in ("timestamp", "action")
        )
        lines.append(f"{entry.get('timestamp')}  {entry.get('action'):20} {detail}")
    return "\n".join(lines)
