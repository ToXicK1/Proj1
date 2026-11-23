# Professional workspaces: audit and functional architecture

Date: 2026-11-23. Source: the "Professional SDLC Roles … Dedicated Role-Specific Workspaces" brief (phases 1 and 2
of its section 14). No workspace code has been written yet. This plan replaces section 4 of `PHASE_7_PLAN.md`
("Workspace UI") and widens Phase 7 from "six department lifecycles" to "six department lifecycles, each with its
own working environment".

## 1. Audit: what exists today

### 1.1 Reusable as it is (backend, tested)

| Area | What exists | Used by the workspaces for |
|---|---|---|
| Workflow engine | State machine (NOT_STARTED … CANCELLED, plus AWAITING_USER_INPUT), phased stage runs, recovery, parallel and conditional stages, dependencies, escalations, rework loops (Phases 5–6) | The single source of stage state for all six departments. The brief's UNDER_REVIEW / AWAITING_APPROVAL map to today's VALIDATING / AWAITING_HUMAN_REVIEW; no new states are needed |
| Artifacts | `artifacts`, `artifact_versions` (immutable, hashed), `review_records`, `approval_decisions` bound to an exact version, `change_requests` | Version history and approvals for every document, diagram, schema and design |
| Governance | Human-only approvals enforced on the server, AI never self-approves, risk acceptances, audit hash chain | Every approval and sign-off screen |
| Execution | Sandbox builds and unit tests with stored evidence, sensors (secrets, build, tests), code archives in object storage | Developer builds, QA automated results, the first real CI pipeline |
| AI | Leads, reviewers, specialists, READ tools over approved upstream work, routing, budgets and failover, live activity | The per-department AI assistant |
| Collaboration | Project team chat, direct messages, tickets with comments, owner questions, notifications | Team Room, clarification requests, the base of defects |
| Access | Org roles, project roles, professional department assignments (`member_profiles`), owner isolation | The permission matrix (section 5) |
| Frontend | Design tokens (RD-11), app shell and sidebar, React Flow (`@xyflow/react`, already a dependency), activity menu | The shell and every diagram editor |

### 1.2 Needs redesign

- **The professional's page.** Today a professional gets one generic "Workspace" tab: a list of their department's
  steps and deliverables, rendered as JSON-shaped text (`ContentView`). The same component serves all six
  departments, which is exactly what the brief rules out.
- **Deliverables are AI-shaped, not work-shaped.** A stage's output is one JSON document (for example
  `functional_requirements` as a block of text). A BA cannot filter, link, version or approve one requirement.
- **Tickets are close to defects but not the same.** They lack severity, build, reproduction steps and the
  New → … → Closed lifecycle.
- **The sidebar** lists departments under each project but they all open the same tab.

### 1.3 Missing

Requirements, user stories, rich documents (BRD/SRS), process and architecture diagrams, data models, API
specifications, technology decisions/ADRs, design screens, components, prototypes, development tasks, repository
views, pipelines, test cases, suites and runs, defects, security findings, environments, deployments, releases,
incidents, formal handoffs, the Professional Team page with live department cards, and a contextual AI assistant per
department.

## 2. The core design decision: work records on top of artifacts

The brief asks for both rich, editable working objects (one requirement, one test case) **and** strict versioning,
approval of exact versions and AI-never-commits-state. Both are possible with one rule:

> **A department's working objects are records** (a requirement, a story, an entity, an endpoint, a screen, a test
> case…), each with an ID, owner, status and its own version history. **What gets approved is a package**: an
> immutable artifact version that snapshots the exact record versions it contains.

- AI stages no longer write free text into one JSON blob. They **propose records** (for example 14 requirements),
  which the engine stores as `proposed`, tagged as AI-authored, with the sources the AI used.
- Professionals edit, accept, reject, merge, link and add records. Every edit is a new record version with author
  and reason; nothing is overwritten.
- "Submit for review" freezes the current record versions into an artifact version. Approvals, reviews and change
  requests keep working exactly as today, bound to that version. Downstream departments read the **approved
  snapshot**, never live drafts (this is what the READ tools already enforce).
