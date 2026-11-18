# Agent Architecture

Status: Proposed (Milestone 1). Implementation: Milestones 5 and 6.

## 1. Separation of concepts

The brief requires distinct objects. We model them as separate tables and domain types:

| Concept | Meaning | Example |
|---|---|---|
| Profile | Area of responsibility; contains stages | Business Analyst |
| Professional representative | User-facing identity of a profile (name, role, voice) | "Riley, Business Analyst" |
| Stage | Specific workflow task inside a profile | Requirement Analysis |
| Agent configuration | Individual execution capability with instructions, model, tools, skills | Requirement Analyst Agent v3 |
| Reviewer | An agent configuration used in an independent verification role | Requirement Critic Agent v2 |
| Approval | Human authorization decision | Owner approves design v4 |

A profile contains many agents. A stage invokes one lead agent and optionally support agents and one reviewer. An agent may be reused across stages if its configuration allows. A reviewer must differ from the generating agent configuration.

## 2. Agent configuration

Required fields (from the brief, Part 10):

- `id`, `name`, `description`, `purpose`
- `system_instructions` (versioned text; never shown to end users)
- `compatible_profiles`, `compatible_stages`
- `provider_config_id` and `model_route` (primary, fallback, routing policy)
- `skills[]` (versioned references)
- `tools[]` with per-tool permission grants (classes READ, WRITE, EXECUTE, ADMINISTRATIVE, EXTERNAL_SIDE_EFFECT)
- `input_schema`, `output_schema` (JSON Schema)
- `context_policy` (what it may receive: artifact types, versions, rule layers, conversation scope)
- `retry_policy`, `timeout_policy`
- `kind`: `lead`, `support`, `reviewer`
- `version`, `status`, change history

Least privilege is enforced at dispatch: an agent run receives only the tools and context listed in its configuration, and the run's `context_manifest` is stored.

## 3. Execution topologies

| Topology | Use | Rule |
|---|---|---|
| Single agent | Most stages | One lead run produces the stage outputs |
| Sequential multi-agent | Lead then specialist | Handoff uses structured output; lead owns final artifact |
| Parallel agents | Independent sections or branches | Results merged by the lead; conflicts recorded as findings |
| Reviewer | After lead output | Separate configuration and context; returns structured findings |
| Second-opinion review | High-risk stages | Reviewer from a different provider (configurable) |
| Specialized subagent | Narrow tasks (e.g. Accessibility Reviewer) | Runs with narrow context and tool grants |

The lead is the only writer of stage artifacts. Support and reviewer outputs are stored as `agent_run` evidence attached to the stage, and the lead must address or reject each finding explicitly.

## 4. Independent review loop

```
Lead agent run (creation) --> artifact version V
  -> deterministic sensors on V (engine)
  -> Reviewer run on V (separate config, separate context) --> findings F (structured)
  -> if blocking findings: lead revision run with F  --> V+1  (bounded by max_loops)
  -> reviewer re-evaluates V+1 (only if the policy requires it)
  -> sensors on final version
  -> human decision (never the agent)
```

Enforcement:

- Dispatcher refuses a reviewer whose configuration id equals the lead's id or whose `base_config_id` equals it.
- The reviewer's prompt contains the artifact and the review rubric only, not the lead's reasoning or chat history.
- A verdict is bound to `artifact_version_id` + content hash; a later version needs a fresh verdict if the policy says so.

## 5. Structured handoffs

Each handoff is a typed JSON document validated against the receiving agent's `input_schema`:

```json
{
  "handoff_id": "uuid",
  "from": {"agent_run_id": "uuid", "profile": "business_analyst"},
  "to": {"agent_config_id": "uuid"},
  "stage_execution_id": "uuid",
  "inputs": [{"artifact_version_id": "uuid", "content_sha256": "hex"}],
  "instructions_ref": "config-version-id",
  "open_questions": [{"id": "Q-1", "text": "..."}],
  "constraints": ["..."]
}
```

Free-form natural-language chaining between agents is not allowed for protected data.

## 6. Context policy

