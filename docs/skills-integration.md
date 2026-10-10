# Skills Integration Map

This document maps all 31 skills in `indie-builder-skills/` to the autopilot pipeline stages. It documents the current integration status honestly -- what is connected, what needs adapter work, and what is still planned.

## Current State of Integration

**Important:** Skills are currently instruction documents (SKILL.md files) that guide AI agents. They are NOT directly executable from GitHub Actions. Integration requires an agent adapter that can read the skill instructions and execute them via an AI agent (Claude Code, Codex, etc.).

**What exists today:**
- 31 SKILL.md files in `indie-builder-skills/skills/` -- each describes a specific task
- 1 mock adapter (`adapters/mock_agent.py`) -- returns fake data for testing pipeline wiring
- 0 production adapters -- no adapter currently reads SKILL.md files and executes them
- 1 workflow (`radar-weekly.yml`) -- uses the mock adapter for discovery

**What is needed:**
- Agent adapters that can read SKILL.md instructions and execute them
- Input/output contracts for each skill (what data goes in, what artifacts come out)
- Workflow files that call the appropriate adapter for each stage

## Integration Status Legend

| Status | Meaning |
|---|---|
| `documented` | Skill exists as SKILL.md with instructions |
| `adapter-needed` | Needs an adapter to be callable from GitHub Actions |
| `mock-available` | Mock adapter can simulate this skill's output |
| `not-yet-integrated` | Not connected to any workflow |

## Pipeline Stage Mapping

### Stage 1: Discovery (workflow: radar-weekly.yml)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 1 | `indie-product-radar` | documented, adapter-needed | Web search results, trend data, pain point signals | Opportunity cards with 8-dimension scores, validation experiments | Agent adapter reads SKILL.md, calls AI agent with web search data, returns opportunity JSON |
| 2 | `emerging-keyword-radar` | documented, adapter-needed | Google Trends data, keyword lists | Keyword candidates with 7-dimension scores, weekly report | Agent adapter reads SKILL.md, calls AI agent with trend API data, returns keyword JSON |

**Current integration:** Mock adapter returns simulated discovery results. No live adapter exists.

**To integrate:**
1. Create a discovery adapter that reads `indie-product-radar/SKILL.md`
2. Configure it to receive data from enabled sources (Hacker News, Google Trends, etc.)
3. Have the adapter call an AI agent with the skill instructions + source data
4. Parse the agent output into the stage-result schema
5. Update `radar-weekly.yml` to use the new adapter instead of mock_agent.py

### Stage 2: Research (workflow: validate-opportunity.yml)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 3 | `product-validation` | documented, adapter-needed | Opportunity card from discovery, user interview data | Validation report: continue/pivot/kill recommendation | Agent adapter reads SKILL.md, validates pain point evidence, returns validation JSON |
| 4 | `competitor-intelligence` | documented, adapter-needed | Product category, target market | Competitor matrix: direct/indirect competitors, positioning, pricing, features | Agent adapter reads SKILL.md, researches competitors via web search, returns competitor JSON |
| 5 | `seo-opportunity-research` | documented, adapter-needed | Target keywords, market description | SEO opportunity report: keyword clusters, search intent, page opportunities | Agent adapter reads SKILL.md, analyzes SEO data, returns opportunity JSON |

**Current integration:** Mock adapter returns simulated research results. No live adapter exists.

**To integrate:**
1. Create a research adapter that can call multiple skills (product-validation, competitor-intelligence, seo-opportunity-research)
2. The adapter should orchestrate them in sequence, passing outputs between them
3. Configure the adapter to receive discovery artifacts as input
4. Return a combined research_result artifact

### Stage 3: Validation (workflow: validate-opportunity.yml, after approval gate)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 3 | `product-validation` | documented, adapter-needed | Research artifacts, validation experiments | Deep validation report with evidence quality assessment | Same adapter as research stage, but with deeper analysis |

