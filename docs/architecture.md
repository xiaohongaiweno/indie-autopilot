# Architecture

> **Note (local driver):** the pipeline no longer runs on GitHub Actions. The
> orchestration layer is now `autopilot.py` + `scripts/orchestrator.py`, which
> drives stages and approval gates locally. Sections below that describe
> workflow YAML files are kept for historical context; see
> [local-usage.md](local-usage.md) for the current driver. The state machine,
> schemas, and artifact rules described here are still accurate.

indie-autopilot is a state-machine pipeline that orchestrates AI skills through a local driver. This document describes the system layers, state machine, data flow, and design decisions.

## System Layers

```
+--------------------------------------------------------------------+
|  Orchestration Layer  (GitHub Actions)                             |
|  radar-weekly | validate-opportunity | plan-product | build-and-   |
|  test | release | growth-review                                    |
+--------------------------------------------------------------------+
         |
         v
+--------------------------------------------------------------------+
|  Execution Layer  (Agent Adapters)                                 |
|  AgentAdapter base class | MockAgent | ClaudeCodeAdapter | ...     |
|  Reads SKILL.md instructions, calls AI agents, returns results    |
+--------------------------------------------------------------------+
         |
         v
+--------------------------------------------------------------------+
|  Logic Layer  (Scripts)                                            |
|  state_machine.py | check_transition.py | validate_artifact.py    |
|  create_issue.py | generate_report.py | validate_environment.py   |
+--------------------------------------------------------------------+
         |
         v
+--------------------------------------------------------------------+
|  Data Layer  (Schemas & State Files)                               |
|  project.schema.json | stage-result.schema.json | approval.schema  |
|  state.json | audit/*.json | artifacts                             |
+--------------------------------------------------------------------+
```

### Data Layer

The data layer stores all persistent state as JSON files validated against JSON Schema.

**Schemas:**
- `schemas/project.schema.json` -- Project state file structure (project_id, name, stage, status, artifacts, approved_stages, audit_log)
- `schemas/stage-result.schema.json` -- Output from each pipeline stage (evidence, assumptions, risks, artifacts, next_actions)
- `schemas/approval.schema.json` -- Human approval records (approval_id, decision, artifact_hash, expires_at)

**State files:**
- `projects/<project-id>/state.json` -- Current pipeline state for a project
- `projects/<project-id>/audit/*.json` -- Individual transition audit records
- `projects/<project-id>/*/` -- Stage artifacts (research, planning, build, testing, release, growth)

**Design decisions:**
- JSON over YAML for state files because schemas enforce structure
- Each project is isolated in its own directory
- Artifacts are referenced by path and hash, not embedded in state.json
- Audit records are append-only JSON files, one per transition

### Logic Layer

The logic layer contains the core pipeline scripts.

**`scripts/state_machine.py`** -- Defines 17 states, 23 transitions, and the rules for moving between them. This is the single source of truth for what transitions are valid.

**`scripts/check_transition.py`** -- Validates whether a specific transition is allowed given the current state, required artifacts, and approval records. Writes audit records.

**`scripts/validate_artifact.py`** -- Validates JSON artifacts against their schemas. Supports strict mode that checks referenced file paths exist.

**`scripts/create_issue.py`** -- Creates GitHub Issues for approval requests and task tracking. Supports idempotency via `.issue-keys.json` marker files.

**`scripts/generate_report.py`** -- Generates Markdown status reports from project state, including artifacts, evidence, risks, next actions, and audit log.

**`scripts/validate_environment.py`** -- Checks that the runtime environment is properly configured (Python version, packages, directories, schemas, gh CLI).

### Execution Layer

The execution layer bridges the workflow engine and AI agents through adapters.

**`adapters/adapter_interface.py`** -- Defines the `AgentAdapter` abstract base class, `StageRequest` and `AgentResponse` data types, and the `validate_response()` helper.

**`adapters/mock_agent.py`** -- Deterministic mock adapter that returns labeled fake data for every stage. Useful for testing pipeline wiring without API costs.

**Adapter contract:**
- Input: `StageRequest` with project_id, stage, task_description, allowed_read_paths, expected_output_schema, timeout_seconds, max_retries
- Output: `AgentResponse` with status (success/partial/failed), stage_result dict, raw_output, errors, duration_seconds, mode (mock/live), is_real_data

