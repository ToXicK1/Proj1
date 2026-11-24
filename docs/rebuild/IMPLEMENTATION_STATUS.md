# Rebuild Implementation Status

Last updated: 2026-11-19.

| Phase | Status | Evidence |
|---|---|---|
| 1 Repository audit | Done | `REPOSITORY_AUDIT.md`, `REBUILD_PLAN.md` |
| 2 AWS AI-DLC research | Done | `docs/reference-research/` (11 documents), checkout `c515d06` |
| 3 Target architecture | Done; decisions D1 to D8 answered | `docs/architecture/` (7 documents), `TECHNICAL_DECISIONS.md` |
| 4 Foundation | Not started | Next |
| 5 to 14 | Not started | — |

## Baseline carried into the rebuild

Working before the rebuild, verified in earlier sessions and in `TEST_RESULTS.md`:

- Accounts, shared organization with admin-confirmed roles and professional profiles, invitations, projects.
- Workflow engine, compiler, versioning, approvals bound to versions, rework, invalidation.
- Provider adapters with encrypted keys, routes and fallback; agents with independent reviewers; skills; 18 sensors; declarative hooks; hierarchical rules with governed proposals; hash-chained audit.
- Workflow Studio with a visual builder, import and export.
- Owner portal with intake, deliverables, conversations, test reports and triage.
- Isolated sandbox that builds and tests generated Python and JavaScript projects; results feed the gates.

Uncommitted at the start of the rebuild: the Milestone 9 portal, the shared-organization remake and the sandbox (decision D8).

## 2026-11-19 — Role-scoped spaces, team chat, tickets and department status (your priority list)

Done ahead of the planned phase order, at your request:

- **Each role sees only its own space** (enforced in the backend): professionals see only their departments' work, status, chat channels, tickets and owner threads; the owner sees the owner view of all departments and never sees internal chat; administrators see everything.
- **Team chat**: a team room plus one channel per department; @mentions notify people; stopped steps post a system note in the department channel.
- **Tickets**: anyone on the project can raise one for a department and pick who to notify. The AI answers questions it can answer safely from the department's work; anything else, or any change, waits for that department's professional, who sees the AI's proposal and can approve it (a change is sent to the AI as a change request on the step waiting for them), resolve, close or comment. The person who raised it can accept an AI answer or reopen.
- **Department status**: each step's state, how long the AI has been working, failed attempts, "slower than usual" after 3 minutes, and plain reasons for stops (specific for professionals, safe wording for owners), plus who it is waiting for.
- **Owner conversation**: owner messages notify the department; professionals reply in person.

Not done yet: AI participation in team chat, ticket assignment changes, attachments, and the visual redesign (you asked to come back to it).

### Team-wide chat and owner isolation (follow-up)

- Team chat is organization-wide (`/team-chat`, API `/api/v1/team-chat/*`), not tied to a project: a General channel plus one channel per department the person holds. Owners and plain members are refused by the backend (403) and get no menu link.
- Project-specific discussion lives in each department's Workspace ("<Department> discussion on this project"). Messages show the author's name ("(you)" only on your own), who they mentioned, and a "Mentioned you" marker.
- Mentions in team chat notify with no project; the notification opens the team chat.
- A project owner always gets the owner view of their own project, even if they also administer the organization. Owners list only their own projects.
- Migration `0015_team_chat` makes `team_messages.project_id` and `notifications.project_id` nullable and moves old project "team" rooms into General.

### Administrators, project managers, oversight and @name direct messages

- New organization role **Project Manager** (`project_manager`; migration `0016_overseers_direct`). Administrators and project managers get a viewer row on every project in the organization (kept in sync when the role changes or a project is created; existing admins backfilled by the migration).
- **Oversight** page (`/oversight`, API `GET /api/v1/oversight`) for both: every project with owners, per-department people, current step and progress, steps waiting for approval and on whom, AI work in progress (slow flagged), issues and open tickets. Overseers can see approvals but cannot give them; only the assigned professional approves.
- Project managers are in the team chat (General and every department channel) and project department discussions. Administrators are not: no channels, no department discussions, 404 on channel reads.
- **Direct messages**: in team chat, starting a message with `@Name` switches to a private chat with that person, which stays until `@everyone` or another `@Name` (like an in-game chat). Direct messages appear in the feed marked "Direct" with "A → B", and the recipient gets a notification. An unrecognised `@name` is refused rather than posted to everyone.
- Who may message whom directly: owner↔project manager, owner↔administrator, administrator↔project manager, project manager↔anyone on the team, professional↔professional. Owners and administrators get a "Messages" page (direct messages only).
- Department discussions in a workspace use inline `@Name` to notify people (the checkboxes are gone).

