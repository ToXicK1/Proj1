# Rebuild Known Issues

Earlier issues remain in `docs/KNOWN_ISSUES.md`. This list tracks what the rebuild must resolve.

| ID | Issue | Impact | Phase |
|---|---|---|---|
| RB-1 | ~~AI work runs inside the API process~~ **Resolved 2026-11-20 (Phase 4):** lifecycle stages, retries, owner answers and ticket triage run in the worker from the PostgreSQL queue | — | 4 |
| RB-2 | No file uploads or knowledge retrieval | Agents see only the brief and recent deliverables | 11 |
| RB-3 | No collaboration between departments | Departments work in isolation | 9 |
| RB-4 | One flat professional qualification; no project reviewer assignments, backups, escalation or reassignment | Review cannot be managed per project | 8 |
| RB-5 | Review actions limited to approve, request changes and reject | Professionals cannot escalate, add findings or edit artifacts | 8 |
| RB-6 | One generic project page instead of department workspaces | Poor professional experience; design is text-only | 10 |
| RB-7 | Sandbox runs unit tests only; no running application, integration tests, lint or type check | QA evidence is limited | 6 and 13 |
| RB-8 | No real deployment target | Release stages produce plans only | 13, needs a target from you |
| RB-9 | No streaming or tool calling in provider adapters | Long runs show no progress; agents cannot use tools | 6 |
| RB-10 | Parallel and conditional stages refused | Lifecycle cannot branch | 5 |
| RB-11 | Email is outbox-only | People must read links from the database | 14 |
| RB-12 | 33-stage lifecycle never run live | Unknown behaviour on a real model | 7 |
| RB-13 | An interrupted test run can leave the embedded test database running | Next test run times out until it is stopped | Test tooling |
| RB-14 | Shared-mode browser specs each need their own empty stack (the first account becomes administrator) | Specs must run one at a time | Test tooling |
| RB-15 | Ticket triage and owner answers use the local 4B model; quality of AI answers is limited | Many tickets will go to a professional | Cloud provider when available |
| RB-16 | Two short administrator actions still call the model inside the request: re-validating a stage (`/workflow-executions/{id}/stages/{key}/validate`) and drafting a rule change proposal | A slow model holds that request open; nothing is left half-done (each is one transaction) | 6 |
| RB-17 | Enqueueing a job commits just after the triggering change, not in the same transaction (the services commit internally) | If the API dies between the two commits, the work waits until the worker's sweep (every 60 s, after 120 s grace) queues it. Lost owner questions are not swept; the owner can ask again | 5 |
| RB-18 | Object storage is used for code archives only so far; uploads, evidence and large artifacts come with Phase 11 | Most content still lives in PostgreSQL | 11 |
| RB-19 | Job delivery is at least once. Handlers are written to be safe to repeat and this is tested, but a new handler must follow the same rule | A careless new handler could act twice | Review rule |
