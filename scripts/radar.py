#!/usr/bin/env python3
"""Opportunity radar: the pre-project "find new needs" step.

This is step 1 of the indie developer workflow, and it happens *before* a
project exists. It runs the ``indie-product-radar`` / ``emerging-keyword-radar``
methodology through the same pluggable agent backends the pipeline uses, then
presents scored opportunities for a human decision. Only an approved opportunity
becomes a project, which then enters the normal state machine at ``discovered``.

Layout::

    radar-data/                     # the radar skill's own persistent workspace
      profile.md                    # founder constraints (asked once, then reused)
      scoreboard.json               # accumulated scoring data
      scans/<date>-report.md        # the human-facing Markdown deliverable
      failures/                     # rejected / failed directions
    radar/scans/<scan-id>/          # per-scan pipeline files
      task.md                       # the self-contained brief
      output.schema.json
      agent-result.json             # the agent's JSON reply

Scoring is never reimplemented here. ``score.py`` (shipped inside the skill) is
the authority: it validates the scoreboard, and its weights are read from the
script so they cannot silently drift.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
for _p in (str(_HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.agent_backends import (  # noqa: E402
    AgentBackend,
    BackendError,
    build_backend,
    load_backends,
)
from adapters.skill_agent import (  # noqa: E402
    _describe_schema_constraints,
    load_skill_bundle,
)

logger = logging.getLogger(__name__)

RADAR_ROOT = REPO_ROOT / "radar"
SCANS_DIR = RADAR_ROOT / "scans"
RADAR_DATA = REPO_ROOT / "radar-data"
PROFILE_PATH = RADAR_DATA / "profile.md"
PROJECTS_DIR = REPO_ROOT / "projects"
SKILLS_DIR = REPO_ROOT / "indie-builder-skills" / "skills"
RADAR_SKILL = "indie-product-radar"
SCORE_PY = SKILLS_DIR / RADAR_SKILL / "scripts" / "score.py"
SCAN_SCHEMA_REL = "schemas/radar-scan.schema.json"
SCAN_SCHEMA = REPO_ROOT / SCAN_SCHEMA_REL
DEFAULT_RADAR_SKILLS = ["indie-product-radar", "emerging-keyword-radar"]

#: score.py's own defaults, used only if its weights cannot be read.
_FALLBACK_DIMS: list[tuple[str, int]] = [
    ("demand", 18), ("trend", 13), ("pay", 18), ("gap", 13),
    ("acq", 13), ("dev", 10), ("moat", 5), ("fit", 10),
]


class RadarError(Exception):
    """Raised for any user-facing radar failure."""


# ---------------------------------------------------------------------------
# Scoring authority
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scoring_spec() -> tuple[list[tuple[str, int]], int, int]:
    """Read the rubric's weights and tier thresholds out of ``score.py``.

    ``score.py`` runs ``parse_args()`` at import time (no ``__main__`` guard), so
    it cannot be imported as a module. Reading its constants keeps it the single
    source of truth instead of duplicating the weights here.
    """
    dims = _FALLBACK_DIMS
    go, watch = 75, 60
    try:
        src = SCORE_PY.read_text(encoding="utf-8")
        # Anchor to the DIMS assignment: ``o["s"].get("fit", 0)`` elsewhere in
        # the file also looks like a ("name", number) pair.
        block = re.search(r"DIMS\s*=\s*\[(.*?)\]", src, re.DOTALL)
        if block:
            found = [
                (m.group(1), int(m.group(2)))
                for m in re.finditer(r'\("(\w+)",\s*(\d+)\)', block.group(1))
            ]
            if len(found) >= 5:
                dims = found
        m_go = re.search(r'"go"\s+if\s+s\s*>=\s*(\d+)', src)
        m_watch = re.search(r'"watch"\s+if\s+s\s*>=\s*(\d+)', src)
        if m_go:
            go = int(m_go.group(1))
        if m_watch:
            watch = int(m_watch.group(1))
    except OSError as exc:  # pragma: no cover - score.py ships with the skill
        logger.warning("Could not read %s (%s); using fallback weights", SCORE_PY, exc)
    return dims, go, watch


def score_opportunity(opp: dict[str, Any]) -> int:
    """Weighted total, matching ``score.py``'s formula."""
    import math

    dims, _, _ = _scoring_spec()
    s = opp.get("s") or {}
    total = sum(weight * s.get(key, 0) / 10 for key, weight in dims)
    return math.floor(total + 0.5)