## 2026-11-20 — Phase 4: Foundation (job queue, worker, object storage, correlation IDs)

- **Job queue** (`app/jobs`, table `jobs`, migration `0017_jobs_storage`).
  - Workers claim jobs with `FOR UPDATE SKIP LOCKED` under a lease (default 300 s), renewed by a heartbeat every third of the lease.
  - A worker that dies loses its job when the lease ends; another worker takes it and records the attempt.
  - Failures are retried with backoff (10 s, doubling, at most 10 minutes) up to 3 attempts, then marked `failed` with the error.
  - Only one job per subject waits at a time (a partial unique index on `dedupe_key`).
- **Worker** (`python -m app.worker`, Compose service `worker`).
  - Runs lifecycle stages (`portal.drive`), owner retries (`portal.resume`), owner answers (`portal.answer`) and ticket triage (`collab.triage`). The API no longer runs any of these in-process.
  - `SIGTERM` lets the current job finish (`stop_grace_period: 60s`).
  - Every 60 s a sweep queues lifecycle work or tickets that are waiting with no job: the safety net for a lost enqueue.
- **Safe to repeat.**
  - A stage commits its result in one transaction, so a crash mid-stage leaves it untouched.
  - Answers and triage mark their job done in the same transaction as their result.
  - Triage skips tickets that are no longer open.
  - Stage `updated_at` now changes on every transition, so the sweep can tell how long work has waited.
- **Object storage** (RD-5, amended).
  - `app/storage` has a small S3 client (SigV4, no new dependency), a `stored_objects` record per object, keys scoped to `orgs/<org>/projects/<project>/<purpose>/<name>`, and a SHA-256 check on every read.
  - Compose runs SeaweedFS with a single identity built from `.env` (`AIDLC_STORAGE_ACCESS_KEY` / `AIDLC_STORAGE_SECRET_KEY`); anonymous and wrong-key requests get 403. Bootstrap creates the bucket.
  - First use: code archives are built once per version, kept, and served from storage after the hash check.
- **Correlation IDs.**
  - Every request gets an `X-Request-ID`: a caller's ID if it is a plain 8–64 character token, otherwise a new one.
  - It appears on the response, every log line, every job, and every audit event (`payload.correlation_id`), and the worker carries it into the work it runs.
- **Readiness**: `GET /readyz` checks the database and (when configured) storage, and returns 503 if either is down.
- **Tests only**: `AIDLC_JOBS_INLINE=true` makes the API run queued jobs after responding. Refused outside development and test.

## 2026-11-20 — Live AI activity panel and the context fix

- **AI activity menu** (top right of every project page, for the professional team: professionals, project managers, administrators; never owners or plain members). API `GET /api/v1/portal/projects/{id}/activity`; table `ai_activity` (migration `0018_ai_activity`).
  - Every step is written in its own short transaction the moment it happens, so it is visible while the stage's own transaction is still open: job started and finished, stage started, what the agent was given, each model call, the result, the independent review, sandbox build and test results, and the outcome.
  - **Live model calls, like a chat app's thinking view:**
    - The exact prompt the agent received: its instructions and its input.
    - An estimate of the prompt's size against the model's context window, with a warning when it may not fit.
    - Any reasoning the model reports, kept separate.
    - The reply streaming in, saved about once a second.
    - While a call runs it shows open with a cursor ("Waiting…", "Thinking…", "Writing…"); when it ends it folds away ("Wrote N characters in Ns").
  - **Streaming:** OpenAI and OpenAI-compatible providers (including Ollama) stream. Reasoning is taken from a `reasoning` / `reasoning_content` field or from `<think>` tags. Anthropic, Gemini and the offline mock still answer in one piece, which then appears whole.
  - **Honest about thinking:** the local `qwen3-vl:4b-instruct` reports no reasoning, so for it the panel shows the reply being written and says so. A reasoning model will show its reasoning.
  - **Who sees what:**
    - Professionals see their own departments only (plus job-level lines).
    - Generated source code, inside prompts or replies, is shown only to people allowed to see code (developers, QA, administrators). Others see a note in its place, and sandbox output lines (which can quote code) are withheld from them too.
    - Writing to the log never breaks the work.
