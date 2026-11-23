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
