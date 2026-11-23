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
| RB-9 | ~~No streaming or tool calling~~ **Done 2026-11-20** for OpenAI and OpenAI-compatible providers (including Ollama). Anthropic and Gemini still answer in one piece and without tools | Agents on those providers cannot use tools | Later |
| RB-10 | ~~Parallel and conditional stages refused~~ **Resolved 2026-11-20 (Phase 5)**; the default lifecycle itself is still sequential | — | 5 |
| RB-11 | Email is outbox-only | People must read links from the database | 14 |
| RB-12 | 33-stage lifecycle never run live | Unknown behaviour on a real model | 7 |
| RB-13 | An interrupted test run can leave the embedded test database running | Next test run times out until it is stopped | Test tooling |
| RB-14 | Shared-mode browser specs each need their own empty stack (the first account becomes administrator) | Specs must run one at a time | Test tooling |
| RB-15 | Ticket triage and owner answers use the local 4B model; quality of AI answers is limited | Many tickets will go to a professional | Cloud provider when available |
| RB-16 | Two short administrator actions still call the model inside the request: re-validating a stage (`/workflow-executions/{id}/stages/{key}/validate`) and drafting a rule change proposal | A slow model holds that request open; nothing is left half-done (each is one transaction) | 6 |
| RB-17 | Enqueueing a job commits just after the triggering change, not in the same transaction (the services commit internally) | If the API dies between the two commits, the work waits until the worker's sweep (every 60 s, after 120 s grace) queues it. Lost owner questions are not swept; the owner can ask again | 5 |
| RB-18 | Object storage is used for code archives only so far; uploads, evidence and large artifacts come with Phase 11 | Most content still lives in PostgreSQL | 11 |
| RB-19 | Job delivery is at least once. Handlers are written to be safe to repeat and this is tested, but a new handler must follow the same rule | A careless new handler could act twice | Review rule |
| RB-20 | The local Ollama model runs with a 4,096-token context window (prompt and reply together), while the platform allows replies of up to 4,096 tokens. Large prompts make Ollama silently drop the start of the prompt, where the instructions are | Long stages (Code Generation in larger scopes) can lose their instructions or get cut off. The activity panel now warns per call. Fix on the machine running Ollama: raise its context length (for example `OLLAMA_CONTEXT_LENGTH=16384`), then set `AIDLC_MODEL_CONTEXT_TOKENS` and `AIDLC_CONTEXT_BUDGET_CHARS` to match | Your setting |
| RB-21 | The activity panel refreshes by polling (every second while work runs and the panel is open), not by server push | Up to about a second of delay; no updates while the browser tab is hidden | Later |
| RB-22 | The default 33-stage lifecycle still runs sequentially; departments that could work at the same time (for example Market Research beside Feasibility) wait for each other | Slower delivery than the engine now allows | Your decision |
| RB-23 | Agents can only read through tools; WRITE, EXECUTE (sandbox on demand) and EXTERNAL_SIDE_EFFECT tools need their approval policies first | Agents cannot run tests or take actions themselves | 8 and later |
| RB-24 | No specialist agents are provisioned by default: the mechanism and registry exist, and administrators can add them, but the lifecycle still uses one lead per step | Each extra specialist adds a model call, which is slow on a local 4B model | Your decision |
| RB-25 | No live call to Claude, OpenAI or Gemini has been made; the adapters and failover are proven against mocked vendor HTTP only | A vendor change to request or error shapes would show up only in real use | Needs your API key, added in AI Settings (never in chat or code) |
| RB-26 | Budgets are checked before each call using spend already recorded; calls running at the same moment can each pass the check, so a month can end slightly over its limit (by at most the cost of the calls in flight) | Small overshoot possible under parallel work | Later |
| RB-27 | Default Claude prices are Anthropic's published list prices as of 2026-11-03. Negotiated or changed prices must be entered by an administrator | Spend shown can differ from the invoice | Your setting |