- **Context gap fixed:**
  - Each lifecycle step now lists the earlier work it needs (`reads`, validated by the compiler to be upstream). For example, Code Generation reads requirements, user stories, functional design, contracts, domain design, refined mockups, NFRs and units first.
  - The nearest earlier work fills any space left, up to 8 items, inside a shared budget (`AIDLC_CONTEXT_BUDGET_CHARS`, default 8,000) split fairly so no single deliverable crowds out the rest.
  - Every cut is recorded and shown in the panel ("2,000 of 5,400 chars").
  - Running projects keep the workflow version they started with; new projects get the new `reads`.

## 2026-11-20 — Phase 5: Workflow engine

- **No lock held during work.** A stage run is now a series of short locked steps around lock-free work:
  1. Claim: READY → RUNNING, committed, recording the job that owns the run.
  2. The AI or deterministic work, with no lock held.
  3. RUNNING → AI_COMPLETED → VALIDATING, committed.
  4. Sandbox build and tests, sensors, then the independent AI review (deterministic checks still come first), with no lock held.
  5. The gate transition, under a lock that confirms the run still owns the stage.

  Before, a stage held the whole execution's row lock for its entire AI run, so approvals and other stages waited for minutes. Now RUNNING and VALIDATING are real, visible states. A run that finds the stage changed underneath it (for example, cancelled by a person) discards its result (`Superseded`).
- **Recovery.**
  - A run whose worker died (its owning job no longer holds a lease) is taken back by the next stage job: RUNNING → READY, or → CHANGES_REQUESTED for an interrupted rework, without using up a rework loop. These are new system-only edges.
  - Interrupted checks resume at VALIDATING without redoing the work: a version already built is not rebuilt, and a version already reviewed is not reviewed again.
  - The sweep also catches RUNNING/VALIDATING stages with no live job.
- **Parallel branches and joins.**
  - Workflows may be `execution: "parallel"`.
  - The planner job (`portal.drive`) queues one `portal.stage` job per stage that is due, so independent branches run on different workers at the same time.
  - A join becomes READY only when all its branches are done. Readiness is decided under the execution's row lock with a fresh read, so two branches finishing together cannot both miss it.
  - Sequential workflows (the default lifecycle) still run one stage at a time.
- **Dependency table.** `stage_dependencies` holds each execution's graph as rows; existing executions were backfilled by migration `0019_engine_phase5`. Readiness reads it.
- **Conditional stages** (`app/workflows/conditions.py`).
  - Structured JSON only (`all`, `any`, `not`, and `fact` or `artifact` tests with `equals`, `in` or `present`), never model text or code. Facts are the project type, the scope and the confirmed brief, fixed when delivery starts; artifact tests read fields of earlier approved work.
  - The compiler refuses unknown facts, non-upstream artifacts, malformed operators, more than 5 levels or 30 parts, and conditions on `mandatory` or sandbox-built stages.
  - A false condition makes the stage SKIPPED (which satisfies dependents), with the reason recorded.
- **New state AWAITING_USER_INPUT** (questions to the owner).
  - The professional who may approve a step can ask the owner a question. The step waits, and nothing can be approved meanwhile.
  - The owner answers from "Waiting for you". The answer becomes a change request, the AI reworks the step with it, and the professional then decides.
  - Questions can be withdrawn. The new edges are human-only.
- **Escalations.**
  - The step's department, a project manager or an administrator can escalate a step. While open, the step is neither run nor approved (`409 escalated`).
  - Managers, administrators and the department are notified.
  - Resolving lets held-back work continue.
  - Owners use tickets instead.
