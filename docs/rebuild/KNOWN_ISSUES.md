# Rebuild Known Issues

Earlier issues remain in `docs/KNOWN_ISSUES.md`. This list tracks what the rebuild must resolve.

| ID | Issue | Impact | Phase |
|---|---|---|---|
| RB-1 | AI work runs inside the API process | A restart can leave a stage half-done | 4 |
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
