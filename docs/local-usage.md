# Local Usage

How to drive the indie-autopilot pipeline on your own machine.

There is one entry point: `autopilot.py`. It walks a project along the state
machine, runs the stage adapter, registers the artifact that stage produced, and
pauses at every approval gate for a local decision. No GitHub, no remote runner,
no CI round trip.

---

## 1. Prerequisites

- Python 3.10+
- `pip install -r requirements.txt`

Check everything is in place:

```bash
python scripts/validate_environment.py
```

This verifies the Python version, required packages, directory layout, schema
files, and that `autopilot.py` + `config/pipeline.yaml` are present.

---

## Finding opportunities first (`autopilot radar`)

Before a project exists, this is step 1 of the workflow: scan for needs worth
building. It runs `indie-product-radar` + `emerging-keyword-radar` through the
same agent backends as the pipeline, scores what it finds with the skill's own
`score.py`, then asks you which opportunity to turn into a project.

```bash
./autopilot.py radar                      # scan, then pick interactively
./autopilot.py radar --yes                # auto-pick the top opportunity
./autopilot.py radar --from-file x.json   # re-use an existing scan result
./autopilot.py radar-list                 # previous scans
```

On the first run it creates `radar-data/profile.md` -- your tech stack, weekly
hours, B2B/B2C, avoided areas, and (most importantly) which audiences you can
actually reach. Fill it in: it is what makes the `fit` dimension meaningful.

Output layout:

```
radar-data/                    # the skill's own persistent workspace
  profile.md                   # your founder profile
  scoreboard.json              # accumulated scoring data across scans
  scans/<date>-report.md       # the human-facing Markdown deliverable
  failures/                    # rejected / failed directions
radar/scans/<scan-id>/         # per-scan pipeline files
  task.md                      # the self-contained brief
  agent-result.json            # the agent's JSON reply
```

With the `handoff` backend the flow is the same as any stage: run `task.md` in
whatever agent you like, save the JSON to `agent-result.json`, re-run
`./autopilot.py radar`.

**Scoring is never reimplemented.** The skill ships
`indie-product-radar/scripts/score.py`, and radar reads its weights and tier
thresholds out of that file, then shells out to `score.py validate` as the
authority. If the scoreboard has errors, radar **refuses to create a project** --
you cannot build on invalid data. Opportunities are ranked by the skill's own
weighted total (demand 18 / trend 13 / pay 18 / gap 13 / acq 13 / dev 10 /
moat 5 / fit 10) with tiers `≥75 立即验证`, `60–74 观察池`, `<60 低分`.

Approving an opportunity creates `projects/<id>/` at `discovered` with the scan
seeded as a `radar/scan.json` artifact, so the research stage can see what
convinced you. It then joins the normal pipeline:

```bash
./autopilot.py radar --yes
./autopilot.py run opp-small-business-shift-scheduler --adapter skill
```

A Chinese opportunity name cannot be slugified into a project id, so radar falls
back to the opportunity's own id (`opp-2026-10-w2-07`) rather than producing a
meaningless id.

---

## 2. Creating a project

A project is a directory under `projects/` containing a `state.json`. The only
required field to get started is `stage: discovered`.

> Prefer `./autopilot.py radar` to create it for you -- it seeds the opportunity
> scan so the research stage has context. Create one by hand only when you
> already know exactly what you are building.

```bash
PROJECT_ID=my-product
mkdir -p "projects/$PROJECT_ID"

cat > "projects/$PROJECT_ID/state.json" << 'EOF'
{
  "project_id": "my-product",
  "name": "My Product",
  "stage": "discovered",
  "status": "active",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-01T00:00:00Z",
  "approved_stages": [],
  "artifacts": {},
  "audit_log": []
}
EOF
```

`project_id` must match `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` (lowercase,
hyphenated, at least 3 characters) -- this is enforced by
`schemas/project.schema.json` and by the stage-result schema, so a bad id fails
fast at the first stage.

Validate the state file if you like:

```bash
python scripts/validate_artifact.py \
  --schema schemas/project.schema.json \
  --artifact projects/my-product/state.json
```

---

## 3. Commands

### `run`

Advance a project. Stops at the first gate you decline, or when the target is
reached.