- **New hook events:** `stage.escalated`, `stage.escalation_resolved`, `stage.recovered`, `stage.skipped`, `stage.awaiting_user_input`.
- **UI:**
  - The owner answers questions inline.
  - Professionals can ask the owner, escalate and resolve from a deliverable, and see a paused or waiting banner.
  - The new state is labelled "Waiting for Owner".
- **Not done:**
  - AWAITING_HUMAN_REVIEW was not renamed to AWAITING_APPROVAL; same meaning, and renaming would churn every screen.
  - UNDER_REVIEW was not added: the AI review runs inside the validation step, so there is no separate waiting state to show.
  - The default lifecycle is still sequential.

## 2026-11-20 — Phase 6: Orchestration

- **Tool calling with permissions** (`app/agents/tool_runtime.py`).
  - Four READ tools now run:
    - `read_project`: the brief and project details;
    - `list_approved_work`;
    - `read_artifact`: a whole earlier deliverable or one field;
    - `search_approved_work`: matching passages.
  - They see only human-approved work from stages upstream of the current one, in the same execution: never drafts, later stages or other projects.
  - Each call is checked against the grants on the agent's version, its arguments validated, its result bounded (3,000 characters) and returned to the model as data.
  - Each run may use tools for at most 4 rounds and 8 calls, and must then answer.
  - Every call is recorded (`tool_executions`: tool, permission class, arguments, status, result size and SHA-256) and shown live in the AI activity panel.
  - WRITE, EXECUTE, ADMINISTRATIVE and EXTERNAL_SIDE_EFFECT tools stay ungrantable.
  - The OpenAI-compatible adapter (including Ollama) sends tool definitions and reads tool calls, streaming or not.
- **The lifecycle leads hold the read tools.** New teams get them; existing teams get a new agent version with them at the next provisioning. Running projects keep the versions they started with.
- **Execution records** on every agent run:
  - department and task (lead, reviewer, specialist, answer or triage);
  - SHA-256 of the exact prompt;
  - the artifact versions it was given;
  - its tool grants;
  - the artifact version it produced;
  - the correlation ID.
- **Routing policies** (`routing_policies`, `GET/PUT /api/v1/orgs/{org}/routing-policies`, administrators only, audited).
  - Choose the model route per task, and optionally per department. The most specific rule wins; without a rule an agent uses its own route.
  - A reviewer rule can require a different provider from the one that wrote the work. If none is available, the review stops with `no_independent_provider` instead of reviewing its own provider's work.
  - Routing also applies to owner answers and ticket triage.
- **Specialist registry.**
  - A third agent kind, `specialist`. A stage can list up to 3; the compiler checks them.
  - Before the lead works, each specialist gives an advisory contribution in its own recorded run, and the lead receives the notes as advice.
  - The orchestrator routes; agents never call each other (RD-9).
  - `GET /api/v1/orgs/{org}/agent-registry` lists every department's leads, reviewers and specialists with version, route, tools and outputs.
- **Studio:** a new "Agents and routing" tab with the registry by department and an editor for routing rules.
- **Live (local `qwen3-vl:4b-instruct`).** On its own, the Intent Capture lead called `read_project`, then `search_approved_work`, then answered. Its runs record department, task, digest, grants, the produced version and the request ID, and the reviewer's input is exactly that version.
- Migration `0020_orchestration`.

## 2026-11-23 — AI spending controls and provider failover (RD-15, RD-16)

- **Prices** (`app/providers/costs.py`, `model_prices`).
  - Claude defaults from Anthropic's list prices (Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50, Fable 5.2 $8/$40 per million input/output tokens). Cache reads cost 0.1× input and cache writes 1.25×.
  - Administrators can override any price and must enter prices for other paid providers.
  - A model with no price records no cost and is counted separately ("runs with no price"); a cost is never guessed. The mock provider costs nothing.
  - Every run's cost includes cache reads and writes (`token_usage.cache_read_tokens/cache_write_tokens`).
