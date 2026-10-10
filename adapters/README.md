# Agent Adapters

Agent adapters are the bridge between the indie-autopilot workflow engine and the AI agents that perform actual work at each pipeline stage. Every adapter implements the same interface so the workflow can swap agents without changing its logic.

## Contents

| File | Purpose |
|---|---|
| `adapter_interface.py` | Abstract `AgentAdapter` base class, `StageRequest` / `AgentResponse` dataclasses, and `validate_response()` helper |
| `mock_agent.py` | Deterministic mock adapter for testing and development |

## The Adapter Contract

Every adapter follows the same contract: **StageRequest in, AgentResponse out**.

### Input: StageRequest

```python
@dataclass
class StageRequest:
    project_id: str              # Project identifier (kebab-case)
    stage: str                   # Pipeline stage: discovery, research, validation,
                                 #   planning, building, testing, release, growth
    task_description: str        # Human-readable description of what to do
    allowed_read_paths: list[str]  # Files the adapter is permitted to read
    expected_output_schema: str  # Path to JSON Schema for output validation
    timeout_seconds: int = 300   # Maximum execution time
    max_retries: int = 2         # Retry count on transient failures
```

The `stage` field must be one of the 8 valid pipeline stages. The adapter should use this to determine which SKILL.md instructions to read and which output schema to target.

### Output: AgentResponse

```python
@dataclass
class AgentResponse:
    status: str                  # "success", "partial", or "failed"
    stage_result: dict | None    # Structured result conforming to stage-result.schema.json
    raw_output: str              # Raw output from the agent (for debugging)
    errors: list[dict]           # Error details if status != "success"
    duration_seconds: float      # How long execution took
    mode: str                    # "mock" or "live"
    is_real_data: bool           # False if any data is simulated or placeholder
```

The `stage_result` dict must validate against `schemas/stage-result.schema.json`. Required fields: `project_id`, `stage`, `status`, `generated_at`, `summary`. Optional fields: `evidence`, `assumptions`, `risks`, `artifacts`, `next_actions`, `errors`.

### The Full Flow

```
Workflow Runner
      |
      v
  StageRequest(project_id, stage, task_description, ...)
      |
      v
  Adapter.execute(request)
      |
      +--> Read SKILL.md instructions for the stage
      +--> Prepare input data from allowed_read_paths
      +--> Call AI agent with instructions + data
      +--> Parse agent output into stage_result dict
      +--> Validate stage_result against schema
      |
      v
  AgentResponse(status, stage_result, raw_output, ...)
      |
      v
  Workflow Runner validates response, updates state, creates issues
```

## How to Implement a New Adapter

### 1. Subclass AgentAdapter

```python
from adapters.adapter_interface import AgentAdapter, AgentResponse, StageRequest

class MyAdapter(AgentAdapter):
    def execute(self, request: StageRequest) -> AgentResponse:
        # 1. Read the SKILL.md instructions for this stage
        # 2. Prepare input data from allowed paths
        # 3. Call your agent (CLI, API, etc.)
        # 4. Parse its output into a stage_result dict
        # 5. Validate the result
        # 6. Return an AgentResponse
        ...

    def health_check(self) -> bool:
        # Return True when the agent is reachable and configured
        ...

    def name(self) -> str:
        return "my-adapter"
```

### 2. Respect the contract

Your adapter **MUST**:

- Accept a `StageRequest` and return an `AgentResponse`.
- Set `mode="mock"` and `is_real_data=False` when returning simulated data.
- Set `mode="live"` and `is_real_data=True` only when all data comes from real sources.
- Populate `stage_result` so it conforms to `schemas/stage-result.schema.json`.
- Respect `request.timeout_seconds` and `request.max_retries`.
- Only read files listed in `request.allowed_read_paths`.

Your adapter **MUST NOT**:

- Modify workflow permissions or approval state.
- Approve its own output.
- Access production credentials (use environment variables or a secrets manager provided by the workflow runner).
- Fabricate real data when running in mock mode.

### 3. Validate your output

Use the built-in helper before returning:

```python
from adapters.adapter_interface import validate_response

errors = validate_response(response, request.expected_output_schema)
if errors:
    response.status = "failed"
    response.errors = [{"message": e} for e in errors]
```

