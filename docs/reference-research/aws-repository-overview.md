# AWS AI-DLC Repository Overview

Repository: https://github.com/awslabs/aidlc-workflows. Checkout studied: `c515d06` (2026-11-18), cloned outside this project at `../aidlc-reference-research`. License: MIT No Attribution (see `licensing-and-attribution.md`).

## What it is

A methodology plus an engine that drives an AI coding assistant (Claude Code, Codex, Copilot, Cursor, Kiro, OpenCode) through a governed software lifecycle. It is not a web application. It runs inside the developer's assistant session, keeps its state in files under the project, and enforces rules through harness hooks.

## Actual structure (verified)

| Path | Files | Role |
|---|---|---|
| `core/aidlc-common/conductor.md` | 1 | The conductor persona: execute one engine directive at a time; the engine owns lifecycle bookkeeping |
| `core/aidlc-common/stages/` | 33 | One file per stage with YAML front matter (lead agent, support agents, mode, reviewer, produces, consumes, sensors, scopes) and step prose |
| `core/aidlc-common/protocols/` | 17 | Stage protocol and modules: approval gates, reviewer, sensors, ensemble, collaborators, loop-back, recovery, learnings, checkpoint, swarm, wave, governance |
| `core/agents/` | 14 | Agent personas (product, product lead reviewer, architect, architecture reviewer, design, developer, quality, devsecops, delivery, pipeline deploy, AWS platform, operations, compliance, composer) |
| `core/knowledge/` | 61 | Per-agent knowledge files plus shared guides |
| `core/memory/` | 8 | Layered rules: `org.md`, `team.md`, `project.md`, per-phase files |
| `core/sensors/` | 6 | Sensor definitions: required sections, upstream coverage, traceability, claim sources, linter, type check |
| `core/hooks/` | 20 | Harness hooks in TypeScript: transition guard, plan-approval guard, review freeze, reviewer scope, run sensors, audit log, human-turn record, stage-rule delivery |
| `core/tools/` | 134 | The engine (`aidlc-orchestrate`, `aidlc-state`, sensors, audit, units, swarm, worktrees, plugins, installers) |
| `core/scopes/` | 11 | Scope definitions: enterprise, feature, mvp, poc, bugfix, refactor, infra, security-patch, classic, workshop, express |
| `core/skills/` | 24 | Helper skills (knowledge, replay, issue report, cost) |
| `harness/` | 113 | Per-assistant packaging; `harness/claude/` holds settings, hooks wiring and a manifest |
| `docs/guide`, `docs/harness-engineering`, `docs/reference` | 107 | User guide, authoring guide, reference (state machine, sensors, rules, agents, stages) |

The paths listed in the rebuild prompt exist as described. `core/aidlc-common/stages/` is split by phase folder.

## Core ideas

1. **Engine owns state; the model executes one move.** The conductor never edits state; it reports outcomes to the engine.
2. **Stages are declarative.** Inputs, outputs, agents, reviewer, sensors and scopes live in front matter, not code.
3. **Approval gates are hard stops.** Every stage except Initialization needs explicit human approval; the assistant must stop and wait.
4. **Independent review.** A separate reviewer agent, run as its own sub-agent, reviews a declared artifact before the gate, with a bounded number of repair iterations.
5. **Deterministic sensors** run at the gate and can block it.
6. **Layered rules** (org, team, project, phase) and a learning ritual that turns corrections into rules only after the person agrees.
7. **Scopes** select which stages run; depth sets detail.
8. **Agents never call each other.** Support agents write contribution files; the lead collates. The conductor is the only bus.
9. **Hash-free but complete audit**: lifecycle, phase and stage events with a fixed taxonomy.

## Relevance

High for concepts (declarative stages, gates, reviewer, sensors, scopes, rules, learning). Low for code: it is TypeScript tied to assistant harnesses and file-based state, while we are a multi-tenant web platform with a database. See `adaptation-decisions.md`.
