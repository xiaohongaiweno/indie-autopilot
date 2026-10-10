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
  research/mock-research-result.json
  validation/mock-validation-result.json
  planning/mock-planning-result.json
  build/mock-building-result.json
  testing/mock-testing-result.json
  release/mock-release-result.json
  growth/mock-growth-result.json
```

Every result file is validated against `schemas/stage-result.schema.json` before
it is registered; a non-conformant result fails the run rather than poisoning the
state.

The mapping from stage to directory and artifact key lives in
`config/pipeline.yaml`.

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

## 10. Troubleshooting

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

Useful diagnostic:

```bash
./autopilot.py --verbose status my-product
python scripts/check_transition.py --project-dir projects/my-product --to-stage validating
```

---

## 11. Version control (optional)

Nothing in the pipeline requires git. If you do use it, committing `state.json`
alongside artifacts gives you a readable history and easy rollback, since the
audit log is part of the state file:

```bash
git add projects/my-product
git commit -m "advance my-product to building"
```

The orchestrator never commits on your behalf, so your working tree stays under
your control.
