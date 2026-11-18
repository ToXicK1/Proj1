# Reusable Concepts

Status: Research, Milestone 1

## Licensing position

The reference is MIT-0 (`LICENSE`: "MIT No Attribution"). That license permits reuse of code and documentation without attribution. Our default is still **independent implementation of the concepts**, for three reasons:

1. Our architecture differs (server-side, multi-tenant, Python), so copying TypeScript harness code would not fit.
2. Copying prose documentation would import assumptions that do not match our product (developer-only, single host).
3. Keeping provenance clean makes our license position simpler for enterprise customers.

No source file, template or stage prose is copied. Where a concept is adopted, this document records it.

## Concept register

| # | Concept | Reference location | Adopt? | How we implement it |
|---|---|---|---|---|
| 1 | Declarative stage definitions compiled to a graph | `core/aidlc-common/protocols/stage-definition.md`, `aidlc-graph` | Yes (concept) | Workflow JSON schema, Python compiler, DB snapshot per execution |
| 2 | Engine-owned transitions; LLM cannot change state | `conductor.md`, `aidlc-state-transition-guard.ts` | Yes, stronger | Server-side only; API and tool executor reject state verbs from agents and users |
| 3 | Independent reviewer as a separate agent | `stage-protocol-reviewer.md` | Yes | Reviewer `AgentConfiguration` with separate instructions; dispatcher refuses self-review |
| 4 | Review verdict bound to artifact fingerprint | `REVIEW_COMPLETED` | Yes | `review_verdicts.artifact_version_id` + `content_sha256` |
| 5 | Review freeze (no writes after terminal review) | `aidlc-review-freeze.ts` | Yes (concept) | A new artifact version after a verdict invalidates it; no in-place edits of versions |
| 6 | Gate with brief digest and sensor state | `STAGE_AWAITING_APPROVAL` | Yes | `ApprovalRequest` snapshot JSON with digest |
| 7 | Finding dispositions at approval | `GATE_APPROVED` | Yes | `approval_finding_dispositions` table |
| 8 | Blocking override with reason | `Blocking Sensor Override` | Yes, with expiry and named approver | `RiskAcceptance` entity |
| 9 | Plan-before-generation gate | `aidlc-plan-approval-guard.ts` | Yes (concept) | Stage-level approval required before any `developer` tool with `WRITE` on repository |
| 10 | Scope presets | `core/scopes/*.md` | Yes | `WorkflowTemplate` + `GovernancePolicy` pairs |
| 11 | Stage-table and scope-table generated views | `aidlc-graph`, `gen stage-table` | Yes | Generated docs for admins from DB definitions |
| 12 | Audit-first atomicity | `12-state-machine.md` | Yes | Audit row inserted in the same DB transaction; no separate file |
| 13 | Event-to-emitter drift test | `t48-audit-event-emitters.test.ts` | Yes | Integration test enumerates event enum vs emitters |
| 14 | Rules hierarchy, additive | `08-rule-system.md` | Yes | Org -> Team -> Project -> Profile -> Stage, additive by default |
| 15 | Learning loop with human-approved rule changes | `stage-protocol-learnings.md` | Yes | `RuleProposal` requires human approval, versioned on accept |
| 16 | Sensor manifests with input/output schema | `07-sensor-system.md` | Yes | Typed sensor registry; manifests reference versioned implementations |
| 17 | Fail-closed sensors (missing source = failure) | `aidlc-traceability.md` | Yes | Sensor returns `ERROR` for missing inputs; gate treats `ERROR` as not passed |
| 18 | Knowledge split from persona | `core/knowledge/` | Yes | `KnowledgePack` versioned records attached to agent configurations |
| 19 | Context isolation for subagents | `conductor.md` | Yes, strict | `AgentRun.context_manifest` recorded; no ambient project access |
| 20 | Voice contract for user-facing narration | `stage-protocol.md` "Talking to the user" | Yes | Professional-representative message templates; internal vocabulary filter on outbound messages |
| 21 | Structured question tags `[Answer]:` | `stage-protocol.md` | Partly | Structured question objects with typed options; no free-text parsing |
| 22 | Dev-time hooks separate from runtime hooks | `06-hooks-and-tools.md` | Yes | `.claude/hooks/` for development; `backend/app/hooks` for runtime |

## Not adopted

- Markdown state files as the source of truth.
- Git worktree coupling for parallelism.
- Shell-command parsing to infer writes.
- Single-developer trust assumptions.
- Per-harness code generation (we target one core and one web UI; provider differences live in adapters).
