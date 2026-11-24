# Architecture clarification: client, Project Manager and the seven-profile organization

Date: 2026-11-24. A report only: no code has been changed for this clarification. Implementation waits for your
confirmation of the decisions in section 9.

## 1. My understanding

- **Discovery is human-led.** The client meets the human Project Manager in person. The PM runs discovery, records
  meetings, collects documents and builds a validated Project Intake Package. AI (the PM persona) structures and
  checks; it never owns business decisions.
- **The Project Manager is the seventh professional profile,** with its own workspace, AI persona, permissions,
  artifacts and approvals. The PM coordinates the six engineering departments but cannot override their specialist
  authority: security, architecture approval, QA results or release authorization.
- **The client has a separate portal:** overview, progress, a chat with the human PM, a project AI assistant, and
  deliverables with feedback, approvals where applicable, and change requests. It is not a chatbot-first intake,
  and it is not an eighth profile.
- **The lifecycle is iterative:** PM discovery, then BA (BRD baseline), then epics and stories, then sprint
  planning, then Architect and Designer in parallel, then development, QA and security, then **BA business
  verification**, then the PM's report to the client, then DevOps release. DevOps works throughout, and there are
  several sprints.
- **One Control Plane governs everything:** the deterministic workflow engine commits transitions, approvals are
  human, authenticated and bound to exact versions, a missing reviewer means wait or escalate, everything is
  audited, and client-facing data is kept separate from internal data.

## 2. What the repository already supports (verified, not inferred from screens)

| Area | Today | Where |
|---|---|---|
| Workflow engine | State machine, phased runs, recovery, parallel branches, conditions, escalations, send-back, owner-input steps; only the engine commits transitions | `app/workflows/` |
| Approvals | Human-only, bound to the exact artifact version, slot policies, separation of duties, sensors that block, risk acceptance | `app/approvals/`, `app/sensors/` |
| Work records | Versioned records with provenance (confirmed, assumption, AI suggestion, open question, platform draft), links, comments, packages that freeze versions, handoffs, RD-19 second-person rule | `app/work/` |
| Departments | Six profiles (`member_profiles`), the BA, Architect and Designer department lifecycles (preview), workspaces with real modules for those three | `app/portal/lifecycle.py`, `frontend/src/workspace/` |
| AI | Leads, independent reviewers, specialists, READ tools over approved work, routing, budgets and failover, live activity, a department assistant | `app/agents/`, `app/providers/`, `app/work/assistant.py` |
| BRD and SRS | Assembled by the platform from approved BA records at the department review | `app/work/documents.py` |
| Audit | Hash-chained, append-only audit log for every decision | `app/audit/` |
| Client portal | Overview (current step, phases, recent activity from records), Lifecycle, Project brief, Deliverables (read, comment, request changes), Tickets, Conversations, Testing | `frontend/src/portal/ProjectPortal.tsx`, `app/portal/` |
| Client to PM chat | Direct messages owner to project manager (and administrator) exist in the global chat | `app/collab/service.py` (`DIRECT_PAIRS`) |
| Client AI | Per-department "representatives" answer the owner from that department's latest deliverable, filtered by an owner-safety classifier, with no tools | `app/portal/service.py:answer_question` |
| Owner feedback | Defect, new requirement, enhancement, usability, security concern, scope change; triaged, never changes approvals | `owner_feedback`, tickets |
| Project Manager | An **organization role** with oversight of every project (Oversight page), project-team chat and direct messages | `app/organizations/models.py`, `app/collab/service.py` |

## 3. What conflicts with the clarification

| # | Conflict | Today | Clarification |
|---|---|---|---|
| C1 | **Who does discovery** | The owner fills an 8-question brief in the portal and confirms it, which starts the lifecycle | The PM meets the client, records meetings, validates an intake package, and starts the BA handoff |
| C2 | **Client approvals** | RD-2 (your earlier decision): the owner never approves; they give input, and the assigned professional approves | "Client reviews and approves the BRD", "approve or reject applicable deliverables", "approve applicable milestones" |
| C3 | **The PM's standing** | An organization role with oversight only: no profile, workspace, AI persona or approvals, and it cannot create projects | A first-class professional profile with a workspace, an AI persona and approval duties (brief, sprint plans, reports, change requests) |
| C4 | **Who creates accounts and projects** | People sign up themselves with a requested role, verify their email, and an administrator confirms them; owners and administrators create projects | The administrator creates every account with its role and a temporary password, and creates projects and assigns people to them; the person changes the password at first sign-in (D2, amended) |
| C5 | **Client AI** | Several per-department AI representatives | One project assistant that answers from authorized project records and routes decisions to the PM |
| C6 | **Shape of the lifecycle** | One linear pipeline of steps (the department preview runs BA, then Architect and Designer in parallel) | Iterative sprints after the backlog, QA alongside development, a BA verification phase, continuous DevOps |