```bash
./autopilot.py run my-product                # to the end of the happy path
./autopilot.py run my-product --to testing   # stop once testing is reached
./autopilot.py run my-product --yes          # auto-approve every gate
./autopilot.py run my-product --rerun        # re-run stages whose artifact exists
./autopilot.py run my-product --adapter mock # choose an adapter (default: mock)
```

`<project>` may also be a path to a project directory.

### `status`

The fastest way to see where you are and what is blocking the next step:

```bash
./autopilot.py status my-product
```

```
project_id : my-product
name       : My Product
stage      : planning
agent      : planning (MVP scope, PRD and task breakdown)
artifacts  :
  ✅ research_result: research/mock-research-result.json
  ✅ validation_result: validation/mock-validation-result.json
approvals  :
  ✅ validating by yourname at 2025-01-01T00:00:00+00:00
next       :
  -> plan_approved  [✅ plan_result, ❌ approval(plan_approved)]
```

Each requirement is marked ✅/❌ so you can see exactly what is missing.

### `history`

Print the audit log:

```bash
./autopilot.py history my-product
./autopilot.py history my-product --limit 20
```

### `approve`

Pre-grant an approval, so a later `run` sails through that gate. Useful when you
have already reviewed an artifact and do not want to be interrupted:

```bash
./autopilot.py approve my-product --stage plan_approved
./autopilot.py approve my-product --stage launched --by yourname
```

### `move`

Deliberately leave the canonical path. This bypasses gates and artifact checks,
so `--force` and `--reason` are both mandatory, and the override is recorded in
the audit log:

```bash
./autopilot.py move my-product --to testing --force --reason "hotfix verification"
```

### `list`

```bash
./autopilot.py list
```

---

## 4. The canonical path

Each stage runs its adapter on entry, producing the artifact the outgoing
transition requires. Gates sit *on transitions*, so the ⏸ line is the boundary
you must pass to reach the next state.

```
discovered
  -> researching              run research adapter   -> research_result
  -> validation_pending                                 (needs research_result)
  -> validating               run validation adapter -> validation_result
  -> validation_approved                                (needs validation_result)
  ⏸ GATE before_design (medium)
  -> planning                 run planning adapter   -> plan_result
  ⏸ GATE before_mvp_commit (medium)                     (needs plan_result)
  -> plan_approved
  -> building                 run building adapter   -> build_result
  -> testing                  run testing adapter    -> test_result
  ⏸ GATE before_code_merge (high)                       (needs test_result)
  -> release_pending          run release adapter    -> release_result
  ⏸ GATE before_production_release (critical)
  -> launched
  -> growing                  run growth adapter     -> growth_review
```

Entering validation is deliberately **ungated**: approving the opportunity
itself (via `autopilot radar`) is already the decision to spend validation
effort, so research and validation run back to back unattended.

So there are **four decisions** between a validated opportunity and a launched
product -- approve design, approve the build, review the code, approve the
release -- plus the opportunity approval in front of all of them.

`growing` is the default target. Beyond it, `growing <-> iterating` is a cycle
(growth is recurring, not one-shot), so `run` stops there unless you ask for
`--to iterating`.

**Shortcut edges do not exist.** There is no `validating -> building`, no
`discovered -> validating`, and no `validating -> planning`. This is deliberate:
those shortcuts made the approval gates meaningless. Use `move --force` when you
genuinely need to skip ahead.

### Gate reference

| Gate | Transition | Risk | Approving stage value |
|---|---|---|---|
| `before_design` | `validation_approved -> planning` | medium | `planning` |
| `before_mvp_commit` | `planning -> plan_approved` | medium | `plan_approved` |
| `before_code_merge` | `testing -> release_pending` | high | `release_pending` |
| `before_production_release` | `release_pending -> launched` | critical | `launched` |

The "approving stage value" is the **target** stage -- what you pass to
`autopilot approve --stage`. Note that `before_code_merge` (code review) sits on
`testing -> release_pending` rather than `building -> testing` so that the
reviewer has the test results in hand; that is also what the gate's own
`requires: [test_result, security_review]` declares.

There is one more gated transition, `failed -> discovered`, which requires
approval before a failed project is reset.

Gate metadata (description, risk level, required artifacts) comes from
`config/workflow-policy.yml`; the gate *decisions* come from the state machine in
`scripts/state_machine.py`. If you edit one, keep the other in mind --
`tests/test_state_machine.py::test_each_happy_path_gate_has_policy_metadata`
fails if a gate exists without policy metadata.

