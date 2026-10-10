"""Mock agent adapter for indie-autopilot.

Returns deterministic, clearly-labeled mock results for every pipeline stage.
Useful for testing, development, and CI without consuming real API credits.

Usage::

    python mock_agent.py --stage discovery --project-id example-product \\
        --output-dir ./projects/example-product/research/

    # Test error handling:
    python mock_agent.py --stage discovery --project-id example-product \\
        --output-dir ./tmp --failure-mode invalid_schema
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as a script from the project root
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.adapter_interface import (
    AgentAdapter,
    AgentResponse,
    StageRequest,
    validate_response,
)

# ---------------------------------------------------------------------------
# Per-stage mock data generators
# ---------------------------------------------------------------------------

_STAGE_SUMMARIES: dict[str, str] = {
    "discovery": (
        "[MOCK] Simulated discovery for '{project_id}'. "
        "Identified 3 potential problem areas and 2 target customer segments. "
        "No real market research was performed."
    ),
    "research": (
        "[MOCK] Simulated research for '{project_id}'. "
        "Found 5 competitor products and 3 adjacent solutions. "
        "All data points are fabricated placeholders."
    ),
    "validation": (
        "[MOCK] Simulated validation for '{project_id}'. "
        "Hypothesis validation used synthetic data only. "
        "No real user interviews or surveys were conducted."
    ),
    "planning": (
        "[MOCK] Simulated planning for '{project_id}'. "
        "Generated a 4-week build plan with 3 milestones. "
        "Timelines and effort estimates are placeholder values."
    ),
    "building": (
        "[MOCK] Simulated build output for '{project_id}'. "
        "Described a minimal implementation plan with 2 core modules. "
        "No code was actually written."
    ),
    "testing": (
        "[MOCK] Simulated test results for '{project_id}'. "
        "All test cases passed in this synthetic run. "
        "No real tests were executed."
    ),
    "release": (
        "[MOCK] Simulated release checklist for '{project_id}'. "
        "Pre-release steps are placeholder recommendations. "
        "Nothing was actually deployed."
    ),
    "growth": (
        "[MOCK] Simulated growth strategy for '{project_id}'. "
        "Suggested 3 acquisition channels and 2 retention tactics. "
        "All metrics are fictional."
    ),
}


def _base_result(project_id: str, stage: str) -> dict[str, Any]:
    """Return the common skeleton shared by every stage result."""
    return {
        "project_id": project_id,
        "stage": stage,
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": _STAGE_SUMMARIES[stage].format(project_id=project_id),
        "mode": "mock",
        "is_real_data": False,
    }


def _discovery_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "discovery")
    result["evidence"] = [
        {
            "source_type": "simulated",
            "claim": "Small-business owners spend 6+ hours/week on manual scheduling",
            "evidence_type": "assumption",
            "confidence": "unavailable",
            "notes": "Simulated – no real survey conducted",
        },
        {
            "source_type": "simulated",
            "claim": "Existing tools charge $20-50/month for basic features",
            "evidence_type": "assumption",
            "confidence": "unavailable",
            "notes": "Simulated – no real pricing research performed",
        },
    ]
    result["assumptions"] = [
        {
            "statement": "Target users have basic technical literacy",
            "risk_if_wrong": "Product may need more onboarding support",
            "how_to_verify": "Conduct 10 user interviews with target segment",
        },
    ]
    result["risks"] = [
        {
            "description": "Market may be saturated with established players",
            "severity": "high",
            "mitigation": "Differentiate on simplicity and price",
        },
    ]
    result["artifacts"] = [
        {"name": "discovery-summary", "path": "research/mock-discovery-result.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Conduct competitor analysis on top 5 alternatives", "priority": "high"},
        {"action": "Define target customer persona", "priority": "high"},
        {"action": "Draft problem-solution fit hypothesis", "priority": "medium"},
    ]
    return result


def _research_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "research")
    result["evidence"] = [
        {
            "source_type": "simulated",
            "claim": "Competitor A has 10k monthly active users",
            "evidence_type": "assumption",
            "confidence": "unavailable",
            "notes": "Simulated traffic estimate",
        },
        {
            "source_type": "simulated",
            "claim": "Competitor B raised $2M seed round",
            "evidence_type": "assumption",
            "confidence": "unavailable",
            "notes": "Simulated funding data",
        },
    ]
    result["artifacts"] = [
        {"name": "competitor-matrix", "path": "research/mock-competitor-matrix.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Deep-dive into competitor B feature set", "priority": "high"},
        {"action": "Identify underserved niches from review analysis", "priority": "medium"},
    ]
    return result


def _validation_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "validation")
    result["evidence"] = [
        {
            "source_type": "simulated",
            "claim": "70% of surveyed users expressed interest in the proposed solution",
            "evidence_type": "assumption",
            "confidence": "unavailable",
            "notes": "Simulated survey – no real users surveyed",
        },
    ]
    result["assumptions"] = [
        {
            "statement": "Users will pay $9/month for this product",
            "risk_if_wrong": "Revenue projections would need significant revision",
            "how_to_verify": "Run a landing-page test with pricing tiers",
        },
    ]
    result["risks"] = [
        {
            "description": "Simulated validation may overestimate real demand",
            "severity": "medium",
            "mitigation": "Follow up with real user interviews before building",
        },
    ]
    result["artifacts"] = [
        {"name": "validation-report", "path": "research/mock-validation-report.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Design and run a real landing-page smoke test", "priority": "high"},
        {"action": "Validate willingness-to-pay with 5 target users", "priority": "high"},
    ]
    return result


def _planning_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "planning")
    result["artifacts"] = [
        {"name": "build-plan", "path": "planning/mock-build-plan.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Set up project repository and CI pipeline", "priority": "high"},
        {"action": "Implement core data model (Week 1)", "priority": "high"},
        {"action": "Build MVP feature set (Weeks 2-3)", "priority": "medium"},
    ]
    return result


def _building_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "building")
    result["artifacts"] = [
        {"name": "implementation-notes", "path": "build/mock-implementation-notes.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Write unit tests for core modules", "priority": "high"},
        {"action": "Set up integration test harness", "priority": "medium"},
    ]
    return result


def _testing_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "testing")
    result["evidence"] = [
        {
            "source_type": "simulated",
            "claim": "All 12 simulated test cases passed",
            "evidence_type": "assumption",
            "confidence": "unavailable",
            "notes": "No real tests were executed",
        },
    ]
    result["artifacts"] = [
        {"name": "test-report", "path": "testing/mock-test-report.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Run real integration test suite", "priority": "high"},
        {"action": "Perform manual QA on critical paths", "priority": "medium"},
    ]
    return result


def _release_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "release")
    result["risks"] = [
        {
            "description": "Deployment pipeline has not been tested with real credentials",
            "severity": "high",
            "mitigation": "Run a staging deployment before production release",
        },
    ]
    result["artifacts"] = [
        {"name": "release-checklist", "path": "release/mock-release-checklist.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Configure production environment variables", "priority": "high"},
        {"action": "Run staging deployment smoke test", "priority": "high"},
        {"action": "Prepare rollback plan", "priority": "medium"},
    ]
    return result


def _growth_result(project_id: str) -> dict[str, Any]:
    result = _base_result(project_id, "growth")
    result["evidence"] = [
        {
            "source_type": "simulated",
            "claim": "Content marketing could drive 500 monthly organic visits within 3 months",
            "evidence_type": "assumption",
            "confidence": "unavailable",
            "notes": "Simulated growth projection",
        },
    ]
    result["artifacts"] = [
        {"name": "growth-strategy", "path": "growth/mock-growth-strategy.json", "type": "json"},
    ]
    result["next_actions"] = [
        {"action": "Set up analytics tracking for key metrics", "priority": "high"},
        {"action": "Publish first 3 SEO-optimized blog posts", "priority": "medium"},
        {"action": "Launch on 2 indie-hacker communities", "priority": "medium"},
    ]
    return result


_GENERATORS = {
    "discovery": _discovery_result,
    "research": _research_result,
    "validation": _validation_result,
    "planning": _planning_result,
    "building": _building_result,
    "testing": _testing_result,
    "release": _release_result,
    "growth": _growth_result,
}


# ---------------------------------------------------------------------------
# Failure modes (for testing error-handling paths)
# ---------------------------------------------------------------------------


def _invalid_schema_result(project_id: str, stage: str) -> dict[str, Any]:
    """Return a result that is *missing* required schema fields."""
    return {
        "project_id": project_id,
        # missing: stage, status, generated_at, summary
        "mode": "mock",
        "is_real_data": False,
        "_note": "Intentionally invalid – missing required fields for testing",
    }


# ---------------------------------------------------------------------------
# MockAgent
# ---------------------------------------------------------------------------


class MockAgent(AgentAdapter):
    """Deterministic mock adapter that returns fake results for every stage.

    Parameters
    ----------
    failure_mode : str | None
        * ``None`` – normal operation.
        * ``"invalid_schema"`` – return a result missing required fields.
        * ``"timeout"`` – raise :class:`TimeoutError`.
        * ``"empty"`` – return ``stage_result=None``.
    """

    def __init__(self, failure_mode: str | None = None) -> None:
        self._failure_mode = failure_mode

    # -- AgentAdapter interface ---------------------------------------------

    def execute(self, request: StageRequest) -> AgentResponse:
        start = time.monotonic()

        # --- failure modes -------------------------------------------------
        if self._failure_mode == "timeout":
            raise TimeoutError(
                f"[MOCK] Simulated timeout after {request.timeout_seconds}s"
            )

        if self._failure_mode == "empty":
            duration = round(random.uniform(0.1, 0.5), 3)
            return AgentResponse(
                status="failed",
                stage_result=None,
                raw_output="[MOCK] Empty result – failure_mode='empty'",
                errors=[{"message": "stage_result is empty", "code": "EMPTY_RESULT"}],
                duration_seconds=duration,
                mode="mock",
                is_real_data=False,
            )

        if self._failure_mode == "invalid_schema":
            duration = round(random.uniform(0.1, 0.5), 3)
            bad_result = _invalid_schema_result(request.project_id, request.stage)
            return AgentResponse(
                status="failed",
                stage_result=bad_result,
                raw_output="[MOCK] Invalid-schema result – failure_mode='invalid_schema'",
                errors=[{"message": "Result intentionally missing required fields", "code": "INVALID_SCHEMA"}],
                duration_seconds=duration,
                mode="mock",
                is_real_data=False,
            )

        # --- normal path ---------------------------------------------------
        generator = _GENERATORS[request.stage]
        stage_result = generator(request.project_id)
        duration = round(random.uniform(0.1, 0.5), 3)

        return AgentResponse(
            status="success",
            stage_result=stage_result,
            raw_output=f"[MOCK] Generated {request.stage} result for {request.project_id}",
            duration_seconds=duration,
            mode="mock",
            is_real_data=False,
        )

    def health_check(self) -> bool:
        return True

    def name(self) -> str:
        return "mock-agent"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mock agent adapter for indie-autopilot",
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=list(_GENERATORS.keys()),
        help="Pipeline stage to simulate",
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="Project identifier",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write the result JSON file",
    )
    parser.add_argument(
        "--failure-mode",
        choices=["invalid_schema", "timeout", "empty"],
        default=None,
        help="Trigger a specific failure mode for testing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    agent = MockAgent(failure_mode=args.failure_mode)

    request = StageRequest(
        project_id=args.project_id,
        stage=args.stage,
        task_description=f"Mock execution of {args.stage} for {args.project_id}",
        allowed_read_paths=[],
        expected_output_schema="schemas/stage-result.schema.json",
    )

    try:
        response = agent.execute(request)
    except TimeoutError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Validate
    schema_path = Path(request.expected_output_schema)
    if schema_path.exists():
        validation_errors = validate_response(response, str(schema_path))
        if validation_errors:
            print("[WARN] Validation errors:", file=sys.stderr)
            for err in validation_errors:
                print(f"  - {err}", file=sys.stderr)

    # Write output
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"mock-{args.stage}-result.json"

    # Write stage result (schema-conformant) to main output
    output_file.write_text(
        json.dumps(response.stage_result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Result written to {output_file}")

    # Write full response metadata alongside for debugging
    meta_file = output_dir / f"mock-{args.stage}-meta.json"
    meta_payload = {
        "response": {
            "status": response.status,
            "raw_output": response.raw_output,
            "errors": response.errors,
            "duration_seconds": response.duration_seconds,
            "mode": response.mode,
            "is_real_data": response.is_real_data,
        },
    }
    meta_file.write_text(
        json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
