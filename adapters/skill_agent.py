"""Skill-driven agent adapter.

Turns the 31 SKILL.md methodology documents into executable work: it composes
the relevant skills, the project's current artifacts, and the required JSON
output contract into one self-contained brief, then hands that brief to an
:mod:`adapters.agent_backends` backend.

The brief is deliberately **self-contained** (artifact contents are inlined, not
merely referenced) so that a handoff run in a plain chat window has everything
it needs without filesystem access.

Which skills run at each stage is configured in ``config/pipeline.yaml`` under
``skills:`` -- it is not hardcoded here, because prompt size matters (all 31
skills together are ~165 KB).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
for _p in (str(_HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.adapter_interface import (  # noqa: E402
    AgentAdapter,
    AgentResponse,
    StageRequest,
    validate_response,
)
from adapters.agent_backends import (  # noqa: E402
    AgentBackend,
    BackendError,
    build_backend,
    load_backends,
)

logger = logging.getLogger(__name__)

SKILLS_DIR = REPO_ROOT / "indie-builder-skills" / "skills"
PIPELINE_CONFIG = REPO_ROOT / "config" / "pipeline.yaml"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_pipeline_yaml() -> dict[str, Any]:
    if not PIPELINE_CONFIG.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(PIPELINE_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s: %s", PIPELINE_CONFIG, exc)
        return {}


def load_skill_map(config: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Return the stage -> skill-name mapping from ``config/pipeline.yaml``."""
    config = config if config is not None else _load_pipeline_yaml()
    raw = config.get("skills") or {}
    return {stage: list(names or []) for stage, names in raw.items()}