**Note:** product-validation is used in both research and validation stages. In research, it does initial validation. In validation (after approval), it does deep validation.

### Stage 4: Planning (workflow: plan-product.yml)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 6 | `product-positioning` | documented, adapter-needed | Validation results, competitor analysis | Positioning statement: target user, core problem, value proposition, differentiation | Agent adapter reads SKILL.md, synthesizes positioning from research, returns positioning JSON |
| 7 | `mvp-scope-planner` | documented, adapter-needed | Validation results, positioning | MVP scope: must-have features, deferred features, non-goals, acceptance criteria | Agent adapter reads SKILL.md, defines scope based on validation, returns scope JSON |
| 8 | `product-requirements` | documented, adapter-needed | MVP scope, positioning | PRD: user stories, requirements, edge cases, dependencies, acceptance criteria | Agent adapter reads SKILL.md, writes PRD from scope, returns requirements JSON |
| 9 | `product-ux-conversion` | documented, adapter-needed | PRD, positioning | UX review: user flows, information hierarchy, mobile considerations, conversion friction | Agent adapter reads SKILL.md, reviews UX from PRD, returns UX review JSON |

**Current integration:** Mock adapter returns simulated planning results. No live adapter exists.

**To integrate:**
1. Create a planning adapter that orchestrates product-positioning -> mvp-scope-planner -> product-requirements -> product-ux-conversion
2. Each skill's output feeds into the next skill's input
3. The adapter returns a combined plan_result artifact

### Stage 5: Building (workflow: build-and-test.yml)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 10 | `indie-tech-architecture` | documented, adapter-needed | PRD, requirements | Tech stack recommendation, platform constraints, cost estimates, PoC plan | Agent adapter reads SKILL.md, evaluates tech options, returns architecture JSON |
| 11 | `ai-coding-workflow` | documented, adapter-needed | Architecture, PRD, user stories | Implementation plan: task breakdown, context checks, minimal changes, test strategy | Agent adapter reads SKILL.md, creates coding workflow, returns implementation JSON |
| 12 | `security-privacy-review` | documented, adapter-needed | Implementation, tech stack | Security review: auth, permissions, keys, data lifecycle, privacy compliance | Agent adapter reads SKILL.md, reviews security, returns security review JSON |

**Current integration:** Mock adapter returns simulated build results. No live adapter exists.

**To integrate:**
1. Create a build adapter that orchestrates indie-tech-architecture -> ai-coding-workflow -> security-privacy-review
2. The adapter needs access to the codebase (via allowed_read_paths)
3. For ai-coding-workflow, the adapter may need to actually execute code generation (via Claude Code or similar)
4. Return build_result and security_review artifacts

### Stage 6: Testing (workflow: build-and-test.yml)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 13 | `launch-readiness-qa` | documented, adapter-needed | Build artifacts, PRD | QA report: core flows, SEO, responsive, forms, performance, error handling | Agent adapter reads SKILL.md, runs QA checks, returns QA report JSON |
| 14 | `deployment-operations` | documented, adapter-needed | Build artifacts, tech stack | Deployment plan: env vars, DNS, deployment steps, monitoring, backup, recovery | Agent adapter reads SKILL.md, creates deployment plan, returns ops JSON |

**Current integration:** Mock adapter returns simulated test results. No live adapter exists.

**To integrate:**
1. Create a testing adapter that orchestrates launch-readiness-qa -> deployment-operations
2. The adapter needs to actually run tests and check deployment readiness
3. Return test_result artifact

### Stage 7: Release (workflow: release.yml)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 14 | `deployment-operations` | documented, adapter-needed | Deployment plan, build artifacts | Execution of deployment: env setup, DNS config, deployment, monitoring | Agent adapter reads SKILL.md, executes deployment, returns deployment JSON |
| 15 | `launch-campaign-planner` | documented, adapter-needed | Product info, positioning | Launch plan: pre-launch assets, launch cadence, channel verification, launch day tasks | Agent adapter reads SKILL.md, plans launch campaign, returns launch plan JSON |

