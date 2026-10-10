# indie-autopilot

Orchestrate an indie developer's workflow from opportunity discovery to growth -- entirely on your own machine.

indie-autopilot is a state-machine pipeline that coordinates 31 specialized AI skills across 8 workflow stages. It moves a product idea through research, validation, planning, building, testing, release, and growth -- with human approval gates at critical decision points.

## Architecture

```
+------------------+     +------------------+     +------------------+     +------------------+
|   Data Sources   |     |  Agent Adapters  |     |  State Machine   |     |   Local Driver   |
|                  |     |                  |     |                  |     |                  |
|  Hacker News     |---->|  Mock Adapter    |---->|  17 States       |---->|  autopilot run   |
|  Google Trends   |     |  Claude Code CLI |     |  19 Transitions  |     |  autopilot status|
|  Reddit          |     |  Codex CLI       |     |  Approval Gates  |     |  autopilot move  |
|  Product Hunt    |     |  Custom API      |     |  Audit Trail     |     |                  |
|  Web Search      |     |                  |     |                  |     |  Terminal gates: |
|                  |     |  Reads SKILL.md  |     |  Validates       |     |  approve with y  |
|  (all mock by    |     |  instructions,   |     |  transitions &   |     |  (no GitHub      |
|   default)       |     |  returns results |     |  artifacts       |     |   round trip)    |
+------------------+     +------------------+     +------------------+     +------------------+
         |                       |                        |                        |
         v                       v                        v                        v
+-------------------------------------------------------------------------------------------+
|                              JSON Schemas & State Files                                  |
|                                                                                          |
|  project.schema.json  |  stage-result.schema.json  |  approval.schema.json  |  state.json |
+-------------------------------------------------------------------------------------------+
```

### How it works

1. **Skills** (`indie-builder-skills/`) are instruction documents (SKILL.md files) that guide AI agents through specific tasks like competitor analysis, MVP scoping, or launch QA.
2. **Agent Adapters** (`adapters/`) bridge the gap between the pipeline and AI agents. They read skill instructions, execute them via an AI agent, and return structured results.
3. **State Machine** (`scripts/state_machine.py`) enforces valid transitions, checks artifact requirements, and manages the approval gate logic.
4. **Local Driver** (`autopilot.py` + `scripts/orchestrator.py`) walks a project along the state machine -- running the stage adapter, registering the artifact it produced, and pausing at each approval gate for a local `y`/`n` decision.

Everything runs offline by default: the `mock` adapter is deterministic, so the entire pipeline can be exercised without API keys, network calls, or model credits.

## Prerequisites

- **Python 3.10+**
- **pip** for dependency management

No GitHub account, remote, or `gh` CLI is required. State and artifacts are plain files in `projects/`, versioned by ordinary `git` if you choose to use it.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Validate your environment
python scripts/validate_environment.py

# 3. Find a need worth building (creates radar-data/profile.md on first run)
./autopilot.py radar

# 4. Approve an opportunity -> it becomes a project at `discovered`,
#    then run the pipeline. It stops at each approval gate and asks you.
./autopilot.py run my-first-product --adapter skill

# 5. Deploy (runs automatically at the release gate too)
./autopilot.py deploy my-first-product

# 6. After launch, feed real results back in (Search Console / GA4)
./autopilot.py metrics my-first-product

# 7. See the whole picture
./autopilot.py report my-first-product   # full markdown report
./autopilot.py report --all              # every project, and what is waiting
./autopilot.py status my-first-product   # terse version
```

See [docs/local-usage.md](docs/local-usage.md) for the full command reference.

To create a project by hand instead:

```bash
mkdir -p projects/my-first-product
cat > projects/my-first-product/state.json << 'EOF'
{
  "project_id": "my-first-product",
  "name": "My First Product",
  "stage": "discovered",
  "status": "active",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-01T00:00:00Z",
  "approved_stages": [],
  "artifacts": {},
  "audit_log": []
}
EOF