---

## 5. How approvals are stored

An approval is an entry in `state.json`'s `approved_stages` array:

```json
"approved_stages": [
  {
    "stage": "plan_approved",
    "approved_at": "2025-01-01T12:00:00+00:00",
    "approval_id": "appr-plan_approved-20250101T120000Z",
    "approved_by": "yourname",
    "mode": "local",
    "gate": "before_mvp_commit"
  }
]
```

The `stage` field is the **target** stage of the transition being approved, not
the stage you are leaving. `scripts/state_machine.py` reads exactly this shape,
so `check_transition.py` and the orchestrator agree about what an approval is.

**Approvals are not bound to artifact hashes.** If a stage is re-run with
`--rerun` and produces different output, an earlier approval for the following
transition remains valid. If that matters to you, re-approve explicitly.

---

## 6. Resuming and idempotency

`state.json` is the only source of progress, so every run is resumable:

- Interrupt with Ctrl-C at any point; `run` again to continue.
- A stage is skipped when its artifact is both registered in `artifacts` **and**
  still present on disk.
- Delete an artifact and re-run to have it regenerated (self-healing).
- `--rerun` forces every stage to execute again.

Running the pipeline twice is safe: the second run performs no work and adds no
audit entries.

---

## 7. Artifact layout

Each stage writes to its own directory under the project, named by the adapter
stage, using the mock convention `mock-<stage>-result.json` (a live adapter
writes `<stage>-result.json`). A `-meta.json` sidecar records the adapter
response for debugging.

```
projects/my-product/
  state.json
  app/                              # the real product source (see below)
    wrangler.toml
    src/index.js
  research/mock-research-result.json
  validation/mock-validation-result.json
  planning/mock-planning-result.json
  build/mock-building-result.json   # pipeline metadata, NOT the product
  testing/mock-testing-result.json
  release/mock-release-result.json
  growth/mock-growth-result.json
  metrics/latest-metrics.json
  deploy/deployment.json
```

`app/` is deliberately separate from `build/`: `build/` holds this stage's
metadata, and treating it as product output once made `deploy` offer to publish
the pipeline's own JSON files as a website.

Every result file is validated against `schemas/stage-result.schema.json` before
it is registered; a non-conformant result fails the run rather than poisoning the
state.

The mapping from stage to directory and artifact key lives in
`config/pipeline.yaml`.

---

## Writing real code (`building`)

The `building` stage is the one where the pipeline stops describing and starts
making. It is configured with `code_dir: app`, which changes three things:

1. The brief tells the agent to **write real files** to the absolute path
   `projects/<id>/app/`, not to paste code into its reply.
2. The orchestrator **verifies** the directory afterwards. A live run that
   reports success while `app/` is empty or missing is a hard failure:

```
ERROR: Stage 'building' 报告成功，但没有在 app/ 写出任何文件。
  该阶段要求产出真实代码；只有 JSON 摘要不算完成。
```

   Nothing is registered, so a confident summary can never stand in for a
   product.
3. A **manifest** of what was written is recorded on the artifact, so you can
   see the product without opening the directory:

```json
"build_result": {
  "path": "build/building-result.json",
  "mode": "live",
  "code": {
    "file_count": 3,
    "bytes": 128,
    "files": ["README.md", "src/index.js", "wrangler.toml"]
  }
}
```

The check applies to **live runs only**. The `mock` adapter is explicitly fake,
so demanding real files from it would be meaningless — and a mock run therefore
produces no `app/`, which is why `deploy` correctly refuses to deploy a
mock-built project.

### What the agent is told to build

The build brief is three skills plus everything the project has produced so far:

| Skill | Role |
|---|---|
| `indie-tech-architecture` | stack and platform constraints |
| `ai-coding-workflow` | working discipline (small steps, verify, keep quality) |
| `security-privacy-review` | least privilege, no hardcoded secrets, default-safe |

The **spec** comes from the planning artifacts, which are inlined into the same
brief. So the agent is not asked to invent a product: it is asked to implement
the MVP that `plan_result` already scoped, and it is told to prefer "minimal but
runnable" over "more features".

### Honest limits

Writing files is necessary but not sufficient. This stage checks that code
*exists*; the `testing` stage then runs the project's own tests (see below).
What is still unverified is that the code does anything *useful* — a suite of one
trivial assertion passes. Judging product quality remains your job at the
`before_code_merge` gate.

