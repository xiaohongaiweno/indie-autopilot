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

### 1. before_deep_validation

**Location:** validation_pending -> validating

**Purpose:** Before investing time in deep opportunity validation, confirm the initial research is worth pursuing.

**Risk level:** Low

**Required artifacts:**
- research_summary
- evidence_files

**What it protects:** Prevents wasting validation effort on opportunities that don't pass initial research review.

### 2. before_mvp_commit

**Location:** planning -> plan_approved

**Purpose:** Before committing to MVP scope, budget, and timeline, review the validation results and positioning.

**Risk level:** Medium

**Required artifacts:**
- validation_result
- positioning_draft

**What it protects:** Prevents building the wrong product or committing to an unvalidated scope.

### 3. before_code_merge

**Location:** building -> testing (when merging AI-generated code)

**Purpose:** Before merging AI-generated code to the main branch, review test results and security.

**Risk level:** High

**Required artifacts:**
- test_results
- security_review

**What it protects:** Prevents unreviewed code from reaching production, catches security issues early.

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

Approvals are recorded as JSON files that conform to `schemas/approval.schema.json`.

### Approval record structure

```json
{
  "approval_id": "appr-validation-20250101",
  "project_id": "my-product",
  "stage": "validating",
  "decision": "approved",
  "approved_by": "github-username",
  "approved_at": "2025-01-01T12:00:00Z",
  "artifact_hash": "sha256:abc123...",
  "comment": "Research looks solid. Proceeding to validation.",
  "source_event": "https://github.com/owner/repo/issues/42",
  "expires_at": "2025-01-08T12:00:00Z"
}
```

### Approval creation flow

1. **Workflow reaches approval gate** -- State machine detects that a transition requires approval.
2. **GitHub Issue created** -- `scripts/create_issue.py` creates an issue with:
   - Title: "Approval required: [stage] for [project-id]"
   - Labels: `approval`, `[stage]`, `project-[project-id]`
   - Body: Links to artifacts, summary of what needs review
3. **Human reviews** -- The project owner reviews the artifacts linked in the issue.
4. **Human approves** -- By commenting "approved" or closing the issue with an approval comment.
5. **Approval record written** -- A JSON file is created with the approval details.
6. **State machine validates** -- `scripts/check_transition.py` verifies the approval record exists and is valid.
7. **Transition proceeds** -- The state machine advances to the next state.

### Approval storage

Approval records are stored in the project's `approved_stages` array in `state.json`:

```json
{
  "approved_stages": [
    {
      "stage": "validating",
      "approved_at": "2025-01-01T12:00:00Z",
      "approval_id": "appr-validation-20250101"
    }
  ]
}
```

## Identity Verification

Only the person who approves via the defined mechanism counts.

### Rules

- **GitHub authentication required** -- Approvals must come from an authenticated GitHub user.
- **Project owner only** -- Only the repository owner or designated approvers can approve.
- **No self-approval by adapters** -- Agent adapters cannot approve their own output.
- **Approval must match project** -- The `project_id` in the approval record must match the project being transitioned.
- **Approval must match stage** -- The `stage` in the approval record must match the target stage of the transition.

### Verification mechanism

The `scripts/check_transition.py` script validates approvals by:

1. Loading the approval file specified in `--approval-file`
2. Validating it against `schemas/approval.schema.json`
3. Checking that `project_id` matches the project's state.json
4. Checking that `stage` matches the target stage
5. Checking that `decision` is "approved" (not "rejected" or "changes_requested")

## Artifact Hash Binding

Approvals are bound to specific artifact versions via SHA-256 hashes.

### How it works

1. **Approval created** -- When a human approves, the `artifact_hash` field records the SHA-256 hash of the artifact that was reviewed.
2. **Artifact changes** -- If the artifact is modified (e.g., research results are updated), the hash changes.
3. **Approval invalidated** -- The state machine checks the current artifact hash against the approval's `artifact_hash`. If they don't match, the approval is invalid.

### Example

```json
{
  "approval_id": "appr-validation-20250101",
  "artifact_hash": "sha256:abc123...",
  ...
}
```

If the research artifact is updated and its hash becomes `sha256:def456...`, the approval is no longer valid. A new approval is required.

### Why this matters

Prevents approving an artifact and then modifying it without re-approval. Ensures the human reviewed the exact version that will be used.

## Expiration

Approvals expire after 7 days or if artifacts change.

### Expiration rules

- **Time-based** -- Approvals have an `expires_at` field set to 7 days after approval.
- **Artifact-based** -- If the artifact hash changes, the approval is immediately invalidated.
- **Explicit revocation** -- Approvals can be revoked by creating a new approval record with `decision: "rejected"`.

### Checking expiration

The state machine checks expiration by:

1. Loading the approval record from `approved_stages`
2. Comparing `expires_at` to the current time
3. If expired, the approval is invalid and a new one is required

### Why expiration matters

Context changes over time. An approval granted a week ago may no longer be valid if:
- Market conditions changed
- New competitor entered the space
- Technical constraints discovered
- User feedback received

Expiration forces re-review of stale decisions.

## Emergency Overrides

Manual state changes require documented justification.

### When to use emergency overrides

