"""Agent adapter interface for indie-autopilot.

Each adapter must implement the AgentAdapter protocol.
The adapter receives a stage request and returns a structured result.
Adapters MUST NOT:
- Modify workflow permissions or approval state
- Approve their own output
- Access production credentials
- Fabricate real data when in mock mode
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import jsonschema


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

VALID_STAGES = (
    "discovery",
    "research",
    "validation",
    "planning",
    "building",
    "testing",
    "release",
    "growth",
)


@dataclass
class StageRequest:
    """Describes a single stage execution that an adapter must fulfil."""

    project_id: str
    stage: Literal[
        "discovery",
        "research",
        "validation",
        "planning",
        "building",
        "testing",
        "release",
        "growth",
    ]
    task_description: str
    allowed_read_paths: list[str]
    expected_output_schema: str  # path to schema file
    timeout_seconds: int = 300
    #: Hint from the orchestrator: additional attempts it may make after an
    #: infrastructure failure. The orchestrator owns the retry *policy* (see
    #: `retry.max_attempts` in config/pipeline.yaml) and sets this before calling
    #: `execute`; adapters should not retry on their own, or a policy of "no
    #: retry" could still spend several paid agent calls.
    max_retries: int = 0
    #: Directory the adapter may use for scratch/handoff files. The orchestrator
    #: sets this to the stage's output directory; backends that need somewhere
    #: to write a task brief rely on it.
    work_dir: str | None = None
    #: When set, this stage is expected to produce **real files** here (not just
    #: a JSON summary). The orchestrator verifies that a live run actually wrote
    #: something, so an agent cannot report success without doing the work.
    code_dir: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in VALID_STAGES:
            raise ValueError(
                f"Invalid stage '{self.stage}'. Must be one of {VALID_STAGES}"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")


@dataclass
class AgentResponse:
    """Structured result returned by an adapter after executing a stage."""

    status: Literal["success", "partial", "failed"]
    stage_result: dict[str, Any] | None
    raw_output: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    mode: Literal["mock", "live"] = "live"
    is_real_data: bool = True


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class AgentAdapter(ABC):
    """Base class every agent adapter must implement."""

    @abstractmethod
    def execute(self, request: StageRequest) -> AgentResponse:
        """Run *request* and return the agent's response.

        Implementations should respect ``request.timeout_seconds``. Retrying is
        the orchestrator's decision, not the adapter's -- see
        ``StageRequest.max_retries``.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Return ``True`` when the adapter is ready to accept requests."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name (e.g. ``"claude-code-cli"``)."""


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def validate_response(response: AgentResponse, schema_path: str) -> list[str]:
    """Validate *response.stage_result* against the JSON Schema at *schema_path*.

    Returns a list of human-readable validation error strings.
    An empty list means the result is valid.
    """
    errors: list[str] = []

    if response.stage_result is None:
        errors.append("stage_result is None – nothing to validate")
        return errors

    path = Path(schema_path)
    if not path.exists():
        errors.append(f"Schema file not found: {schema_path}")
        return errors

    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"Schema file is not valid JSON: {exc}")
        return errors

    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(response.stage_result), key=str):
        path_str = ".".join(str(p) for p in error.absolute_path) or "<root>"
        errors.append(f"{path_str}: {error.message}")

    return errors
