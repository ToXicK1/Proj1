# Workflow Analysis

Status: Research, Milestone 1
Source: `core/aidlc-common/stages/**`, `core/aidlc-common/protocols/stage-definition.md`, `core/scopes/*.md`, `docs/reference/04-stage-protocol.md`, `docs/reference/15-stage-definition.md`

## 1. Phases and stages (reference)

| Phase | Stage files | Notes |
|---|---|---|
| Initialization | workspace-detection, state-init, workspace-scaffold | Detects greenfield vs brownfield, creates state |
| Ideation | intent-capture, team-formation, market-research, feasibility, scope-definition, rough-mockups, approval-handoff | Mostly human-gated prose stages |
| Inception | practices-discovery, requirements-analysis, reverse-engineering, user-stories, domain-design, units-generation, contract-design, refined-mockups, delivery-planning | Produces requirements, units of work |
| Construction | functional-design, nfr-requirements, nfr-design, infrastructure-design, code-generation, build-and-test, ci-pipeline | Per-unit build loop |
| Operation | environment-provisioning, deployment-pipeline, deployment-execution, performance-validation, observability-setup, incident-response, feedback-optimization | Release and run |

Each stage file has YAML frontmatter that the compiler reads. Documented fields (`docs/reference/15-stage-definition.md`): `slug`, `phase`, `execution` (`ALWAYS`|`CONDITIONAL`), `condition`, `lead_agent` (validated against `agents/*.md`), plus `reviewer`, `review_class`, `produces[]`, `consumes[]`, sensor imports and learning module flags.

## 2. Stage protocol

`core/aidlc-common/protocols/stage-protocol.md` is mandatory for every stage. Its major rules:

1. **The person drives.** Explicit user requests are executed; questions are asked only when intent is genuinely unclear. The engine never second-guesses a recorded choice.
2. **Voice contract.** Users hear professional narration, not framework internals (a directly relevant precedent for our End-User Portal).
3. **Tri-mode input.** Guided, self-guided (edit the file), or chat. All three converge on the same file, which is the source of truth.
4. **Structured questions** use `[Answer]:` tags with lettered options and an "X = Other" option, so answers are machine-parseable.
5. **Review, then gate.** A stage body produces artifacts, a reviewer (optional, per `review_class`) checks them, then a human gate opens (`[?]`).

## 3. Scopes (workflow profiles)

Scopes are presets selecting which stages run and which guard/sensor/review policies apply. Examples from `core/scopes/`:

| Scope | Depth | Guard policy | Review cap | Intent |
|---|---|---|---|---|
| express | Minimal | off | none | Lightest run, requirements to deploy |
| feature | Standard | off | (default) | Full lifecycle for features |
| enterprise | Comprehensive | strict | (default) | Regulated, full audit trail, plan approval on |
| poc | Minimal | off | advisory | Prove feasibility fast, skeleton off |
| bugfix / security-patch / refactor | Minimal | off | (default) | Narrow work on existing code |

**Analysis.** Scopes give the reference a clean separation between *how much ceremony* (depth, skeleton, approvals) and *what is enforced* (guard policy, sensors). This separation is good and we will keep it, but scope names are developer-oriented. Our equivalent is a **Workflow Template** plus **Governance Policy** pair, selectable by the organization.

## 4. Gates and approvals

Each stage that needs a human ends in a gate `[?]`. Approval is recorded by `GATE_APPROVED` in the audit with the person's words, the brief digest, and the sensor state at the time. Details in `APPROVAL_GATE_ANALYSIS.md`.

Revise and rework: `report --result revised` reopens a gate; `Request Changes` sends feedback back to the lead agent; a new review attempt is started; reviewer iterations are capped (`reviewer_max_iterations`).

## 5. Ordering and dependencies

- The compiled stage graph gives each stage its predecessors. Unit-level stages (Construction) run per unit, with "unit-major" or "stage-major" ordering and optional swarm/bolt parallelism.
- Parallelism exists (swarm workers in worktrees, `aidlc-bolt.ts`, `aidlc-swarm`), but it is coupled to git worktrees and a developer's local repo.

## 6. Lessons for our Workflow Engine

| Observation | Decision for our platform |
|---|---|
| Stage structure should come from data, not code | Yes. Workflows are versioned JSON validated by a compiler (M3). |
| Stage prose and structure must not drift | Yes. Compile at publish time; runtime reads compiled, validated snapshot only. |
| Scope = preset of stages + policies | Yes. Template + policy profile. |
| Parallelism via worktrees | No. Our parallelism is per stage-execution with DB-level claims and concurrency control. |
| Reviewer as a sub-agent | Yes, but reviewer identity is a first-class `AgentConfiguration` with its own context policy. |
| Free-form chat drives the state | No. Users and LLMs never call state verbs; they submit typed commands the engine validates. |

## 7. Our default lifecycle (from the product brief)

Six professional profiles executed in order, each with its stages and gates, as given in the master prompt Part 8. The reference's five phases map as follows: Initialization = Project Setup; Ideation + Inception = Business Analyst and Solution Architect; Design = UI/UX; Construction = Software Developer and QA & Security; Operation = DevOps & Release. The reference has no UI/UX profile and no user-facing portal, so these are our additions.