- Every record carries a `provenance` field: `confirmed` (stated by the owner or a professional), `assumption`,
  `ai_suggestion` or `open_question`. This drives the visual distinction the brief asks for in 3.C, and stops the AI
  silently inventing requirements: AI-proposed records start as `ai_suggestion` until a person confirms them.

One generic backend serves all records: `work_items` (id, project, department, kind, key such as `REQ-012`,
current version, status, provenance, owner), `work_item_versions` (immutable JSON body validated against the kind's
schema, author, reason), `work_item_links` (typed: `derives_from`, `implements`, `tests`, `depends_on`, `blocks`,
`designs`), `comments` (anchored to an item version, optionally to a field or a pinned position) and `handoffs`.
Kinds and their JSON schemas live in code (`app/work/kinds/*.py`), so each department gets proper validation and its
own UI without a new table per object. Things with their own lifecycle and machinery get their own tables: test
runs, defects, pipelines and deployments (section 4).

Why not one table per object: about 30 object types share 90% of their behaviour (versioning, links, comments,
permissions, audit, search). One tested core keeps that behaviour identical everywhere; the kind schema gives each
its own fields. Traceability (BA section G) then becomes a query over `work_item_links`.

## 3. Global application structure

| Brief | Plan |
|---|---|
| Organization and project selector | Kept in the sidebar; the selected project becomes the context for every workspace route |
| Global project overview | Today's project Overview, plus the department cards below |
| Professional Team page | New `/projects/:id/team`: six cards with assigned people, AI profile and version, current stage (engine), pending tasks, approvals and blockers, latest activity, and progress = approved stages / applicable stages (never a typed percentage) |
| Department workspaces | New routes `/projects/:id/ba`, `/architect`, `/design`, `/dev`, `/qa`, `/devops`, each with its own left navigation (the module lists in the brief) and its own main area |
| Project Team Room, Notifications | Today's team chat and notifications, plus handoff threads |
| Deliverables, Activity and decision history | Today's deliverables and audit trail, filtered per department |
| Right contextual panel | Shared component: AI assistant (section 6), comments on the selected item, linked items, the human supervisor. Collapsible, so the design canvas and diagram editors can use the full width |

Shared building blocks, built once in the shell phase: record table (search, filter, sort, group, saved views),
record detail with version history and side-by-side compare, comment thread, link picker, package submit and
review screen, handoff screen, diagram editor (React Flow, saving node/edge JSON, never screenshots), rich document
editor, and empty, loading, error and permission-denied states.

## 4. The six workspaces: what is real, and what needs something we do not have

Each module is marked **Real** (built on existing or planned platform functionality), **Needs your decision** (a
real version needs an outside system), or **Labelled** (shown as a plan or design, clearly marked as not live).

### 4.1 Business Analyst: requirements engineering

All 13 modules are **Real** on the work-records core. Kinds: `requirement`, `user_story`, `epic`, `stakeholder`,
`process_flow` (React Flow, As-Is/To-Be), `risk`, `assumption`, `discovery_question`, `document` (BRD, SRS and the
other named documents: rich text with section outline, linked requirement IDs, export to Markdown/PDF). Discovery
reuses owner questions: the BA asks, the owner answers in the portal, answers are recorded and can be promoted to
confirmed requirements. Traceability is a matrix from client request to test case, highlighting missing links.
Handoff shows completion, coverage, open questions and approval state, and submits the package to the gate.

### 4.2 Solution Architect: architecture design

**Real:** system/context/component/deployment/data-flow diagrams (React Flow with typed nodes: service, database,
queue, external system, trust boundary), database design (entities, attributes, keys, relationships, indexes, ER
view, SQL DDL export, schema versions), API workspace (endpoints with schemas, auth, errors, OpenAPI 3.1 import and
export), technology decisions and ADRs, security and infrastructure sections, risk register, independent review
findings (from the AI reviewer and humans, with severity and artifact references), handoff package.
**Labelled:** cloud resources are a proposed design; nothing is provisioned.