- **Budgets** (`spend_budgets`): one per month for the organization, plus optional ones per project.
  - Checked on the server before every AI call (`service._affordable`).
  - Administrators get a notification once a month when spending passes the warning percentage, and again when it reaches the limit.
  - At the limit, either *pause*: the step fails with `budget_exhausted` and no paid call is made. Or *free only*: work continues only on providers that cost nothing (a zero price, or a local OpenAI-compatible model with no price).
- **Provider pauses** (`ai_providers.paused_until/paused_reason`), saved in their own transaction so they hold even when the run fails.
  - Out of credit or at a spend cap (402, Anthropic `billing_error`/"credit balance", 429 `enforced_spend_limit_reached`, OpenAI `insufficient_quota`): skipped until the 1st of next month, never retried.
  - Key refused: skipped until the key is replaced (rotating the key clears the pause).
  - Rate limited, down or slow: skipped for 60 or 30 seconds, or the provider's `retry-after` (up to an hour).
  - Routes go straight to their next provider. Administrators can resume a provider.
- **Route strategy** (`model_routes.strategy`): *ordered* (primary, then fallbacks) or *cheapest* (the cheapest priced candidate first; unpriced ones last).
- **Claude adapter**, rebuilt on the documented Messages API:
  - instructions sent as a cached system block, plus top-level automatic caching of the growing tool conversation;
  - adaptive thinking with summarized reasoning on 5.x models, which feeds the live activity panel (no temperature or thinking budget, which these models reject); output room of at least 16,000 tokens;
  - tools converted to `input_schema`, and tool turns replayed with Claude's own blocks (thinking signatures kept);
  - server-sent event streaming of text, reasoning and tool arguments;
  - refusals become `content_filtered`.
- **APIs** (organization administrators only, audited):
  - `GET /api/v1/orgs/{org}/spend`;
  - `PUT/DELETE …/model-prices` and `…/spend-budgets`;
  - `POST …/providers/{id}/resume`;
  - `PATCH …/model-routes/{id}` (strategy).
  - Oversight carries a spend summary for administrators only.
- **Studio:** a new "Spend and budgets" tab with this month's spend by model (including tokens served from cache), budgets, provider pauses with Resume, route strategy, and the price list. **Oversight:** a spend tile and a paused-provider notice.
- Migration `0021_spend_controls`.
- **Not done:** Anthropic's Batches API (50% cheaper but asynchronous, up to 24 h) is not used, because stages wait at human gates and need answers in minutes. No live call to a paid provider has been made: that needs your key.

## 2026-11-23 — Step 7.0: work records and the workspace shell (RD-17, RD-18)

- **Work records** (`app/work/`, migration `0022_work_records`):
  - `work_items`, `work_item_versions` (append-only, blocked by a database trigger), `work_item_links`, `work_comments`, `work_packages`, `handoffs`.
  - Kinds are defined in code with field checks (`app/work/kinds.py`). The BA kinds exist today: requirement, user story, stakeholder, assumption, risk, discovery question, document, process flow.
  - Keys like `REQ-001` are unique per project.
  - Every edit is a new version with author and reason. Edits use optimistic locking (`expected_version`, 409 on conflict).
  - Versions can be compared field by field. Records are archived and restored, never deleted.
  - Provenance on every version: confirmed, assumption, AI suggestion or open question. Only the engine's `propose()` creates AI suggestions; it records the agent and its sources. HTTP callers cannot create AI suggestions.
  - Typed links between records; traceability is computed from them.
  - Comments are tied to an exact version, optionally anchored to a field.
- **Packages:**
  - Submitting freezes the exact record versions (with a SHA-256 fingerprint). AI suggestions and open questions must be confirmed first.
  - Only the department's assigned professionals submit and decide (approve, or request changes with a reason). There is no AI path to either.
  - A record edited after submission is not approved by the decision.
  - Other departments read only approved packages, at the approved versions.
