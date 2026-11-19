# Adaptation Decisions

How the AWS AI-DLC concepts become part of our six-department, human-supervised platform.

| # | AWS concept | Our adaptation | Decision |
|---|---|---|---|
| A1 | Engine owns state; model executes one move | Workflow engine is the only writer of stage state; agents return structured output only | REFERENCE ONLY (built) |
| A2 | Declarative stage files | Versioned stage specs in the database, edited in the Studio, compiled before use | ADAPT |
| A3 | Five phases, 33 stages | Replaced as the default by the prompt's six department stage lists (D1); the AWS set is kept as an importable template | ADAPT |
| A4 | Scopes select stages | Project applicability profiles per project type select stages; governance stages can never be removed | ADAPT |
| A5 | Every stage gated by the person | Every AI stage gated by an assigned human professional; named user approval stages for the project owner (D2) | ADAPT |
| A6 | Independent reviewer, bounded repair | Separate reviewer run with read-only access, optional different provider, iteration limit, review package | ADAPT |
| A7 | Sensors at the gate | Sensors on every version and at the gate; real sandbox evidence for code | REFERENCE ONLY (built) |
| A8 | Support agents contribute, lead collates, agents never call each other | Collaboration hub with channels, contributions, objections, handoffs and decisions; the orchestrator routes every message; humans participate | ADAPT |
| A9 | Loop-back from build-and-test to code generation | QA to Developer rework transition with evidence | ADAPT |
| A10 | Session recovery | Durable job queue and idempotent stage steps | ADAPT |
| A11 | Layered rules and learnings | Hierarchical rules and governed proposals | REFERENCE ONLY (built) |
| A12 | Knowledge per agent | Department skills plus a retrieval layer over project files | ADAPT |
| A13 | Model tiers per agent | Routing policies by task type, complexity and cost | ADAPT |
| A14 | Units of work, swarm, worktrees | Development task breakdown and parallel branches, without git worktrees | REFERENCE ONLY |
| A15 | Human-turn records | Every human message and decision stored with its author | ADAPT |
| A16 | Harness packaging, installers, Claude settings | Not part of the product | EXCLUDE |

## Departures from AWS, and why

- **Multi-tenant web platform**, not files in one developer's workspace: state lives in PostgreSQL with tenant isolation.
- **Several human professionals** per department plus a project owner, not one person driving the assistant.
- **Persistent cross-department collaboration** with human participants, not ephemeral contributions inside one stage.
- **Provider-independent** execution through our adapters, not a coding assistant's own model.
- **Enforcement in backend code**, never in prompt text alone.
