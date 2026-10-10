# Recovery Runbook

> **Driver:** this runbook now uses the local driver. Recovery is
> `./autopilot.py run <project>` (resumes from `state.json`) or
> `./autopilot.py move <project> --to <stage> --force --reason "..."` for an
> audited override. See [local-usage.md](local-usage.md).

When things break -- and they will -- this runbook tells you how to diagnose and recover. The state machine has built-in recovery paths, but you need to know which one to use.

## Failure Classification

All failures fall into one of four categories. Identifying the category first tells you the recovery path.

### 1. Transient Failures (retry)

**Symptoms:**
- Timeouts during adapter execution
- Network errors (DNS, connection refused, 5xx responses)
- GitHub API rate limiting
- Temporary service unavailability

**Diagnosis:**
- Check the workflow run logs for timeout or network error messages
- Look for `TimeoutError` or HTTP 5xx status codes
- Check if the external service status page reports issues

**Recovery:**
- Wait and retry. The workflow has built-in retry logic based on `retry_limit` in `config/workflow-policy.yml`.
- If retries are exhausted, manually re-trigger the workflow.

```bash
# Re-trigger a workflow
./autopilot.py radar
```

**When to escalate:** If the same transient failure occurs 3+ times in a row, investigate the underlying service.

### 2. Deterministic Failures (fix and retry)

**Symptoms:**
- Schema validation errors
- Missing required artifacts
- Invalid JSON in state files
- Adapter returns `status: "failed"` with specific error messages

**Diagnosis:**
- Check the workflow logs for validation error messages
- Run `python scripts/validate_artifact.py` manually on the failing artifact
- Check `state.json` for structural issues

**Recovery:**
1. Fix the root cause (update the artifact, fix the schema, correct the state file)
2. Validate the fix
3. Retry the transition

```bash
# Validate the failing artifact
python scripts/validate_artifact.py \
  --schema schemas/stage-result.schema.json \
  --artifact projects/my-product/research/discovery-result.json

# Check if the transition is now valid
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage validating

# If OK, re-trigger the workflow
./autopilot.py run my-product --adapter skill
```

**When to escalate:** If you cannot determine the root cause from the error messages, check the audit log for context.

### 3. Blocked States (needs human)

**Symptoms:**
- Project is in `blocked` state
- Workflow cannot proceed without external input
- Approval is pending or expired

**Diagnosis:**
- Check `state.json` for `stage: "blocked"`
- Look at the audit log to see what caused the block
- Check if there are pending approval issues on GitHub

**Recovery:**

The `blocked` state has three recovery options:

```
blocked -> researching   (retry research with new information)
blocked -> validating    (retry validation if block was temporary)
blocked -> building      (retry build if block was infrastructure-related)
```

```bash
# Check what transitions are valid from blocked
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage researching

# If the transition is valid, manually update state.json
# (or re-trigger the appropriate workflow)
```

**Manual state update (if needed):**

```bash
# Edit state.json to change stage
# WARNING: This bypasses the state machine. Use only when necessary.
cd projects/my-product
# Edit state.json: change "stage" from "blocked" to "researching"
# Add audit log entry documenting the manual change

# Validate the updated state
python scripts/validate_artifact.py \
  --schema schemas/project.schema.json \
  --artifact projects/my-product/state.json
```

