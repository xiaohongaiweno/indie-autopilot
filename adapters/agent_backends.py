"""Agent backends: how a stage prompt actually gets executed.

indie-autopilot deliberately does **not** hard-depend on one AI CLI. A "backend"
is any way of getting a prompt executed and a JSON object back, so the same
pipeline can run under Claude Code, Codex, CodeBuddy, DeepSeek Harness, a plain
API call, or by hand.

Two backends ship here:

``CommandBackend``
    Runs a configurable command template as a subprocess (no shell involved).
    Presets for ``claude`` / ``codex`` live in ``config/pipeline.yaml``; adding
    another agent means adding one more entry there, not writing Python.

``HandoffBackend``
    Writes a self-contained task brief and waits for a JSON result file. This is
    the zero-dependency fallback: you run the brief in whatever agent you like
    (including this one) and drop the result back. It needs no credentials and
    no CLI.

Because agent CLIs differ wildly in their output, every backend funnels through
:func:`extract_json_object`, which tolerates markdown fences, leading prose, and
CLI JSON envelopes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BackendError(Exception):
    """Raised when a backend cannot produce a usable result."""


# ---------------------------------------------------------------------------
# Tolerant JSON extraction
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` / ``` ... ``` wrappers if present."""
    fence = re.search(r"```(?:json|JSON)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _first_balanced_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block, ignoring braces in strings."""
    start = text.find("{")
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
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


_WRAPPER_KEYS = (
    "structured_output",
    "structuredOutput",
    "result",
    "output",
    "content",
    "response",
)

#: Keys that identify a dict as a stage result rather than a CLI envelope.
_PAYLOAD_KEYS = ("project_id", "summary", "stage")


def _looks_like_payload(parsed: dict[str, Any]) -> bool:
    return any(key in parsed for key in _PAYLOAD_KEYS)


def _try_parse(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from arbitrary agent output.

    Handles, in order: the raw text, fenced code blocks, CLI envelopes that wrap
    the payload under a known key (string *or* nested object), and the first
    balanced object found in surrounding prose.

    Envelopes are always unwrapped in favour of their contents -- a wrapper is
    never returned as if it were the payload. Returns ``None`` when nothing
    parseable is found.
    """
    if not text or not text.strip():
        return None

    queue: list[str] = [text.strip(), _strip_code_fences(text)]
    seen: set[str] = set()

    while queue:
        candidate = queue.pop(0)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)

        parsed = _try_parse(candidate)
        if parsed is None:
            block = _first_balanced_object(candidate)
            if block:
                parsed = _try_parse(block)
        if not isinstance(parsed, dict):
            continue

        # A genuine stage result wins outright, even if it happens to carry a
        # key that also looks like an envelope field.
        if _looks_like_payload(parsed):
            return parsed

        # Otherwise treat wrapper keys as envelopes and dig into their contents.
        queued = False
        for key in _WRAPPER_KEYS:
            inner = parsed.get(key)
            if isinstance(inner, dict):
                queue.append(json.dumps(inner, ensure_ascii=False))
                queued = True
            elif isinstance(inner, str) and inner.strip():
                queue.append(inner)
                queued = True
        if queued:
            continue

        # A dict with none of the expected keys is the best guess available.
        return parsed

    return None


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class BackendResult:
    """Outcome of one backend invocation."""

    payload: dict[str, Any] | None
    raw_output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0
    command: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.payload is not None and self.error is None


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class AgentBackend(ABC):
    """Executes a prompt and returns a JSON object."""

    #: short identifier used in config and on the CLI
    name: str = "backend"

    def __init__(self, **options: Any) -> None:
        self.options = options

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return ``(usable, human_readable_reason)``."""

    @abstractmethod
    def run(
        self,
        prompt: str,
        *,
        work_dir: Path,
        json_schema: dict[str, Any] | None = None,
        timeout_seconds: int = 1800,
    ) -> BackendResult:
        """Execute *prompt* and return the parsed JSON payload."""

    # -- shared helpers ----------------------------------------------------

    @staticmethod
    def _write_task_files(
        work_dir: Path, prompt: str, json_schema: dict[str, Any] | None
    ) -> tuple[Path, Path | None]:
        work_dir.mkdir(parents=True, exist_ok=True)
        task_file = work_dir / "task.md"
        task_file.write_text(prompt, encoding="utf-8")
        schema_file = None
        if json_schema is not None:
            schema_file = work_dir / "output.schema.json"
            schema_file.write_text(
                json.dumps(json_schema, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return task_file, schema_file

    def _result_from_files(
        self, work_dir: Path, raw_output: str, started: float
    ) -> BackendResult:
        """Read ``agent-result.json`` if the agent wrote one, else parse stdout."""
        duration = round(time.monotonic() - started, 3)
        result_file = work_dir / "agent-result.json"
        if result_file.is_file():
            text = result_file.read_text(encoding="utf-8")
            payload = extract_json_object(text)
            if payload is not None:
                return BackendResult(
                    payload=payload,
                    raw_output=raw_output or text,
                    duration_seconds=duration,
                    artifacts=[str(result_file)],
                )
            return BackendResult(
                payload=None,
                raw_output=raw_output,
                error=f"{result_file} does not contain a JSON object",
                duration_seconds=duration,
            )
        payload = extract_json_object(raw_output)
        if payload is None:
            return BackendResult(
                payload=None,
                raw_output=raw_output,
                error="no JSON object found in agent output",
                duration_seconds=duration,
            )
        return BackendResult(payload=payload, raw_output=raw_output, duration_seconds=duration)


# ---------------------------------------------------------------------------
# Command backend
# ---------------------------------------------------------------------------


class CommandBackend(AgentBackend):
    """Runs a configured command template as a subprocess.

    The template is a list of argv items; the following placeholders are
    substituted (each stays a single argv element, so there is no shell and no
    quoting or injection surface):

    ``{prompt}``       full prompt text
    ``{prompt_file}``  path to the written ``task.md``
    ``{schema}``       the JSON Schema as a string
    ``{schema_file}``  path to the written ``output.schema.json``
    ``{work_dir}``     the stage output directory
    ``{result_file}``  where the agent should write its JSON result

    Example (claude)::

        command: ["claude", "-p", "{prompt}", "--output-format", "json"]
    """

    def __init__(self, command: list[str] | str | None = None, **options: Any) -> None:
        super().__init__(**options)
        if command is None:
            raise BackendError("CommandBackend requires a 'command' template")
        if isinstance(command, str):
            command = shlex.split(command)
        if not command:
            raise BackendError("CommandBackend 'command' template is empty")
        self.command = list(command)
        self.name = options.get("name") or self.command[0]

    def available(self) -> tuple[bool, str]:
        exe = self.command[0]
        from shutil import which

        path = which(exe)
        if path:
            return True, path
        return False, f"'{exe}' not found on PATH"

    def _build_argv(
        self,
        prompt: str,
        work_dir: Path,
        json_schema: dict[str, Any] | None,
        *,
        prompt_file: Path,
        schema_file: Path | None,
    ) -> list[str]:
        mapping = {
            "prompt": prompt,
            "prompt_file": str(prompt_file),
            "schema": json.dumps(json_schema or {}, ensure_ascii=False),
            "schema_file": str(schema_file) if schema_file else "",
            "work_dir": str(work_dir),
            "result_file": str(work_dir / "agent-result.json"),
        }
        argv: list[str] = []
        for item in self.command:
            for key, value in mapping.items():
                item = item.replace("{" + key + "}", value)
            argv.append(item)
        return argv

    def run(
        self,
        prompt: str,
        *,
        work_dir: Path,
        json_schema: dict[str, Any] | None = None,
        timeout_seconds: int = 1800,
    ) -> BackendResult:
        usable, reason = self.available()
        if not usable:
            raise BackendError(f"Backend '{self.name}' unavailable: {reason}")

        work_dir = Path(work_dir)
        prompt_file, schema_file = self._write_task_files(work_dir, prompt, json_schema)
        argv = self._build_argv(
            prompt, work_dir, json_schema, prompt_file=prompt_file, schema_file=schema_file
        )

        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(work_dir),
            )
        except subprocess.TimeoutExpired:
            return BackendResult(
                payload=None,
                error=f"backend timed out after {timeout_seconds}s",
                duration_seconds=round(time.monotonic() - started, 3),
                command=argv,
            )
        except OSError as exc:
            return BackendResult(
                payload=None,
                error=f"could not run backend: {exc}",
                duration_seconds=round(time.monotonic() - started, 3),
                command=argv,
            )

        raw = proc.stdout or ""
        result = self._result_from_files(work_dir, raw, started)
        result.command = argv

        if result.payload is None:
            detail = (proc.stderr or "").strip()[:400]
            result.error = (
                f"{result.error} (exit={proc.returncode}"
                + (f", stderr={detail}" if detail else "")
                + ")"
            )
        return result


# ---------------------------------------------------------------------------
# Handoff backend
# ---------------------------------------------------------------------------


class HandoffBackend(AgentBackend):
    """Write a task brief, then wait for a JSON result to be produced.

    This is the agent-agnostic escape hatch. It requires no CLI, no
    credentials, and no network: it prepares everything an agent needs, then you
    run the brief anywhere (Claude Code, Codex, CodeBuddy, DeepSeek Harness, a
    chat window) and save the JSON reply to ``agent-result.json``.
    """

    name = "handoff"
    RESULT_NAME = "agent-result.json"

    def available(self) -> tuple[bool, str]:
        return True, "always available (manual handoff)"

    def run(
        self,
        prompt: str,
        *,
        work_dir: Path,
        json_schema: dict[str, Any] | None = None,
        timeout_seconds: int = 1800,
    ) -> BackendResult:
        work_dir = Path(work_dir)
        prompt_file, schema_file = self._write_task_files(work_dir, prompt, json_schema)
        result_file = work_dir / self.RESULT_NAME

        # Already supplied (e.g. `autopilot prepare` then the user ran it).
        if result_file.is_file():
            return self._result_from_files(work_dir, "", time.monotonic())

        lines = [
            "",
            "=" * 72,
            "需要你手动执行这一步（handoff 模式）",
            "=" * 72,
            f"任务书   : {prompt_file}",
        ]
        if schema_file:
            lines.append(f"输出要求 : {schema_file}")
        lines += [
            f"结果写到 : {result_file}",
            "",
            "做法：把 task.md 的内容交给任意一个 agent（Claude Code / Codex /",
            "CodeBuddy / DeepSeek Harness / 网页对话都行），让它只返回一个 JSON",
            "对象，然后把该 JSON 原样保存到上面那个结果文件路径。",
            "=" * 72,
        ]
        print("\n".join(lines), flush=True)

        if not sys.stdin.isatty():
            raise BackendError(
                f"handoff 模式需要交互确认，但 stdin 不是 TTY。\n"
                f"任务书已写好：{prompt_file}\n"
                f"请在任意 agent 中执行它，并把 JSON 结果保存到：{result_file}\n"
                f"然后重新运行本命令（结果文件已存在时会自动读取）。"
            )

        started = time.monotonic()
        try:
            input("完成并保存好结果文件后，按回车继续 > ")
        except (EOFError, KeyboardInterrupt) as exc:
            raise BackendError("handoff 被中断，未读取结果") from exc

        if not result_file.is_file():
            raise BackendError(
                f"未找到结果文件：{result_file}\n"
                f"请确认已把 JSON 保存到该路径。"
            )
        return self._result_from_files(work_dir, "", started)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def load_backends(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Normalise the ``backends:`` block of pipeline.yaml.

    Each entry is ``{name: {"class": "...", "options": {...}}}``. A bare
    ``class`` string is also accepted.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, spec in (raw or {}).items():
        if isinstance(spec, str):
            spec = {"class": spec}
        out[name] = {
            "class": spec.get("class"),
            "options": spec.get("options") or {},
        }
    return out


def build_backend(name: str, registry: dict[str, dict[str, Any]], **overrides: Any) -> AgentBackend:
    """Instantiate a registered backend by name."""
    spec = registry.get(name)
    if spec is None:
        known = ", ".join(sorted(registry)) or "none"
        raise BackendError(f"Unknown agent backend '{name}'. Registered: {known}")

    class_path = spec.get("class")
    if not class_path or "." not in class_path:
        raise BackendError(f"Backend '{name}' has an invalid class path: {class_path!r}")

    module_name, _, cls_name = class_path.rpartition(".")
    import importlib

    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, cls_name)
    except (ImportError, AttributeError) as exc:
        raise BackendError(f"Could not load backend '{name}' ({class_path}): {exc}") from exc

    options = {**spec.get("options", {}), **overrides}
    options.setdefault("name", name)
    return cls(**options)