---

## Verifying it actually works (`testing`)

The `testing` stage used to ask an agent for a QA verdict. An agent can be
confident about code that nothing has executed, so the project's **own tests run
first**, and a red suite stops the pipeline before the agent is even called:

```
[testing] 运行项目自带的测试 ...
   ❌ 验证结果: failed
      命令: python -m pytest -q
      来源: Python project (tests)
      退出码: 1
ERROR: 测试未通过（failed）...
  状态仍是 'testing' 之前，修好后重跑即可；测试红了不能进入代码检视。
```

The agent is never invoked, `test_result` is not registered, and the transition
to the code-review gate cannot happen. Same principle as deployment: a fact about
the world gates the qualitative step, instead of a model's opinion standing in
for it.

### What command runs

Detected from what the project declares — never invented:

| Declared | Command |
|---|---|
| `package.json` -> `scripts.test` | `npm test` / `pnpm test` / `yarn test` / `bun test`, per the lockfile |
| pytest config, or a `tests/` / `test/` directory | `python -m pytest -q` |
| `Makefile` with a `test:` target | `make test` |

`npm init`'s placeholder script (`echo "Error: no test specified" && exit 1`) is
recognised as *no tests*, not as a failing suite — otherwise every fresh Node
project would report red.

Check what will run without executing anything:

```bash
./autopilot.py verify my-product --dry-run   # show the detected command
./autopilot.py verify my-product             # run it (no state changes)
```

### When nothing is declared

The run is recorded as `not_configured` and the stage **continues**, but the
result is explicitly marked unverified and the console says so:

```
⚠️  项目没有声明测试命令：本次运行**未经验证**，代码检视门会看到这一点。
```

The pipeline will not write tests on your behalf, and will not pretend it
verified something it did not. To make that fatal instead:

```yaml
# config/pipeline.yaml
verify:
  require_tests: true
```

### Dependencies

A generated Node project usually has no `node_modules`, and without them the
tests cannot run at all. By default the pipeline installs them first, using the
runner the lockfile implies, and announces it:

```
依赖未安装，先执行：npm install（可用 verify.install_dependencies 关闭）
```

Set `verify.install_dependencies: false` to be asked instead; the run then
reports `dependencies_missing`. Python projects need no install step.

### Evidence

Every run writes `projects/<id>/testing/test-run.json` **before** the agent
starts, so the brief it receives contains the real command, exit code and output
tail, and an `audit_log` entry of action `tests_run` is appended. On a red suite
that record is still written — the failure is preserved as evidence rather than
swallowed.

A mock-built project has no `app/`, so verification reports `no_code` and skips.
That is the honest outcome: there was nothing to test.

---

## 8. Running real work: skills + agent backends

There are two adapters:

| Adapter | What it does | When to use |
|---|---|---|
| `mock` (default) | Deterministic fake data for every stage | Wiring, tests, trying the flow |
| `skill` | Runs the real SKILL.md methodology through an agent backend | Actual work |

```bash
./autopilot.py run my-product --adapter mock    # fake, instant, offline
./autopilot.py run my-product --adapter skill   # real
```

### Agent backends

`skill` does not hard-depend on any particular AI tool. It composes a brief and
hands it to a **backend**, configured in `config/pipeline.yaml`:

| Backend | Needs | Notes |
|---|---|---|
| `handoff` (default) | nothing | Writes a task brief; you run it anywhere and save the JSON back |
| `claude` | `claude` CLI on PATH | `claude -p … --output-format json` |
| `codex` | `codex` CLI on PATH | `codex exec …` |
| *(any)* | — | Add one entry with a command template |

Select one per run:

```bash
./autopilot.py run my-product --adapter skill               # uses default_backend
AUTOPILOT_BACKEND=claude ./autopilot.py run my-product --adapter skill
```

Adding a new agent (CodeBuddy, DeepSeek Harness, a custom wrapper) is a config
edit, not code:

```yaml
backends:
  codebuddy:
    class: adapters.agent_backends.CommandBackend
    options:
      command: ["codebuddy", "run", "--file", "{prompt_file}"]
```