**Current integration:** Mock adapter returns simulated release results. No live adapter exists.

**To integrate:**
1. Create a release adapter that orchestrates deployment-operations -> launch-campaign-planner
2. The adapter needs production credentials (via environment variables)
3. Return release_checklist and rollback_plan artifacts

### Stage 8: Growth (workflow: growth-review.yml)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 16 | `indie-product-reach` | documented, adapter-needed | Product info, launch results | Growth plan: product profile, readiness diagnosis, cross-channel playbook | Agent adapter reads SKILL.md, coordinates growth skills, returns growth plan JSON |
| 17 | `content-marketing-engine` | documented, adapter-needed | Positioning, SEO research | Content plan: topic clusters, content briefs, internal linking, CTA strategy | Agent adapter reads SKILL.md, creates content strategy, returns content plan JSON |
| 18 | `distribution-channel-research` | documented, adapter-needed | Product info, target market | Channel analysis: directories, communities, content platforms, partnership channels | Agent adapter reads SKILL.md, researches channels, returns channel JSON |
| 19 | `google-indexing-diagnostics` | documented, adapter-needed | Search Console data, site URLs | Indexing report: crawl issues, index status, ranking problems, traffic analysis | Agent adapter reads SKILL.md, diagnoses indexing, returns diagnostics JSON |
| 20 | `product-analytics` | documented, adapter-needed | Analytics data, product info | Analytics setup: events, traffic sources, activation, retention, conversion funnel | Agent adapter reads SKILL.md, defines metrics, returns analytics JSON |
| 21 | `conversion-optimization` | documented, adapter-needed | Analytics data, user feedback | Conversion experiments: hypotheses, metrics, guardrail metrics, result criteria | Agent adapter reads SKILL.md, designs experiments, returns optimization JSON |
| 22 | `pricing-monetization` | documented, adapter-needed | Product info, competitor pricing | Pricing strategy: pricing models, competitor packages, cost analysis, pricing experiments | Agent adapter reads SKILL.md, analyzes pricing, returns pricing JSON |
| 23 | `customer-feedback-loop` | documented, adapter-needed | User feedback, support tickets | Feedback analysis: categorization, pattern detection, iteration tasks | Agent adapter reads SKILL.md, analyzes feedback, returns feedback JSON |

**Current integration:** Mock adapter returns simulated growth results. No live adapter exists.

**To integrate:**
1. Create a growth adapter that orchestrates indie-product-reach (which coordinates other growth skills)
2. The adapter needs access to analytics, Search Console, and feedback data
3. Return growth_review artifact

### Stage 9: Maintain (no dedicated workflow yet)

| # | Skill | Status | Input | Output | Integration Method |
|---:|---|---|---|---|---|
| 24 | `product-lifecycle-manager` | documented, not-yet-integrated | Product metrics, growth data | Lifecycle decision: continue/pivot/maintain/stop | Agent adapter reads SKILL.md, evaluates lifecycle, returns decision JSON |
| 25 | `project-retrospective` | documented, not-yet-integrated | Project goals, actual results | Retrospective: what worked, what didn't, root causes, lessons, next steps | Agent adapter reads SKILL.md, analyzes project, returns retrospective JSON |
| 26 | `saas-cost-monitor` | documented, not-yet-integrated | SaaS bills, usage data | Cost report: hosting, storage, bandwidth, API, email, payment costs | Agent adapter reads SKILL.md, monitors costs, returns cost report JSON |
| 27 | `technical-debt-manager` | documented, not-yet-integrated | Codebase, issue tracker | Tech debt backlog: prioritized by user impact, risk, frequency, fix cost | Agent adapter reads SKILL.md, assesses debt, returns debt backlog JSON |
| 28 | `indie-builder-memory` | documented, not-yet-integrated | Project decisions, lessons learned | Memory entries: decisions, pitfalls, experiment results, applicable conditions | Agent adapter reads SKILL.md, records lessons, returns memory JSON |
| 29 | `support-knowledge-base` | documented, not-yet-integrated | Support tickets, FAQs | Knowledge base: troubleshooting steps, version-specific docs, support replies | Agent adapter reads SKILL.md, organizes support docs, returns KB JSON |
| 30 | `indie-workflow-automation` | documented, not-yet-integrated | Repetitive tasks, workflow patterns | Automation plan: task identification, permission design, approval points, retry logic | Agent adapter reads SKILL.md, designs automation, returns automation plan JSON |
| 31 | `skills-quality-auditor` | documented, not-yet-integrated | SKILL.md files, integration results | Quality report: responsibility boundaries, duplication, input/output, evidence standards | Agent adapter reads SKILL.md, audits skills, returns quality report JSON |