**Key constraint:** Adapters read SKILL.md instruction files and execute them via AI agents. Skills are NOT directly callable from GitHub Actions -- they require an adapter that understands the skill's input/output format.

### Orchestration Layer

GitHub Actions workflows orchestrate the pipeline. Each workflow:
1. Validates the environment
2. Runs the appropriate adapter for the stage
3. Validates the output against the schema
4. Checks if the transition is allowed
5. Creates approval issues if needed
6. Generates reports
7. Handles failures

**Workflow files:**
- `radar-weekly.yml` -- Discovery stage (scheduled weekly + manual trigger)
- `validate-opportunity.yml` -- Validation stage (requires approval)
- `plan-product.yml` -- Planning stage (requires approval)
- `build-and-test.yml` -- Building and testing stages
- `release.yml` -- Release stage (requires approval)
- `growth-review.yml` -- Growth and iteration stage

## State Machine

The state machine defines 17 states and 23 transitions.

### States

**Happy path (13 states):**
1. `discovered` -- Initial state, opportunity identified
2. `researching` -- Active research in progress
3. `validation_pending` -- Research complete, awaiting approval to validate
4. `validating` -- Deep validation in progress
5. `validation_approved` -- Validation passed, ready for planning
6. `planning` -- MVP scoping and planning in progress
7. `plan_approved` -- Plan approved, ready to build
8. `building` -- Implementation in progress
9. `testing` -- Testing in progress
10. `release_pending` -- Build complete, awaiting approval to release
11. `launched` -- Product is live in production
12. `growing` -- Active growth and marketing
13. `iterating` -- Based on user feedback, iterating on the product

**Recovery states (4 states):**
14. `blocked` -- Cannot proceed, needs human intervention
15. `failed` -- Stage failed, needs reset or retry
16. `paused` -- Manually paused
17. `rejected` -- Opportunity rejected, can restart from discovered

### State Diagram

```
                                    +-----------+
                                    | DISCOVERED|<---+
                                    +-----------+    |
                                          |          |
                                          v          |
                                    +-----------+    |
                              +---->|RESEARCHING|   |
                              |     +-----------+    |
                              |           |          |
                              |           v          |
                              |     +------------------+
                              |     |VALIDATION_PENDING|
                              |     +------------------+
                              |           |
                              |     (ungated: opportunity approval covers it)
                              |           |
                              |           v
                              |     +-----------+
                              |     |VALIDATING |
                              |     +-----------+
                              |           |
                              |           v
                              |     +---------------------+
                              |     |VALIDATION_APPROVED  |
                              |     +---------------------+
                              |           |
                              |           v
                              |     +----------+
                              |     | PLANNING |
                              |     +----------+
                              |           |
                              |     [approval: before_mvp_commit]
                              |           |
                              |           v
                              |     +--------------+
                              |     | PLAN_APPROVED|
                              |     +--------------+
                              |           |
                              |           v
                              |     +---------+
                              |     |BUILDING |
                              |     +---------+
                              |           |
                              |           v
                              |     +--------+
                              |     |TESTING |
                              |     +--------+
                              |           |
                              |           v
                              |     +----------------+
                              |     |RELEASE_PENDING |
                              |     +----------------+
                              |           |
                              |     [approval: before_production_release]
                              |           |
                              |           v
                              |     +---------+
                              |     |LAUNCHED |
                              |     +---------+
                              |           |
                              |           v
                              |     +---------+     +-----------+
                              +-----+GROWING  |<--->|ITERATING  |
                                    +---------+     +-----------+
                                    
Recovery paths:
  BLOCKED  --> RESEARCHING | VALIDATING | BUILDING
  FAILED   --> DISCOVERED (requires approval) | RESEARCHING
  PAUSED   --> DISCOVERED | RESEARCHING
  REJECTED --> DISCOVERED
```

### Transition Rules

Each transition has:
- **required_artifacts** -- List of artifact keys that must exist in state.json
- **approval_required** -- Whether a human approval record is needed
- **auto** -- Whether the transition can happen automatically
- **failure_action** -- What happens on failure: "block" (stay in current state), "fail" (move to failed), "pause" (move to paused)
- **gate** -- Optional gate identifier for approval tracking

**Example transition config:**
```python
(S.RELEASE_PENDING, S.LAUNCHED): _tc(
    approval_required=True,
    gate="before_production_release",
    failure_action="block",
)
```

This means: to move from release_pending to launched, you need an approval record, the gate is "before_production_release", and if it fails the project stays blocked in release_pending.

