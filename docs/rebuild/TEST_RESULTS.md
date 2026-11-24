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