- Each agent receives: its instructions, applicable rules (rule resolver output for its scope), the stage inputs (artifact versions it is allowed to read), and the relevant part of the project conversation **only if its context policy allows** (for example the portal's routing agent may read user messages; a developer agent may not).
- Project-wide memory is not injected by default.
- Secrets are never in context. Provider credentials are resolved inside the provider adapter.
- Context manifest stored per run: list of artifact version IDs, rule version IDs, skill versions, conversation message IDs (not contents).

## 7. Provider abstraction

Interface (Python, illustrative):

```python
class ProviderAdapter(Protocol):
    name: str
    async def health(self) -> HealthReport: ...
    async def complete(self, req: CompletionRequest) -> CompletionResult: ...
    async def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]: ...
    def capabilities(self) -> ProviderCapabilities: ...  # tool_calling, structured_output, streaming, max_context
    def estimate_cost(self, usage: Usage) -> Money: ...
```

Adapters: `anthropic`, `openai`, `gemini`, `openai_compatible` (base URL + auth scheme), `local` (e.g. Ollama or vLLM through the OpenAI-compatible path).

Requirements (from the brief) and where they live:

| Requirement | Mechanism |
|---|---|
| Authentication | Credentials from the secret store, decrypted only inside the adapter process; never returned by any API |
| Model selection | `ModelRoute`: primary, fallback list, selection by stage or task type |
| Message formatting | Adapter translates the canonical `CompletionRequest` to vendor format |
| Streaming | Adapter yields normalized `StreamEvent`s; UI shows real progress from these events, never simulated |
| Tool calling | Only tools the agent configuration grants; adapter translates tool schemas; tool results re-validated |
| Structured outputs | Output validated against the agent's JSON Schema; one repair attempt; then fail |
| Token and cost tracking | `TokenUsage` row per call with price table versioned per provider/model |
| Timeouts | Per-call timeout from agent policy; cancellation propagated |
| Retries | Exponential backoff on retryable errors only (429, 5xx, network); no retry on 4xx validation errors |
| Error normalization | Adapter maps vendor errors to `ProviderError{kind: rate_limited | auth | invalid_request | timeout | content_filtered | unavailable}` |
| Health checks | Scheduled probe per provider config; results shown to admin; unhealthy routes skipped |

Fallback preserves task context and output schema: the fallback receives the same `CompletionRequest` and the same JSON Schema, and its output is validated the same way. A fallback that changes provider is recorded on the run.

Routing examples from the brief are configuration, not code: "architecture generation: Claude; independent architecture review: GPT; code generation: Claude; code review: Gemini".

## 8. Tools

Each tool has: name, description, JSON input schema, output schema, required permission class, execution environment (`in_process`, `sandbox_worker`, `external`), timeout, retry config and security classification. Tools are registered by administrators; imported MCP servers and tools are `pending_review` until an admin authorizes them, and only authorized versions are callable.

Permission classes:

| Class | Examples | Default policy |
|---|---|---|
| READ | read artifact version, read project metadata | allowed per agent grant |
| WRITE | create artifact version, write notes | allowed per grant; scoped to stage outputs |
| EXECUTE | run tests or linters in sandbox | sandbox only, no network unless granted |
| ADMINISTRATIVE | change configuration, permissions | never granted to agents; admin humans only |
| EXTERNAL_SIDE_EFFECT | production deployment, sending messages, modifying production data, publishing, infrastructure changes, financial transactions | requires explicit authorization policy with human approval per action or standing approved policy with limits |

No agent may elevate its own permissions. Agent configuration changes are themselves governed (rule-change flow, admin approval).

## 9. Developer profile specifics (M6)

Code generation writes into a sandboxed workspace per project, not into the server. Sandbox has no production credentials, no network unless the stage grants a package registry, and CPU/memory/time limits. Generated code and test results become artifacts; the Code Review reviewer and sensors (lint, type-check, unit tests, secret detection, dependency audit) run in the same sandbox. The Developer profile never pushes code or deploys; those are DevOps stages with EXTERNAL_SIDE_EFFECT authorization.
