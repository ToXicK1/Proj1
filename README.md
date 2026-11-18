# AI-DLC Orchestration Platform

A configurable, governed platform that runs a software project through a professional AI-assisted lifecycle (Business Analysis, Architecture, UI/UX Design, Development, QA & Security, DevOps & Release). AI agents generate and review work, deterministic sensors validate it, humans authorize every protected transition, and the workflow engine advances the state.

Status: **Milestone 1 (research and architecture) only.** There is no runnable application yet.

## Start here

- Plan and status: [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md), [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Research on the reference design: [docs/research/REFERENCE_ARCHITECTURE.md](docs/research/REFERENCE_ARCHITECTURE.md)
- Open questions and risks: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)

## Layout

```
backend/    FastAPI service (bounded contexts under backend/app)
frontend/   React + TypeScript console and end-user portal
shared/     JSON schemas, API contracts, workflow templates
infrastructure/  Docker and deployment
tests/      integration, end-to-end and security suites
docs/       research, architecture, development and operations documents
.claude/    development-time Claude Code agents, skills and hooks (planned)
```

## Principles

1. The workflow engine is the only writer of stage state.
2. Only authenticated humans can approve; approvals are bound to exact artifact versions.
3. Mandatory validations fail closed.
4. Secrets are never sent to the browser, logged, or committed.
5. Configuration is versioned data; running executions keep their pinned version.

## Not yet available

Running the application, Docker Compose, live AI provider calls, and CI. These begin in Milestone 2.