## Data Flow

### How a project moves through the pipeline

1. **Discovery** (discovered -> researching)
   - Trigger: Weekly radar scan or manual creation
   - Adapter: mock_agent.py or live discovery adapter
   - Output: research_result artifact with evidence, assumptions, risks
   - Transition: automatic

2. **Research** (researching -> validation_pending)
   - Trigger: Discovery complete
   - Adapter: research adapter (calls competitor-intelligence, seo-opportunity-research skills)
   - Output: research_result artifact
   - Transition: requires research_result artifact

3. **Validation Entry** (validation_pending -> validating)
   - Trigger: automatic
   - Gate: none -- approving the opportunity (radar / project creation) is
     already the decision to spend validation effort
   - Transition: no approval required

4. **Validation** (validating -> validation_approved)
   - Trigger: Deep validation complete
   - Adapter: validation adapter (calls product-validation skill)
   - Output: validation_result artifact
   - Transition: requires validation_result artifact

5. **Design Approval** (validation_approved -> planning)
   - Trigger: Human decides the validated opportunity is worth designing
   - Gate: before_design
   - Transition: requires approval for `planning`

6. **Planning** (planning -> plan_approved)
   - Trigger: Validation passed and design was approved
   - Adapter: planning adapter (calls mvp-scope-planner, product-requirements skills)
   - Output: plan_result artifact
   - Transition: requires plan_result artifact + approval (before_mvp_commit gate)

6. **Building** (plan_approved -> building -> testing)
   - Trigger: Plan approved
   - Adapter: build adapter (calls indie-tech-architecture, ai-coding-workflow skills)
   - Output: build_result artifact
   - Transition: requires build_result artifact

7. **Testing** (testing -> release_pending)
   - Trigger: Build complete
   - Adapter: testing adapter (calls launch-readiness-qa, security-privacy-review skills)
   - Output: test_result artifact
   - Transition: requires test_result artifact

8. **Release** (release_pending -> launched)
   - Trigger: Human approves release
   - Gate: before_production_release
   - Adapter: release adapter (calls deployment-operations, launch-campaign-planner skills)
   - Transition: requires approval record

9. **Growth** (launched -> growing -> iterating)
   - Trigger: Product is live
   - Adapter: growth adapter (calls indie-product-reach, product-analytics, content-marketing-engine skills)
   - Output: growth_review artifact
   - Transition: requires growth_review artifact, failure action is "pause"

## Approval Flow

Human approval gates protect critical decisions. The approval flow:

1. **State machine reaches approval gate** -- e.g., validation_pending -> validating
2. **Workflow creates GitHub Issue** -- with labels like "approval", "validation", project ID
3. **Human reviews artifacts** -- reads research results, validation reports, etc.
4. **Human approves or rejects** -- by commenting on the issue or closing it
5. **Approval record created** -- JSON file with approval_id, decision, artifact_hash, expires_at
6. **State machine validates approval** -- check_transition.py verifies the approval record exists and is valid
7. **Transition proceeds** -- if approval is valid, the state machine advances

**Approval record structure:**
```json
{
  "approval_id": "appr-validation-20250101",
  "project_id": "my-product",
  "stage": "validating",
  "decision": "approved",
  "approved_by": "github-username",
  "approved_at": "2025-01-01T12:00:00Z",
  "artifact_hash": "sha256:abc123...",
  "source_event": "https://github.com/owner/repo/issues/42",
  "expires_at": "2025-01-08T12:00:00Z"
}
```

**Approval rules:**
- Approvals expire after 7 days or if artifacts change
- Approvals are bound to artifact hashes -- if the artifact changes, the approval is invalidated
- Only the person who approves via the defined mechanism counts
- Adapters cannot approve their own output
- Emergency overrides require documented justification

See `docs/approval-policy.md` for the full approval policy.

## Agent Adapter Contract

### Input: StageRequest

```python
@dataclass
class StageRequest:
    project_id: str              # Project identifier
    stage: str                   # Pipeline stage (discovery, research, validation, etc.)
    task_description: str        # What the adapter should do
    allowed_read_paths: list[str]  # Files the adapter can read
    expected_output_schema: str  # Path to JSON Schema for validation
    timeout_seconds: int = 300   # Max execution time
    max_retries: int = 2         # Retry count on transient failures
```

### Output: AgentResponse

