# Rebuild Plan

Date: 2026-11-19. Source: the Master Rebuild Prompt, `REPOSITORY_AUDIT.md`, and the research under `docs/reference-research/`.

## 1. Approach

Evolve the existing modular monolith. Keep the tested engine, approvals, providers, sensors, hooks, rules, audit and sandbox. Add the missing subsystems around them and rebuild the user-facing workspaces. No module is rewritten without a demonstrated reason (prompt rule 29.3).

## 2. Decisions (answered 2026-11-19; see `TECHNICAL_DECISIONS.md` RD-1 to RD-8)

Outcome: D1 department stages, D2 professional-only approval with owner input routed through the professional, D3 to D7 as recommended, D8 commit to main and push.

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Default lifecycle | (a) The rebuild prompt's department stage lists: BA 8, Architect 10, Designer 10, Developer 9, QA 11, DevOps 9. (b) Keep the AWS 33-stage lifecycle. | (a). The prompt is explicit and says not to reproduce the AWS lifecycle blindly. Keep AWS-style scopes to choose which stages apply per project type. Keep the AWS template importable. |
| D2 | Who approves | Each department ends with Human Professional Review, then User Review and Approval where the prompt lists it | Both. Professionals approve their department's work. The project owner approves the stages the prompt names as user approvals. This replaces the earlier "owner never approves" choice. |
| D3 | Rebuild strategy | Evolve the monolith, or start a new codebase | Evolve |
| D4 | Durable execution | PostgreSQL job queue with a worker process, or Redis and a task framework | PostgreSQL queue (`FOR UPDATE SKIP LOCKED`). No new service; transactional with workflow state. |
| D5 | File storage | MinIO (S3-compatible) in Compose, or a local volume | MinIO. Matches production object storage. |
| D6 | Styling | Adopt Tailwind while rebuilding the workspaces, or keep plain CSS | Adopt Tailwind with the existing colour tokens during Phase 10 |
| D7 | Provider for the end-to-end proof | Local Ollama (no keys), or a cloud provider key set by you in `.env` | Ollama first. Add a cloud key when you choose. |
| D8 | Uncommitted work | Commit the current tree as a baseline before the rebuild, or keep it uncommitted | Commit to a branch as the baseline |

## 3. Phases

Each phase ends with tests, verified behaviour, updated docs and known issues.

| Phase | Content | Exit check |
|---|---|---|
| 1 Audit | `REPOSITORY_AUDIT.md`, this plan | Done |
| 2 Research | `docs/reference-research/` (11 documents) | Done |
| 3 Architecture | `docs/architecture/` (7 documents) | Done, pending D1 to D8 |
| 4 Foundation | Roles and permissions model, object storage, job queue and worker, correlation IDs, baseline commit | Done 2026-11-20: worker survived an API restart and a SIGKILL mid-stage (live); permission matrix tests |
| 5 Workflow engine | New states, parallel and conditional stages, stage dependencies table, recovery, escalation hooks | Every valid and invalid transition tested |
| 6 Orchestration | Specialist agent registry per department, execution records, context retrieval, streaming, tool calling with permissions, routing policies | One real provider end to end |
| 7 Profiles | Six departments with their stages, agents and deliverables (BA first, end to end) | BA complete before the rest |
| 8 Human supervision | Reviewer assignments (primary, backup, project), review queues, review packages, all review actions, escalation, reassignment | AI cannot approve or advance a human gate |
| 9 Collaboration | Channels, threads, handoffs, decisions, disagreement escalation, human participation | Cross-profile discussion linked to artifacts |
| 10 Workspaces | Project workspace, six profile workspaces, collaboration area, Tailwind | Every visible control works |
| 11 Files and knowledge | Uploads, validation, extraction, OCR, chunks, provenance, stage-specific retrieval | Agents receive only their files |
| 12 Studio | Departments, specialists, reviewer assignment, escalation and routing policies | Invalid workflows cannot publish |
| 13 End to end | The 15-step lifecycle in the prompt | Passes on a real provider |
| 14 Hardening | Security and performance testing, monitoring, backup, deployment docs | Readiness assessment |

## 4. What is kept, changed and retired

- Kept: auth, organizations, projects, engine core, compiler, approvals, artifacts, providers, agents, skills, sensors, hooks, rules, audit, studio, sandbox.
- Changed: lifecycle definition (D1), approval roles (D2), portal service split into workspace, intake and conversation services, background tasks replaced by the worker (D4).
- Retired: Milestone 3 demonstration work functions and template, the owner keyword router (replaced by a validated classifier with the rules as fallback), empty planned folders.

## 5. Risks

- Scope: the prompt is very large. Phases 6 to 11 each need several working sessions.
- Local model quality: a 4B model will produce weak specialist output and slow runs. A cloud provider will be needed for credible end-to-end quality.
- Real deployment needs a target environment and credentials that only you can provide.
