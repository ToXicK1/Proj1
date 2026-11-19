# AWS File Mapping

Every candidate studied, with a final decision. License for all rows: MIT No Attribution (no attribution required; we credit the project anyway). Decisions: ADAPT, REUSE, REWRITE, REFERENCE ONLY, EXCLUDE.

| Path | What it does | Dependencies | Concept | Relevance | Maps to | Modifications | Decision |
|---|---|---|---|---|---|---|---|
| `core/aidlc-common/conductor.md` | Persona for executing engine directives well | Engine directives, harness | Model executes, engine decides | High | Orchestrator rules; agents never touch state | Our orchestrator is code, not a persona | REFERENCE ONLY |
| `core/aidlc-common/stages/*/*.md` (33) | Declarative stage definitions | Agents, sensors, scopes, artifact vocabulary | Stage = data with produces, consumes, reviewer, sensors | High | Workflow definition stages; `stage_definitions` | Re-author for six departments; database not files | ADAPT (concept) |
| `protocols/stage-protocol.md` | Gates, voice contract, questions, completion messages | All modules | Hard human gate, plain-language voice | High | Approval engine, owner wording guard | Enforced by backend, not prompt text | ADAPT |
| `protocols/stage-protocol-reviewer.md` | Independent reviewer as separate sub-agent, bounded repair | Reviewer agents | Separate review execution path | High | Review service, max iterations | Add provider diversity option | ADAPT |
| `protocols/stage-protocol-reviewer-repair.md`, `-reviewer-unit.md` | Lead repairs after review; per-unit review | Reviewer | Bounded repair loop | Medium | Rework loop with review iteration limit | DB-backed loop counter (exists) | REFERENCE ONLY |
| `protocols/stage-protocol-sensors.md` | Blocking gate sensors | Sensors | Sensor failure keeps gate shut | High | Sensors at gate (exists) | None | REFERENCE ONLY (already built) |
| `protocols/stage-protocol-ensemble.md`, `-collaborators.md` | Multi-agent stages, contribution files, positions, objection triage | Support agents | Support agents contribute, lead collates | High | Collaboration hub: contributions, positions, objections | Persistent channels, human participants, DB records | ADAPT |
| `protocols/stage-protocol-loopback.md` | Build-and-test failure loops back to code generation | Sandbox runs | Failure root cause returns upstream | High | Rework from QA to Developer | Engine-driven, with real sandbox evidence | ADAPT |
| `protocols/stage-protocol-recovery.md` | Session resume, re-runs, change handling | State files | Recoverable execution | High | Durable job queue, idempotent steps | DB jobs instead of session files | ADAPT |
| `protocols/stage-protocol-learnings.md` | Corrections become rules only with consent | Rules | Governed learning | High | Rule proposals (exists) | None | REFERENCE ONLY (already built) |
| `protocols/stage-protocol-governance.md` | Phase boundary verification | Phases | Checks at phase transitions | Medium | Phase gate hooks | Expressed as hooks | ADAPT |
| `protocols/stage-protocol-checkpoint.md`, `-swarm.md`, `-wave.md` | Unit checkpoints, parallel per-unit work, worktrees | Git worktrees | Parallel units of work | Medium | Parallel stages per unit (Phase 5) | No git worktrees; sandbox workspaces | REFERENCE ONLY |
| `protocols/stage-definition.md` | Front matter schema | Stages | Typed stage contract | High | Stage spec schema | Pydantic, DB | ADAPT |
| `core/agents/*.md` (14) | Personas with tiers and tool limits | Knowledge | Lead and reviewer roles, read-only reviewers | High | Specialist agent registry | Re-cast into six departments' specialists | ADAPT |
| `core/knowledge/**` (61) | Practice guides per agent | Agents | Curated domain knowledge | Medium | Department skills and knowledge | Write our own, shorter | REFERENCE ONLY |
| `core/memory/*.md` | Org, team, project and phase rules | Rule resolver | Layered rules | High | Hierarchical rules (exists) | None | REFERENCE ONLY (already built) |
| `core/sensors/*.md` (6) | Sensor contracts with schema, timeout, severity | Engine | Sensor as declared contract | High | Sensor registry (18 exist) | Add traceability over requirement IDs, claim sources | ADAPT |
| `core/hooks/aidlc-state-transition-guard.ts` | Blocks direct state edits by agents | Harness | Only the engine moves state | High | Engine-only transitions (exists) | None | REFERENCE ONLY |
| `core/hooks/aidlc-plan-approval-guard.ts` | Plan before code generation | Code generation stage | Plan approval before code | High | Development Planning stage gated before Implementation | Stage dependency, not a hook | ADAPT |
| `core/hooks/aidlc-review-freeze.ts` | No writes between review and gate | Reviewer | Reviewed version is frozen | High | Review package locks the artifact version | DB lock on version | ADAPT |
| `core/hooks/aidlc-reviewer-scope.ts` | Reviewer may read only its scope | Reviewer | Least-privilege review context | High | Reviewer context manifest (exists) | None | REFERENCE ONLY |
| `core/hooks/aidlc-run-sensors.ts` | Runs sensors after writes | Sensors | Sensors on artifact change | High | Sensors on new artifact version (exists) | None | REFERENCE ONLY |
| `core/hooks/aidlc-write-audit-log.ts`, `aidlc-record-human-turn.ts` | Audit of artifact writes and human turns | Audit | Every change and human act is recorded | High | Audit events (exist); human message log | Add correlation IDs | ADAPT |
| `core/hooks/aidlc-deliver-stage-rules.ts` | Delivers active rules to sub-agents | Rules | Rules reach every executor | High | Rule snapshot in context package (exists) | None | REFERENCE ONLY |
| `core/hooks/` other (session, statusline, install) | Harness housekeeping | Harness | — | None | — | — | EXCLUDE |
| `core/tools/aidlc-orchestrate.ts`, `aidlc-state.ts`, `aidlc-lifecycle.ts` | The engine | Whole toolchain | Directive loop, state machine | High | Our workflow engine (exists) | Different language and storage | REWRITE (concept only) |
| `core/tools/aidlc-sensor-*.ts` | Sensor implementations | Engine | Deterministic checks | Medium | Sensor functions | Python, our artifact model | REWRITE |
| `core/tools/aidlc-unit*.ts`, `aidlc-swarm*.ts`, `aidlc-worktree.ts`, `aidlc-bolt.ts` | Units of work, parallel construction | Git | Units and bolts | Medium | Development task breakdown and parallel stages | No git worktrees | REFERENCE ONLY |
| `core/tools/aidlc-model-policy.ts`, `aidlc-tiers.ts` | Model tiers per agent | Harness | Task-based model selection | High | Model routing policies | Provider-independent | ADAPT |
| `core/tools/aidlc-learnings.ts`, `aidlc-rule-schema.ts` | Learning and rule schema | Rules | Governed rule changes | High | Rule proposals (exist) | None | REFERENCE ONLY |
| `core/tools/aidlc-audit.ts`, `aidlc-attest.ts` | Audit and commit provenance | Git | Provenance from code to reviewed units | Medium | Requirement-to-code traceability | Artifact links, not git | ADAPT |
| `core/tools/aidlc-message-store.ts`, `aidlc-question-store.ts` | Records human messages and questions | Harness | Faithful record of human input | High | Conversation messages | DB tables | ADAPT |
| `core/tools/` installers, plugins, harness helpers (about 80 files) | Packaging and per-assistant support | Harness | — | None | — | — | EXCLUDE |
| `core/scopes/*.md` (11) | Which stages run per scope | Stages | Scope-driven stage applicability | High | Project applicability profiles | Re-map to department stages | ADAPT |
| `core/skills/**` | Helper skills | Harness | — | Low | — | — | EXCLUDE |
| `harness/claude/**` | Claude Code packaging, settings, hooks wiring | Claude Code | — | None for the product | — | Product must not depend on any coding assistant | EXCLUDE |
| `docs/reference/12-state-machine.md` | Workflow, phase and stage state machines; audit taxonomy | Engine | Three-level state machine | High | Workflow and phase status | Add phase status | ADAPT |
| `docs/reference/07-sensor-system.md`, `08-rule-system.md`, `10-knowledge-system.md` | Reference for those systems | — | — | High | Research inputs | — | REFERENCE ONLY |
| `docs/guide/05-scopes-and-depth.md` | Scope matrix | Scopes | — | High | Applicability matrix | — | REFERENCE ONLY |

No file is copied verbatim into this product. The current `backend/app/portal/lifecycle.py` re-authors the AWS stage names and scope matrix in our own words; under D1 it becomes an importable template instead of the default.