def load_skill_text(skill_name: str) -> str:
    """Read one SKILL.md, raising a clear error when it is missing."""
    path = SKILLS_DIR / skill_name / "SKILL.md"
    if not path.is_file():
        raise BackendError(f"Skill not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_skill_bundle(skill_name: str, *, max_chars: int = 80_000) -> str:
    """SKILL.md **plus** its ``references/`` and ``assets/`` files.

    Skills routinely delegate detail to reference documents (scoring rubrics,
    search playbooks, output schemas, report templates). A handoff agent has no
    filesystem access, so anything the skill points at has to travel with the
    brief -- otherwise the agent is told to follow a rubric it cannot see.

    Files are included in sorted order until *max_chars* is reached; anything
    skipped is announced in the brief so the omission is visible, never silent.
    """
    skill_dir = SKILLS_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise BackendError(f"Skill not found: {skill_md}")

    main = skill_md.read_text(encoding="utf-8").strip()
    parts: list[str] = [main]
    used = len(main)

    for sub in ("references", "assets"):
        sub_dir = skill_dir / sub
        if not sub_dir.is_dir():
            continue
        for path in sorted(sub_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if used + len(text) > max_chars:
                parts.append(
                    f"\n### 附：{sub}/{path.name}\n\n"
                    f"[已省略：超出本次 {max_chars} 字符预算]"
                )
                continue
            parts.append(f"\n### 附：{sub}/{path.name}\n\n{text}")
            used += len(text)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _read_project_context(
    project_dir: Path, max_artifact_chars: int
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Return (state, [(label, text)]) for the project."""
    state_path = project_dir / "state.json"
    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}

    blocks: list[tuple[str, str]] = []
    for key, entry in (state.get("artifacts") or {}).items():
        rel = entry.get("path")
        if not rel:
            continue
        abs_path = project_dir / rel
        if not abs_path.is_file():
            continue
        try:
            text = abs_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if len(text) > max_artifact_chars:
            text = text[:max_artifact_chars] + "\n... (已截断)"
        blocks.append((f"{key} ({rel})", text))
    return state, blocks


def _describe_schema_constraints(schema: dict[str, Any], max_lines: int = 40) -> str:
    """Summarise required fields and enum values in plain language.

    A handoff agent cannot afford to guess: one schema violation means a whole
    manual round-trip. So enums (and uniform numeric ranges) are spelled out
    instead of leaving the agent to read them out of the raw schema.

    ``$ref`` is resolved against the root schema, because the schemas here put
    their interesting enums in ``definitions``.
    """
    lines: list[str] = []

    required = schema.get("required") or []
    if required:
        lines.append(f"- 必填字段：{', '.join(str(r) for r in required)}")

    def resolve(spec: Any) -> dict[str, Any]:
        if isinstance(spec, dict) and isinstance(spec.get("$ref"), str):
            ref = spec["$ref"]
            if ref.startswith("#/"):
                node: Any = schema
                for part in ref[2:].split("/"):
                    if not isinstance(node, dict):
                        return {}
                    node = node.get(part, {})
                return node if isinstance(node, dict) else {}
        return spec if isinstance(spec, dict) else {}

    def _uniform_integer_range(props: dict[str, Any]) -> tuple[int, int] | None:
        """Return (min, max) when every property is an integer in the same range."""
        bounds: set[tuple[int, int]] = set()
        for raw in props.values():
            spec = resolve(raw)
            if spec.get("type") != "integer":
                return None
            low, high = spec.get("minimum"), spec.get("maximum")
            if low is None or high is None:
                return None
            bounds.add((int(low), int(high)))
        return bounds.pop() if len(bounds) == 1 else None

    def walk(props: dict[str, Any], prefix: str = "", depth: int = 0) -> None:
        if depth > 4 or not isinstance(props, dict):
            return
        for name, raw in props.items():
            spec = resolve(raw)
            path = f"{prefix}{name}"
            if "enum" in spec:
                allowed = ", ".join(str(v) for v in spec["enum"])
                lines.append(f"- `{path}` 只能取：{allowed}")
                continue
            spec_type = spec.get("type")
            if spec_type == "array":
                items = resolve(spec.get("items"))
                if "enum" in items:
                    allowed = ", ".join(str(v) for v in items["enum"])
                    lines.append(f"- `{path}[]` 只能取：{allowed}")
                elif items.get("properties"):
                    walk(items["properties"], f"{path}[].", depth + 1)
            elif spec.get("properties"):
                bounds = _uniform_integer_range(spec["properties"])
                if bounds:
                    lines.append(
                        f"- `{path}` 下每个维度都必须是 {bounds[0]}–{bounds[1]} 的整数"
                    )
                else:
                    walk(spec["properties"], f"{path}.", depth + 1)

    walk(schema.get("properties"))
    return "\n".join(lines[:max_lines])


def build_prompt(
    request: StageRequest,
    project_dir: Path,
    skill_names: list[str],
    schema: dict[str, Any],
    *,
    max_artifact_chars: int = 4000,
    skill_max_chars: int = 80_000,
) -> str:
    """Compose the self-contained brief handed to the agent."""
    state, context_blocks = _read_project_context(project_dir, max_artifact_chars)

    parts: list[str] = []
    parts.append(
        f"你是 indie-autopilot 流水线在 `{request.stage}` 阶段的执行者。\n"
        f"项目 ID：{request.project_id}\n"
        f"当前状态机阶段：{state.get('stage', 'unknown')}\n"
    )

    if skill_names:
        parts.append("\n# 必须遵循的专业方法论\n")
        parts.append(
            "以下是本项目内置的专业 skill 指令（含其 references 与 assets 附件）。"
            "它们是硬约束，不是参考建议；其中的“铁律”部分必须严格遵守。\n"
        )
        for name in skill_names:
            try:
                text = load_skill_bundle(name, max_chars=skill_max_chars)
            except BackendError as exc:
                parts.append(f"\n## skill: {name}\n(无法加载：{exc})\n")
                continue
            parts.append(f"\n---\n\n## skill: {name}\n\n{text}\n")

    parts.append("\n# 项目现状\n")
    if context_blocks:
        parts.append("已有产物内容如下（可能被截断）：\n")
        for label, text in context_blocks:
            parts.append(f"\n## 产物：{label}\n\n```json\n{text}\n```\n")
    else:
        parts.append("这是该项目的第一个阶段，暂无已有产物。\n")

    parts.append(f"\n# 你的任务\n\n{request.task_description}\n")

    if request.code_dir:
        parts.append(
            "\n# 必须真的写出代码（本阶段的产物是文件，不是描述）\n\n"
            f"请把真实代码写到这个绝对路径：`{request.code_dir}`\n\n"
            "硬性要求：\n"
            "- **必须实际创建文件**，用你的文件写入能力落盘；只在回复里贴代码不算完成\n"
            "- 该目录是产品源码目录，不是临时目录\n"
            "- 不要在代码目录里放 result JSON、任务书或临时笔记\n"
            "- 严格按上面的 plan 产物实现 MVP 的最小可用范围，不要自由发挥加功能\n"
            "- **能跑起来优先于功能多**：先保证一个最小闭环可运行\n"
            "- 遵守上面 security-privacy-review 的约束（最小权限、不硬编码密钥）\n"
            "- 如果当前环境不允许写文件，**明确说明失败**，不要假装完成——"
            "流水线会检查这个目录，空的会被判为失败\n"
        )

    parts.append(
        "\n# 输出要求（务必严格遵守）\n\n"
        "只输出**一个 JSON 对象**，不要输出任何解释、前言、结语或 markdown 代码块标记。\n"
        "该 JSON 必须满足下面的 JSON Schema：\n\n"
        "```json\n" + json.dumps(schema, indent=2, ensure_ascii=False) + "\n```\n"
    )

    constraints = _describe_schema_constraints(schema)
    if constraints:
        parts.append(
            "\n## 字段约束速查（**必须逐条核对**）\n\n"
            "下列字段的取值有硬性限制。写错任何一个，整份结果都会被判为无效，"
            "在 handoff 模式下这意味着你要把整个任务重跑一遍：\n\n"
            f"{constraints}\n"
        )

    parts.append(
        "\n## 硬性要求\n\n"
        f"- `project_id` 必须是 {request.project_id!r}\n"
        f"- `stage` 必须是 {request.stage!r}\n"
        "- `status` 必须是 success / partial / failed 之一\n"
        "- `generated_at` 用 ISO 8601 UTC 时间\n"
        "- `summary` 用中文，说清楚这次做了什么、结论是什么\n"
        "- **不要编造任何用户反馈、搜索量、竞品数据或收入数字。**"
        "拿不到真实数据就如实标注为 unavailable，并在 `assumptions` 中说明。\n"
    )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class SkillAgentAdapter(AgentAdapter):
    """Runs the configured skills for a stage through a pluggable backend.

    Backend selection order:

    1. ``backend`` constructor argument
    2. ``AUTOPILOT_BACKEND`` environment variable
    3. ``default_backend`` in ``config/pipeline.yaml``
    4. ``handoff`` (always available, needs nothing)
    """

    def __init__(
        self,
        backend: AgentBackend | None = None,
        *,
        backend_name: str | None = None,
        config: dict[str, Any] | None = None,
        max_artifact_chars: int = 4000,
    ) -> None:
        self._config = config if config is not None else _load_pipeline_yaml()
        self._skill_map = load_skill_map(self._config)
        self._max_artifact_chars = max_artifact_chars

        if backend is not None:
            self._backend = backend
        else:
            registry = load_backends(self._config.get("backends"))
            if not registry:
                registry = {"handoff": {"class": "adapters.agent_backends.HandoffBackend"}}
            name = (
                backend_name
                or os.environ.get("AUTOPILOT_BACKEND")
                or self._config.get("default_backend")
                or "handoff"
            )
            self._backend = build_backend(name, registry)

    # -- AgentAdapter interface -------------------------------------------

    def name(self) -> str:
        return f"skill-agent:{self._backend.name}"

    def health_check(self) -> bool:
        try:
            usable, reason = self._backend.available()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Backend health check raised: %s", exc)
            return False
        if not usable:
            logger.warning("Backend '%s' unavailable: %s", self._backend.name, reason)
        return usable

    def execute(self, request: StageRequest) -> AgentResponse:
        import time

        started = time.monotonic()

        project_dir = Path(request.allowed_read_paths[0]) if request.allowed_read_paths else Path(".")
        work_dir = Path(request.work_dir) if request.work_dir else project_dir / request.stage

        schema_rel = request.expected_output_schema
        schema_path = Path(schema_rel)
        if not schema_path.is_absolute():
            schema_path = REPO_ROOT / schema_rel
        if not schema_path.is_file():
            return AgentResponse(
                status="failed",
                stage_result=None,
                raw_output="",
                errors=[{"message": f"output schema not found: {schema_path}"}],
                mode="live",
                is_real_data=False,
            )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        skill_names = self._skill_map.get(request.stage, [])
        prompt = build_prompt(
            request,
            project_dir,
            skill_names,
            schema,
            max_artifact_chars=self._max_artifact_chars,
        )

        try:
            result = self._backend.run(
                prompt,
                work_dir=work_dir,
                json_schema=schema,
                timeout_seconds=request.timeout_seconds,
            )
        except BackendError as exc:
            return AgentResponse(
                status="failed",
                stage_result=None,
                raw_output="",
                errors=[{"message": str(exc), "code": "BACKEND_ERROR"}],
                duration_seconds=round(time.monotonic() - started, 3),
                mode="live",
                is_real_data=False,
            )

        duration = result.duration_seconds or round(time.monotonic() - started, 3)

        if result.payload is None:
            return AgentResponse(
                status="failed",
                stage_result=None,
                raw_output=result.raw_output,
                errors=[{"message": result.error or "backend returned no payload", "code": "NO_PAYLOAD"}],
                duration_seconds=duration,
                mode="live",
                is_real_data=False,
            )

        payload = self._normalise_payload(result.payload, request)
        errors = validate_response(
            AgentResponse(
                status="success",
                stage_result=payload,
                raw_output=result.raw_output,
                mode="live",
                is_real_data=True,
            ),
            str(schema_path),
        )
        if errors:
            return AgentResponse(
                status="failed",
                stage_result=payload,
                raw_output=result.raw_output,
                errors=[{"message": e, "code": "SCHEMA"} for e in errors],
                duration_seconds=duration,
                mode="live",
                is_real_data=False,
            )

        return AgentResponse(
            status="success",
            stage_result=payload,
            raw_output=result.raw_output,
            duration_seconds=duration,
            mode="live",
            # The agent really ran, but only the payload can say whether every
            # data point was real; skills are instructed to mark unavailable
            # data explicitly rather than invent it.
            is_real_data=bool(payload.get("is_real_data", True)),
        )

    @staticmethod
    def _normalise_payload(payload: dict[str, Any], request: StageRequest) -> dict[str, Any]:
        """Stamp orchestrator-known facts the agent may have omitted."""
        payload = dict(payload)
        payload.setdefault("project_id", request.project_id)
        payload["project_id"] = request.project_id
        payload["stage"] = request.stage
        payload.setdefault("status", "success")
        payload.setdefault(
            "generated_at", datetime.now(timezone.utc).isoformat()
        )
        return payload