- **Handoffs:** only for approved packages. They record sender, recipient, package, exact versions, note, time and reply. The receiver acknowledges or asks for clarification, and both sides are notified. Handoffs never change workflow state.
- **Access** (server-side): own department, project managers and administrators read; only the department's assigned professionals change. Owners and plain members have no access here.
- **API** under `/api/v1/projects/{id}/work`: kinds, team, items (search, filter, sort), versions, compare, archive, links, comments, traceability, packages, decisions, handoffs.
- **Frontend:**
  - *Professional team* page (`/projects/:id/team`): six cards with people, AI lead, current lifecycle step, approvals waiting, blockers, records to confirm, packages and handoffs. All figures come from records.
  - *Department workspace* (`/projects/:id/work/ba|architect|design|dev|qa|devops`): each department's own module navigation from the brief, a work area and a collapsible context panel.
    - Built today: BA records (requirements, discovery questions, documents, stories, process flows, stakeholders, risks and assumptions), Reviews & Approvals (packages), Handoffs, Traceability and Conversations. Shared record screens offer search, filters, sorting, create, edit, confirm, archive, history, compare, links and comments.
    - Modules not built yet say which step brings them; nothing is simulated.
    - The AI assistant panel says it arrives in 7.1.
    - Structured fields (document sections, process diagrams) are edited as JSON until their own editors arrive in 7.1.
  - The sidebar's department links open the workspaces for the internal team; owners keep their deliverables view.
- **Not yet:** lifecycle approvals still happen in the project's step reviews; they move into the workspace in 7.1, together with the BA lifecycle stages proposing records.

## 2026-11-23 — Step 7.1a: lifecycle steps work through records and packages (RD-19)

- **Steps propose records.** A step spec can carry `records`, a map from an output key to a record kind; the compiler checks the kind, the department, that the key is a required output, and that the step is human-gated and builds no code. When the AI finishes, each usable entry of that list becomes an AI suggestion linked to the step, sourced to the step's artifact version. Unusable entries are skipped and counted in the activity log.
- **Rework keeps people's work.** When a step is reworked, its suggestions nobody confirmed are archived and replaced by the new run's. Records a person confirmed or edited stay.
- **The step is approved through its package.**
  - Submitting a package for a step requires every live record of that step. It assembles a system-authored artifact version of the step from the exact record versions, and runs the step's sensors on it.
  - The decision goes through the normal approval gate (slots, sensors, hooks, audit, transition), so approving the package *is* approving the step.
  - The old direct approval of a record step's AI version is refused (`package_required`).
  - After a step decision, the workflow is queued to continue: the next step, or the rework.
- **RD-19, second person for own edits.** Each package entry records who last changed the record's content. Confirming a suggestion or changing only its provenance does not count as an edit.
  - A package with the submitter's own edits cannot be approved by the submitter (`separation_of_duties`).
  - If the department has no other assigned professional, administrators are notified to assign one.
  - The workspace shows both the step and this rule on each package.
- Migration `0023_stage_records`.
- **Not yet:** the BA lifecycle template that uses this (7.1b), and the step review screens inside the workspace (7.1c). No lifecycle step in the default template has `records` yet, so running projects behave as before.

## 2026-11-23 — Step 7.1b: the Business Analyst department lifecycle

- **Template:** a new scope, *Preview: the Business Analyst department lifecycle only*, chosen at intake like any other kind of work. It never becomes the default until all six departments exist (RD-14). The existing eleven templates are unchanged. Steps, in order, each reading the department's earlier work:

  | # | Step | Kind | Becomes records |
  |---|---|---|---|
  | B.1 | Intake Review | AI | open questions, assumptions |
  | B.2 | Discovery | AI | stakeholders |
  | B.3 | Requirements Analysis | AI | requirements, assumptions |
  | B.4 | User Story Development | AI | user stories |
  | B.5 | Scope Definition | AI | risks |
  | B.6 | Requirements Review | AI, independent review | review findings with severity |
  | B.7 | Human Professional Review | the department's approved work gathered for one decision | — |
  | B.8 | User Review and Approval | the owner's input, then the professional's final approval | — |

