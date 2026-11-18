# Reference Architecture: awslabs/aidlc-workflows

Status: Research, Milestone 1
Reference snapshot: `d52a31cb` (2026-11-18, shallow clone kept outside this repo at `C:\Users\vyshu\Desktop\aidlc-reference-research`, never mixed into our source)
License: **MIT No Attribution (MIT-0)**, Copyright Amazon.com, Inc. No attribution is required, but we still implement our own code and cite concepts here for traceability.

## 1. What the reference actually is

AI-DLC is a **prompt-and-harness framework**, not a service. Its core is Markdown plus a small TypeScript toolchain that runs inside a coding assistant (Claude Code, Kiro, Codex CLI, Cursor, opencode, Copilot). It is "one harness-neutral core" (`README.md`) generated into each harness's runtime directory (`.claude/`, `.kiro/`, ...).

Top-level layout (2,360 files):

| Area | Path | Role |
|---|---|---|
| Source of truth | `core/` | Hand-authored, harness-neutral stages, agents, hooks, sensors, scopes, knowledge, tools |
| Stage definitions | `core/aidlc-common/stages/` | 33 stage files in 5 phases: initialization (3), ideation (7), inception (9), construction (7), operation (7) |
| Protocols | `core/aidlc-common/protocols/` | 17 shared protocol modules (stage protocol, reviewer, sensors, ensemble, swarm, recovery, learnings, ...) |
| Agents | `core/agents/` | 14 flat Markdown personas with YAML frontmatter (`disallowedTools`, `tier`) |
| Scopes | `core/scopes/` | 11 workflow profiles (`express`, `feature`, `enterprise`, `mvp`, `poc`, `bugfix`, `refactor`, ...) |
| Hooks | `core/hooks/` | Harness lifecycle hooks (TypeScript): PreToolUse guards, audit writers, statusline |
| Sensors | `core/sensors/` | 6 deterministic checks as Markdown manifests (`traceability`, `required-sections`, `linter`, `type-check`, `claim-sources`, `upstream-coverage`) |
| Knowledge | `core/knowledge/` | 61 reference guides loaded per agent |
| Tools | `core/tools/` | 134 TypeScript CLI tools (`aidlc-state`, `aidlc-orchestrate`, `aidlc-log`, `aidlc-audit`, `aidlc-graph`, ...) |
| Docs | `docs/guide`, `docs/reference`, `docs/harness-engineering` | 46 + 50 + 11 documents, the most detailed source for behavior |
| Tests | `tests/unit` (920), `tests/integration` (270), `tests/e2e` (91), `tests/harness` (95) | Heavy test suite |

Important: the reference's own `docs/reference/12-state-machine.md` states the north-star invariant: *"TypeScript owns deterministic bookkeeping; the LLM owns judgment."* That invariant is the same one our platform adopts, but the reference enforces it **inside a developer's local harness**, not on a server. That is the central architectural difference (see `OUR_PLATFORM_DIFFERENCES.md`).

## 2. Runtime components

```
Developer's coding assistant (host harness)
  |- Slash command /aidlc  -> skill (SKILL.md) = forwarding loop
  |- Hooks (PreToolUse / PostToolUse / SessionStart / Stop ...)
  |     -> guard fences, audit writers, sensor runners, review-freeze
  |- Subagents (native dispatch: Claude `Task`, Kiro delegates)
  |- Engine CLI (aidlc orchestrate / state / log / audit / graph)
        |- reads compiled stage graph (stage-graph.json, from YAML frontmatter)
        |- reads scope grid (compiled from core/scopes)
        |- writes state file (aidlc-state.md) and audit shards (audit/*.md)
        |- writes artifacts under aidlc/spaces/<space>/intents/<record>/
```

Key facts verified in the reference:

- **Engine owns lifecycle.** The conductor (the LLM) may only open, approve, revise, complete or skip a stage through `aidlc-orchestrate.ts report`, never by hand-editing `aidlc-state.md` (`core/aidlc-common/conductor.md`, stage-protocol section "Files and commands"). Direct stage-status verbs are refused by `aidlc-state` itself (`ENGINE_OWNED_STATE_TRANSITIONS`, `core/hooks/aidlc-state-transition-guard.ts`).
- **Hooks are the enforcement point, and they run in the developer's host.** `aidlc-state-transition-guard.ts` and `aidlc-plan-approval-guard.ts` are PreToolUse hooks that exit 2 to refuse a tool call. The guard is only as strong as the host's hook execution. `docs/reference/06-hooks-and-tools.md` notes that Claude Code's `allowManagedHooksOnly` policy disables them.
- **Audit-first atomicity.** Tools emit audit rows *before* mutating state, so `audit.md` and state never disagree (`docs/reference/12-state-machine.md`).
- **Stage graph is compiled.** YAML frontmatter in each stage file is compiled by `aidlc-graph compile` into `stage-graph.json`; CI fails on drift (`docs/reference/15-stage-definition.md`). This is a strong pattern: the runtime never parses prose for structure.
- **Three nested state machines**: workflow (Running/Completed/Archived), phase (Active/verified/skipped) and stage (`[ ]`, `[?]` gate open, `[x]` complete, plus revise/reject loops). Separating them lets a status command answer "what is blocking" in one read.

## 3. Why we are not forking or wrapping it

- The reference is designed for **one developer, one repo, one host**. Our product is **multi-tenant, multi-user, server-side**. Enforcement must live in a backend the user cannot modify from their harness.
- Its state is Markdown plus per-clone audit shards, which the reference itself calls "operational evidence, not a tamper-proof" record (`core/knowledge/aidlc-shared/audit-format.md`, around line 129). We need tamper-evidence and multi-user concurrency control.
- Its agents are coding-assistant personas. Our profiles, end-user portal and provider abstraction are product concerns it does not address.

We will re-implement the **concepts** (stage graph compiled from declarative definitions, engine-owned transitions, reviewer independence, sensors, scope presets, rule layering, audit-first writes) on our own stack. See `REUSABLE_CONCEPTS.md`.

## 4. Mapping to our platform

| Reference concept | Our platform equivalent | Milestone |
|---|---|---|
| Stage YAML frontmatter compiled to graph | `WorkflowVersion` JSON compiled and validated by Workflow Compiler | M3 |
| Engine-owned transitions | Workflow engine service: the only writer of `StageExecution.status` | M3 |
| Scope grid (`aidlc-feature`, `aidlc-enterprise`) | Versioned `WorkflowTemplate` (e.g. "Default six-profile lifecycle", "Lean MVP") | M3/M8 |
| Reviewer sub-agent (`disallowedTools: Task`) | Reviewer `AgentConfiguration` with separate instructions and context, enforced at dispatch | M6 |
| PreToolUse guards | Server-side policy checks on every API call and tool call | M2/M4 |
| `aidlc-state.md` + `audit/*.md` | Relational tables + hash-chained `audit_events` | M2 |
| Sensors (Markdown manifests + scripts) | Sensor registry (Python), declarative manifests in DB | M7 |
| Rules hierarchy (`memory/` files) | Org -> Team -> Project -> Profile -> Stage rule layers in DB | M7 |
| Learning loop (`stage-protocol-learnings.md`) | Governed rule proposals requiring human approval | M7 |
| Harness adapters (Claude/Kiro/Codex...) | Provider adapters (Anthropic/OpenAI/Gemini/OpenAI-compatible/local) | M5 |

## 5. Open questions carried forward

1. The reference's exact scope-to-stage matrix is generated from `core/scopes/*.md`; we will re-derive ours from the six professional profiles in the product brief rather than copy its 11 scopes.
2. The reference's "tier" field (`judgment`, etc.) on agents controls model selection. We will model tiers as provider/model routing policies (see `docs/AGENT_ARCHITECTURE.md` once written).