- **Critical bug in production** -- Need to rollback without going through the full release pipeline
- **Security vulnerability** -- Need to patch immediately
- **Data loss risk** -- Need to reset state to recover

### Override procedure

1. **Document the justification** -- Create a GitHub Issue with:
   - Title: "EMERGENCY OVERRIDE: [reason]"
   - Labels: `emergency`, `override`
   - Body: Detailed explanation of why the override is necessary
2. **Get explicit approval** -- The project owner must comment on the issue approving the override.
3. **Record the override** -- The state change is recorded in the audit log with:
   - `action: "emergency_override"`
   - `actor: "github-username"`
   - `details: "Issue #123: [reason]"`
4. **Resume normal flow** -- After the emergency is resolved, resume the normal approval flow.

### Override constraints

- **Audit trail required** -- Every override must be recorded in the audit log.
- **Justification required** -- No overrides without documented reasons.
- **Post-override review** -- After the emergency, review what went wrong and update processes to prevent recurrence.

## What Cannot Be Auto-Approved

Certain decisions require explicit human approval and cannot be automated.

### Non-auto-approvable actions

1. **Production releases** -- Deploying to production always requires human approval (before_production_release gate).
2. **Paid service activation** -- Activating paid services or increasing budget always requires approval (before_paid_service gate).
3. **Data deletion** -- Deleting user data or project artifacts requires explicit approval.
4. **Emergency overrides** -- Manual state changes require documented justification and approval.
5. **Failed project resets** -- Resetting a failed project to discovered requires approval to prevent accidental data loss.

### Why these cannot be auto-approved

- **Irreversible** -- Production releases, data deletion, and paid services are hard to undo.
- **High cost** -- Paid services have financial consequences.
- **User impact** -- Production releases affect real users.
- **Compliance** -- Data deletion may have legal implications.

## Approval and Rejection Flow Examples

### Example 1: Validation approval

**Scenario:** Research is complete, ready for deep validation.

1. **State:** Project is in `validation_pending`
2. **Workflow:** Creates GitHub Issue #42 with title "Approval required: validation for my-product"
3. **Human reviews:** Reads research artifacts, checks evidence quality
4. **Human approves:** Comments "approved" on Issue #42
5. **Approval record created:**
   ```json
   {
     "approval_id": "appr-validation-20250101",
     "project_id": "my-product",
     "stage": "validating",
     "decision": "approved",
     "approved_by": "owner",
     "approved_at": "2025-01-01T12:00:00Z",
     "artifact_hash": "sha256:abc123...",
     "source_event": "https://github.com/owner/repo/issues/42",
     "expires_at": "2025-01-08T12:00:00Z"
   }
   ```
6. **Transition check:** `python scripts/check_transition.py --project-dir projects/my-product --to-stage validating --approval-file approval.json`
7. **Result:** TRANSITION OK: validation_pending -> validating
8. **State updated:** Project moves to `validating`

### Example 2: Validation rejection

**Scenario:** Research is incomplete, needs more work.

1. **State:** Project is in `validation_pending`
2. **Workflow:** Creates GitHub Issue #43
3. **Human reviews:** Finds evidence is weak, assumptions not validated
4. **Human rejects:** Comments "rejected: need more competitor analysis" on Issue #43
5. **Approval record created:**
   ```json
   {
     "approval_id": "appr-validation-20250102",
     "project_id": "my-product",
     "stage": "validating",
     "decision": "rejected",
     "approved_by": "owner",
     "approved_at": "2025-01-02T10:00:00Z",
     "artifact_hash": "sha256:abc123...",
     "comment": "Need more competitor analysis",
     "source_event": "https://github.com/owner/repo/issues/43"
   }
   ```
6. **Transition check:** Fails because decision is "rejected"
7. **Result:** TRANSITION BLOCKED: Approval decision is 'rejected', expected 'approved'
8. **State unchanged:** Project stays in `validation_pending`
9. **Next action:** Run additional research, update artifacts, request new approval

### Example 3: Approval expiration

**Scenario:** Approval was granted 8 days ago.

1. **State:** Project has approval record with `expires_at: 2024-12-25T12:00:00Z`
2. **Current time:** 2025-01-02T12:00:00Z (8 days later)
3. **Transition check:** State machine checks `expires_at` vs current time
4. **Result:** TRANSITION BLOCKED: Approval expired at 2024-12-25T12:00:00Z
5. **Action required:** Request new approval

### Example 4: Artifact hash mismatch

**Scenario:** Research artifact was updated after approval.

1. **State:** Approval record has `artifact_hash: sha256:abc123...`
2. **Artifact updated:** Research artifact modified, new hash is `sha256:def456...`
3. **Transition check:** State machine compares current artifact hash to approval hash
4. **Result:** TRANSITION BLOCKED: Artifact hash mismatch
5. **Action required:** Review updated artifact and request new approval

## Summary

Approval gates are the safety mechanism that prevents automated systems from making irreversible decisions without human oversight. They enforce:

- **Human review** at critical decision points
- **Artifact integrity** via hash binding
- **Temporal validity** via expiration
- **Identity verification** via GitHub authentication
- **Audit trail** for all approvals and rejections

The approval system is designed to be lightweight (GitHub Issues) but rigorous (hash binding, expiration, identity verification). It balances automation speed with human judgment at the moments that matter most.