Nothing needs **removing**. Each conflict is resolved by changing who does a step or by adding a layer; working
modules stay.

## 4. Gap analysis

| Requirement | Current implementation | Gap | Action |
|---|---|---|---|
| Physical PM-led discovery | None; the owner self-serves the brief | Whole capability | BUILD (PM meetings and intake), MODIFY the owner brief (C1) |
| Meeting records | None | Whole capability (meeting record, notes, attachments, decisions, actions) | BUILD as work-record kinds plus file attachments in object storage |
| AI meeting analysis | None; the department assistant is the nearest pattern | PM persona analysis of meeting notes, provisional until validated | BUILD on the assistant pattern (suggestions only) |
| Project intake | `intake_revisions`: 8 owner-answered fields, confirmed by the owner | PM-owned, richer fields (objectives, stakeholders, NFRs, integrations, dependencies, decisions, budget), validated by the PM | EXTEND the intake model and MODIFY who confirms it |
| Project brief | The confirmed intake acts as the brief; no document | A versioned Project Brief or PID approved by the PM before the BA handoff | BUILD (assembled draft like the BRD, PM approval) |
| BA handoff | Handoffs exist between departments, for approved packages | A PM to BA handoff of the intake package, and BA clarification requests routed through the PM | EXTEND handoffs (PM as a department) |
| Dedicated PM workspace | Oversight page only | 12 modules | BUILD on the workspace shell |
| PM AI persona | None | PM lead agent and assistant with PM-only tools and context | BUILD (agents and routing exist) |
| Seven professional profiles | Six | The `project_manager` profile | EXTEND `TEAM` and profiles; keep the org role for org-wide oversight |
| Client portal | Overview, Lifecycle, Brief, Deliverables, Tickets, Conversations, Testing | Sprint progress, milestones, a PM chat inside the project, approvals and change requests | EXTEND (keep the portal; no chatbot-first) |
| Client AI assistant | Per-department representatives answering from one deliverable | One project assistant over approved, client-visible records only; routes scope changes to the PM; never commits | MODIFY the representatives into one assistant |
| Client to PM communication | Direct messages exist in the global chat | A project-scoped thread with the assigned PM, inside the portal | EXTEND |
| Approval versioning | Yes, exact versions, for professionals | Client approvals on selected deliverables (if you confirm C2) | EXTEND (an extra approval slot, same machinery) |
| Sprint management | None | Sprints, sprint plans with PM approval, activation by the engine | BUILD |
| Task allocation | None (records have owners; steps belong to departments) | Department tasks with owner, due date, dependencies, reassignment history | BUILD as a record kind plus links (reassignment is a versioned edit) |
| Timeline and dependencies | Stage dependencies and record links exist | Milestones and a view of what blocks what | BUILD milestones; EXTEND links (`blocks`, `depends_on` exist) |
| Risks and issues | Risk records (BA), technical risks (Architect), escalations | A PM risk and issue register with explicit owners | EXTEND (a PM risk kind and owner field) |
| Change requests | Step-level change requests; owner feedback of kind "scope change" | The full CR process: impact by BA, Architect and PM, a report, approvals, then a baseline update | BUILD a CR workflow on the existing records and engine |
| BA business verification | None | A verification step after QA, with a report | BUILD (a BA step in the delivery phase) |
| Central workflow orchestration | Yes | Sprint-level workflows | EXTEND |
| Role-based permissions | Yes, server-side, per profile and project | PM-specific rules (coordinates, cannot override specialists); client visibility per artifact | EXTEND |
| Audit history | Yes | New actions audited the same way | KEEP |

## 5. Proposed architecture

### 5.1 Organization