### 4. Register in workflow config

Add your adapter to the pipeline configuration (e.g. `config/pipeline.yaml`):

```yaml
stages:
  discovery:
    adapter: my_adapter_module.MyAdapter
    timeout_seconds: 300
    max_retries: 2
  research:
    adapter: my_adapter_module.MyAdapter
    timeout_seconds: 600
    max_retries: 1
```

The workflow runner instantiates the adapter class and calls `execute()` for each stage.

## Testing Requirements

Every adapter must be tested before deployment. The testing strategy has three layers.

### Unit Tests

Test the adapter logic in isolation:

```python
# tests/test_my_adapter.py
import pytest
from adapters.adapter_interface import StageRequest
from adapters.my_adapter import MyAdapter

def test_execute_returns_valid_result():
    adapter = MyAdapter()
    request = StageRequest(
        project_id="test-product",
        stage="discovery",
        task_description="Test discovery",
        allowed_read_paths=[],
        expected_output_schema="schemas/stage-result.schema.json",
    )
    response = adapter.execute(request)
    assert response.status == "success"
    assert response.stage_result is not None
    assert response.stage_result["project_id"] == "test-product"
    assert response.stage_result["stage"] == "discovery"

def test_health_check():
    adapter = MyAdapter()
    assert adapter.health_check() is True

def test_name():
    adapter = MyAdapter()
    assert adapter.name() == "my-adapter"
```

### Schema Validation Tests

Verify that the adapter's output always validates against the schema:

```python
def test_output_validates_against_schema():
    adapter = MyAdapter()
    request = StageRequest(...)
    response = adapter.execute(request)

    from adapters.adapter_interface import validate_response
    errors = validate_response(response, "schemas/stage-result.schema.json")
    assert errors == [], f"Validation errors: {errors}"
```

### Failure Mode Tests

Test that the adapter handles failures gracefully:

```python
def test_timeout_handling():
    adapter = MyAdapter(timeout=1)  # Very short timeout
    request = StageRequest(...)
    response = adapter.execute(request)
    assert response.status == "failed"
    assert any("timeout" in e["message"].lower() for e in response.errors)

def test_empty_input_handling():
    adapter = MyAdapter()
    request = StageRequest(
        project_id="test-product",
        stage="discovery",
        task_description="",  # Empty task
        allowed_read_paths=[],
        expected_output_schema="schemas/stage-result.schema.json",
    )
    response = adapter.execute(request)
    assert response.status in ("failed", "partial")
```

### Integration Tests

Test the adapter within the workflow context:

```bash
# Run the adapter via the mock_agent.py CLI pattern
python adapters/my_adapter.py \
    --stage discovery \
    --project-id test-product \
    --output-dir ./tmp/test/

# Validate the output
python scripts/validate_artifact.py \
    --schema schemas/stage-result.schema.json \
    --artifact ./tmp/test/mock-discovery-result.json
```

### Test Checklist

Before deploying an adapter, verify:

- [ ] `execute()` returns a valid `AgentResponse` for every stage
- [ ] `stage_result` validates against `schemas/stage-result.schema.json`
- [ ] `health_check()` returns True when the agent is ready
- [ ] `name()` returns a unique, descriptive name
- [ ] Timeout handling works correctly
- [ ] Retry logic respects `max_retries`
- [ ] Mock mode sets `is_real_data=False`
- [ ] Live mode sets `is_real_data=True` only for real data
- [ ] Path restrictions are enforced
- [ ] Error messages are descriptive and actionable

## Security Constraints

1. **No credential access.** Adapters receive tasks and return results. They never read or write production secrets. The workflow runner injects any needed credentials through environment variables scoped to the adapter process.

2. **No self-approval.** An adapter cannot mark its own output as approved. Approval is handled by a separate human-in-the-loop or automated review step in the workflow.

3. **Path restriction.** Adapters must only read files listed in `StageRequest.allowed_read_paths`. The workflow runner should enforce this at the OS level (e.g. container bind-mounts or sandbox profiles).

4. **Mock/live separation.** When `mode="mock"`, the adapter must set `is_real_data=False` and must not claim data came from real sources. This prevents mock data from leaking into production decisions.