./autopilot.py run my-first-product
```

## Project Structure

```
indie-autopilot/
  autopilot.py             # Local CLI driver (run / status / history / approve / move)
  adapters/                # Agent adapter implementations
    adapter_interface.py   # Abstract base class + data types
    mock_agent.py          # Deterministic mock for testing
  config/                  # Pipeline configuration
    pipeline.yaml          # Stage -> agent/artifact mapping (drives the orchestrator)
    workflow-policy.yml    # Approval gates, timeouts, retry limits
    sources.yml            # Data source status (mock/live)
  docs/                    # Documentation
    local-usage.md         # How to drive the local pipeline
    architecture.md        # System architecture details
    approval-policy.md     # Human approval gate rules
    recovery-runbook.md    # How to fix things when they break
    skills-integration.md  # Skill-to-pipeline mapping
  indie-builder-skills/    # 31 AI skill instruction documents
    skills/                # One directory per skill, each with SKILL.md
    CATALOG.md             # Skill catalog with priorities
    HANDOFF-MAP.md         # Skill handoff relationships
  projects/                # Per-project state and artifacts
    <project-id>/
      state.json           # Current pipeline state (the single source of truth)
      audit/               # Transition audit trail
      research/            # Research artifacts
      validation/          # Validation artifacts
      planning/            # Plans and specs
      build/               # Build artifacts
      testing/             # Test results
      release/             # Release checklists
      growth/              # Growth strategies
  schemas/                 # JSON Schema definitions
    project.schema.json    # Project state file schema
    stage-result.schema.json  # Stage output schema
    approval.schema.json   # Approval record schema
  scripts/                 # Core pipeline scripts
    orchestrator.py        # Pipeline engine (drives stages, gates, artifacts)
    state_machine.py       # State definitions and transition logic
    validate_artifact.py   # JSON Schema validation
    check_transition.py    # Standalone transition check
    report.py              # Project / portfolio markdown reports
    validate_environment.py  # Environment health checks
  tests/                   # Test suite
  requirements.txt         # Python dependencies
```

## Creating a New Project

```bash
# Create the project directory structure
PROJECT_ID=my-new-product
mkdir -p projects/$PROJECT_ID/{audit,research,planning,build,testing,release,growth}

# Initialize state.json
cat > projects/$PROJECT_ID/state.json << 'EOF'
{
  "project_id": "my-new-product",
  "name": "My New Product",
  "description": "A brief description of the product idea",
  "stage": "discovered",
  "status": "active",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-01T00:00:00Z",
  "approved_stages": [],
  "artifacts": {},
  "audit_log": []
}
EOF

# Validate the state file
python scripts/validate_artifact.py \
  --schema schemas/project.schema.json \
  --artifact projects/$PROJECT_ID/state.json
```

## Running the Pipeline

The whole pipeline is driven by one command. It walks the project along the
canonical path, running each stage's adapter and pausing at every approval gate.

```bash
# Run until the next refusal, or to the end of the happy path
./autopilot.py run my-first-product

# Stop once a specific stage is reached
./autopilot.py run my-first-product --to testing

# Auto-approve every gate (unattended)
./autopilot.py run my-first-product --yes
```

### The canonical path

```
discovered
  -> researching              run research adapter, register research_result
  -> validation_pending
  -> validating               run validation adapter, register validation_result
  -> validation_approved
  ⏸ GATE before_design
  -> planning                 run planning adapter, register plan_result
  ⏸ GATE before_mvp_commit
  -> plan_approved
  -> building                 run building adapter, register build_result
  -> testing                  run testing adapter, register test_result
  ⏸ GATE before_code_merge
  -> release_pending          run release adapter, register release_result
  ⏸ GATE before_production_release
  -> launched
  -> growing                  run growth adapter, register growth_review