Command templates are executed **without a shell** — each placeholder stays a
single argv element, so prompts containing shell metacharacters cannot be
interpreted. Available placeholders: `{prompt}`, `{prompt_file}`, `{schema}`,
`{schema_file}`, `{work_dir}`, `{result_file}`.

### The handoff workflow

With no agent CLI configured (or no CLI that works non-interactively), the
default `handoff` backend turns each stage into a manual handoff:

```bash
$ ./autopilot.py run my-product --adapter skill
[researching] 运行 research agent ...

======================================================================
需要你手动执行这一步（handoff 模式）
======================================================================
任务书   : projects/my-product/research/task.md
输出要求 : projects/my-product/research/output.schema.json
结果写到 : projects/my-product/research/agent-result.json
...
```

1. `task.md` is a **self-contained** brief: it contains the full text of every
   skill configured for that stage, the contents of all existing artifacts, and
   the exact JSON contract to return.
2. Give `task.md` to any agent, in any window. Ask it for a single JSON object.
3. Save that JSON to `agent-result.json`.
4. Re-run the same command. The result is validated against
   `schemas/stage-result.schema.json`, the artifact is registered, and the
   pipeline continues to the next gate.

Because the brief is self-contained, it works in a plain chat window with no
filesystem access — but that also means it inlines artifact contents, truncated
at 4000 characters each by default.

### Which skills run at each stage

Configured under `skills:` in `config/pipeline.yaml`. Prompt size is the reason
this is explicit rather than "use everything": all 31 skills total ~165 KB, and
the growth stage alone would be ~49 KB. Current defaults are 2–3 focused skills
per stage.

To get richer (and more expensive) output, add more names:

```yaml
skills:
  planning:
    - product-positioning
    - mvp-scope-planner
    - product-requirements
    - product-ux-conversion      # add
    - indie-tech-architecture    # add
```

### Reducing failed handoff round-trips

A schema violation on a handoff result costs a full manual round-trip, so the
generated brief does not rely on the agent reading raw JSON Schema. It appends a
plain-language constraint summary extracted from the schema:

```
## 字段约束速查（必须逐条核对）
- 必填字段：project_id, stage, status, generated_at, summary
- `status` 只能取：success, partial, failed, skipped
- `evidence[].source_type` 只能取：web_search, api, document, observation, user_input, simulated, unavailable
- `evidence[].evidence_type` 只能取：fact, inference, assumption, unknown
```

The brief also refuses to let the agent invent data: skills are instructed to
mark anything unobtainable as `unavailable` rather than fabricate it, and
`product-validation`'s own rules forbid claiming demand without ≥3 independent
user quotes.

### Writing a new adapter (instead of a backend)

Only needed if a stage must do something other than "read skills, call an
agent". Implement `AgentAdapter` from `adapters/adapter_interface.py` and
register it under `adapters:` in `config/pipeline.yaml`:

```yaml
adapters:
  skill:
    module: adapters.skill_agent
    class: SkillAgentAdapter
```

`StageRequest` carries `work_dir` for scratch/handoff files, and adapters are
constructed with no arguments — read any configuration from
`config/pipeline.yaml` or the environment.

Adapters must **not** modify `state.json`, approve their own output, or read
credentials. The orchestrator owns state; approvals come from a human.

---

## 9. Deploying to Cloudflare

Deployment is the one step that is **not** an agent task. It is a shell command
whose success is what makes `launched` true, so it runs as a *pre-transition
action* on `release_pending -> launched`:

```
release_pending
  ⏸ GATE before_production_release      (you approve production)
  🚀 wrangler deploy                    (pre-transition action)
  -> launched                           (recorded only if the deploy succeeded)
```

This ordering matters. If the deploy fails, the project **stays at
`release_pending`** with no `deployment` artifact, so it is retryable and is
never falsely marked launched. A run that reaches `launched` has really
deployed.

### Commands

```bash
./autopilot.py deploy my-product              # gate -> deploy -> launched
./autopilot.py deploy my-product --dry-run    # print the command only
./autopilot.py deploy my-product --environment preview
./autopilot.py deploy my-product --yes        # auto-approve the gate
./autopilot.py deploy-status my-product       # URL, type, domain status
./autopilot.py domain my-product --domain myapp.com   # record the manual step
```

`deploy` is also reachable implicitly: `./autopilot.py run my-product` deploys
when it reaches that transition. `deploy` on an already-`launched` project
redeploys in place without touching state.

### Credentials

