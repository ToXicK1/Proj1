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