```

Entering validation is deliberately ungated: approving the opportunity itself is
already the decision to spend validation effort, so research and validation run
back to back. After that, four gates take it to launch -- approve design, approve
the build, review the code, approve the release.

### Deployment

The `before_production_release` gate is followed by a real Cloudflare deployment,
which runs **before** the `launched` state is recorded:

```
release_pending
  ⏸ GATE before_production_release
  🚀 wrangler deploy
  -> launched          (recorded only if the deploy succeeded)
```

So a failed deploy leaves the project retryable at `release_pending` rather than
falsely launched. Credentials are prompted for on first use and stored in `.env`
(gitignored, mode 0600); the values are never printed.

```bash
./autopilot.py deploy my-product --dry-run        # show the command
./autopilot.py deploy my-product                  # gate -> deploy -> launched
./autopilot.py deploy-status my-product           # URL, type, domain status
./autopilot.py domain my-product --domain myapp.com  # record the domain you attached
```

Attaching a custom domain is a Cloudflare dashboard action, so the pipeline
prints instructions and you record the result with `domain`. See
[docs/local-usage.md](docs/local-usage.md#9-deploying-to-cloudflare).

### Real code, not a description

The `building` stage is configured with `code_dir: app`, so the agent must write
real files to `projects/<id>/app/`. The orchestrator verifies that afterwards: a
live run reporting success with an empty `app/` is a hard failure and registers
nothing, so a confident summary can never stand in for a product. A manifest of
what was written is recorded on the artifact.

```bash
# live build: the agent writes real code, then deploy finds it
./autopilot.py run my-product --adapter skill
./autopilot.py deploy my-product --dry-run
```

The check applies to live runs only — the mock adapter is explicitly fake, which
is why `deploy` correctly refuses to deploy a mock-built project.

### Tests actually run

The `testing` stage runs the project's **own** tests before the QA agent, and a
red suite stops the pipeline before the agent is even called — so nothing
untested can reach the code-review gate. The command is detected from what the
project declares (`package.json` scripts.test, pytest config, a Makefile `test`
target) and never invented:

```bash
./autopilot.py verify my-product --dry-run   # show the detected command
```

If the project declares no tests, the run is recorded as `not_configured` and
marked unverified rather than passing silently (`verify.require_tests: true`
makes it fatal instead). The result is written to `testing/test-run.json` before
the agent starts, so the brief it receives contains the real command, exit code
and output.

### Seeing where things stand

`status` is terse; `report` is the full picture and leads with what is waiting
for you — a project parked on an ungranted gate is the most actionable fact
there is:

```bash
./autopilot.py report my-first-product   # gate, artifacts with real-vs-mock
                                         # provenance, real numbers, code manifest