`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are read from the
environment, then from `.env` (gitignored). The first time they are needed you
are prompted for them, and they are saved to `.env` with mode `0600`. Values
are never echoed or printed, and are passed to wrangler through its environment
rather than on the command line.

If you prefer not to be prompted, put them in `.env` yourself:

```
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ACCOUNT_ID=...
```

### What gets deployed

Detected from the project directory, in this order:

| Found | Treated as | Command |
|---|---|---|
| `wrangler.toml` / `wrangler.json` / `wrangler.jsonc` | a Worker | `wrangler deploy` |
| `dist/` or `public/` or `build/` (non-empty) | a Pages site | `wrangler pages deploy <dir>` |

If neither exists, deployment fails with guidance rather than inventing a
placeholder site. (The pipeline's current build stage produces mock artifacts,
so there is nothing real to deploy yet -- that changes once the `building`
stage produces actual code.)

How wrangler is invoked is configurable in `config/pipeline.yaml`, or per-run:

```bash
AUTOPILOT_WRANGLER="pnpm dlx wrangler" ./autopilot.py deploy my-product
```

### The domain step is yours

Cloudflare custom domains need a dashboard action, so the pipeline stops and
prints instructions instead of pretending to do it. Once it is live, record it:

```bash
./autopilot.py domain my-product --domain myapp.com
```

That is written to `deploy/deployment.json` and the audit log; it does not
change the project's stage. `deploy-status` then reports it, and a later
redeploy preserves it.

### Deployment record

`projects/<id>/deploy/deployment.json` holds the provider, kind, environment,
URL, timestamp, the exact command, and up to ten previous deployments.

---

## 10. Closing the loop: real Search Console / GA4 data

Everything upstream of `growing` is a guess. This is where the pipeline reads
what actually happened: what Google showed, whether anyone clicked, and what
they did after arriving.

```bash
./autopilot.py metrics my-product --dry-run   # show config, call no APIs
./autopilot.py metrics my-product             # fetch, store, register
./autopilot.py metrics my-product --days 7    # shorter window
```

`metrics` registers the result as a `metrics` artifact, so the **next growth run
inlines real data into its brief**:

```bash
./autopilot.py metrics my-product
./autopilot.py run my-product --adapter skill   # growth now sees real numbers
```

### One-time setup (the part that actually takes effort)

Both APIs grant read access to a **service account**, which needs no browser
flow and no expiring refresh token:

1. <https://console.cloud.google.com> -> create/select a project
2. Enable **Search Console API** and **Google Analytics Data API**
3. IAM & Admin -> Service Accounts -> Create. Then Keys -> Add key -> JSON
4. Grant it access at the property level, or every call returns 403:
   - Search Console -> Settings -> Users and permissions -> add the service
     account email as **Full**
   - GA4 -> Admin -> Property access management -> add it as **Viewer**
5. Point the pipeline at the JSON key:

```bash
# in .env (gitignored), or let `autopilot metrics` prompt you once
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

`google-auth` is required for this step only; it is imported lazily, so the rest
of the pipeline works without it. If it is missing you get an install hint
rather than an import traceback.

### Which site / property

`config/sources.yml` says *how* to connect; `projects/<id>/metrics.yml` says
*which* site, because that differs per product. The command prompts for
anything missing and **saves it**, so you are asked once:

```yaml
# projects/my-product/metrics.yml
search_console:
  site_url: "sc-domain:example.com"      # or "https://example.com/"
analytics:
  property_id: "properties/123456789"
```

Then enable the sources globally:

```yaml
# config/sources.yml
search_console:
  enabled: true
analytics:
  enabled: true
```

### What it fetches

| Source | Dimensions | Metrics |
|---|---|---|
| Search Console | `query`, and separately `page` | clicks, impressions, CTR, average position |
| Analytics (GA4) | `sessionSourceMedium`, `landingPagePlusQueryString` | sessions, users |

It fetches the current window **and the previous one of the same length**, so
the report carries period-over-period deltas. CTR and position are
impression-weighted, not averaged across rows — averaging them would let a
one-impression query skew the picture.

GSC data lags, so the window ends two days before today rather than including a
half-populated final day.

### Opportunities are computed, not guessed

Two of the most actionable SEO facts are arithmetic, so the pipeline computes
them rather than asking a model:

