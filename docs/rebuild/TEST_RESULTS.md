# Rebuild Test Results

## 2026-11-19 — Baseline before the rebuild

| Suite | Result | Notes |
|---|---|---|
| Backend (`pytest`, full) | 358 passed, 5 skipped, 0 failed (6 min 16 s) | Skipped tests are live model tests that need `AIDLC_LIVE_OLLAMA_URL` |
| Lint (`ruff`) | Clean at last run (2026-11-18) | Not rerun today |
| Frontend unit and typecheck | 8 passed, typecheck clean at last run (2026-11-18) | Not rerun today |
| Browser (Playwright) | Shared-mode lifecycle spec passed with the real sandbox (2026-11-18); the other-specs run was interrupted | Docker Desktop was not running on 2026-11-19, so browser tests were not rerun |
| Sandbox attack probe | All attempts blocked; real Python and JavaScript projects built and tested (2026-11-18) | `tests/security/sandbox_probe.py` |
| Live model | 6-stage lifecycle passed on `qwen3-vl:4b-instruct` (2026-11-18) | 33-stage lifecycle never run live |

Fixes needed to get a clean run today:

- An embedded test database left running by the interrupted session made 216 tests error at start-up. Stopping it resolved them (known issue RB-13).
- `test_every_sensor_named_in_the_brief_exists` expected 17 sensors; it now allows the `code_builds` sandbox sensor added on 2026-11-18.

## 2026-11-19 — Design system (RD-11)

| Suite | Result | Notes |
|---|---|---|
| Frontend unit and typecheck | 10 passed, typecheck clean, production build clean | New tests for status and identity markers |
| Browser, one-organization-per-account mode | 20 passed | Isolated Compose stack with the offline test connection |
| Browser, shared-organization mode | 1 passed (full lifecycle spec with the real sandbox) | Same isolated stack, recreated empty |
| Visual check | Desktop and 390px phone screenshots reviewed | Sidebar folds behind a Menu button on phones |

Fixes made along the way: the sidebar's project switcher was renamed "Switch project" because its label clashed with the invite form's "Project" field; the browser warm-up now waits up to 120 s for a freshly built dev server.

## 2026-11-19 — Fluid layout and motion

Frontend 10 unit tests and typecheck pass; browser tests 20 passed (one-organization mode, including a wide, collapsed and 1024px screenshot run) and 1 passed (shared mode). Loading placeholders are marked busy rather than as status messages, so they never compete with real notices.

### Team-wide chat follow-up (2026-11-19)

- Backend `tests/test_collab.py`: 11 passed (new: team chat is team-wide and refused to owners; project discussions stay in department workspaces; owner who administers gets the owner view).
- Browser: personal 19 passed; shared `collab.spec.ts` 1 passed and `lifecycle.spec.ts` 1 passed, each on its own fresh stack.
- Main stack rebuilt at `0015_team_chat`; demo owner gets 403 on team chat and sees only her 2 projects; demo analyst sees General + Business Analyst channels.

### Administrators, project managers and direct messages (2026-11-19)

- Backend full suite: 370 passed, 5 skipped. `tests/test_collab.py` 12 passed (new: overseers see every project and only managers chat; direct messages reach only the two people and follow the who-may-message-whom rules).
- Frontend: typecheck, lint, build clean; 13 unit tests (new `chatTargets.test.ts` for @name, @everyone, mentions and suggestions).
- Browser: personal 19 passed; shared `collab.spec.ts` (now covers @name/@everyone, owner→project manager, oversight) and `lifecycle.spec.ts` each passed on a fresh stack.
- The browser run found two real bugs, fixed: a message could be sent before the people list loaded, so `@Name` went to everyone; and text typed while a message was sending was wiped.

## 2026-11-20 — Phase 4: Foundation

- **Backend full suite:** 408 tests ran, with 400 passed, 5 skipped (live model tests) and 3 failed.
  - All three failures were wrong expectations in the new tests, not code faults. The first AI stage starts after deterministic setup stages, and personal sign-up mode gives every account its own oversight page.
  - After correcting them, the three new files were rerun: 33 of 33 passed.
- **New tests:**
  - `test_jobs.py` (14): de-duplication, `SKIP LOCKED`, lease expiry and re-claim, ignoring a late finisher, failing a job whose last attempt died, backoff then `failed`, unknown kinds, correlation ID carried into the job, heartbeat ownership, a long job keeping its lease, delivery only queueing work, a worker killed mid-stage (simulated) leaving nothing half done and finishing on attempt 2 with exactly one version, the sweep recovering a lost job once and leaving recent work alone, and inline jobs refused in production.
  - `test_permissions.py` (13): who may read a project, approve, steer delivery, see oversight, change roles and join team chat, for the owner, administrator, project manager, assigned professional, another professional, a plain member and an outsider. No job or storage API exists to reach.
  - `test_storage.py` (6):
    - signing matches the published AWS example;
    - an in-memory S3 checks the signature and payload hash;
    - keys are scoped and unsafe names refused;
    - changed bytes are refused on read;
    - `/readyz` reports storage;
    - code archives are written once and then served from storage.