./autopilot.py report --all              # portfolio view + what needs a decision
./autopilot.py list                      # marks waiting projects with ⏸
```

Concurrent runs are safe: each state-mutating command takes an exclusive
per-project lock, so two `run` invocations can no longer overwrite each other's
`state.json`.

### Closing the loop

Everything upstream of `growing` is a guess. `metrics` reads what actually
happened -- impressions, clicks, click-through rate, average position, traffic
sources -- straight from Google Search Console and GA4:

```bash
./autopilot.py metrics my-first-product --dry-run   # show what is configured
./autopilot.py metrics my-first-product             # fetch and register
./autopilot.py run my-first-product --adapter skill # growth now sees real data
```

The result is registered as a `metrics` artifact, so the next growth run inlines
real numbers into its brief — and the ten growth skills that actually consume
them (indexing diagnostics, conversion, feedback loop, distribution, pricing,
lifecycle) run at that stage.

The `growing <-> iterating` cycle really cycles: coming back around re-runs the
analysis rather than reusing last round's conclusions. Two SEO opportunities are **computed** rather than
guessed by a model: queries ranking 11-20 (push onto page one) and queries with
many impressions but under 2% CTR (rewrite the title).

When credentials or configuration are missing, the report says
`mode: "unavailable"` and `is_real_data: false` -- a failure is never passed off
as feedback. See
[docs/local-usage.md](docs/local-usage.md#10-closing-the-loop-real-search-console--ga4-data).

Shortcut edges that skip a stage or a gate do not exist. To leave the path on
purpose, use the audited escape hatch:

```bash
./autopilot.py move my-first-product --to testing --force --reason "hotfix verification"
```

### Inspecting a project

```bash
./autopilot.py status my-first-product     # stage, artifacts, approvals, next steps
./autopilot.py history my-first-product    # full audit log
./autopilot.py list                        # all known projects
```

### Approving a gate ahead of time

```bash
./autopilot.py approve my-first-product --stage plan_approved
```

Approvals are recorded in `state.json`'s `approved_stages` array, which is what
the state machine reads. Nothing else needs to know how the approval was given.

Full reference: [docs/local-usage.md](docs/local-usage.md).

## Switching from Mock to Live Mode

By default, the pipeline uses the deterministic `mock` adapter -- no API keys, no
network, no model credits. To use a real agent you need an adapter that
implements `AgentAdapter`, registered in `config/pipeline.yaml`:

```bash
./autopilot.py run my-first-product --adapter mock   # default
```

Data sources are configured separately in `config/sources.yml`:

1. Set `enabled: true` + `mode: live` for each source you want to activate.
2. Provide the required API keys as environment variables.

```yaml
# config/sources.yml example
hacker_news:
  enabled: true
  mode: live

google_trends:
  enabled: true
  api_key_env: SERPAPI_KEY
  mode: live
```

```bash
# Trigger with live mode
gh workflow run radar-weekly.yml -f project_id=my-product -f mock_mode=false
```

Currently available live sources:
- **Hacker News** -- free Algolia API, no key required (enabled by default)
- All other sources require API keys and are disabled by default

## Running Real Skills

`mock` is the offline adapter. The `skill` adapter runs the real SKILL.md
methodology through a pluggable **agent backend**, so the pipeline is not tied
to any one AI tool:

```bash
./autopilot.py run my-first-product --adapter skill     # default backend: handoff
AUTOPILOT_BACKEND=claude ./autopilot.py run my-first-product --adapter skill
```

With the default `handoff` backend, each stage writes a self-contained brief
(`task.md`) plus the JSON contract, and waits for you to drop the result into
`agent-result.json`. You can run that brief in Claude Code, Codex, CodeBuddy,
DeepSeek Harness, or a plain chat window -- no credentials or CLI required.

Adding another agent is a config edit, not code:

```yaml
# config/pipeline.yaml
backends:
  codebuddy:
    class: adapters.agent_backends.CommandBackend
    options:
      command: ["codebuddy", "run", "--file", "{prompt_file}"]
```

Which skills each stage runs is configured under `skills:` in the same file
(deliberately a focused subset -- all 31 skills total ~165 KB).

See [docs/local-usage.md](docs/local-usage.md#8-running-real-work-skills--agent-backends)
for the full backend reference and the handoff walkthrough.

## Adding a New Adapter

Only needed if a stage must do something other than "read skills, call an
agent". See `adapters/README.md` for full details. The short version:

```python
from adapters.adapter_interface import AgentAdapter, AgentResponse, StageRequest

class MyAdapter(AgentAdapter):
    def execute(self, request: StageRequest) -> AgentResponse:
        # Call your agent, parse output, return AgentResponse
        ...

    def health_check(self) -> bool:
        # Return True when ready
        ...

    def name(self) -> str:
        return "my-adapter"
```

Then register it in `config/pipeline.yaml` and select it with `--adapter`:

```yaml
# config/pipeline.yaml
adapters:
  mock:
    module: adapters.mock_agent
    class: MockAgent
  skill:
    module: adapters.skill_agent
    class: SkillAgentAdapter