| Type | Condition | Action |
|---|---|---|
| `striking_distance` | position 11-20, >=30 impressions | Build depth and internal links to push onto page one |
| `low_ctr` | >=50 impressions, CTR < 2% | Rewrite the title and meta description |

`striking_distance` wins when both apply, because ranking lifts impressions
*and* clicks; the low CTR is then recorded under `also` instead of being
duplicated. A query already ranking well with a healthy CTR is not flagged.

### When there is no real data

If sources are disabled, credentials are missing, or an API call fails, the
report says so instead of inventing numbers: `mode: "unavailable"`,
`is_real_data: false`, and the reason per source. `metrics` exits non-zero, and
the artifact is registered as **not** real data — so nothing downstream can
mistake a failure for feedback. A failure in one source does not lose the other.

### The iteration loop

`growing <-> iterating` is a cycle, so the growth analysis re-runs every time you
come back around:

```bash
./autopilot.py run my-product --to growing     # analyse (1st time)
./autopilot.py run my-product --to iterating   # ship the improvements
./autopilot.py run my-product --to growing     # analyse again — a NEW analysis
```

This is deliberate, because the opposite failure is silent. An artifact is only
treated as "already done" if it was produced **during the current visit** to that
stage. Coming back through `iterating` makes the previous `growth_review` stale,
so the stage runs again; resuming an interrupted run still skips completed work,
because its artifact postdates its own entry transition.

Before this was enforced, re-entering `growing` did nothing at all — you got last
round's conclusions while believing they were fresh.

### Which skills the growth stage runs

Ten skills, ~100 KB of methodology, because this is the stage that decides
whether the product is worth continuing:

| Skill | What it does with the data |
|---|---|
| `indie-product-reach` | cross-channel playbook (AI search, backlinks, communities, email, social proof) — ~60% of the brief |
| `product-analytics` | reads GA4 sessions/sources |
| `google-indexing-diagnostics` | reads GSC impressions/clicks/CTR |
| `conversion-optimization` | funnel work on GA4 data |
| `customer-feedback-loop` | turns feedback into the next iteration |
| `distribution-channel-research` | backlinks and channels |
| `content-marketing-engine` | topic clusters, content briefs, internal links |
| `pricing-monetization` | whether it can actually make money |
| `product-lifecycle-manager` | continue / pivot / maintain / stop |
| `project-retrospective` | what this iteration taught you |

If the prompt is too heavy, `indie-product-reach` is the lever — it alone is
about 60 KB. Remove it from `skills.growth` in `config/pipeline.yaml`.

`tests/test_skill_agent.py` fails if a stage silently loses these, or if skills
become orphaned beyond a documented allow-list (cross-project memory,
skill-library self-auditing, post-launch support docs, cost monitoring, and meta
workflow tooling — none of which has a stage today).

---

## 11. Seeing where things stand

`status` is terse. `report` is the full picture, in Markdown, and it is
opinionated about ordering:

```bash
./autopilot.py report my-product     # one project in full
./autopilot.py report --all          # every project at a glance
./autopilot.py report my-product --output report.md
```

The project report leads with **what is waiting for you** — a project sitting on
an ungranted gate is the most actionable fact there is, and nothing used to say
so — then:

| Section | Why it is there |
|---|---|
| 概览 | stage, status, timestamps |
| 待办 | the pending gate, the exact `approve` command, and which requirements are ✅/❌ |
| 产物 | every artifact with its **provenance**: `mock` artifacts are labelled "not evidence" |
| 真实数据 | GSC clicks/impressions/CTR, period deltas, computed SEO opportunities, GA4 totals, the test run, the deployment URL and domain |
| 代码 | the build stage's file manifest |
| 批准记录 | who approved what, and through which gate |
| 最近动态 | the audit timeline |

The portfolio view flags waiting projects and counts real-data artifacts per
project, so you can see at a glance which of several products needs a decision:

```
| 项目      | 阶段    | 待办                  | 真实数据 | 最近更新 |
| `alpha`   | testing | ⏸ before_code_merge  | 3 项     | ...      |

## 等待你处理
- **alpha**：`before_code_merge`（testing → release_pending） → `./autopilot.py run alpha`
```

`./autopilot.py list` also marks waiting projects with `⏸`, which is the fastest
way to answer "is anything blocked on me?".