def tier_opportunity(opp: dict[str, Any]) -> str:
    """``veto`` / ``go`` / ``watch`` / ``low``, matching ``score.py``."""
    if opp.get("veto"):
        return "veto"
    _, go, watch = _scoring_spec()
    value = score_opportunity(opp)
    if value >= go:
        return "go"
    if value >= watch:
        return "watch"
    return "low"


TIER_LABEL = {"go": "立即验证", "watch": "观察池", "low": "低分", "veto": "否决"}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

_PROFILE_TEMPLATE = """# 创始人画像（radar profile）

产品雷达每次扫描都会读这个文件，用来判断「这个机会是否适合**你**」。
不填也能跑，但 `fit`（创始人匹配度）这一维会失去意义。

## 技术栈
（例：Python + Cloudflare Workers，前端 React；不熟的：移动端原生）

## 每周可投入时间
（例：工作日晚上 + 周末，约 15 小时）

## 目标客户
（B2B 小微企业 / B2B 中大型 / B2C 消费者 / 开发者工具）三选一或写清主次

## 回避领域
（例：重度合规、需要牌照、医疗金融、需要 7x24 客服）

## 关注赛道
（例：垂直 SaaS、办公效率、开发者工具）

## 行业经验与人脉
你在哪些行业有深度经验或人脉？这直接决定获客难度。

## 可触达的受众与渠道
（例：博客 2000 订阅、X 关注 800、某行业微信群 3 个、无任何渠道）

## 其他约束
（预算上限、能否接受付费投放、是否必须做成开源等）
"""


def ensure_profile() -> tuple[Path, bool]:
    """Create a profile template if absent. Returns ``(path, created)``."""
    if PROFILE_PATH.is_file():
        return PROFILE_PATH, False
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(_PROFILE_TEMPLATE, encoding="utf-8")
    return PROFILE_PATH, True


# ---------------------------------------------------------------------------
# Scan prompt
# ---------------------------------------------------------------------------


def new_scan_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def load_radar_config() -> dict[str, Any]:
    """Read ``config/pipeline.yaml`` for radar skills and backends."""
    path = REPO_ROOT / "config" / "pipeline.yaml"
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read %s: %s", path, exc)
    skills = data.get("radar_skills") or (data.get("skills") or {}).get("discovery") or DEFAULT_RADAR_SKILLS
    return {"skills": list(skills), "backends": data.get("backends") or {}, "default_backend": data.get("default_backend") or "handoff"}


def existing_projects() -> list[tuple[str, str]]:
    """``(project_id, stage)`` for every project, to avoid re-suggesting them."""
    out: list[tuple[str, str]] = []
    projects = PROJECTS_DIR
    if not projects.is_dir():
        return out
    for path in sorted(projects.iterdir()):
        state_file = path / "state.json"
        if not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append((path.name, str(state.get("stage", "?"))))
    return out


def known_opportunity_names() -> list[str]:
    """Names already in ``radar-data/scoreboard.json`` (incremental scans)."""
    path = RADAR_DATA / "scoreboard.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return [str(o.get("name", "")) for o in data if isinstance(o, dict)]
    return []


