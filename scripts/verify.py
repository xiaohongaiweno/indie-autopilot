#!/usr/bin/env python3
"""Run a project's own tests, so "it passed" is a fact rather than a claim.

The `testing` stage used to ask an agent for a QA verdict. An agent can be
confident and wrong, and there was nothing checking the code it was judging. So
verification runs *before* the agent: if the product's own tests are red, the
pipeline stops there and never reaches the code-review gate.

Design notes
------------
* **Detection is explicit, never magic.** A project's test command comes from
  what the project declares (a `package.json` script, pytest config, a Makefile
  target). If nothing is declared, that is reported as `not_configured` -- not
  silently treated as a pass.
* **The npm placeholder is not a test.** `npm init` writes
  ``echo "Error: no test specified" && exit 1``, which would otherwise read as a
  failing suite on a project that simply has no tests.
* **Everything is injectable.** The command runner is a parameter, so all of
  this is testable without node, npm, or a real project.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
for _p in (str(_HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)

PIPELINE_CONFIG = REPO_ROOT / "config" / "pipeline.yaml"

DEFAULT_TIMEOUT_SECONDS = 600
OUTPUT_TAIL_CHARS = 8000

#: `npm init`'s placeholder test script. Not a real suite.
NPM_PLACEHOLDER = "no test specified"

#: Python project markers that imply a pytest suite.
PYTHON_TEST_MARKERS = (
    "pytest.ini",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "tests",
    "test",
)


class VerifyError(Exception):
    """Raised for user-facing verification failures."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_verify_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the ``verify:`` block of pipeline.yaml."""
    if config is None:
        config = {}
        if PIPELINE_CONFIG.is_file():
            try:
                import yaml

                config = yaml.safe_load(PIPELINE_CONFIG.read_text(encoding="utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read %s: %s", PIPELINE_CONFIG, exc)
                config = {}
    block = dict(config.get("verify") or {})
    block.setdefault("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    # Installing a generated project's dependencies is what you would do by
    # hand anyway, and without it tests cannot run at all. Announced, bounded,
    # and switchable off.
    block.setdefault("install_dependencies", True)
    # Missing tests are reported, not fatal, unless you ask for strictness.
    block.setdefault("require_tests", False)
    return block


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclass
class DetectedCommand:
    argv: list[str]
    source: str
    install: list[str] | None = None
    notes: str = ""


@dataclass
class VerifyResult:
    status: str  # passed | failed | timeout | not_configured | no_code | dependencies_missing | error
    code_dir: str
    command: list[str] | None = None
    source: str | None = None
    exit_code: int | None = None
    duration_seconds: float = 0.0
    output_tail: str = ""
    install_command: list[str] | None = None
    notes: str = ""
    is_real_data: bool = False

    @property
    def ok(self) -> bool:
        return self.status in ("passed", "no_code", "not_configured")


def _read_package_json(code_dir: Path) -> dict[str, Any] | None:
    path = code_dir / "package.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _package_manager(code_dir: Path) -> tuple[str, list[str] | None]:
    """Pick the runner the project's lockfile implies."""
    if (code_dir / "pnpm-lock.yaml").is_file():
        return "pnpm", ["pnpm", "install"]
    if (code_dir / "yarn.lock").is_file():
        return "yarn", ["yarn", "install"]
    if (code_dir / "bun.lockb").is_file() or (code_dir / "bun.lock").is_file():
        return "bun", ["bun", "install"]
    return "npm", ["npm", "install"]


def detect_command(code_dir: Path | str) -> DetectedCommand | None:
    """What command verifies this project, or ``None`` if it declares nothing."""
    code_dir = Path(code_dir)
    if not code_dir.is_dir():
        return None

    # --- Node ---------------------------------------------------------------
    package = _read_package_json(code_dir)
    if package is not None:
        script = (package.get("scripts") or {}).get("test")
        if isinstance(script, str) and script.strip():
            if NPM_PLACEHOLDER in script:
                # A placeholder that always exits 1 is the absence of tests.
                pass
            else:
                runner, install = _package_manager(code_dir)
                argv = [runner, "test"]
                if runner == "npm":
                    argv = ["npm", "test", "--silent"]
                return DetectedCommand(
                    argv=argv,
                    source=f"package.json (scripts.test via {runner})",
                    install=install,
                )

    # --- Python -------------------------------------------------------------
    for marker in PYTHON_TEST_MARKERS:
        if (code_dir / marker).exists():
            has_tests = (code_dir / "tests").is_dir() or (code_dir / "test").is_dir()
            globbed = list(code_dir.glob("test_*.py")) + list(code_dir.glob("*_test.py"))
            if has_tests or globbed or marker in ("pytest.ini", "tox.ini"):
                return DetectedCommand(
                    argv=[sys.executable, "-m", "pytest", "-q"],
                    source=f"Python project ({marker})",
                    install=None,
                )
            break

    # --- Makefile -----------------------------------------------------------
    makefile = code_dir / "Makefile"
    if makefile.is_file():
        try:
            text = makefile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if re.search(r"^test\s*:", text, re.MULTILINE):
            return DetectedCommand(argv=["make", "test"], source="Makefile (test target)")

    return None


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

#: ``runner(argv, cwd, timeout) -> (exit_code, combined_output)``
Runner = Callable[[list[str], Path, int], tuple[int, str]]


def _default_runner(argv: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _tail(text: str, limit: int = OUTPUT_TAIL_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else "...(截断)...\n" + text[-limit:]


def inspect_code_dir(code_dir: Path | str) -> tuple[bool, int]:
    """``(has_code, file_count)`` -- delegates to the orchestrator's rules."""
    from orchestrator import inspect_code_dir as _inspect

    report = _inspect(Path(code_dir))
    return bool(report["file_count"]), int(report["file_count"])


def run_verification(
    project_dir: Path | str,
    *,
    code_dir: Path | str,
    config: dict[str, Any] | None = None,
    runner: Runner | None = None,
    timeout_seconds: int | None = None,
) -> VerifyResult:
    """Run the project's tests. Never raises for a red suite -- inspect `.status`."""
    project_dir = Path(project_dir)
    code_dir = Path(code_dir)
    cfg = load_verify_config(config)
    timeout = int(timeout_seconds or cfg["timeout_seconds"])
    run = runner or _default_runner

    has_code, file_count = inspect_code_dir(code_dir)
    if not has_code:
        return VerifyResult(
            status="no_code",
            code_dir=str(code_dir),
            notes=(
                f"{code_dir} 里没有代码（{file_count} 个文件），无可验证的对象。"
                "mock 构建不会产出代码，所以这是预期情况。"
            ),
        )

    detected = detect_command(code_dir)
    if detected is None:
        return VerifyResult(
            status="not_configured",
            code_dir=str(code_dir),
            notes=(
                "项目没有声明测试命令（没有 package.json 的 scripts.test、"
                "没有 pytest 配置、没有 Makefile 的 test 目标）。"
                "流水线不会凭空造测试：这一项如实标为「未验证」。"
            ),
            is_real_data=True,
        )

    install_output = ""
    if detected.install and cfg.get("install_dependencies"):
        missing = _dependencies_missing(code_dir)
        if missing:
            print(f"   依赖未安装，先执行：{' '.join(detected.install)}（可用 verify.install_dependencies 关闭）")
            try:
                code, install_output = run(detected.install, code_dir, timeout)
            except subprocess.TimeoutExpired:
                return VerifyResult(
                    status="dependencies_missing",
                    code_dir=str(code_dir),
                    command=detected.argv,
                    source=detected.source,
                    install_command=detected.install,
                    notes=f"安装依赖超时（{' '.join(detected.install)}）",
                )
            except OSError as exc:
                return VerifyResult(
                    status="dependencies_missing",
                    code_dir=str(code_dir),
                    command=detected.argv,
                    source=detected.source,
                    install_command=detected.install,
                    notes=f"无法安装依赖：{exc}",
                )
            if code != 0:
                return VerifyResult(
                    status="dependencies_missing",
                    code_dir=str(code_dir),
                    command=detected.argv,
                    source=detected.source,
                    install_command=detected.install,
                    output_tail=_tail(install_output),
                    notes=f"依赖安装失败，退出码 {code}",
                )
        elif missing is None:
            # Could not tell; let the test run reveal it.
            pass

    started = time.monotonic()
    try:
        exit_code, output = run(detected.argv, code_dir, timeout)
    except subprocess.TimeoutExpired:
        return VerifyResult(
            status="timeout",
            code_dir=str(code_dir),
            command=detected.argv,
            source=detected.source,
            duration_seconds=round(time.monotonic() - started, 3),
            notes=f"测试超时（{timeout}s）",
            is_real_data=True,
        )
    except FileNotFoundError as exc:
        return VerifyResult(
            status="error",
            code_dir=str(code_dir),
            command=detected.argv,
            source=detected.source,
            notes=f"找不到命令 {detected.argv[0]}：{exc}",
        )
    except OSError as exc:
        return VerifyResult(
            status="error",
            code_dir=str(code_dir),
            command=detected.argv,
            source=detected.source,
            notes=f"无法执行测试命令：{exc}",
        )

    duration = round(time.monotonic() - started, 3)
    return VerifyResult(
        status="passed" if exit_code == 0 else "failed",
        code_dir=str(code_dir),
        command=detected.argv,
        source=detected.source,
        exit_code=exit_code,
        duration_seconds=duration,
        output_tail=_tail((install_output + "\n" if install_output else "") + output),
        install_command=detected.install,
        is_real_data=True,
    )


def _dependencies_missing(code_dir: Path) -> bool | None:
    """Whether Node dependencies look uninstalled. ``None`` when not applicable."""
    package = _read_package_json(code_dir)
    if package is None:
        return None
    return not (code_dir / "node_modules").is_dir()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def to_artifact(result: VerifyResult) -> dict[str, Any]:
    """The JSON stored on disk and shown to the agent."""
    return {
        "status": result.status,
        "code_dir": result.code_dir,
        "command": result.command,
        "detected_from": result.source,
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "output_tail": result.output_tail,
        "install_command": result.install_command,
        "notes": result.notes,
        "verified_at": utc_now(),
        "is_real_data": result.is_real_data,
    }


def describe(result: VerifyResult) -> str:
    marks = {
        "passed": "✅",
        "failed": "❌",
        "timeout": "⏱",
        "not_configured": "⚠️ ",
        "no_code": "⏸",
        "dependencies_missing": "📦",
        "error": "❌",
    }
    lines = [f"{marks.get(result.status, '?')} 验证结果: {result.status}"]
    if result.command:
        lines.append(f"   命令: {' '.join(result.command)}")
    if result.source:
        lines.append(f"   来源: {result.source}")
    if result.exit_code is not None:
        lines.append(f"   退出码: {result.exit_code}   用时: {result.duration_seconds}s")
    if result.notes:
        lines.append(f"   {result.notes}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(description="Run a project's tests.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--code-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    code_dir = args.code_dir or str(Path(args.project_dir) / "app")

    if args.dry_run:
        detected = detect_command(Path(code_dir))
        if detected is None:
            print(f"没有检测到测试命令（{code_dir}）")
            return 1
        print(" ".join(detected.argv), f"  <- {detected.source}")
        return 0

    result = run_verification(args.project_dir, code_dir=code_dir)
    print(describe(result))
    if result.output_tail:
        print("\n" + result.output_tail)
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