5. **Schema conformance.** Every `stage_result` must validate against `schemas/stage-result.schema.json`. The `validate_response()` helper enforces this. Results that fail validation should be returned with `status="failed"` and descriptive errors.

## Example Adapters

### Claude Code CLI adapter (conceptual)

```python
class ClaudeCodeAdapter(AgentAdapter):
    """Runs claude-code CLI as a subprocess."""

    def execute(self, request: StageRequest) -> AgentResponse:
        import subprocess, time
        start = time.monotonic()
        proc = subprocess.run(
            ["claude", "--print", request.task_description],
            capture_output=True, text=True,
            timeout=request.timeout_seconds,
        )
        duration = time.monotonic() - start
        # Parse proc.stdout into stage_result ...
        return AgentResponse(
            status="success",
            stage_result={...},
            raw_output=proc.stdout,
            duration_seconds=duration,
            mode="live",
            is_real_data=True,
        )

    def health_check(self) -> bool:
        import shutil
        return shutil.which("claude") is not None

    def name(self) -> str:
        return "claude-code-cli"
```

### Codex CLI adapter (conceptual)

```python
class CodexAdapter(AgentAdapter):
    """Runs OpenAI Codex CLI as a subprocess."""

    def execute(self, request: StageRequest) -> AgentResponse:
        ...

    def health_check(self) -> bool:
        ...

    def name(self) -> str:
        return "codex-cli"
```

### Custom API adapter (conceptual)

```python
class CustomAPIAdapter(AgentAdapter):
    """Calls a remote agent API (e.g. OpenAI Assistants, Anthropic Messages)."""

    def execute(self, request: StageRequest) -> AgentResponse:
        import httpx
        resp = httpx.post(
            self._endpoint,
            json={"task": request.task_description, "stage": request.stage},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=request.timeout_seconds,
        )
        ...

    def health_check(self) -> bool:
        ...

    def name(self) -> str:
        return "custom-api"
```

## Using the Mock Agent

The mock agent is useful for testing pipeline wiring without spending API credits:

```bash
# Normal mock run
python adapters/mock_agent.py \
    --stage discovery \
    --project-id example-product \
    --output-dir ./projects/example-product/research/

# Test invalid-schema error handling
python adapters/mock_agent.py \
    --stage discovery \
    --project-id example-product \
    --output-dir ./tmp \
    --failure-mode invalid_schema

# Test timeout handling
python adapters/mock_agent.py \
    --stage research \
    --project-id example-product \
    --output-dir ./tmp \
    --failure-mode timeout

# Test empty-result handling
python adapters/mock_agent.py \
    --stage planning \
    --project-id example-product \
    --output-dir ./tmp \
    --failure-mode empty
```

The mock agent supports all 8 pipeline stages: discovery, research, validation, planning, building, testing, release, growth. Each stage returns deterministic, clearly-labeled mock data with `mode: "mock"` and `is_real_data: false`.

## Adapter-to-Skill Mapping

Each adapter may call one or more skills from `indie-builder-skills/`. The mapping:

| Adapter | Skills Called |
|---|---|
| Discovery | `indie-product-radar`, `emerging-keyword-radar` |
| Research | `product-validation`, `competitor-intelligence`, `seo-opportunity-research` |
| Validation | `product-validation` (deep validation) |
| Planning | `product-positioning`, `mvp-scope-planner`, `product-requirements`, `product-ux-conversion` |
| Build | `indie-tech-architecture`, `ai-coding-workflow`, `security-privacy-review` |
| Testing | `launch-readiness-qa`, `deployment-operations` |
| Release | `deployment-operations`, `launch-campaign-planner` |
| Growth | `indie-product-reach`, `content-marketing-engine`, `distribution-channel-research`, `google-indexing-diagnostics`, `product-analytics`, `conversion-optimization`, `pricing-monetization`, `customer-feedback-loop` |
| Maintain | `product-lifecycle-manager`, `project-retrospective`, `saas-cost-monitor`, `technical-debt-manager`, `indie-builder-memory`, `support-knowledge-base`, `indie-workflow-automation`, `skills-quality-auditor` |

See `docs/skills-integration.md` for the full integration map with status, input/output, and integration methods for each skill.