```

```bash
./autopilot.py run my-first-product --adapter skill
```

Note that `config/pipeline.yaml`'s `stages:` section maps *pipeline stages* to
the adapter stage that fulfils them (and the artifact it must produce) -- it is
not where adapters are selected.

## Recovering from Failures

Progress lives entirely in `state.json`, so **re-running is the recovery
mechanism** -- `autopilot run` picks up from the recorded stage and skips work
whose artifact is already present on disk:

```bash
./autopilot.py run my-first-product          # resume wherever it stopped
./autopilot.py run my-first-product --rerun  # force every stage to re-run
```

The state machine has built-in recovery paths:

| Current State | Recovery Options |
|---|---|
| `blocked` | Retry to `researching`, `validating`, or `building` |
| `failed` | Reset to `discovered` (requires approval) or retry `researching` |
| `paused` | Reset to `discovered` or retry `researching` |
| `rejected` | Reset to `discovered` to start over |

If the state machine cannot route where you need to go, use the audited
override rather than editing `state.json` by hand:

```bash
./autopilot.py move my-first-product --to blocked --force --reason "why"
```

```bash
# Check what transitions are valid
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage researching

# See docs/recovery-runbook.md for detailed recovery procedures
```

## Security Model

- **Human approval gates** at validation, planning, and release -- enforced by the
  state machine and surfaced as local terminal prompts
- **No self-approval** -- the adapter that produces an artifact is never the
  component that grants the approval; the gate is answered by a human at a TTY
  (or explicitly waived with `--yes`)
- **Mock/live separation** -- mock data is clearly labeled (`is_real_data: false`)
  and never treated as real
- **Path restrictions** -- adapters declare which paths they may read
- **No credential access** -- adapters receive tasks and return results; they do
  not read production secrets
- **Audit trail** -- every stage execution, approval, rejection, and transition is
  logged in `state.json`'s `audit_log` with timestamp, actor, and details
- **Audited overrides** -- `autopilot move --force` requires a `--reason` and
  records that gates were bypassed

Approvals are recorded locally with an approver name and timestamp. There is no
cryptographic binding of an approval to an artifact hash today, so an approval
stays valid if the artifact it covered is later regenerated.

See `docs/approval-policy.md` for the full approval policy.

## Configuration

### pipeline.yaml

Maps pipeline stages to the adapter stage that fulfils them, and to the artifact
the outgoing transition requires:

```yaml
stages:
  building:
    agent_stage: building
    output_dir: build
    artifact_key: build_result
```

### workflow-policy.yml

Controls stage execution behavior (timeouts are read from here by the orchestrator):

```yaml
stages:
  validation:
    auto_advance: false        # Requires human approval
    approval_required: true
    approval_gate: "before_design"
    timeout_minutes: 60
    retry_limit: 1
```

The gate *decisions* live in `scripts/state_machine.py`; this file supplies the
gate metadata used to render the approval prompt plus the per-stage timeout.

### sources.yml

Controls data source availability:

```yaml
sources:
  google_trends:
    enabled: false
    api_key_env: SERPAPI_KEY
    mode: mock
```

### Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `SERPAPI_KEY` | Optional | Google Trends via SerpAPI |
| `AHREFS_API_KEY` | Optional | SEO research |
| `REDDIT_CLIENT_ID` | Optional | Reddit data source |

## Contributing

This is a solo indie developer project, but contributions are welcome:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-improvement`
3. Make your changes and add tests
4. Ensure all tests pass: `pytest tests/`
5. Validate schemas: `python scripts/validate_artifact.py --schema schemas/project.schema.json --artifact projects/example-product/state.json`
6. Submit a pull request

### Development Guidelines

- All stage outputs must validate against `schemas/stage-result.schema.json`
- All state files must validate against `schemas/project.schema.json`
- New adapters must implement the `AgentAdapter` interface
- Mock mode must always set `is_real_data=False`
- Include audit log entries for all state transitions
- Do not commit secrets, API keys, or credentials

## License

This project is for educational and personal use. See individual skill licenses in `indie-builder-skills/`.