**Current integration:** None. These skills are documented but not connected to any workflow.

**To integrate:**
1. Create a maintain workflow (e.g., `maintain-review.yml`)
2. Create adapters for each maintain skill
3. Schedule the workflow (e.g., monthly review)

## Skill Handoff Relationships

Based on `indie-builder-skills/HANDOFF-MAP.md`, here are the handoff relationships:

### Discovery -> Definition
- `indie-product-radar` output (Top opportunity cards) -> `product-validation` input
- `emerging-keyword-radar` output (high-value keywords) -> `seo-opportunity-research` input; also feeds `content-marketing-engine` and `indie-product-reach`
- Validated direction -> `competitor-intelligence` + `seo-opportunity-research` (parallel)
- Research conclusions -> `product-positioning` input

### Definition -> Build
- `mvp-scope-planner` output (feature list) -> `product-requirements` input
- `product-requirements` + `product-positioning` -> `product-ux-conversion` input
- `product-requirements` -> `indie-tech-architecture` input

### Build -> Launch
- `indie-tech-architecture` + `ai-coding-workflow` complete development
- `security-privacy-review` reviews security and privacy
- `launch-readiness-qa` pre-launch QA
- `deployment-operations` executes deployment
- `launch-campaign-planner` plans launch campaign

### Launch -> Growth
- `indie-product-reach` executes promotion (SEO, directories, communities, content, email, social proof)
- `content-marketing-engine` + `distribution-channel-research` continuous content and channel expansion
- `google-indexing-diagnostics` diagnoses indexing issues
- `product-analytics` defines and tracks growth metrics
- `conversion-optimization` optimizes conversion funnel
- `pricing-monetization` adjusts pricing strategy
- `customer-feedback-loop` collects and processes user feedback

### Growth -> Maintain
- `product-lifecycle-manager` evaluates continue/pivot/maintain/stop
- `project-retrospective` compares goals vs actuals
- `saas-cost-monitor` monitors costs
- `technical-debt-manager` manages tech debt
- `indie-builder-memory` records lessons
- `support-knowledge-base` organizes support docs
- `indie-workflow-automation` automates repetitive work
- `skills-quality-auditor` audits skill quality

## Integration Priority

Based on skill priorities from `indie-builder-skills/CATALOG.md`:

### P0 (Must integrate first)
1. `indie-product-radar` -- Core discovery skill
2. `product-validation` -- Validates opportunities
3. `competitor-intelligence` -- Competitive analysis
4. `seo-opportunity-research` -- SEO opportunities
5. `product-positioning` -- Defines positioning
6. `mvp-scope-planner` -- Defines MVP scope
7. `product-requirements` -- Writes PRD
8. `indie-tech-architecture` -- Tech stack selection
9. `ai-coding-workflow` -- Coding workflow
10. `launch-readiness-qa` -- Pre-launch QA
11. `indie-product-reach` -- Growth orchestration
12. `product-analytics` -- Growth metrics
13. `indie-builder-memory` -- Cross-project learning