### 4.3 UI/UX Designer: design studio

**Real (built in-house):** a frame-based canvas (zoom, pan, device viewports, layers, components, text, shapes,
tokens for colour, typography and spacing), screen records, a design system editor seeded from RD-11 tokens,
prototypes (hotspot links between frames, previewed in the browser), feedback pinned to a position on an exact
screen version, version compare, developer handoff (specs, tokens, states, accessibility notes). Screens are stored
as a JSON element tree and rendered as real HTML/CSS, so the developer and the owner see actual markup, not
pictures. This is a wireframe and layout tool, not a Figma replacement.
**Needs your decision:** Figma integration (section 7, D1).

### 4.4 Software Developer: implementation

**Real:** tasks derived from approved stories and architecture, the implementation planner (modules, dependencies,
sequencing), builds and unit/integration tests in the sandbox with logs and evidence, code review (changed files,
diff viewer, findings from the independent AI reviewer and sensors, human decision), defect rework, QA handoff.
The **repository explorer** is real for the platform's own repository: every generated or edited code version
becomes a commit, so file tree, history and diffs are genuine.
**Needs your decision:** connecting an outside repository such as GitHub (D2).
**Not included:** an in-browser editor or terminal. Professionals edit code through review and rework; an
executable IDE would need a controlled environment the platform does not have, and the brief forbids pretending.

### 4.5 QA & Security: testing platform

**Real:** test cases, suites and campaigns, manual test execution (steps, actual result, screenshots and logs to
object storage, evidence linked to the build version), automated runs (sandbox, actual results only), defects with
the full board (New → Triaged → Assigned → In Progress → Fixed → Ready for Retest → Retesting → Closed/Reopened,
replacing and migrating today's defect tickets), security findings (from sensors: secrets, dependency audit,
static analysis; plus manual findings), UAT as an owner input step, reports computed from recorded runs, sign-off
that separates test results, AI recommendation and human QA approval.
**Real but limited:** performance testing in the sandbox (short load runs against the preview environment only).

### 4.6 DevOps & Release: release console

**Real:** a pipeline engine that runs Source → Build → Static Analysis → Tests → Security Checks → Artifact →
Approval → Deployment → Verification as recorded jobs, each with status, times, logs, execution ID and artifact
references, rerun of failed jobs; build artifacts; configuration (no secret values shown, ever); release planning
and the readiness checklist computed from real records (QA sign-off, open blockers, reviews, migrations); release
approval bound to an exact artifact and environment; incidents; operational handover.
**Needs your decision:** where deployments go (D3). Until a target exists, Deployment and Verification are
**Labelled** "no deployment target configured", the pipeline stops at Approval, and monitoring shows nothing.
Production deployment always needs explicit human authorization at the moment of deploying, on top of the release
approval.

## 5. Permissions (enforced on the server)

| | Owner | Professional, own department | Professional, other department | Project manager | Org admin |
|---|---|---|---|---|---|
| Read own department's records | via portal summaries | yes | approved packages only | yes | yes |
| Create and edit records | answers, feedback, UAT | yes | no (comment and request clarification) | no | no |
| Submit a package for review | no | yes | no | no | no |
| Approve a package or sign off | no (input only, RD-2) | yes, if assigned approver and not the author of the edit being approved | no | no | no |
| Comment, hand off, escalate | on owner-visible items | yes | yes | yes | yes |
| Deploy to production | no | DevOps approver, explicit action | no | no | no |

AI agents act as their department, can only propose records and comments, and can never submit, approve or move a
stage. The engine checks every transition.

## 6. AI assistant per department

One shared panel. It runs the department's lead agent in "assistant" mode with the department's READ tools,
the current project and the item the professional has selected. It answers and proposes (new records, edits as
suggested diffs, findings), and the professional accepts or rejects each proposal. Proposals are recorded as
`ai_suggestion` with sources. It uses the department's routing and is subject to budgets.

## 7. Decisions needed