```
Client ──(in person)──► Human Project Manager ◄── PM AI persona (drafts, analysis; never decides)
   │                          │ coordinates (no specialist override)
   │ client portal            ▼
   │ (overview, progress,  ┌─────────────── six engineering departments ───────────────┐
   │  PM chat, assistant,  │ BA · Architect · Designer · Developer · QA & Security ·   │
   │  deliverables, CRs)   │ DevOps & Release (each: AI agents + human supervisor)      │
   ▼                       └───────────────────────────────────────────────────────────┘
AI-DLC Control Plane: workflow engine · approvals · records and artifacts · context · routing · sensors ·
hooks · audit · notifications · permissions (everything above runs through it)
```

### 5.2 How it fits the existing architecture (no duplication)

- **The PM is a profile and a department,** in `TEAM`, `member_profiles` and the work-record kinds, so it gets the
  workspace shell, records, packages, handoffs, assistant, routing and audit **for free**. The existing
  organization role `project_manager` stays for organization-wide oversight. The two are different things: being
  allowed to see every project, and being the PM of a project.
- **Meetings, intake items, the brief, sprint plans, tasks, milestones, PM risks and change requests are new
  record kinds**, with versions, provenance, links and comments as today. Only what needs its own lifecycle gets a
  table: sprints (activation by the engine) and change requests (a multi-party approval).
- **The project brief is assembled like the BRD** (a platform draft from validated intake records) and approved by
  the PM. Its approval is a step in the lifecycle, so the BA department can only start from an approved brief.
- **Client approvals,** if confirmed, become an extra approval slot `client` on chosen steps (BRD baseline, design
  sign-off, UAT, milestones). The professional's approval still comes first, and the same machinery binds to the
  exact version.
- **The client assistant** replaces the per-department representatives. It is one agent with a client-safe context
  built only from client-visible approved artifacts, the project status (records and workflow), and the client's
  own requests. It has no internal records, agent traces or prompts. It can create a question or a change request
  for the PM, and never commits anything.
- **Sprints** are a second layer above the department lifecycle. The baseline phases (PM intake, BA baseline,
  Architect and Designer baseline) stay lifecycle steps. Each sprint is then its own workflow execution created from
  a sprint template (development, code review, QA and security, BA verification, sprint review), activated by the
  engine after the PM approves the sprint plan. Several sprints can be open at once, and DevOps has a continuous
  track. The engine already supports several executions per project; the portal and records only need to know
  which execution is which (decision D5).

### 5.3 Lifecycle and workflow states

The stage states stay the same. New step kinds and records:

| Phase | Steps (kind) | Who decides |
|---|---|---|
| 1 PM discovery | Client meetings (PM records), AI meeting analysis (AI suggestions), Intake validation (records), Project Brief (platform draft) | PM approves the brief |
| 2 BA baseline | Today's BA steps, starting from the approved brief instead of the owner's form; BRD and SRS | BA approves the package; PM reviews scope alignment; client approves the BRD (if D1) |
| 3 Backlog | Epics, stories, acceptance criteria, Definition of Done, priorities, dependencies (BA) | BA; PM validates planning suitability |
| 4 Sprint planning | PM AI drafts the sprint plan | PM approves; the engine activates the sprint |
| 5 Architecture and design | Architect and Designer lifecycles (parallel) | Architect and Designer |
| 6 to 8 Sprint delivery (per sprint) | Development, code review, QA and security, defects back to development, BA verification | Developer, QA, BA; mandatory gates cannot be overridden |
| 9 Reporting | PM AI consolidates from records; PM reviews; client portal update | PM; client feedback or approval (if D1) |
| 10 Release | DevOps release steps (continuous track plus release) | Release Manager authorization only |

### 5.4 New data (entities)

| Entity | Form | Notes |
|---|---|---|
| `project_manager` profile | profile row and `TEAM` entry | per-project assignment, like other profiles |
| Client meeting | record kind `meeting` | title, time, participants, objectives, raw notes, structured notes, decisions, follow-ups, status; attachments via stored objects |
| Meeting attachment | `stored_objects` (exists) linked to the record | access by project role; never shown to other clients |
| Intake item | record kinds (`business_objective`, `feature_discussed`, `constraint`, `integration`, `dependency`, `decision`, `budget_timeline`) plus the existing BA kinds where they fit | PM-owned, validated by the PM |
| Project brief | record `document` with `doc_type=project_brief` (platform draft) | PM approval binds to its version |
| Epic, Definition of Done | record kinds (BA) | links to stories and requirements |
| Sprint | table `sprints` (number, goal, dates, status, plan record version, workflow execution) | activated only by the engine after the PM's approval |
| Task | record kind `task` (department, owner, priority, due date, status, blockers) | reassignment is a versioned edit with an audit event |
| Milestone | record kind `milestone` (date, criteria, linked records) | progress only from linked records' state |
| PM risk or issue | record kind with an explicit owner | |
| Change request | table `change_requests_v2`, or an extension of the existing one, with impact entries per department and a baseline-update record | the baseline changes only after the required approvals |
| Client approval | approval slot `client` on chosen steps (existing tables) | only if D1 is confirmed |
| Client assistant exchange | table like `assistant_exchanges`, client scope | |