- **AI steps** are told the exact shape of each list (the kind's fields and allowed values). The AI's values are normalized before checking: `Functional` becomes `functional`, `MUST` becomes `must`, and lines become lists. B.1 to B.6 are approved through their packages (7.1a). Requirements Review advises and never approves.
- **Human Professional Review** shows the whole package. It is approved like any step, or the professional sends one named earlier AI step back with a note:
  - that step is reworked with the note;
  - the later steps wait for re-approval;
  - the review waits until they are approved, then gathers the package afresh.
- **User Review and Approval:** the professional sends the work to the owner with the existing ask-the-owner action, and the owner gives input or says there is none. The input goes back to the professional (not to an AI rework), who gives the final approval. That approval is refused until the owner has answered in the current round. The owner can never approve (RD-2). The invariant that only a person moves a step to the owner is kept.
- **Engine:**
  - a new transition: a review can send an approved step back (a person's action);
  - reworks wait until the steps they build on are approved again;
  - internal review steps appear in Deliverables for the professional team but not for the owner.
  - No migration was needed.
- **Not yet (7.1c):** submitting a step's package and sending a step back are API-only; asking the owner already has its button in the step review. Their buttons in the workspace come next, together with the document and process-flow editors, Scope & Priorities, Change Requests and the AI assistant.

## 2026-11-23 — Step 7.1c: the workspace works the department lifecycle

- **Lifecycle steps** (new module in every department workspace, from `GET /work/{department}/steps`): each step of the department with its status, records, change requests, what it waits for, and the actions the professional may take:
  - *record steps:* see the AI's suggestions, confirm them as written (recorded as the professional's decision) or work on them in their module, then submit the step package. Its decision is the step's approval (Reviews & Approvals).
  - *Human Professional Review:* read the gathered package, approve it, or send one earlier AI step back with a note.
  - *User Review and Approval:* ask the owner for input, read their answer, then give the final approval. The button stays disabled until the owner has answered, and the server refuses it too.
  - The list refreshes every 3 seconds while the AI is working on a step.
- **The department's AI assistant** (context panel; `POST/GET /work/{department}/assistant`, job `work.assistant`, table `assistant_exchanges`, migration `0024_assistant`):
  - The professional asks, optionally about the open record. The department's lead agent answers through its route, so budgets, failover and the activity log apply. It has READ tools and the department's record list, and may propose new records.
  - Proposals are only shown. A person adds one, and it enters as an AI suggestion sourced to the exchange, to be confirmed before it can be submitted. The assistant never edits, submits or approves.
  - Unusable proposals (wrong department, missing fields) are dropped and counted.
- **Editors:**
  - *Documents:* a section outline with headings and text, add, remove and reorder sections, and export to Markdown.
  - *Process flows:* a diagram editor (React Flow) with start, step, decision and end shapes, labelled arrows, drag, remove, and a text reading of the diagram for screen readers. The editable definition (nodes with positions, edges) is saved as the record's new version, never a picture.
- **Scope & Priorities:** requirements and user stories on a MoSCoW board. Changing a priority saves a new version with the reason.
- **Change Requests:** every change request on the department's steps (the professional's, the owner's answers, send-backs), with its status.
- **Offline mock model:** for record steps it now returns one example item per list, built from the field description the step gives. Demos and browser tests can then exercise the records. Every value says "offline mock".

## 2026-11-23 — Step 7.1d: the BA department on a real model (Phase 7 BA exit check)

- **Exit check passed:** a project went through all 8 BA steps on the local model (`qwen3-vl:4b-instruct` through Ollama), with every decision made in the workspace by the test's analyst. The analyst confirmed suggestions, submitted and approved six step packages and approved the department review. They then asked the owner, who answered, and gave the final approval. The workflow completed.
- **What the first live run exposed, and the fixes:**
  - The model returned valid JSON with empty lists (`"requirements": []`). The platform accepted it, so a Requirements Analysis with zero requirements could be approved.
  - Steps now name the lists that may not be empty: requirements, user stories and stakeholders (`records_min`, checked by the compiler). A reply without enough usable items gets the standard repair request saying exactly what is needed. If the model still does not comply, the step stops; it is never approved empty.
  - The same model still returned empty lists when told only the field names. Every record list's instructions, and the repair request, now carry one example entry with placeholders. With it, the model wrote real requirements. Entries that copy the placeholders instead of writing content are never turned into records.
- Lists that may honestly be empty (open questions, assumptions, risks, review findings) stay optional. In the passing run Intake Review and Requirements Review produced none.

## 2026-11-23 — Step 7.2a: Solution Architect and UI/UX Designer departments

- **Record kinds** (29 in all now, each with its own key prefix and field checks):
  - *Architect:* architecture drivers, components, architecture diagrams, data entities (attributes with keys and references), API endpoints (method, path, request and response shapes, auth, errors, rate limit), architecture decisions (ADRs), security controls, proposed infrastructure resources, technical risks, architecture documents, review findings.
  - *Designer:* personas, research notes, site map entries, user journeys, screens (purpose, sections, states, responsive notes, and a layout for the canvas in 7.2c), design tokens, UI components, prototype interactions, review findings.
- **Lifecycles:**
  - *Architect (10 steps):* Requirements Analysis, System Decomposition, Technology Selection, Data Architecture, API and Integration, Security and Infrastructure, Architecture Documentation, Independent Review, Human Review, User Review.
  - *Designer (9):* Design Discovery, Information Architecture, User Journey Mapping, Wireframes, Visual Design, Prototype and UI Specs, Independent Review, Human Review, User Design Review and Approval. The listed "User Design Review" and "Design Approval" are one owner-input step, as for the BA.
  - Every AI step names the lists that may not be empty. The Visual Design brief keeps the platform's colours (RD-11).
- **New preview scope** *"the department lifecycle so far"* (27 steps, parallel execution):
  - the BA department first;
  - the Architect and Designer then both start from the BA's approved User Review, run side by side, and each read the BA's approved requirements, stories and scope (RD-13);
  - the BA-only preview is unchanged.
- **Workspaces:** 19 Architect and Designer modules now open their record screens (search, edit, versions, links, comments, packages). Architecture diagrams use the diagram editor and documents use the section editor; entity attributes and API shapes are edited as JSON until their own editors arrive (7.2b). The design canvas, design versions and Figma stay labelled for 7.2c and 7.2d.
- **AI instructions** now give example shapes for structured fields (entity attributes, document sections, request and response shapes).
- **Fix:** allowed values are matched case-insensitively, so `post` becomes `POST` as well as `Functional` becoming `functional`.

## 2026-11-23 — BRD and SRS drafts for the BA department

- **Why:** the BA workspace had a "BRD / SRS Documents" module, but the BA lifecycle never produced a BRD or SRS. It turned the AI's work into separate requirements, stories, stakeholders and risks, and nothing assembled them into documents.
- **What now happens:** when Human Professional Review gathers the department's work, the platform assembles both documents from the department's *approved* records. No AI is involved, so the content is exactly what was approved (`app/work/documents.py`).
  - **BRD:** purpose and business problem (the approved intake summary), stakeholders, business requirements, scope (in and out of scope, first release, success measures), assumptions, risks, and open questions with their answers.
  - **SRS:** introduction, functional requirements with priority and acceptance criteria, non-functional requirements, constraints, user stories with acceptance criteria, and traceability (each requirement and the records linked to it).
  - Every line names its record and version (`REQ-003 v2`).
- **Governance:**
  - The drafts' exact versions are part of the review step's content, so the professional's approval of the review covers them.
  - They are a new kind of record version, a *platform draft* (`system_draft`, author "Platform"). A person confirms or edits one before it can go into a package, as for AI suggestions, and nobody can create a platform draft through the API.
- **After a send-back** the drafts are re-assembled from the newly approved records. A draft the professional has edited is never overwritten: it is kept, the activity log says so, and the review lists it as "your edited version, kept".
- **In the workspace:** the drafts appear in *BRD / SRS Documents* as documents with sections, Markdown export and a "Confirm draft" button. The Human Professional Review step lists them.
- Migration `0025_system_drafts` (check constraints for the new provenance and the platform author).
- **Your main stack was out of date:** it was still the 20 November build, before any workspace work. It has been rebuilt from the current code, keeping its data. Projects created before the department lifecycle use the older lifecycles, so their BA workspaces start empty. New projects choose the department preview at intake.