def build_scan_prompt(
    scan_id: str,
    skills: list[str],
    *,
    schema: dict[str, Any] | None = None,
    skill_max_chars: int = 80_000,
) -> str:
    """Compose the self-contained radar brief."""
    schema = schema if schema is not None else json.loads(SCAN_SCHEMA.read_text(encoding="utf-8"))
    profile = PROFILE_PATH.read_text(encoding="utf-8") if PROFILE_PATH.is_file() else "(未配置)"

    parts: list[str] = []
    parts.append(
        "你是独立开发者的**产品雷达**，负责在正式立项前找出值得做的需求。\n"
        f"本次扫描 ID：{scan_id}\n"
        "当前日期以系统时间为准，搜索时使用真实年份。\n"
    )

    parts.append("\n# 必须遵循的专业方法论\n")
    parts.append(
        "以下是本项目内置的雷达 skill 指令（含其 references 与 assets 附件）。"
        "它们是硬约束，不是参考建议；**「铁律」部分必须严格遵守**——"
        "尤其是「不编造数据」「事实与推测分开写」「证据分级」。\n"
    )
    for name in skills:
        try:
            parts.append(f"\n---\n\n## skill: {name}\n\n{load_skill_bundle(name, max_chars=skill_max_chars)}\n")
        except BackendError as exc:
            parts.append(f"\n## skill: {name}\n(无法加载：{exc})\n")

    parts.append("\n# 创始人画像（决定 fit 维度）\n\n```markdown\n" + profile + "\n```\n")

    projects = existing_projects()
    parts.append("\n# 已经存在的项目（不要重复推荐）\n\n")
    parts.append(
        "\n".join(f"- {pid}（当前阶段：{stage}）" for pid, stage in projects) if projects
        else "（暂无。这是第一次扫描。）\n"
    )

    known = known_opportunity_names()
    if known:
        parts.append("\n# 历史已评估过的机会（只做增量更新，沿用原 id）\n\n")
        parts.append("\n".join(f"- {name}" for name in known) + "\n")

    parts.append(
        "\n# 工作区约定\n\n"
        f"- 雷达工作区：`{RADAR_DATA}`（不存在则创建）\n"
        f"  - 分数数据：`{RADAR_DATA / 'scoreboard.json'}`\n"
        f"  - 报告交付物：`{RADAR_DATA / 'scans'}/<日期>-report.md`\n"
        f"  - 淘汰记录：`{RADAR_DATA / 'failures'}/`\n"
        f"- 打分脚本：`{SCORE_PY}`\n"
        f"  用 `python3 {SCORE_PY} validate <你的 scoreboard.json>` 自查，改到 0 错误为止。\n"
        "- 若当前环境没有联网工具：**明确说明无法做真实扫描**，只整理已有材料，"
        "并把所有判断标为「推测」，不要用记忆冒充实时数据。\n"
    )

    parts.append(
        "\n# 你的任务\n\n"
        "1. 按 skill 流程做多源信号扫描，交叉验证。单一信号不算机会；"
        "至少 3 类信号同时出现才值得深挖。\n"
        "2. 按八维模型打分，写进 scoreboard.json，并用 score.py 校验通过。\n"
        "3. 产出 Markdown 报告到上面约定的路径。\n"
        "4. 另外**额外交付**一个 JSON 对象给本流水线（skill 说 JSON 不作为给用户的交付物，"
        "但这里是机器消费者，需要它来自动立项）。\n"
    )

    parts.append(
        "\n# 输出要求（务必严格遵守）\n\n"
        "只输出**一个 JSON 对象**，不要解释、不要 markdown 代码块标记。\n"
        "结构如下（`opportunities` 就是你的 scoreboard 数组，字段名必须逐字一致，"
        "因为 score.py 依赖它们）：\n\n"
        "```json\n"
        + json.dumps(
            {
                "scan_id": scan_id,
                "generated_at": "<ISO 8601 UTC>",
                "summary": "<中文摘要>",
                "report_path": "radar-data/scans/<日期>-report.md",
                "unavailable": ["<哪些数据源不可用>"],
                "opportunities": ["<scoreboard 条目数组>"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n```\n"
    )

    constraints = _describe_schema_constraints(schema)
    if constraints:
        parts.append(
            "\n## 字段约束速查（**必须逐条核对**）\n\n"
            "写错任何一个，整份结果都会被判为无效——在 handoff 模式下这意味着重跑一遍：\n\n"
            f"{constraints}\n"
        )

    parts.append(
        "\n## 硬性要求\n\n"
        "- `opportunities` 里每条必须含 id/name/pos/s/sig/veto/status/fact 全部字段\n"
        "- `s` 的八个维度都必须是 **0–10 的整数**，不能有小数、不能省略\n"
        "- `fact` 为「事实」或「部分验证」时，`links` 必须至少有 1 条 http 链接\n"
        "- 命中任一 `veto` 项的机会，`status` 最高只能是 `watch`\n"
        "- 信号类型少于 3 类时，`status` 不能是 `validating` 或 `building`\n"
        "- **绝不编造搜索量、收入、用户数、价格。** 找不到就写「未核实」或 `未估算`，"
        "并放进 `unavailable`。\n"
    )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Running a scan
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    scan_id: str
    payload: dict[str, Any]
    opportunities: list[dict[str, Any]]
    scan_dir: Path
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    ranked: list[dict[str, Any]] = field(default_factory=list)


def _find_json_array(text: str) -> list[Any] | None:
    """Find the first balanced ``[...]`` and parse it."""
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : idx + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, list) else None
    return None


def coerce_scan(payload: dict[str, Any] | None, raw: str, scan_id: str) -> dict[str, Any]:
    """Accept our envelope, a bare scoreboard array, or a single opportunity.

    The skill's native output is a bare array, so an agent that follows the skill
    literally must still be understood rather than rejected.
    """
    if isinstance(payload, dict) and isinstance(payload.get("opportunities"), list):
        payload.setdefault("scan_id", scan_id)
        payload.setdefault("generated_at", utc_now())
        payload.setdefault("summary", "")
        return payload

    if isinstance(payload, list):
        return _envelope(payload, scan_id)
    if isinstance(payload, dict) and ("name" in payload and "s" in payload):
        return _envelope([payload], scan_id)

    if raw:
        import json as _json

        try:
            parsed = _json.loads(raw)
        except (_json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            return _envelope(parsed, scan_id)
        if isinstance(parsed, dict):
            if isinstance(parsed.get("opportunities"), list):
                return coerce_scan(parsed, "", scan_id)
            # CLI envelopes may carry the array as a string or a nested list.
            for key in ("result", "output", "content", "response", "structured_output"):
                inner = parsed.get(key)
                if isinstance(inner, list):
                    return _envelope(inner, scan_id)
                if isinstance(inner, str) and inner.strip():
                    return coerce_scan(None, inner, scan_id)
        array = _find_json_array(raw)
        if array is not None:
            return _envelope(array, scan_id)

    raise RadarError(
        "雷达结果里找不到 opportunities 数组。"
        "期望一个含 opportunities 字段的 JSON 对象，或 scoreboard 数组。"
    )


def _envelope(opportunities: list[Any], scan_id: str) -> dict[str, Any]:
    return {
        "scan_id": scan_id,
        "generated_at": utc_now(),
        "summary": f"（agent 只返回了数组，共 {len(opportunities)} 条机会）",
        "opportunities": [o for o in opportunities if isinstance(o, dict)],
    }


def validate_scoreboard(opportunities: list[dict[str, Any]], work_dir: Path) -> tuple[list[str], list[str]]:
    """Validate via the skill's own ``score.py validate``. Returns (errors, warnings)."""
    if not SCORE_PY.is_file():
        return ([f"score.py 不存在：{SCORE_PY}"], [])
    board = work_dir / "scoreboard.json"
    board.write_text(json.dumps(opportunities, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(SCORE_PY), "validate", str(board)],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ([f"无法运行 score.py: {exc}"], [])

    errors, warnings = [], []
    for line in (proc.stdout or "").splitlines():
        if line.startswith("ERROR"):
            errors.append(line[5:].strip())
        elif line.startswith("WARN"):
            warnings.append(line[4:].strip())
    return errors, warnings


def run_scan(
    *,
    scan_id: str | None = None,
    backend: AgentBackend | None = None,
    config: dict[str, Any] | None = None,
    from_file: Path | None = None,
    timeout_seconds: int = 3600,
) -> ScanResult:
    """Produce a validated scan, either from a file or by running the agent."""
    config = config or load_radar_config()
    scan_id = scan_id or new_scan_id()
    scan_dir = SCANS_DIR / scan_id
    scan_dir.mkdir(parents=True, exist_ok=True)

    if from_file is not None:
        raw_text = Path(from_file).read_text(encoding="utf-8")
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise RadarError(f"{from_file} 不是合法 JSON: {exc}") from exc
        payload = coerce_scan(parsed if isinstance(parsed, dict) else None, raw_text, scan_id)
    else:
        profile_path, created = ensure_profile()
        if created:
            print(f"⚠️  已创建创始人画像模板：{profile_path}")
            print("    建议先填一下（尤其是『可触达的受众与渠道』），否则 fit 维度没有意义。\n")

        backend = backend or _build_backend(config)
        prompt = build_scan_prompt(scan_id, config["skills"])
        try:
            result = backend.run(
                prompt, work_dir=scan_dir, json_schema=None, timeout_seconds=timeout_seconds
            )
        except BackendError as exc:
            # Surface the actionable handoff instructions as a normal error
            # rather than a traceback.
            raise RadarError(str(exc)) from exc
        if result.payload is None and not result.raw_output:
            raise RadarError(f"雷达执行失败：{result.error or '没有输出'}")
        payload = coerce_scan(result.payload, result.raw_output, scan_id)

    opportunities = [o for o in (payload.get("opportunities") or []) if isinstance(o, dict)]
    errors, warnings = validate_scoreboard(opportunities, scan_dir)

    ranked = sorted(opportunities, key=score_opportunity, reverse=True)
    return ScanResult(
        scan_id=scan_id,
        payload=payload,
        opportunities=opportunities,
        scan_dir=scan_dir,
        validation_errors=errors,
        validation_warnings=warnings,
        ranked=ranked,
    )


def _build_backend(config: dict[str, Any]) -> AgentBackend:
    registry = load_backends(config.get("backends"))
    if not registry:
        registry = {"handoff": {"class": "adapters.agent_backends.HandoffBackend"}}
    import os

    name = os.environ.get("AUTOPILOT_BACKEND") or config.get("default_backend") or "handoff"
    return build_backend(name, registry)


# ---------------------------------------------------------------------------
# Presentation and selection
# ---------------------------------------------------------------------------


def describe_scan(result: ScanResult, *, max_cards: int = 5) -> str:
    lines: list[str] = []
    lines.append(f"扫描 ID  : {result.scan_id}")
    lines.append(f"工作目录 : {result.scan_dir}")
    if result.payload.get("report_path"):
        lines.append(f"报告     : {result.payload['report_path']}")
    summary = str(result.payload.get("summary") or "").strip()
    if summary:
        lines.append(f"摘要     : {summary}")

    if result.validation_errors:
        lines.append(f"\n❌ score.py 校验发现 {len(result.validation_errors)} 个错误：")
        for err in result.validation_errors[:10]:
            lines.append(f"   - {err}")
    if result.validation_warnings:
        lines.append(f"\n⚠️  {len(result.validation_warnings)} 个警告：")
        for warn in result.validation_warnings[:5]:
            lines.append(f"   - {warn}")

    if not result.ranked:
        lines.append("\n（没有解析出任何机会）")
        return "\n".join(lines)

    lines.append(f"\n共 {len(result.ranked)} 个机会，按总分排序：\n")
    for idx, opp in enumerate(result.ranked[:max_cards], start=1):
        total = score_opportunity(opp)
        tier = TIER_LABEL[tier_opportunity(opp)]
        signals = len(set(opp.get("sig") or []))
        lines.append(f"[{idx}] {opp.get('name', '?')}   {total}/100  {tier}")
        lines.append(f"     {opp.get('pos', '')}")
        if opp.get("market"):
            lines.append(f"     市场：{opp['market']}")
        if opp.get("pricing"):
            lines.append(f"     定价：{opp['pricing']}")
        lines.append(f"     证据：{opp.get('fact', '?')}   信号：{signals}/6   匹配度：{(opp.get('s') or {}).get('fit', '?')}/10")
        if opp.get("veto"):
            lines.append(f"     ⛔ 否决项：{', '.join(opp['veto'])}")
        if opp.get("exp"):
            lines.append(f"     验证实验：{opp['exp']}")
        lines.append("")
    if len(result.ranked) > max_cards:
        lines.append(f"... 另有 {len(result.ranked) - max_cards} 个机会（总分更低）")
    return "\n".join(lines)


def choose_opportunities(result: ScanResult, *, assume_yes: bool = False) -> list[dict[str, Any]]:
    """Ask which opportunities to turn into projects."""
    if not result.ranked:
        return []
    if result.validation_errors:
        raise RadarError(
            "score.py 校验未通过，拒绝基于无效数据立项。请让 agent 修正后重跑"
            "（或用 --from-file 传入修正后的结果）。"
        )

    if assume_yes:
        print(f"--yes：自动选择第 1 个（{result.ranked[0].get('name')}）")
        return [result.ranked[0]]

    if not sys.stdin.isatty():
        raise RadarError(
            "需要你选择要立项的机会，但 stdin 不是 TTY。"
            "交互运行，或用 --yes 自动选第一个，或用 --pick N 指定。"
        )

    print("\n要基于哪个机会立项？")
    print("  输入编号（可多选，逗号分隔，如 1,3）")
    print("  n = 本轮都不做，只保留报告")
    while True:
        try:
            answer = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return []
        if answer in ("n", "no", "q", ""):
            return []
        picks: list[int] = []
        ok = True
        for chunk in answer.replace("，", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if not chunk.isdigit() or not (1 <= int(chunk) <= len(result.ranked)):
                ok = False
                break
            picks.append(int(chunk))
        if ok and picks:
            return [result.ranked[i - 1] for i in sorted(set(picks))]
        print(f"  请输入 1-{len(result.ranked)} 之间的编号，或 n")


# ---------------------------------------------------------------------------
# Project creation
# ---------------------------------------------------------------------------


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value).lower())
    return re.sub(r"-+", "-", text).strip("-")


def _fit_project_id(candidate: str) -> str | None:
    """Coerce to ``^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`` or give up."""
    text = slugify(candidate)
    if len(text) > 64:
        text = text[:64].rstrip("-")
    if len(text) < 3 or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", text):
        return None
    return text


def project_id_for(opp: dict[str, Any], scan_id: str, index: int) -> str:
    projects_dir = PROJECTS_DIR
    taken = {p.name for p in projects_dir.iterdir()} if projects_dir.is_dir() else set()

    # Only non-empty bases are usable: a Chinese opportunity name slugifies to
    # "" and must not degrade into a bare "opp" prefix.
    bases = [
        slugify(opp.get("name", "")),
        slugify(opp.get("id", "")),
        f"{slugify(scan_id)}-{index}".strip("-"),
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{index}",
    ]
    for base in bases:
        if not base:
            continue
        fitted = _fit_project_id(f"opp-{base}")
        if fitted and fitted not in taken:
            return fitted
        if fitted:
            for suffix in range(2, 100):
                alt = _fit_project_id(f"{fitted}-{suffix}")
                if alt and alt not in taken:
                    return alt
    raise RadarError("无法为该机会生成合法的 project_id")


def create_project(
    opp: dict[str, Any],
    result: ScanResult,
    *,
    index: int = 1,
    actor: str | None = None,
) -> Path:
    """Create ``projects/<id>/`` at ``discovered``, seeded with the scan."""
    from adapters.skill_agent import load_skill_map  # noqa: F401  (keeps import graph explicit)

    actor = actor or _default_actor()
    project_id = project_id_for(opp, result.scan_id, index)
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        raise RadarError(f"项目已存在：{project_dir}")
    (project_dir / "radar").mkdir(parents=True, exist_ok=True)

    scan_copy = project_dir / "radar" / "scan.json"
    scan_copy.write_text(
        json.dumps(
            {**result.payload, "opportunities": [opp], "selected_from_scan": result.scan_id},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts: dict[str, Any] = {
        "opportunity_scan": {
            "path": "radar/scan.json",
            "stage": "discovered",
            "generated_at": utc_now(),
            "mode": "live",
            "is_real_data": True,
        }
    }

    report_rel = result.payload.get("report_path")
    if report_rel:
        report_src = REPO_ROOT / str(report_rel)
        if report_src.is_file():
            shutil.copy2(report_src, project_dir / "radar" / "report.md")
            artifacts["radar_report"] = {
                "path": "radar/report.md",
                "stage": "discovered",
                "generated_at": utc_now(),
                "mode": "live",
                "is_real_data": True,
            }

    now = utc_now()
    state = {
        "project_id": project_id,
        "name": str(opp.get("name") or project_id)[:120],
        "description": str(opp.get("pos") or "")[:500],
        "stage": "discovered",
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "approved_stages": [],
        "artifacts": artifacts,
        "audit_log": [
            {
                "timestamp": now,
                "action": "project_created",
                "actor": actor,
                "details": (
                    f"来自雷达扫描 {result.scan_id}，总分 {score_opportunity(opp)}/100，"
                    f"分级 {TIER_LABEL[tier_opportunity(opp)]}"
                ),
            }
        ],
    }
    (project_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return project_dir


def _default_actor() -> str:
    import getpass

    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover
        return "unknown"