### 5.5 APIs (new or extended)

- `/api/v1/orgs/{org}/people` (administrator): create an account with role and profiles, returning the temporary password once; reset it; `/api/v1/auth/password` for the forced first change.
- `/projects/{id}/work/project_manager/...`: the existing record, package and handoff APIs, used by the new department.
- `/projects/{id}/meetings/{record}/attachments`: upload and download through object storage, with role checks.
- `/projects/{id}/pm/analysis`: PM AI meeting analysis (a queued job; results are suggestions).
- `/projects/{id}/sprints`: create a plan, approve it (PM), view; activation by the engine.
- `/projects/{id}/change-requests`: create (client or PM), request impact, record impact, decide, apply to the baseline.
- `/portal/projects/{id}/assistant`: the client assistant, with client-safe context only.
- `/portal/projects/{id}/pm-chat`: the project thread with the assigned PM.
- `/portal/projects/{id}/progress`: sprints, milestones and deliverables, from records only.

### 5.6 Permissions and approvals (the PM's limits are enforced on the server)

| Action | Client | PM | BA | Architect, Designer, Developer | QA & Security | DevOps & Release |
|---|---|---|---|---|---|---|
| Accounts, roles, projects, assignment | — | — (the administrator does this) |  |  |  |  |
| Meetings, intake, brief | read the brief (if shared) | create, validate, approve the brief | read the approved brief | read the approved brief | read | read |
| BRD baseline | approve (if D1) | review scope alignment | approve the package | read | read | read |
| Sprint plan | see progress | approve | contribute | contribute | contribute | contribute |
| Tasks | — | assign and reassign (audited) | own their department's tasks | same | same | same |
| Architecture decision | — | cannot approve | — | Architect approves | — | — |
| QA and security gates | — | cannot pass or override | — | — | QA decides; mandatory gates hold | — |
| Production release | — | cannot authorize | — | — | sign-off | Release Manager authorizes |
| Change request | create | route and decide on planning | business impact | technical impact | quality impact | release impact |
| Client-facing report | read | approve before sending | contribute | contribute | contribute | contribute |

## 6. Changes by type

| Type | Change | Affected (main files) |
|---|---|---|
| KEEP | Workflow engine, approvals, sensors, audit, work records, packages, handoffs, routing, budgets, BA, Architect and Designer lifecycles, workspace shell | `app/workflows`, `app/approvals`, `app/work`, `app/providers`, `frontend/src/workspace` |
| EXTEND | `TEAM` and profiles gain `project_manager`; handoffs from the PM; intake fields; the portal gains progress, a PM chat, approvals and CRs; client approval slots (D1); sprint-aware executions; record kinds; permission rules for the PM's limits | `app/portal/lifecycle.py`, `app/portal/service.py`, `app/work/kinds.py`, `app/approvals/policy.py`, `ProjectPortal.tsx`, `modules.ts` |
| MODIFY | Who confirms the intake (the PM, not the owner: C1); who creates projects (C4); the per-department client representatives become one client assistant (C5); RD-2 if you choose client approvals (C2) | `app/portal/service.py` (intake, `answer_question`), `app/projects/service.py`, `app/organizations/service.py`, docs |
| BUILD | PM workspace (12 modules), PM AI persona, meetings and attachments, meeting analysis, project brief, sprints, tasks, milestones, change-request workflow, BA business verification, client assistant | new modules under `app/work`, `app/pm` (thin), `frontend/src/workspace`, `frontend/src/portal` |
| REMOVE | Nothing. The owner's 8-question form becomes optional (see D2) rather than being deleted | — |

## 7. Roadmap (foundations first)

