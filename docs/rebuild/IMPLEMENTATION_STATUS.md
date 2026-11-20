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
