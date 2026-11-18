# Hooks and Sensors Analysis

Status: Research, Milestone 1
Source: `core/hooks/*.ts`, `core/sensors/*.md`, `docs/reference/06-hooks-and-tools.md`, `docs/reference/07-sensor-system.md`

## 1. Hooks in the reference

The reference ships about 17 hook sources (the tree has 20 files including helpers such as `runtime-integrity.ts` and `system-install.ts`). They are registered in the host harness (`settings.json` `hooks` block) and invoked as PreToolUse, PostToolUse, SessionStart, Stop and statusline entry points.

| Hook | Purpose |
|---|---|
| `aidlc-state-transition-guard.ts` | Refuses direct stage-status verbs and delegated agents calling lifecycle verbs |
| `aidlc-plan-approval-guard.ts` (3,300 lines) | Enforces "plan before generation": code-generation cannot write project code until Approve Plan is recorded |
| `aidlc-review-freeze.ts` | Refuses writes to produced artifacts after a terminal review receipt, so the reviewed bytes are the approved bytes |
| `aidlc-run-sensors.ts` | Runs sensors on writes to a stage's outputs |
| `aidlc-write-audit-log.ts`, `aidlc-log-subagent.ts`, `aidlc-fold-usage.ts` | Audit and usage recording |
| `aidlc-record-human-turn.ts` | Records the person's messages so approvals can cite them |
| `aidlc-session-start.ts`, `aidlc-session-end.ts`, `aidlc-continue-workflow.ts` | Session lifecycle |
| `aidlc-validate-state.ts`, `aidlc-sync-workflow-state.ts`, `aidlc-rebuild-stage-graph.ts` | State integrity and graph rebuild |

### Hook design, as implemented

- Refusal contract: print a reason to stderr and exit 2 to block a tool call; exit 0 to allow.
- Hooks read facts from the audit ledger and compiled graph, not from the LLM's claims.
- Guards are scoped by policy: `guard_policy: strict | relaxed | off`, set per scope and per intent. Strict enforces everything; off enforces only what cannot be bypassed.
- Delegated helper agents get a per-persona shell deny list (`DELEGATED_*` verb sets) so a sub-agent cannot run lifecycle verbs.

### Limits we must not inherit

1. **Host-dependent.** Enforcement depends on the host executing hooks. `allowManagedHooksOnly` in Claude Code disables project hooks; the reference documents this itself. A server platform must enforce on the server.
2. **Path and shell parsing.** Several guards parse shell commands to detect writes. Parsing is inherently incomplete. We enforce at the API and tool-executor boundary instead, with typed tool inputs and no free-form shell.
3. **Single-user trust model.** The developer is trusted and the guard protects them from their own assistant. In a multi-tenant product, the end user and the AI are both untrusted relative to the organization's policy.

## 2. Sensors in the reference

A sensor is a deterministic check with a Markdown manifest (`core/sensors/aidlc-*.md`). The manifest's frontmatter declares `id`, `kind: deterministic`, `command`, `default_severity` (`advisory` or blocking), `fire_on: gate`, `matches` (glob), `input_schema`, `output_schema`, and `timeout_seconds`.

The six shipped sensors:

| Sensor | Checks |
|---|---|
| `aidlc-required-sections` | Required headings present in a document |
| `aidlc-traceability` | Element-level coverage: every requirement traced to stories, units and code paths; detects `GAP`, `ORPHAN`, missing rows, undeclared upstream IDs; fails closed |
| `aidlc-linter` | Linting of generated code |
| `aidlc-type-check` | Type checking |
| `aidlc-claim-sources` | Verifies claims cite sources |
| `aidlc-upstream-coverage` | Upstream artifacts are covered downstream |

`docs/reference/07-sensor-system.md` states that sensors fire on writes and at gate open, and that the gate records a per-sensor state (`passed`, `failed(n)`, `not-run`) in the audit.

### Strong patterns to keep

- **Declarative manifests with input and output schemas.** Every sensor has a typed contract.
- **Fire at the gate, on the bytes being approved.** The gate row records each sensor's state, and blocking failures require an explicit override with a recorded reason.
- **Fail closed.** The traceability sensor fails when its expected source is missing rather than passing silently.
- **Severity separation** between advisory and blocking.

## 3. How we will implement it

| Concern | Our design |
|---|---|
| Hook registration | Hooks are DB rows (`HookDefinition`) with event subscription, priority, condition, permissions, timeout, failure policy and version. Built-in hooks are Python code. Organization-authored hooks are declarative (`action: run_sensor`, `action: require_approval`, `action: notify`), not arbitrary code. |
| Mandatory hooks | Mandatory hooks fail closed on error or timeout: the stage transition is refused. |
| Unreviewed AI-generated hooks | Cannot be enabled. Hook creation by an AI agent produces a *proposal* that a human admin must approve (same path as rule proposals). |
| Sandboxing | Any hook that executes code runs in a separate worker with no network by default, CPU/memory/time limits, and a read-only view of the artifact snapshot. |
| Sensor framework | Python registry of sensor implementations, each with a typed input/output schema (Pydantic). Manifests reference a registry ID and a version. |
| Sensor statuses | `PASS`, `FAIL`, `WARNING`, `NOT_APPLICABLE`, `ERROR` (as in the master prompt). `ERROR` never counts as `PASS`. |
| LLM and sensors | An LLM may explain a finding and propose remediation. It cannot write a sensor result. Sensor results come only from the deterministic runner and are stored with the artifact version they examined. |
| Mandatory failure | A failed mandatory sensor blocks the gate unless an authorized risk-acceptance exception is recorded with a named human, a reason and an expiry. |
| Dev-time hooks | Claude Code hooks for formatting, linting and secret detection live in `.claude/hooks/` and are separate from platform runtime hooks. |

## 4. Decision

We keep the reference's two-part split (declarative hook/sensor definitions, deterministic implementations) and move enforcement to the server. We reject shell-parsing guards for runtime enforcement.