| ID | Question | Options |
|---|---|---|
| D1 | Design canvas | (a) Build the in-house frame and layout canvas described in 4.3. (b) Also integrate Figma (needs a Figma account, an OAuth app and your authorization; files stay in Figma, the platform links and versions them). |
| D2 | Repository | (a) The platform's own repository of generated code, with real commits and diffs. (b) Also connect GitHub (needs a GitHub App installed by you; credentials stay in encrypted secret storage). |
| D3 | Deployment target | (a) A local preview environment: the release deploys a container onto this machine's Docker as staging, with real health checks, and production stays unconfigured. (b) A cloud target you choose; paid infrastructure, needs your explicit authorization and credentials. (c) None for now: release stops at approval, clearly labelled. |
| D4 | Order of work | (a) Shell and work-records core first, then each department's lifecycle stages **and** workspace together, BA first, keeping RD-12 to RD-14 (recommended). (b) All six workspaces first on today's lifecycle, then the department lifecycles. |

## 8. Phasing (assuming D4 = a)

| Step | Content | Exit check |
|---|---|---|
| 7.0 | Work-records core, comments, links, handoffs, package snapshots; app shell, Professional Team page, workspace routing, shared components, assistant panel | Tests for versioning, links, permissions, package freeze, and that the AI cannot submit or approve |
| 7.1 | BA lifecycle (8 stages, PHASE_7_PLAN §4) plus the BA workspace (13 modules) | A project goes through all BA stages on the real model; the professional edits requirements, approves the package; the owner gives input |
| 7.2 | Architect and Designer (parallel, RD-13), with their workspaces | Both approved from the same BA package |
| 7.3 | Developer workspace, internal repository, code review | Approved code version with real build and tests |
| 7.4 | QA workspace, defects board, security findings, sign-off | A defect goes to the developer and back, retest, sign-off |
| 7.5 | DevOps console, pipeline engine, releases (target per D3) | An authorized release with a recorded pipeline run |
| 7.6 | End-to-end across six departments, then the department lifecycle becomes the default (RD-14) | The brief's section 14 phase 6 list |

## 9. Honest scale

This is the largest part of the rebuild: roughly 30 record kinds, a canvas, a pipeline engine and six distinct
interfaces. Each step above is a phase-sized piece with its own tests and live check, and later ones may move as
earlier ones teach us. Nothing will be shown as working before it works; modules that wait on D1–D3 are labelled
in the UI until then.

### Answers (2026-11-23)

- **D1: (b).** In-house canvas, plus a Figma integration. Figma needs your Figma account, an OAuth app you create, and your authorization when it is connected; credentials go only into encrypted secret storage, never chat or code.
- **D2: (b).** The platform's own repository, plus GitHub through a GitHub App you install; same rule for credentials.
- **D3: (a).** A local preview environment on this machine's Docker as staging, with real health checks. Production stays unconfigured and labelled.
- **D4: (a).** Department by department: step 7.0 (shared core and shell) first, then the BA lifecycle and workspace.

The Figma and GitHub connections are built in the Designer (7.2) and Developer (7.3) steps; they are not needed earlier.

## 10. Step 7.1 in slices (2026-11-23)

| Slice | Content |
|---|---|
| 7.1a | Rule RD-19 (second person for a package with the submitter's own edits). AI stages propose records from their output (a stage's `records` map from output key to record kind). Stage-bound packages: submitting a package for a step creates a system-assembled artifact version of that step and runs the step's sensors on it; the decision goes through the existing approval gate (slots, sensors, hooks, audit), so approving the package *is* approving the step. Rework replaces unconfirmed AI suggestions and keeps confirmed or edited records |
| 7.1b | The 8-stage BA department lifecycle template with the new step kinds: `ai_review` (independent review of the whole department's work), `review_aggregate` (Human Professional Review of the package) and `owner_input` (User Review and Approval, RD-2) |
| 7.1c | Workspace UI: step reviews inside the workspace, the document section editor, the process-flow diagram editor, Scope & Priorities, Change Requests, and the AI assistant panel |
| 7.1d | Live run of the BA department on the real model (the Phase 7 exit check) |
