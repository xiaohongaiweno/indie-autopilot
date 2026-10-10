# indie-autopilot

Orchestrate an indie developer's workflow from opportunity discovery to growth -- using GitHub Actions as the execution backbone.

indie-autopilot is a state-machine pipeline that coordinates 31 specialized AI skills across 8 workflow stages. It moves a product idea through research, validation, planning, building, testing, release, and growth -- with human approval gates at critical decision points.

## Architecture

```
+------------------+     +------------------+     +------------------+     +------------------+
|   Data Sources   |     |  Agent Adapters  |     |  State Machine   |     | GitHub Actions   |
|                  |     |                  |     |                  |     |                  |
|  Hacker News     |---->|  Mock Adapter    |---->|  17 States       |---->|  radar-weekly    |
|  Google Trends   |     |  Claude Code CLI |     |  23 Transitions  |     |  validate-opp    |
|  Reddit          |     |  Codex CLI       |     |  Approval Gates  |     |  plan-product    |
|  Product Hunt    |     |  Custom API      |     |  Audit Trail     |     |  build-and-test  |
|  Web Search      |     |                  |     |                  |     |  release         |
|                  |     |  Reads SKILL.md  |     |  Validates       |     |  growth-review   |
|  (all mock by    |     |  instructions,   |     |  transitions &   |     |                  |
|   default)       |     |  returns results |     |  artifacts       |     |                  |
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
2. **Agent Adapters** (`adapters/`) bridge the gap between the workflow engine and AI agents. They read skill instructions, execute them via an AI agent, and return structured results.
3. **State Machine** (`scripts/state_machine.py`) enforces valid transitions, checks artifact requirements, and manages the approval gate logic.
4. **GitHub Actions** (`.github/workflows/`) orchestrate the pipeline -- running adapters, validating outputs, creating issues for approvals, and generating reports.

## Prerequisites

- **Python 3.10+**
- **GitHub account** with `gh` CLI installed and authenticated
- **pip** for dependency management

```bash
# Verify gh CLI
gh auth status
```

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/indie-autopilot.git
cd indie-autopilot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Validate your environment
python scripts/validate_environment.py

# 4. Run mock discovery (no API keys needed)
python adapters/mock_agent.py \
  --stage discovery \
  --project-id my-first-product \
  --output-dir projects/my-first-product/research/

# 5. Validate the output
python scripts/validate_artifact.py \
  --schema schemas/stage-result.schema.json \
  --artifact projects/my-first-product/research/mock-discovery-result.json

# 6. Generate a status report
python scripts/generate_report.py \
  --project-dir projects/my-first-product
```

## Project Structure

```
indie-autopilot/
  .github/workflows/       # GitHub Actions pipeline definitions
    radar-weekly.yml       # Weekly opportunity scan
    validate-opportunity.yml
    plan-product.yml
    build-and-test.yml
    release.yml
    growth-review.yml
  adapters/                # Agent adapter implementations
    adapter_interface.py   # Abstract base class + data types
    mock_agent.py          # Deterministic mock for testing
  config/                  # Pipeline configuration
    workflow-policy.yml    # Approval gates, timeouts, retry limits
    sources.yml            # Data source status (mock/live)
  docs/                    # Documentation
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
      state.json           # Current pipeline state
      audit/               # Transition audit trail
      research/            # Discovery and research artifacts
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
    state_machine.py       # State definitions and transition logic
    validate_artifact.py   # JSON Schema validation
    check_transition.py    # Transition validation with approval checks
    create_issue.py        # GitHub Issue creation (for approvals)
    generate_report.py     # Markdown status report generator
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

## Running Workflows

### radar-weekly (Discovery)

Runs every Monday at 9am UTC. Scans for new opportunities.

```bash
# Manual trigger via gh CLI
gh workflow run radar-weekly.yml -f project_id=new -f mock_mode=true
```

### validate-opportunity

Deep validation of a discovered opportunity. Requires approval to proceed.

```bash
gh workflow run validate-opportunity.yml -f project_id=my-product
```

### plan-product

MVP scoping and planning. Requires approval before committing to build.

```bash
gh workflow run plan-product.yml -f project_id=my-product
```

### build-and-test

Implementation and testing. Runs the build and test stages.

```bash
gh workflow run build-and-test.yml -f project_id=my-product
```

### release

Production release. Requires approval before deploying.

```bash
gh workflow run release.yml -f project_id=my-product
```

### growth-review

Post-launch growth analysis and iteration planning.

```bash
gh workflow run growth-review.yml -f project_id=my-product
```

## Switching from Mock to Live Mode

By default, all data sources are in mock mode. To use real data:

1. Edit `config/sources.yml` and set `enabled: true` + `mode: live` for each source you want to activate.
2. Provide the required API keys as environment variables or GitHub secrets.
3. Set the `mock_mode` input to `false` when triggering workflows.

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

## Adding a New Agent Adapter

See `adapters/README.md` for full details. The short version:

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

Register the adapter in your pipeline config:

```yaml
# config/pipeline.yaml
stages:
  discovery:
    adapter: my_adapter_module.MyAdapter
    timeout_seconds: 300
    max_retries: 2
```

## Recovering from Failures

The state machine has built-in recovery paths:

| Current State | Recovery Options |
|---|---|
| `blocked` | Retry to `researching`, `validating`, or `building` |
| `failed` | Reset to `discovered` (requires approval) or retry `researching` |
| `paused` | Reset to `discovered` or retry `researching` |
| `rejected` | Reset to `discovered` to start over |

```bash
# Check what transitions are valid
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage researching

# See docs/recovery-runbook.md for detailed recovery procedures
```

## Security Model

- **Human approval gates** at validation, planning, release, and paid service stages
- **Artifact hash binding** -- approvals are invalidated if artifacts change
- **No self-approval** -- adapters cannot approve their own output
- **Mock/live separation** -- mock data is clearly labeled and never treated as real
- **Path restrictions** -- adapters can only read files in allowed paths
- **No credential access** -- adapters receive tasks and return results, never touch production secrets
- **Audit trail** -- every state transition is logged with timestamp, actor, and details

See `docs/approval-policy.md` for the full approval policy.

## Configuration

### workflow-policy.yml

Controls stage execution behavior:

```yaml
stages:
  validation:
    auto_advance: false        # Requires human approval
    approval_required: true
    approval_gate: "before_deep_validation"
    timeout_minutes: 60
    retry_limit: 1
```

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
| `GITHUB_TOKEN` | For live mode | GitHub API access |
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