- **Live (Compose, real local model `qwen3-vl:4b-instruct`, worker lease 30 s for the second check):**
  - `docker compose restart api` during a running stage: the job stayed on attempt 1 and finished in 2 min 52 s; the stage reached the human gate.
  - `docker kill` (SIGKILL) on the worker 2 s into the first AI stage: the job stayed `running`, the stage stayed `READY` with 0 versions. A new worker re-claimed the job after the lease (attempt 2), the stage reached the human gate with exactly 1 version and 1 committed RUNNING transition.
  - The request ID sent with the confirm (`restart-proof-*`) appeared on the job and in every worker log line for it.
  - The SeaweedFS store refused anonymous and wrong-key requests (403) and served the platform client's put, get, head and delete.
- **Browser (Playwright, stack now with worker and object store):** personal 19 passed; shared `lifecycle.spec.ts` and `collab.spec.ts` each passed on a fresh stack.
- **Correction to earlier entries:** "frontend lint clean" meant the TypeScript check only. The frontend has no linter configured.

## 2026-11-20 — Live AI activity panel and the context fix

- **Backend full suite:** 420 tests: 415 passed, 5 skipped (live model tests), 0 failed.
- **`tests/test_activity.py` (12):**
  - The story of a stage in order.
  - Entries readable while the stage's own transaction is still open.
  - Owners refused, professionals limited to their departments.
  - Generated code shown only to people allowed to see code.
  - A model outage recorded plainly; a broken log never breaks the work.
  - The adapter streams and separates reasoning (`reasoning` field and split `<think>` tags).
  - A model call visible half-written mid-stream, with its exact prompt.
  - Prompts that may not fit the window flagged.
  - Code Generation reads the approved work it needs.
  - The budget shared and every cut recorded.
  - `reads` refused unless upstream.