```python
@dataclass
class AgentResponse:
    status: str                  # "success", "partial", or "failed"
    stage_result: dict | None    # Structured result conforming to stage-result.schema.json
    raw_output: str              # Raw output from the agent
    errors: list[dict]           # Error details if status != "success"
    duration_seconds: float      # How long execution took
    mode: str                    # "mock" or "live"
    is_real_data: bool           # False if any data is simulated
```

### Security Constraints

1. **No credential access** -- Adapters receive tasks and return results. They never read or write production secrets.
2. **No self-approval** -- An adapter cannot mark its own output as approved.
3. **Path restriction** -- Adapters must only read files listed in `StageRequest.allowed_read_paths`.
4. **Mock/live separation** -- When `mode="mock"`, the adapter must set `is_real_data=False`.
5. **Schema conformance** -- Every `stage_result` must validate against `schemas/stage-result.schema.json`.

## File Organization and Naming Conventions

### Project directories

```
projects/
  <project-id>/                  # kebab-case, e.g., "my-awesome-product"
    state.json                   # Current pipeline state
    .issue-keys.json             # Idempotency markers for GitHub Issues
    audit/                       # Transition audit trail
      20250101T120000Z-discovered-researching.json
    research/                    # Discovery and research artifacts
      mock-discovery-result.json
      mock-research-result.json
      report.md
    planning/                    # Plans and specs
      mock-planning-result.json
    build/                       # Build artifacts
      mock-building-result.json
    testing/                     # Test results
      mock-testing-result.json
    release/                     # Release checklists
      mock-release-result.json
    growth/                      # Growth strategies
      mock-growth-result.json
```

### Naming conventions

- **Project IDs**: kebab-case, 3-64 characters, alphanumeric + hyphens, must start and end with alphanumeric
- **Stage result files**: `<stage>-result.json` or `mock-<stage>-result.json`
- **Audit records**: `<timestamp>-<from_stage>-<to_stage>.json` (timestamp format: YYYYMMDDTHHMMSSZ)
- **Approval IDs**: `appr-<stage>-<date>` (e.g., `appr-validation-20250101`)
- **Labels**: alphanumeric + hyphens only (e.g., `approval`, `validation`, `radar`)

## Recovery and Retry Logic

The state machine provides built-in recovery paths for failed or blocked projects.

### Failure actions

Each transition has a `failure_action` that determines what happens when a stage fails:

- **"block"** -- Project stays in the current state, moves to `blocked` if retries exhausted
- **"fail"** -- Project moves to `failed` state
- **"pause"** -- Project moves to `paused` state

### Recovery transitions

**From blocked:**
- blocked -> researching (retry research)
- blocked -> validating (retry validation)
- blocked -> building (retry build)

**From failed:**
- failed -> discovered (full reset, requires approval)
- failed -> researching (retry research)

**From paused:**
- paused -> discovered (reset to start)
- paused -> researching (retry research)

**From rejected:**
- rejected -> discovered (start over with new opportunity)

### Retry logic

Each stage has a `retry_limit` defined in `config/workflow-policy.yml`:

```yaml
stages:
  testing:
    retry_limit: 3  # Retry up to 3 times before failing
```

Retries are automatic for transient failures (timeouts, network errors). Deterministic failures (invalid schema, missing artifacts) do not retry.

## Audit Trail Structure

Every state transition is recorded in the audit trail for traceability.

### In-state audit log

The `audit_log` array in `state.json` contains recent transitions:

```json
{
  "audit_log": [
    {
      "timestamp": "2025-01-01T12:00:00Z",
      "action": "transition",
      "actor": "system",
      "from_stage": "discovered",
      "to_stage": "researching"
    }
  ]
}
```

### File-based audit records

Individual transition records are stored in `projects/<project-id>/audit/`:

```json
{
  "timestamp": "2025-01-01T12:00:00Z",
  "project_id": "my-product",
  "from_stage": "discovered",
  "to_stage": "researching",
  "action": "transition_check",
  "actor": "check_transition.py"
}
```

### Audit record fields

- **timestamp** -- ISO 8601 timestamp of the transition
- **project_id** -- Project identifier
- **from_stage** -- Source state
- **to_stage** -- Target state
- **action** -- Type of action (e.g., "transition", "transition_check", "approval")
- **actor** -- What performed the action (e.g., "system", "check_transition.py", GitHub username)
- **details** -- Optional additional context

Audit records are append-only. They are never modified or deleted, providing a complete history of all state changes.