| Phase | Objective | Backend and database | Frontend | AI | Tests and acceptance |
|---|---|---|---|---|---|
| P0 | Administrator-provisioned accounts | accounts created by an administrator with role and profiles; a generated temporary password (hash only, shown once, expires after 7 days); forced change at first sign-in (every other action refused until then); administrator reset (new temporary password, sessions ended); self-signup off by configuration; a command to create the first administrator; projects created by administrators with people assigned; migration | Team page: add person, show the temporary password once, reset; a change-password page that opens first; project creation and assignment for administrators | — | the temporary password is never stored or logged in plain text; nothing works before the change; an expired one is refused; non-administrators cannot create accounts or projects; tests and browser specs move from self-signup to provisioned accounts |
| P1 | PM as the seventh profile | profile, `TEAM`, PM record kinds, permission rules for the PM's limits, migration | Professional team shows 7; PM workspace shell | — | a PM is assigned per project; specialist overrides are refused (architecture, QA, release) |
| P2 | Client meetings and intake | meeting kind, attachments (object storage), intake kinds, validation | Client Meetings, Project Intake modules | — | records, files, validation and audit; the client cannot see internal notes |
| P3 | PM AI persona | PM lead and assistant; meeting analysis job; suggestions only | AI Meeting Analysis module | PM agents, routing, budgets | analysis is provisional; nothing is validated without the PM |
| P4 | Brief and BA handoff | project brief draft (assembler), PM approval step, BA lifecycle starts from the approved brief, clarification through the PM | Project Brief, BA Handoff modules | — | the BA cannot start before the brief is approved; versions are recorded |
| P5 | Client portal alignment | client assistant (client-safe context), project PM chat, progress endpoint, client approval slots (D1), CR creation | portal Overview and Progress, PM chat, assistant, approvals | client assistant | no internal data leaks (canary tests as today); approvals bound to versions |
| P6 | Backlog and sprints | epics, DoD, sprints table, sprint template execution, PM approval, activation | Sprint Management, Task Allocation, Timeline | PM AI sprint drafting | the engine activates only approved plans; progress only from records |
| P7 | Change requests | CR workflow with impact from departments and a baseline update after approval | Change Requests (PM and client) | PM AI impact analysis | the baseline never changes before approval |
| P8 | Delivery phases | BA business verification step; reports | Deliverable Reviews and Reports | PM AI report drafting | the PM reviews before the client sees it |
| — | Then the remaining Phase 7 work | Architect studio, design canvas, Figma (7.2b–d), Developer, QA, DevOps departments | | | |

Each phase ends with its own tests, a browser check and a live run where it involves the model, as before.

## 8. Risks

- **Scope:** this is about as large as Phase 7 so far. P1 to P4 are the foundation; the rest can follow in order.
- **Changing who does intake** affects every existing project. Running projects keep their versions (the engine
  pins them), and only new projects use the PM-led start.
- **Sprints** change the shape of delivery. Doing them before the Developer and QA departments means those are built
  sprint-aware from the start, rather than reworked later.

## 9. Decisions (answered 2026-11-24)

| ID | Question | Answer |
|---|---|---|
| D1 | Client approvals | **The client approves chosen items:** the BRD baseline, design sign-off, UAT and milestones. The professional approves first; the client's is a second, required approval on those items only. Elsewhere the client gives input. This amends RD-2 |
| D2 | Accounts and projects (amended 2026-11-24) | **The administrator does it all.** They create each account (client, PM, professionals, other administrators) with one of the platform's roles and a generated temporary password, shown to them once to pass on. The person must change it at first sign-in. The administrator also creates projects and assigns the client, the PM and the professionals to them. Self-signup and invitations by the PM are not used. The permissions behind each role stay as the platform defines them; custom roles are not part of this |
| D3 | The client's 8-question brief form | **An optional pre-meeting form.** Its answers feed the PM's intake as unconfirmed input; only the PM validates the intake and approves the brief |
| D4 | Client AI | **One project assistant** replaces the per-department representatives. It answers from client-visible approved records and project status, and routes decisions and scope changes to the PM |
| D5 | Shape of delivery | **Baseline, then sprints.** PM intake, the BA baseline and the first architecture and design stay lifecycle steps; each approved sprint plan starts its own sprint workflow; several sprints can run; DevOps has a continuous track |
| D6 | Order | **Now, before 7.2b.** P1 to P8 come before the Architect studio, design canvas, Figma and the last three departments |
| — | Uncommitted 7.2a and BRD/SRS work | Commit and push first |