- **Frontend:** typecheck and build clean; 17 unit tests (new: the activity menu lists steps and file names, treats AI text as text, closes on Escape, shows a running call live and folds it when done, explains withheld code).
- **Browser:** personal 17 passed and 2 failed at browser launch; `auth.spec.ts` then passed 5 of 5 on its own. Shared `lifecycle.spec.ts` and `collab.spec.ts` each passed on a fresh stack. The failures came from two test runs using one Compose test project at the same time (one reset the other's stack), not from the code: runs must not overlap.
- **Live (local `qwen3-vl:4b-instruct`, Ollama 0.40.16, context window 4,096):**
  - A model call sampled once a second went `waiting` → `streaming` with the reply growing 1 → 27 → 95 → … → 360 characters → `done` at 15.7 s.
  - In the browser the menu showed the live call ("Waiting for the model…", cursor, prompt block) as the project manager.
  - The model reports no separate reasoning.

## 2026-11-23 — AI spending controls and provider failover

- **Backend full suite:** 495 tests: 489 passed, 5 skipped (live model tests), 1 failed. The failure was the migration-drift check, caused by a new migration file appearing while the run was in progress; it passed when rerun on its own.
- **`tests/test_spend.py` (16):**
  - Claude requests cache the instructions and use adaptive thinking with summaries on 5.x models; older models keep temperature.
  - Tool calls are replayed in Claude's own blocks, thinking signatures included.
  - Streaming carries reasoning, text and tool arguments.
  - Refusals become content-filtered.
  - Out of credit and spend caps (402, `billing_error`, `enforced_spend_limit_reached`, `insufficient_quota`) are told apart from rate limits.
  - Costs are computed from the published price, cache included.
  - An out-of-credit provider is paused until next month and skipped, then resumed by an administrator.
  - A rate limit means a short cooldown, and a cooldown does not block a route that has no other provider.
  - A pause budget stops paid calls and notifies the administrators once a month; a free-only budget continues on the local model.
  - Cheapest-first ordering.
  - Price overrides, and one organization budget.
  - Members and strangers refused.
- **Regression found and fixed:** a 30-second cooldown made an immediate retry, or the reviewer call, on a route's only provider fail as "paused". Cooldowns now apply only when another provider is available.
- **Frontend:** typecheck and build clean; 17 unit tests passed.
- **Live:** no call to a paid provider was made (needs your key; RB-25). The live end-to-end run on the local model went through Intent Capture, Reverse Engineering and Requirements Analysis with approvals. At Code Generation the model's code built but its own unit tests failed; the sensors blocked the step and it went back for rework. The rework outlasted the test's 20-minute wait, so the Phase 6 live exit check has not passed yet.

## 2026-11-23 — Step 7.0: work records and the workspace shell

- **`tests/test_work.py` (9), all passed:**
  - Create and edit with full history.
  - Optimistic locking (409 on a stale version).
  - Field-by-field compare, search and archive.
  - The database refuses to change a stored version.
  - Bodies are checked against their kind.
  - Other departments, owners and members cannot change work, and cannot read drafts.
  - AI suggestions must be confirmed by a person before submission.
  - Packages freeze exact versions; only the department decides; an edit made after submission is not approved.
  - Other departments see only approved versions.
  - Handoffs only for approved packages; only the receiver replies; no workflow transition is created.
  - Links, comments anchored to a field, and traceability.
  - Team overview counts come from records.
- **Migration 0022:** no drift; downgrade and re-upgrade succeed.
- **Frontend:** typecheck and build clean; 17 unit tests passed.
- **Browser (isolated Compose test stack, mock model):**
  - Shared `collab.spec.ts` passed. It now also covers: the analyst opens the BA workspace from the sidebar, creates REQ-001, edits it to version 2, compares versions, sees six department cards on the Professional team page; the architect sees no BA drafts.
  - Shared `lifecycle.spec.ts` passed. Personal mode: 19 passed.
  - Two earlier attempts failed for test-setup reasons, not product ones: an email-verification wait under load, and a rerun without a fresh stack. A third failed on an ambiguous locator in the new spec, which was fixed.
- **Backend full suite:** not rerun after step 7.0. The new tests and the drift check ran on their own.

## 2026-11-23 — Step 7.1a

- **`tests/test_stage_records.py` (5), all passed:**
  - AI output becomes suggestions linked to the step; unusable entries are skipped and counted.
  - A record step cannot be approved around its package.
  - Approving the package approves the step on the exact system-assembled version; the approval decision and the package point at the same version.
  - Own edits need a second professional, and administrators are notified when there is none.
  - Requested changes rework the step: confirmed records are kept and new suggestions are added.
- **Bug found by these tests and fixed:** a package decision on a step did not queue the workflow, so neither the next step nor the rework would start.
- **`tests/test_work.py` updated for RD-19:** a second analyst approves, and the author is refused.
- **Migration 0023:** no drift; downgrade and re-upgrade succeed. Frontend typecheck clean.
- **Backend full suite:** 503 tests: 498 passed, 5 skipped (live model tests), 0 failed.

## 2026-11-23 — Step 7.1b

- **`tests/test_ba_lifecycle.py` (2), both passed.** A project runs all 8 BA steps on the fake model:
  - each AI step's records are confirmed and approved through packages, with values normalized;
  - the professional review sends Requirements Analysis back with a note, and the step is reworked;
  - later steps are re-approved and the review is gathered afresh, then approved;
  - the final approval is refused until the owner answers; the professional asks the owner, the owner gives input and cannot approve, and the professional is notified and gives the final approval;
  - the workflow completes;
  - sending back is refused for other departments, for non-review steps and for later steps.
- **Bug found and fixed:** Deliverables hid every step not visible to the owner from the professional team as well, so internal review steps could not be opened.
- **A governance test caught a design mistake, now fixed.** My first owner step had the system move the step to the owner, which breaks the rule that only a person does that. The professional now asks the owner, and the system-asked questions (with their migration) were removed.
- **The lifecycle registry test** now counts the original 33 steps and the 8 department steps separately.

## 2026-11-23 — Step 7.1c

- **`tests/test_assistant.py` (3), all passed:**
  - The assistant answers and unusable proposals are dropped.
  - Nothing is added without a person; an added proposal is an AI suggestion sourced to the exchange; adding it twice is refused; the call is a recorded agent run.
  - Only the department uses its assistant.
  - Before the lifecycle starts, the assistant says so.
- **`tests/test_ba_lifecycle.py`:** a new test of the steps view (kinds, statuses and suggestions; another department and the owner are refused).
- **Migration 0024:** no drift; downgrade and re-upgrade succeed. Frontend typecheck and build clean; 17 unit tests passed.
- **Backend full suite:** 510 tests: 505 passed, 5 skipped (live model tests). One run failed one test whose expectation was wrong (it expected the project owner to see the department steps; owners are correctly refused); corrected and passed.
- **Other browser specs, each on a fresh stack:** shared `collab.spec.ts` and `lifecycle.spec.ts` passed; personal 19 passed.
- **Browser (isolated stack, mock model, shared mode), new `ba-department.spec.ts`, passed:**
  - The owner starts a project on the BA preview.
  - The analyst sees the first step's suggestions, confirms them, submits the step package and approves it in Reviews & Approvals.
  - The next step starts on its own and waits.
  - The assistant answers.
  - The confirmed records appear in their module, and the owner is refused the workspace.
- **Bug found by the spec and fixed:** the steps list never refreshed, so a step the AI was working on looked stuck on "Starting".

## 2026-11-23 — Step 7.1d: live BA department (Phase 7 BA exit check)

- **Live, local `qwen3-vl:4b-instruct` (Ollama), shared mode, `ba-department-live.spec.ts`, every decision through the UI:**
  - **Run 1, passed in 17.9 min, but showed a gap.** All steps were approved, yet Intake Review, Discovery and Requirements Analysis had returned empty lists, so no requirements existed.
  - **Run 2, failed at sign-up.** The first account's email verification took over 2 minutes while the full backend suite ran at the same time. No project was created; this was a load problem, not a product one.
  - **Run 3, stopped correctly.** With the new minimum, Requirements Analysis was asked again twice and still returned `[]`, so it stopped rather than be approved empty.
  - **A direct probe of the model,** after adding an example entry to the instructions, gave 6 usable requirements on each of two tries.
  - **Run 4, passed in 33.1 min. This is the exit check:**
    - 21 model calls, all succeeded;
    - all 8 steps approved, 6 packages approved, the workflow completed, and the owner's input recorded;
    - records: 2 stakeholders, 5 requirements (booking, reminders, reception management, mobile, data security), 5 user stories and 3 risks;
    - no open questions, assumptions or review findings.
  - The spec now fails if Requirements Analysis has no records.
- **Backend:** full suite 511 tests: 506 passed, 5 skipped, before the example change. After it, the 32 tests in the affected files passed (`test_ba_lifecycle.py`, including new tests for empty lists and copied placeholders, `test_stage_records.py`, `test_assistant.py` and `test_portal.py`).

## 2026-11-23 — Step 7.2a

- **`tests/test_departments.py` (2), both passed:**
  - A project runs the BA's 8 steps; both the Architect's and the Designer's first steps then wait at the same time.
  - The two departments are decided step by step, interleaved: 19 steps, with records of 17 kinds confirmed and approved through packages, both owner-input steps answered, and the workflow completed.
  - The Designer reads the BA's work and not the Architect's.
  - Another department cannot see or submit a department's steps.
- **Bug found and fixed:** HTTP methods from the AI were lower-cased and then rejected, because the normalizer only knew lower-case values.
- **The lifecycle registry test** now counts 33 standard steps plus 8 BA, 10 Architect and 9 Designer steps.

## 2026-11-23 — BRD and SRS drafts

- **`tests/test_ba_documents.py` (3), all passed:**
  - Both drafts are assembled from the approved records, and each line names its record and version, with acceptance criteria, stakeholders and risks.
  - Versions are authored by the platform; the exact draft versions are inside the review step's content.
  - A draft must be confirmed before packaging, and a person cannot create a platform draft.
  - After a send-back the BRD is refreshed and the analyst's edited SRS is kept and flagged.
- **Bugs found and fixed:**
  - A version was read back before it was flushed, which left the review step stuck.
  - Two places read the oldest version of a deliverable as if it were the newest (one in the Steps screen).
- **Migration 0025:** no drift; downgrade and re-upgrade succeed. Frontend typecheck, build and 17 unit tests passed.
- **Backend full suite** (7.2a plus the BRD and SRS drafts): 517 tests: 511 passed, 5 skipped, 1 error. The error was in one test's setup: a session timed out while the machine slept overnight. That file passed when rerun (3 of 3).
- **Frontend:** a new unit test for the Lifecycle steps polling (it refreshes while the AI works and shows the step when it is the professional's turn); 18 unit tests passed.
- **Browser (isolated stack, mock model), each on a fresh stack:**
  - `ba-department.spec.ts` is extended: the analyst works all six AI steps through the UI, the Human Professional Review lists the BRD and SRS, and the BRD opens in BRD / SRS Documents with its sections, Markdown export and "Confirm draft". It passed.
  - Shared `collab.spec.ts` and `lifecycle.spec.ts` passed; personal 19 passed.
  - One earlier attempt failed because the operating system suspended networking mid-run (`ERR_NETWORK_IO_SUSPENDED` in the trace); the rerun passed.

## 2026-11-24 — P0: administrator-created accounts

- **`tests/test_accounts.py` (6), all passed:**
  - Nothing works until the temporary password is changed; a wrong, reused or weak password is refused; the session carries on and the temporary password stops working.
  - People are created with a role; the temporary password is shown once and never stored or audited in plain text; a duplicate email is refused.
  - Only administrators create people, and nobody signs up.
  - An expired temporary password is refused.
  - A reset ends sessions and issues a new temporary password, and administrators cannot reset their own.
  - Administrators create projects for a client: a client is required, the project manager and the administrator oversee it, and clients and PMs cannot create projects.
- **Browser (new `accounts.spec.ts`, managed stack, first administrator from the command), passed:** no sign-up; the administrator's forced change; adding a client and an analyst (each password shown once); creating the project for the client; the client's and the analyst's first sign-ins; and a reset.
  - The first two attempts failed: the managed message was placed inside the wrong branch of the sign-up page (fixed), and the spec opened a page before sign-in finished (a test race, fixed).
- **Migration 0026:** no drift; downgrade and re-upgrade succeed. Frontend typecheck clean; 18 unit tests passed.
- **Backend full suite after P0:** 523 tests: 518 passed, 5 skipped (live model tests), 0 failed. No migration drift.
- **The older browser specs (self-service mode) were NOT re-run for P0.** After `accounts.spec.ts` passed, Playwright's Chrome on this machine stopped loading pages. A bare probe showed Chrome launching in 3.5 s and then hanging on `page.goto`, past even its own 30-second timeout, against a stack that served the same page instantly to another browser. Earlier traces showed `ERR_NETWORK_IO_SUSPENDED` (the OS suspending Chrome's networking). The bundled Chromium cannot start here (blocked by Application Control). These specs need re-running once Chrome works again.
- **Test-script incident, found and fixed:** the managed run script held the throwaway test administrator's temporary password in a shell variable named `TEMP`, which on Windows is also the temporary-files location. Node and Playwright therefore created a cache folder named after that password inside `tests/e2e`. The folder was never committed, it held only caches, and the stack it belonged to had already been destroyed with its database. The folder was deleted and the variable renamed. The product itself never writes temporary passwords anywhere.

## 2026-11-24 — P1 and P2

- **`tests/test_pm.py` (2):**
  - The PM is the seventh profile; PM accounts hold it; seven team cards with the PM first.
  - Only an administrator assigns the PM, and only someone holding the PM profile; exactly that person is the project's PM, and another PM can see but not edit.
  - The PM cannot write, edit or approve the BA's records or packages, nor create projects or accounts.
- **`tests/test_meetings.py` (3):**
  - A meeting with an attached document: the filename's path parts are dropped, the stored key is random, downloads are sent as attachments with nosniff, HTML is refused (415), files over 10 MB are refused (413), and uploads are audited.
  - Only the assigned PM writes or attaches; the client sees neither meetings nor files.
  - One intake per project; it is created as a draft and validated only once confirmed, and validation is audited.
- **Existing tests updated for seven profiles:** the team-page cards (7), the project manager's channels (8 including general), the profiles and reviewer agents (7), and the standard lifecycle using six of the seven profiles (the PM has no AI steps there). Oversight keeps listing the six delivery departments (a product choice: the PM has no lifecycle steps to show).
- **Migrations 0027 and 0028.** Frontend typecheck clean; 18 unit tests passed.
- **Backend full suite (P1 and P2):** 528 tests: 523 passed, 5 skipped, 0 failed. No drift through migration 0028; downgrade and re-upgrade succeed.
- **Browser, each on a fresh stack:**
  - The managed `accounts.spec.ts`, now with PM assignment, the PM workspace and a meeting with an attached file, passed in 1.2 minutes.
  - Shared `ba-department.spec.ts` passed. Shared `collab.spec.ts` passed after its card count went from 6 to 7. Shared `lifecycle.spec.ts` passed after a fix. Personal 19 passed after a fix.
- **Regressions the browser specs found and fixed:**
  - The Team page's department checkboxes had lost their full titles ("QA & Security Engineer").
  - In self-service mode the Team page showed both "Add a person" and invitations, making its email field ambiguous. Each mode now shows only its own form.
- **Not re-verified:** after those two UI fixes, three reruns of the managed spec failed for environment reasons. One failed in warm-up, unable to load the sign-in page; two ran out of the 4-minute limit at steps that had passed, with every step far slower than before. A probe showed this machine's Chrome stalling 15 seconds on a request to the API that curl answered in 0.06 seconds. The fixes do not touch the managed path except to show "Add a person" in managed mode, and one of the failed runs got through those steps. The spec still needs a clean rerun.

## 2026-11-24 — P3

- **`tests/test_pm_analysis.py` (4), all passed on the first run:**
  - The analysis is an AI suggestion linked to its meeting with its source version; the meeting is untouched; the model gets the persona's rules and the notes as data, with no tools; the run is recorded at project level.
  - Only the project's PM asks, the client sees nothing, and only meetings can be analysed.
  - A reply in the wrong shape is repaired once, then fails with `bad_response`, and no record is stored.
  - The PM assistant answers with no lifecycle at all.
- **Migration 0029:** no drift; downgrade and re-upgrade succeed. Frontend typecheck clean; 18 unit tests passed.
- **Full backend suite:** 525 passed, 5 skipped, 2 failed. Both failures were expected-count tests that predate the PM persona, a seventh agent with no read tools (one more agent in the catalog; no tools to compare). The tests were updated to count it, and both now pass.
- **Managed browser spec (`accounts.spec.ts`, with "Analyze with AI"):**
  - The first run failed on a test race. `chooseOwnPassword` waited for the sidebar's Notifications link, which the password page also shows, so the test opened the project before the new password was saved and was sent back to the password page.
  - The helper now waits until the password page is gone.
  - The rerun passed (52.5s). This also covers the P1 UI fixes, which had not been re-verified.

## 2026-11-25 — P4

- **`tests/test_brief.py` (4), all passed:**
  - The brief is assembled from the validated intake (refused before that). Its lines cite `INT-001 v2` and `MTG-001 v1`, and it links to its sources.
  - Re-assembling with no changes adds no version; the PM's own edits are kept; nobody can create a brief by hand.
  - Only an approved brief starts delivery, and only the project's PM can start it. The execution records the exact brief version and starts with the brief as its project input; the BA's first AI step receives it. Starting twice, or re-assembling after the start, is refused. The BA's clarification request notifies the PM.
  - RD-19: a brief with the PM's own edits cannot be approved by that PM.
  - The client's form, with managed accounts, is refused as a start (`pm_led`) and is sent to the PM instead, with no execution.
- **Full backend suite:** 532 passed, 5 skipped, 0 failed, 1 error. (This entry first said 603 passed. That number was wrong, and it was corrected on 2026-11-25 by counting the run's own result marks.)
  - The error was in the setup of `test_permissions.py::test_nobody_reads_the_job_queue_or_storage_records_through_the_api[manager]`: right after sign-up, the fixture's first request got 401. The whole file passed when rerun (15 with the Tasks tests). This is recorded as a flake, not hidden.
  - Two earlier runs did not count. One was cut off at about 87% with no summary. In the next, the test database would not start because a Postgres left from that run still held its folder; it was stopped cleanly.
- **Managed browser spec (`accounts.spec.ts`, extended with P4):** passed on the fourth run (1.7 min). It validates the intake, assembles, reads, confirms, submits and approves the brief, then hands it to the BA and sees delivery start. The first three runs found:
  - The record panel covered the records table. The panel now has a Close button.
  - The Approval list did not refresh after submitting, a real bug. It now reloads.
  - A case-sensitive check in the test.
- **Frontend:** typecheck clean; 18 unit tests passed. Lint clean.

## 2026-11-25 — The PM's Tasks page

- **`tests/test_pm_tasks.py` (2), passed:**
  - The to-dos follow the path from intake to handoff.
  - Department work lists the BA's steps with the BA as approver.
  - A clarification request appears as an urgent to-do.
  - The client cannot read the page.
- **The browser demo** on the managed test stack showed the three tabs working. It also found that the new module shared the key `tasks` with the Task Allocation placeholder, so both were highlighted; the new module is now `pm_tasks`.
- Typecheck clean; 18 unit tests passed; lint clean.

## 2026-11-25 — P5

- **`tests/test_client_sign_off.py` (2):**
  - The client approves the BRD baseline only after the BA, on the same version. Slots are filled `s1`, then `s2`; the BA cannot fill the client's slot; the client cannot reject; the client is notified once, and the execution completes.
  - A client's request for changes at sign-off is recorded, and the BA's earlier approval stops counting.
- **`tests/test_client_portal.py` (4):**
  - The client's question goes to the PM's thread; the PM is notified and replies.
  - The client assistant's answer is labelled "Project assistant (AI)" and recorded as a project-level run with no tools. A canary in internal meeting notes never reaches its prompt.
  - A reply that names how the platform works inside is replaced by a holding reply.
  - A change request reaches the PM's to-dos and notifications and starts nothing.
  - Progress is "Discovery", then "Delivery" with 0 of 8 steps done.
- **`tests/test_brief.py`** now also checks that the PM's start turns client approvals on.
- **Expected-count tests** were updated for the client assistant (one more agent, with no tools).
- **Full backend suite:** 539 passed, 5 skipped, 0 failed, 0 errors. Counted from the run's result marks (`-q` printed no summary line).
- **Managed browser spec** (with P5: Progress, a change request, and a question answered by the assistant in the PM thread): passed on the first run (45.6s).
- **Frontend:** typecheck clean; 18 unit tests passed. Lint clean.

## 2026-11-25 — The project start flow (RD-26, RD-27)

- **`tests/test_start_flow.py` (5):**
  - The kickoff checklist follows the kind of work. Changing to the three-department preview needs an Architect and a Designer, so the kickoff is refused with the gaps listed. A kickoff cannot be created through the generic records route, it is recorded once, and every change of the kind of work is audited.
  - The client approves the brief after the PM. The client is notified, the PM cannot decide for the client, a request for changes needs a note, starting is refused until the client approves, the client's note becomes an urgent PM to-do, and the kind of work locks after approval.
  - Changing the kind of work withdraws a brief that was waiting for the client.
  - An administrator starts delivery only with a reason. It is audited as started by an administrator, and the PM is notified. A BA cannot start.
  - The brief needs the kickoff.
- **Updated:** `test_brief` (kickoff, client approval, kind of work from the project), `test_pm_tasks` (kickoff first; the brief waits for the client), `test_client_portal`, `test_accounts` (kind of work required at creation).
- **Found while testing:**
  - A notification kind longer than its 64-character column.
  - A misleading `brief_changed` error when the client had asked for changes. The client's decision is now checked first.
- **Migration 0030:** no drift; downgrade and re-upgrade succeed. Checked on the test stack's database, since the main stack was not running.
- **Full backend suite:** 544 passed, 5 skipped, 0 failed, 0 errors.
- **Managed browser spec:** passed (2.0 min), through kind of work at creation, kickoff, the client approving the brief, the handoff, and the client's P5 steps. The first attempt did not run: a line break inside a string broke the spec file.
- **Frontend:** typecheck clean; 18 unit tests passed. Lint clean.

## 2026-11-25 — Phase 1a: the executor

- **`tests/test_executor.py` (5)**, using a fake Docker client:
  - Each container gets the locked-down settings: no network, read-only root, capabilities, limits, an empty environment, no host mounts, only the throwaway `/job` volume. The container and volume are always removed.
  - An unknown kind is rejected with nothing started.
  - A silent container is an error, and a hung one is killed and `timed_out`; neither keeps a result. This test found a real bug: a timed-out job kept whatever result it had printed. Fixed.
  - Only known kinds are queued.
  - Only engineering professionals and administrators queue executions (the client and the PM are refused), and requests are audited.
- **Migration 0031:** no drift; downgrade and re-upgrade succeed.
- **Real Docker, on the isolated test stack:**
  - The first attempt **timed out and was recorded as `timed_out` with no result**. Docker's attach stream never delivered the end of the input, and the Docker SDK cannot close standard input after one write. The job now arrives as a read-only file on a throwaway volume.
  - The executor's first start also crashed on an unloaded model registry: foreign keys to `organizations` could not resolve. Fixed; it now loads every model and waits out database errors.
  - **The demonstration job succeeded in 1 s:** `Python files compile`, `Tests: 5 passed`. Its tests prove, from inside the container, that the network is unreachable, `/etc` cannot be written, the code runs as uid 2000, and no `AIDLC`, `KEY` or `SECRET` variables exist. The recorded limits are `{"network": "none", "memory": "768m", "cpus": 1.0, "pids": 128, "read_only_root": true, "timeout_seconds": 180}`.
  - Afterwards, 0 job containers remained and no job volume was left (the 4 unattached volumes on the machine date from 20 November and June).
- **Regression subset** (executor, permissions, portal, start flow, jobs, sandbox): 65 passed.

## 2026-11-25 — Phase 1b–1d and Phase 1 as a whole

- **`tests/test_repositories.py` (3)**, with simulated git results; the real git path is below:
  - Only engineers create the repository, once, and the client is refused.
  - A commit to `main` is refused.
  - A change set is approved at its exact commit; the author cannot approve; merging before approval is refused.
  - A new commit makes the approval stale, and reviewing the old commit is refused.
  - The merge passes the approved commit, and the audit trail is in order.
  - Asking for changes needs a note, and the public executions API refuses `git.merge`.
- **`tests/test_tool_registry.py` (3):**
  - The registry mirrors all 13 definitions; a second sync writes nothing; a change without a new version is refused; new versions are kept.
  - Executor heartbeat health.
  - Administrators disable tools (audited, tied to the request's correlation ID), and members cannot.
  - Executor tools are not grantable yet.
  - A disabled tool is refused both for new grants and at run time to an agent version that already holds it.
  - Department authorisation.
- **`tests/test_events.py` (2):**
  - A WebSocket follows an execution live (queued, then started and finished), and REST catches up.
  - The client, another origin and an unauthenticated visitor are refused.
  - Run three times after a fix: the test had assumed started and finished always arrive in one batch, but they are separate commits.
- **Frontend `liveEvents.test.tsx` (2):** REST catch-up, then the socket from the last event seen; a policy refusal stops retries.
- **Migrations 0032, 0033, 0034:** no drift; downgrade and re-upgrade succeed.
- **Real Docker, on the test stack:**
  - **Git:** create, log, commit, change set, real diff, read at a branch. Refused: commit to `main`, approving one's own change set, merging before approval, approving a stale commit. A second engineer approved at `b7da0cc` and merged; `main` is now `b7da0cc`.
  - **Bugs found and fixed on the way:**
    - init did not reuse the folder the executor provides;
    - Docker's archive upload ignores ownership, so git jobs now hand `/repo` to uid 2000 and drop privileges themselves;
    - `/work` was not writable by the git user;
    - a new branch's ref update expected the base commit instead of "must not exist".
  - **Live events in the browser:** with a Software Developer workspace open, a real execution and a commit made through the API appeared in its Live activity panel within about a second, with no reload (six events).
  - The registry shows executor tools healthy from the executor's heartbeat.
- **Full backend suite:** 557 passed, 5 skipped, 0 failed, 0 errors (544 before, plus the 13 new Phase 1 tests).
- **Managed browser spec:**
  - The first run failed on **a regression from Phase 1**: the Live indicator used the `status` role, so pages had two status regions and the spec's status check became ambiguous (seven specs rely on one). The indicator is now a labelled note.
  - The next run timed out at the first sign-in while Vite re-optimised its dependencies after the WebSocket proxy change, a one-time rebuild on a fresh container. The rerun passed (56.6 s).
- **Frontend:** typecheck clean; 20 unit tests passed. Lint clean (backend).
- **Self-service browser specs (open item, not resolved):**
  - On the Phase 1 tree, `ba-department.spec.ts` failed at the sign-up step "Your email is verified" (the page showed "Something went wrong"), and `lifecycle.spec.ts` failed waiting for the Studio link.
  - Run on the commit **before** Phase 1 (67383e4, in a separate worktree), `lifecycle.spec.ts` failed on the **same** email-verification step, while `ba-department.spec.ts` passed.
  - The email-verification step therefore fails intermittently with and without Phase 1. It is recorded as a pre-existing flake to investigate, not as passing.
  - The run's `--grep-invert live` filter also excluded tests whose names merely contain "live" (such as "deliverables"), so only 3 tests ran.

## 2026-11-25 — Phase 2a–2c: the Developer IDE

- **Frontend unit tests:** 23 passed. New: `src/ide/paths.test.ts` (3) covers path validation matching the git job's rule, explorer folder grouping and order, and testing what is on screen (unsaved tabs replace or add to committed files).
- **Browser spec `ide.spec.ts`**, on the managed stack after `accounts.spec.ts`, one worker. **Passed (1.2 min; both specs together 3.0 min).** It drives the real IDE:
  - create the repository;
  - New file `calc.py` and `test_calc.py`, typed in Monaco;
  - Build and test with the unsaved changes: `succeeded`, network none, "Tests: 1 passed";
  - commit two files to a new branch (`feature/opening-hours`, status bar clean);
  - open change set #1 and its diff;
  - "Approve" as the author is refused with "You cannot approve your own change set".
- **Problems found and fixed on the way:**
  - The IDE first sat inside the page frame and was squeezed; it now owns the window and is responsive.
  - There was no way to create a file; there is now New file.
  - `window.prompt` dialogs were replaced with inline inputs.
  - Build and test ignored unsaved edits; it now tests what is on screen.
  - A newly created file did not take focus, so typing went elsewhere; it now does.
  - Monaco 0.57's export map needed new worker import paths.
  - The production build ran out of memory; the build script now raises the heap.
  - **Monaco was loaded on every page**, making the first load slow. The IDE is now lazy-loaded: the main bundle went from about 4.5 MB to 400 KB, and the IDE is a 4.1 MB chunk loaded on demand.
  - **One network error while waiting for a build made the IDE give up** ("queued" forever, although the build succeeded in 2 s). Waiting now survives transient errors, and unexpected errors show their real message.
- **Test infrastructure:**
  - The managed mode ran only `accounts.spec.ts`; it now runs `ide.spec.ts` too, on one worker, in order.
  - The warm-up allows 3 minutes while a fresh Vite pre-compiles Monaco.
  - The spec inserts code lines instead of typing them, because Monaco's auto-closing brackets would double them.
  - One run did not start because the test stack failed to come up (a transient Docker failure); the rerun was clean.
- **Observed and noted, not changed:** each git operation is a fresh container on a single executor, about 1–3 s each and one at a time. A change-set diff (two reads) takes several seconds. Executor throughput (parallel jobs) is a candidate for later.
- **Backend:** no changes in Phase 2a–2c. The last full suite passed 557 tests, and the spend fix's file passes 16.

## 2026-11-26 — Phase 2d: the IDE terminal

- **New backend tests, `tests/test_terminal.py`: 5 passed.** Docker is faked; the real path is proven in the browser spec below.
  - Only engineers open a terminal. It needs a repository and a valid branch, and opening it needs the CSRF token. Opening is audited and published live, and the nonce is never returned.
  - People see only their own sessions.
  - The executor accepts the nonce once, refuses a wrong or empty one, and refuses one older than two minutes.
  - The relay refuses another origin, another engineer, the client, and anyone not signed in. Nothing reaches the executor.
  - A session starts a container with no network, a read-only root, all capabilities dropped and no environment variables. The shell runs as uid 2000 and resize values are clamped.
  - Each submitted line and any unsubmitted text are recorded, and so is the transcript. The container is always removed.
  - A refused connection starts no container.
- **Full backend suite: 562 passed, 5 skipped, 0 failed, 0 errors.** That is the previous 557 plus the 5 new tests, counted from the result marks. The first attempt errored before any test ran: an interrupted earlier run had left the embedded test PostgreSQL unclean, and its recovery took longer than pgserver's start-up timeout (about 37 s, mostly waiting out a Windows file lock on its log). It had recovered on its own by the rerun, which was clean. No code was changed for it.
- **Frontend:** 23 unit tests passed. The production build (type check plus Vite) succeeded.
- **Browser specs, managed stack, rebuilt from scratch: `accounts.spec.ts` and `ide.spec.ts` both passed (5.4 min).** The IDE spec now ends with a real terminal:
  - open it on `feature/opening-hours`;
  - `ls && id -u` shows `calc.py` and `2000`;
  - a Python attempt to connect to 1.1.1.1 fails, so the shell prints the no-network marker;
  - End session shows "session ended".
- **Checked in the test stack's database afterwards:**
  - The session is `ended`, its nonce is cleared and its limits record network `none`.
  - Both typed lines are recorded with timestamps, along with 615 bytes of transcript.
  - `terminal.opened` and `terminal.closed` appear in live events, with one `terminal.opened` audit event.
  - **No terminal container was left behind.**