**When to escalate:** If the block is due to a fundamental problem with the opportunity (e.g., market doesn't exist), consider moving to `rejected` instead of retrying.

### 4. Failed States (needs reset)

**Symptoms:**
- Project is in `failed` state
- Multiple retries have been exhausted
- Deterministic failure that cannot be fixed without starting over

**Diagnosis:**
- Check `state.json` for `stage: "failed"`
- Review the audit log to see the failure sequence
- Check if the failure is recoverable or fundamental

**Recovery:**

The `failed` state has two recovery options:

```
failed -> discovered    (full reset, requires approval)
failed -> researching   (retry research without full reset)
```

**Option A: Reset to discovered (full reset)**

This discards all progress and starts over. Requires approval to prevent accidental data loss.

```bash
# Create an approval record for the reset
cat > projects/my-product/reset-approval.json << 'EOF'
{
  "approval_id": "appr-reset-20250101",
  "project_id": "my-product",
  "stage": "discovered",
  "decision": "approved",
  "approved_by": "your-github-username",
  "approved_at": "2025-01-01T12:00:00Z",
  "artifact_hash": "",
  "comment": "Resetting due to fundamental flaw in research approach",
  "source_event": "manual"
}
EOF

# Check the transition
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage discovered \
  --approval-file projects/my-product/reset-approval.json

# If OK, update state.json manually or via workflow
```

**Option B: Retry research (partial reset)**

This keeps the project identity but restarts from the research stage.

```bash
# Check the transition
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage researching

# If OK, re-trigger the research workflow
./autopilot.py run my-product --adapter skill
```

**When to escalate:** If the failure is due to a fundamental problem with the product idea, consider moving to `rejected` and starting a completely new project.

## How to Reset a Project to a Previous State

Sometimes you need to roll back a project to an earlier state (e.g., undo a transition that was made in error).

### Procedure

1. **Identify the target state** -- Determine which state you want to roll back to.
2. **Check if a valid transition exists** -- Use `check_transition.py` to see if the state machine allows the transition.
3. **If no valid transition exists** -- You need a manual override (see Emergency Overrides below).
4. **Update state.json** -- Change the `stage` field to the target state.
5. **Add audit log entry** -- Document the rollback with a clear explanation.
6. **Validate the state** -- Run `validate_artifact.py` to ensure the state file is still valid.

### Example: Roll back from testing to building

```bash
# Check if the transition is valid
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage building

# If blocked (no direct transition), you need a manual override
```

### Manual override procedure

```bash
# 1. Create a GitHub Issue documenting the override
gh issue create \
  --title "EMERGENCY OVERRIDE: Roll back my-product from testing to building" \
  --body "Reason: Discovered critical bug in build artifact that needs to be fixed before testing." \
  --label "emergency,override"

# 2. Edit state.json
cd projects/my-product
# Change "stage" from "testing" to "building"
# Add audit log entry:
# {
#   "timestamp": "2025-01-01T12:00:00Z",
#   "action": "emergency_override",
#   "actor": "your-github-username",
#   "from_stage": "testing",
#   "to_stage": "building",
#   "details": "Issue #123: Roll back to fix critical bug"
# }

# 3. Validate the updated state
python scripts/validate_artifact.py \
  --schema schemas/project.schema.json \
  --artifact projects/my-product/state.json
```

## How to Handle Stuck Transitions

A stuck transition is one that cannot proceed because of missing artifacts, expired approvals, or other blockers.

### Diagnosis

```bash
# Check what's blocking the transition
python scripts/check_transition.py \
  --project-dir projects/my-product \
  --to-stage validating

# Common output:
# TRANSITION BLOCKED: Missing required artifact: 'research_result'.
# TRANSITION BLOCKED: Approval required for stage 'validating' but no matching entry found in approved_stages.
# TRANSITION BLOCKED: Approval expired at 2024-12-25T12:00:00Z.
```

### Recovery by blocker type

**Missing artifact:**
- Run the stage that produces the artifact
- Or manually create the artifact if it was lost

```bash
# Re-run discovery to produce research_result
python adapters/mock_agent.py \
  --stage discovery \
  --project-id my-product \
  --output-dir projects/my-product/research/

# Update state.json to reference the new artifact
# Then re-check the transition
```

**Approvals do not expire.** An approval stays valid until you revoke it. If you
want to re-confirm a decision, re-run the pipeline and decline the gate, then
approve again — or simply approve the new target stage.

**Missing approval:**

Approvals are written by the pipeline, never by hand:

```bash
# See what is waiting and what it needs
./autopilot.py report my-product

# Approve the next gate
./autopilot.py approve my-product --stage planning

# Or run interactively and answer the prompt
./autopilot.py run my-product
```

If you are editing `state.json` directly, the shape is a list of entries whose
`stage` is the **target** stage:

```json
"approved_stages": [
  {"stage": "planning", "approved_at": "...", "approval_id": "appr-...", "approved_by": "you"}
]
```

Prefer `autopilot approve` — it fills in the id, the actor, and the audit entry.

**Artifact file not found:**
- Check if the artifact file exists at the path specified in state.json
- If the file was moved or deleted, update the path in state.json or restore the file

```bash
# Check what artifacts are referenced in state.json
cat projects/my-product/state.json | jq '.artifacts'

# Verify the files exist
ls -la projects/my-product/research/
```

## How to Deal with Expired Approvals

Approvals expire after 7 days or if artifacts change. When an approval expires, the transition is blocked until a new approval is granted.

### Checking approval expiration

```bash
# Look at approved_stages in state.json
cat projects/my-product/state.json | jq '.approved_stages[]'

# Check the expires_at field
# If expires_at is in the past, the approval is expired
```

### Getting a new approval

1. **Review the artifacts** -- Make sure they are still valid and relevant.
2. **Re-approve the gate** -- `./autopilot.py approve <project> --stage <target>`, noting in your own records why it is being re-confirmed.
3. **Get approval** -- Follow the normal approval flow.
4. **Update state.json** -- Add the new approval to `approved_stages`.

### Preventing expiration

- **Approve promptly** -- Don't let approval issues sit for more than a few days.
- **Batch approvals** -- If multiple stages need approval, review them together.
- **Set reminders** -- GitHub notifications can remind you of pending approvals.

## Common Error Messages and Their Meanings

### "No transition defined from 'X' to 'Y'"

**Meaning:** The state machine does not allow a direct transition from state X to state Y.

**Fix:** Check the state diagram in `docs/architecture.md` to see valid transitions. You may need to go through an intermediate state.

### "Missing required artifact: 'X'"

**Meaning:** The transition requires an artifact with key 'X' in state.json, but it's not present.

**Fix:** Run the stage that produces the artifact, or manually add it to state.json if it was lost.

### "Approval required for stage 'X' but no matching entry found in approved_stages"

**Meaning:** The transition requires human approval, but no approval record exists in state.json.

**Fix:** Create a GitHub Issue for approval, get the approval, and add it to `approved_stages`.

### "Approval decision is 'rejected', expected 'approved'"

**Meaning:** An approval record exists, but the decision is "rejected" or "changes_requested".

**Fix:** Address the feedback, update artifacts if needed, and request a new approval.

### "Artifact 'X' file not found: path/to/file.json"

**Meaning:** The artifact is referenced in state.json, but the file does not exist on disk.

**Fix:** Restore the file from backup, or update the path in state.json to point to the correct location.

### "Transition 'X' -> 'Y' requires approval but no --approval-file was provided"

**Meaning:** You're running `check_transition.py` without specifying the approval file for a transition that requires approval.

**Fix:** Add `--approval-file path/to/approval.json` to the command.

### "Schema file not found: schemas/X.schema.json"

**Meaning:** The JSON Schema file is missing.

**Fix:** Check that the schema file exists in the `schemas/` directory. If it was deleted, restore it from git.

### "Could not import state_machine module"

**Meaning:** The `state_machine.py` script cannot be found or imported.

**Fix:** Ensure you're running the script from the project root, or that the `scripts/` directory is in the Python path.

## When to Escalate to Manual Intervention

Most failures can be recovered using the procedures above. However, some situations require manual intervention.

### Escalate when:

1. **Multiple recovery attempts have failed** -- If you've tried 3+ recovery paths and none work, the problem may be fundamental.

2. **State file is corrupted** -- If `state.json` is invalid JSON or fails schema validation in a way that cannot be fixed, you may need to reconstruct it from the audit log.

3. **Audit log is inconsistent** -- If the audit log doesn't match the current state, there may be a bug in the state machine or manual edits have caused drift.

4. **Approval chain is broken** -- If approvals reference artifacts that no longer exist, or if the approval chain has gaps, you may need to rebuild the approval history.

5. **Unknown state** -- If the project is in a state that is not one of the 17 valid states, the state file has been corrupted.

### Manual intervention procedure

1. **Stop all workflows** -- Don't trigger new workflows until the problem is diagnosed.

```bash
# Check running workflows
./autopilot.py radar-list
# Cancel if needed
gh run cancel <run-id>
```

2. **Backup the current state** -- Copy the project directory to a backup location.

```bash
cp -r projects/my-product projects/my-product-backup-$(date +%Y%m%d)
```

3. **Diagnose the problem** -- Review the audit log, check artifacts, and identify the root cause.

4. **Fix or reconstruct** -- Depending on the problem:
   - Fix the state file manually
   - Reconstruct missing artifacts
   - Rebuild the approval chain
   - Or start over with a new project

5. **Validate the fix** -- Run `validate_artifact.py` on the state file and all artifacts.

6. **Resume workflows** -- Once validated, re-trigger the appropriate workflow.

7. **Document the incident** -- Create a GitHub Issue documenting what went wrong and how it was fixed, so you can learn from it.

## Recovery Decision Tree

```
Project stuck?
  |
  +-> Check error message
  |     |
  |     +-> "Missing artifact" -> Run the stage that produces it
  |     +-> "Approval required" -> Create approval issue
  |     +-> "Approval expired" -> Request new approval
  |     +-> "No transition defined" -> Check valid transitions in architecture.md
  |
  +-> Check project state
  |     |
  |     +-> "blocked" -> Use recovery transitions (blocked -> researching/validating/building)
  |     +-> "failed" -> Reset to discovered (with approval) or retry researching
  |     +-> "paused" -> Reset to discovered or retry researching
  |     +-> "rejected" -> Reset to discovered to start over
  |
  +-> Still stuck?
        |
        +-> Backup state
        +-> Diagnose root cause
        +-> Fix or reconstruct
        +-> Validate
        +-> Resume
        +-> Document incident
```

## Quick Reference

| Problem | Recovery Command |
|---|---|
| Transient failure | `./autopilot.py run <project>` (resumes from `state.json`) |
| Missing artifact | Re-run the stage or manually add artifact |
| Expired approval | Create new approval issue |
| Blocked state | `check_transition.py --to-stage researching` (or validating/building) |
| Failed state | `check_transition.py --to-stage discovered --approval-file reset.json` |
| Stuck transition | Diagnose with `check_transition.py`, fix root cause |
| Corrupted state | Backup, reconstruct from audit log, validate |
| Unknown state | Reconstruct state.json from scratch using audit log |
