# AI Orchestration (target)

## Loop

For each READY stage the worker:

1. Loads project, workflow version and stage spec.
2. Picks the department and the specialist agent(s) for the stage.
3. Builds a context package (below) within a token budget.
4. Resolves rules (snapshot) and tool permissions for that agent version.
5. Picks a model by routing policy.
6. Executes: one call, or a lead with contributions from support specialists, each recorded as an execution.
7. Validates structured output against the output schema; one repair attempt; otherwise FAILED with reason.
8. Persists an immutable artifact version.
9. Runs sensors (and sandbox execution where the stage requires real evidence).
10. Dispatches the independent review (read-only, optional different provider).
11. Freezes a review package and notifies the assigned professional.
12. Waits. Never transitions past a human gate.

## Provider interface

`generate(request) -> result`, `stream(request) -> events`, `call_tools(request, tools) -> tool_calls`, `health()`. Request carries system and user parts, schema, model, limits and timeout. Result carries text or parsed object, token usage, cost estimate, latency, normalized error kind. Adapters: Anthropic, OpenAI, Gemini, OpenAI-compatible (including local Ollama). Keys stay encrypted in the backend.

## Routing policies

Rules choose a route by task type (generation, review, extraction, classification, code), required capabilities (structured output, tools, long context), organization policy, cost ceiling and provider health. A review route can require a provider different from the producer's.

## Agent execution record

Agent ID and version, department, project, stage, task, input artifact references, context package digest, provider and model, tool grants, output schema, status, output artifact references, tokens, cost, duration, errors, review references, correlation ID.

## Context engineering

Priority order: stage instructions and rules → approved upstream artifacts relevant to the stage → owner statements and confirmed requirements → unresolved assumptions (labelled) → reviewer findings and change requests for this stage → relevant file chunks for the department → decisions. Each item is labelled by authority (owner statement, approved, assumption, superseded). Untrusted content is wrapped as data. Only the stage's department files are eligible.

## Tools

Registry with input and output schemas, permission class (READ, WRITE, EXECUTE, ADMINISTRATIVE, EXTERNAL_SIDE_EFFECT), environment, timeout and retries. Grants are per agent version. EXECUTE tools run in the sandbox. EXTERNAL_SIDE_EFFECT tools need a human authorization record for each use. Every call is stored.

## Independent review

A separate execution with its own reviewer agent, the exact artifact version, approved requirements and rules, read-only. Produces findings with severity and evidence. Advisory: it can trigger rework by policy but can never approve.