### P1 (Integrate after P0)
14. `emerging-keyword-radar` -- Keyword discovery
15. `product-ux-conversion` -- UX review
16. `security-privacy-review` -- Security review
17. `deployment-operations` -- Deployment
18. `launch-campaign-planner` -- Launch campaign
19. `content-marketing-engine` -- Content strategy
20. `distribution-channel-research` -- Channel research
21. `google-indexing-diagnostics` -- Indexing diagnostics
22. `conversion-optimization` -- Conversion experiments
23. `pricing-monetization` -- Pricing strategy
24. `customer-feedback-loop` -- Feedback analysis
25. `product-lifecycle-manager` -- Lifecycle decisions
26. `project-retrospective` -- Project review
27. `saas-cost-monitor` -- Cost monitoring
28. `skills-quality-auditor` -- Skill quality

### P2 (Integrate last)
29. `technical-debt-manager` -- Tech debt management
30. `support-knowledge-base` -- Support docs
31. `indie-workflow-automation` -- Workflow automation

## What Needs to Be Built

To fully integrate all 31 skills, the following needs to be built:

### 1. Agent Adapters (8 adapters, one per stage)

- **Discovery adapter** -- Calls indie-product-radar, emerging-keyword-radar
- **Research adapter** -- Calls product-validation, competitor-intelligence, seo-opportunity-research
- **Planning adapter** -- Calls product-positioning, mvp-scope-planner, product-requirements, product-ux-conversion
- **Build adapter** -- Calls indie-tech-architecture, ai-coding-workflow, security-privacy-review
- **Testing adapter** -- Calls launch-readiness-qa, deployment-operations
- **Release adapter** -- Calls deployment-operations, launch-campaign-planner
- **Growth adapter** -- Calls indie-product-reach (which coordinates other growth skills)
- **Maintain adapter** -- Calls maintain skills (product-lifecycle-manager, project-retrospective, etc.)

### 2. Workflow Files (5 additional workflows)

- `validate-opportunity.yml` -- Research and validation stages
- `plan-product.yml` -- Planning stage
- `build-and-test.yml` -- Building and testing stages (exists but uses mock)
- `release.yml` -- Release stage
- `growth-review.yml` -- Growth stage
- `maintain-review.yml` -- Maintain stage (new)

### 3. Input/Output Contracts

For each skill, define:
- What data it expects as input (JSON schema)
- What artifacts it produces (JSON schema)
- How to validate the output

### 4. Testing Infrastructure

- Integration tests for each adapter
- End-to-end tests for each workflow
- Mock data generators for each skill
- Validation tests for input/output contracts

## Honest Assessment

**What works today:**
- State machine with 17 states and 23 transitions
- Mock adapter that simulates all 8 stages
- Schema validation for projects, stage results, and approvals
- GitHub Actions workflow for discovery (using mock)
- Scripts for validation, transition checking, issue creation, and report generation

**What does not work yet:**
- No live agent adapters that read SKILL.md files
- No workflows that call real AI agents
- No input/output contracts for individual skills
- No integration testing for skill adapters
- No maintain workflow

**What is the biggest gap:**
The biggest gap is the lack of agent adapters that can read SKILL.md instructions and execute them via AI agents. Without these adapters, the skills are just documentation -- they cannot be called from GitHub Actions.

**What is the recommended next step:**
1. Build a discovery adapter that reads `indie-product-radar/SKILL.md` and calls an AI agent
2. Test it with live data (Hacker News, which is free)
3. Update `radar-weekly.yml` to use the new adapter
4. Once that works, build adapters for the other stages in priority order

## Summary

All 31 skills are documented as SKILL.md files. None are currently integrated into the autopilot pipeline beyond the mock adapter. Integration requires building agent adapters that can read skill instructions, call AI agents, and return structured results. The mock adapter provides a testing foundation, but live adapters are needed for real execution.

The handoff relationships are well-defined in HANDOFF-MAP.md. The integration priority is clear from CATALOG.md. What remains is the implementation work: building adapters, defining contracts, creating workflows, and testing end-to-end.