This replaces `scripts/generate_report.py`, which was left over from the GitHub
flow and — after the move to a local driver — was no longer called by anything.

### Concurrent runs

Each state-mutating command takes an exclusive per-project lock
(`projects/<id>/.lock`). Two runs on the same project no longer interleave:

```
$ ./autopilot.py run my-product    # in one terminal
ERROR: 另一个 autopilot 进程正在操作 my-product（pid=1794 since=...）。
  等它结束后重试；如果确认没有进程在跑，锁会随进程退出自动释放。
```

The lock is advisory and released by the kernel if the process dies, so a stale
lock file is never a problem. The old GitHub workflows got this from
`concurrency:` groups; locally nothing provided it and two runs could silently
overwrite each other's `state.json`.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Approval required but stdin is not a TTY` | You are in a script/pipe. Run interactively, use `--yes`, or pre-grant with `approve`. |
| `No valid route from 'X' to 'Y'` | There is no legal path (e.g. moving backwards). Use `move --force --reason`. |
| `Missing required artifact: 'build_result'` | The stage that produces it has not run. Run to that stage; the orchestrator registers it automatically. |
| `Artifact 'X' file not found` | An artifact is registered but its file was deleted. Re-run that stage; it regenerates. |
| `does not match '^[a-z0-9]...'` | Bad `project_id`. Use lowercase hyphenated ids, at least 3 chars. |
| `Aborted at gate; state left unchanged` | You answered `q`. Nothing was written. |
| `Unknown target stage 'research'` | Stage names are state-machine names: use `researching`, not `research`. |
| `缺少 Cloudflare 凭据` | Put them in `.env`, or run in an interactive terminal to be prompted. |
| `没有可部署的内容` | Neither a wrangler config nor a non-empty `dist/`/`public/`/`build/` exists. See [section 9](#9-deploying-to-cloudflare). |
| `部署失败：...` and the project is still `release_pending` | Correct behaviour -- a failed deploy must not mark the project launched. Fix the cause and re-run `deploy`. |
| npm cache `EPERM` errors | The sandbox blocks npm's cache writes. Run `deploy` outside a restricted sandbox, or install wrangler globally and set `AUTOPILOT_WRANGLER=wrangler`. |
| `项目处于 'X'，不能部署` | Only `release_pending` (first deploy) and `launched` (redeploy) can be deployed. |
| `缺少 Google 服务账号密钥` | Set `GOOGLE_APPLICATION_CREDENTIALS` in `.env`, or run interactively to be prompted. |
| `权限不足（403）` | Add the service-account email to the property: Full in Search Console, Viewer in GA4. |
| `未配置 search_console.site_url` | Let the command prompt you (it saves the answer), or write `projects/<id>/metrics.yml`. |
| `没有取到任何真实数据` | Expected when sources are disabled or credentials are missing. Check with `metrics --dry-run`. |
| `报告成功，但没有在 app/ 写出任何文件` | The agent returned JSON without writing code. In handoff mode, run `task.md` in an agent that can write files, pointed at that absolute path. |
| `没有可部署的内容` on a mock-built project | Expected: mock builds produce no `app/`. Build with a live adapter first. |
| `测试未通过（failed）` | The project's own tests failed. The pipeline stopped before the QA agent; fix the code and re-run. |
| `dependencies_missing` | Dependencies could not be installed. Run the install by hand, or set `verify.install_dependencies: false` to be asked instead. |
| `not_configured` but you expected tests | The project declares no test command. See the detection table above; `verify --dry-run` shows what was found. |
| `no_code` | There is no `app/` yet. A mock build produces none — build with a live adapter first. |
| Re-entering `growing` seems to do nothing | It should now re-run; if it does not, check `--rerun`. The artifact is stale-by-design on a loop-back. |
| `另一个 autopilot 进程正在操作 <project>` | Another run holds the project lock. Wait for it, or check nothing is still running. |

Useful diagnostic:

```bash
./autopilot.py --verbose status my-product
python scripts/check_transition.py --project-dir projects/my-product --to-stage validating
```

---

## 13. Version control (optional)

Nothing in the pipeline requires git. If you do use it, committing `state.json`
alongside artifacts gives you a readable history and easy rollback, since the
audit log is part of the state file:

```bash
git add projects/my-product
git commit -m "advance my-product to building"
```

The orchestrator never commits on your behalf, so your working tree stays under
your control.
