# Approval Policy

> **Note (local approvals):** approval is now obtained locally. `autopilot run`
> pauses at each gate and asks `[y]批准 [n]拒绝 [q]退出`; the decision is written
> to `state.json`'s `approved_stages` array by `scripts/orchestrator.py`. GitHub
> Issues and `/approve` comments are no longer part of the mechanism.
> `autopilot approve --stage <stage>` pre-grants a gate.
>
> The gate *rules* below (which transitions are gated, their risk levels, and
> what they protect) still apply. The artifact-hash binding and expiration
> mechanisms described in this document are **not implemented** -- see
> [local-usage.md](local-usage.md#5-how-approvals-are-stored).

indie-autopilot uses human approval gates at critical decision points to prevent automated systems from making irreversible or high-cost decisions without human review.

This document defines the approval rules, mechanisms, and constraints.

## Approval Gates

There are 6 approval gates in the pipeline. Each protects a specific decision point.

Note: entering validation (`validation_pending -> validating`) is deliberately
**not** gated. Approving the opportunity itself -- via `autopilot radar`, or by
creating the project -- is already the human decision to spend validation effort.

### 1. before_design

**Location:** validation_approved -> planning

**Purpose:** Validation passed; decide whether the opportunity is worth investing design and MVP-scoping time in.

**Risk level:** Medium

**Required artifacts:**
- validation_result

**What it protects:** Prevents a validated-but-unattractive opportunity from consuming design effort. Without this gate the pipeline moved straight from "validation passed" into planning with no human in the loop.

### 2. before_mvp_commit

**Location:** planning -> plan_approved

**Purpose:** Before committing to MVP scope, budget, and timeline, review the validation results and positioning.

**Risk level:** Medium

**Required artifacts:**
- validation_result
- positioning_draft

**What it protects:** Prevents building the wrong product or committing to an unvalidated scope.

### 3. before_code_merge

**Location:** testing -> release_pending (code review before the release path)

**Purpose:** Review the AI-generated code together with the test results before it moves toward release.

**Risk level:** High

**Required artifacts:**
- test_result
- security_review

**What it protects:** Prevents unreviewed code from reaching production, catches security issues early. It sits after `testing` rather than after `building` so the reviewer has the test results in hand, which is what this gate declares it requires.

### 4. before_production_release

**Location:** release_pending -> launched

**Purpose:** Before deploying to production, confirm the release checklist and rollback plan are complete.

**Risk level:** Critical

**Required artifacts:**
- release_checklist
- rollback_plan

**What it protects:** Prevents broken or unready products from reaching users. Ensures rollback capability.

### 5. before_paid_service

**Location:** Any stage that activates paid services or increases budget

**Purpose:** Before activating any paid service (hosting, API, advertising), review cost estimates and get budget approval.

**Risk level:** High

**Required artifacts:**
- cost_estimate
- budget_approval

**What it protects:** Prevents unexpected costs and ensures budget alignment.

### 6. failed -> discovered (reset approval)

**Location:** failed -> discovered

**Purpose:** Before resetting a failed project back to the start, confirm the reset is intentional.

**Risk level:** Medium

**Required artifacts:** None

**What it protects:** Prevents accidental loss of work by requiring explicit approval to discard a failed project.

## How Approvals Are Recorded

An approval is an entry in `state.json`'s `approved_stages` array:

```json
{
  "stage": "planning",
  "approved_at": "2026-01-01T12:00:00+00:00",
  "approval_id": "appr-planning-20260101T120000Z",
  "approved_by": "yourname",
  "mode": "local",
  "gate": "before_design"
}
```

`stage` is the **target** stage of the gated transition, not the stage being left.

That array is the only approval representation. `scripts/state_machine.py` reads
it when evaluating a transition, `scripts/orchestrator.py` writes it, and
`scripts/check_transition.py` reads the same thing. There is no separate
approval file, and therefore no way for two components to disagree about what an
approval is.

### How an approval is granted

| Route | Command | Notes |
|---|---|---|
| At the gate | `./autopilot.py run <project>` | prompts `[y]批准 [n]拒绝 [q]退出` |
| Unattended | `./autopilot.py run <project> --yes` | approves each gate it meets |
| Ahead of time | `./autopilot.py approve <project> --stage <target>` | after reviewing an artifact yourself |

A refusal is recorded as an `approval_rejected` audit entry and the project stays
put, so nothing downstream runs.

### What is deliberately not implemented

- **Artifact hash binding.** An approval is not tied to the hash of the artifact
  it covered, so regenerating an artifact with `--rerun` does not invalidate it.
  If that matters, re-approve explicitly.
- **Expiry.** Approvals do not expire.
- **Remote or cryptographic identity.** `approved_by` is your local username,
  recorded for the audit trail; it is not verified.

An earlier version of this document specified these, and
`schemas/approval.schema.json` encoded them. Neither existed in code -- the
orchestrator wrote a different, simpler shape -- so the schema was misleading
and has been removed rather than left as a promise, and this section now says
what is actually true.

## Identity Verification

- Approvals record `approved_by` (your local username) and `approved_at`.
- **Adapters never approve.** The component that produces an artifact has no
  access to `approved_stages`; approvals are written only by
  `scripts/orchestrator.py`.
- **A model cannot approve its own output.** The gate is answered from a TTY, or
  waived explicitly with `--yes`, or pre-granted with `approve`. There is no
  code path where an agent's response becomes an approval.

## Emergency Overrides

```bash
./autopilot.py move <project> --to <stage> --force --reason "..."
```

This bypasses gates and artifact checks. It is the documented escape hatch, and
it is always audited:

```json
{
  "action": "forced_transition",
  "actor": "yourname",
  "from_stage": "building",
  "to_stage": "testing",
  "reason": "hotfix verification",
  "warning": "gates and artifact requirements were bypassed"
}
```

`--reason` is mandatory and `--force` must be passed explicitly, so an override
can never happen by accident, and its audit entry states plainly that gates were
skipped.

## What Cannot Be Auto-Approved

These always require an explicit human decision:

1. **Production releases** -- the `before_production_release` gate. The deploy
   then runs as a pre-transition action, so a failure cannot mark a project
   launched.
2. **Paid service activation** -- `before_paid_service`. Declared for future use;
   no stage is wired to it yet.
3. **Failed project resets** -- `failed -> discovered` requires approval, so a
   failed project is not silently discarded.
4. **Emergency overrides** -- need `--force` plus a documented reason.

Why: production releases are hard to undo and affect real users; paid services
have financial consequences; a failed project may still hold work worth keeping.

## Summary

The gate policy is real and enforced: the transitions listed under
[Approval Gates](#approval-gates) cannot be crossed without an entry in
`approved_stages`, and that entry is written only in response to a human
decision.

Everything else that used to be described here -- hash binding, expiry,
identity verification, a separate approval record format -- was aspirational.
It is listed above as not implemented rather than presented as a feature.
