# Agent Analysis

Status: Research, Milestone 1
Source: `core/agents/*.md` (14 files), `core/knowledge/*` (61 guides), `core/aidlc-common/protocols/stage-protocol-reviewer.md`, `stage-protocol-ensemble.md`, `docs/reference/05-agent-system.md`

## 1. Agent inventory

| Agent | Role in reference | Our profile mapping |
|---|---|---|
| aidlc-product-agent | Requirements, user stories, functional design | Business Analyst |
| aidlc-product-lead-agent | Reviews product work (reviewer) | BA reviewer |
| aidlc-architect-agent | Domain, contracts, units, NFR design | Solution Architect |
| aidlc-architecture-reviewer-agent | Reviews architecture (reviewer) | Architecture Critic |
| aidlc-design-agent | UX, wireframes, component specs, accessibility | UI/UX Designer |
| aidlc-developer-agent | Code analysis and generation | Software Developer |
| aidlc-quality-agent | Test strategy, NFR validation | QA & Security (testing) |
| aidlc-devsecops-agent | Threat modelling (STRIDE), security guide | QA & Security (security) |
| aidlc-pipeline-deploy-agent | CI/CD, deployment strategies | DevOps & Release |
| aidlc-aws-platform-agent | Cloud infrastructure (CDK) | DevOps & Release (infra) |
| aidlc-operations-agent | SLOs, observability, incidents | DevOps & Release (operations) |
| aidlc-compliance-agent | Regulatory frameworks | Governance (optional profile) |
| aidlc-delivery-agent | Team topologies, workflow planning | Project coordination |
| aidlc-composer-agent | Composes custom workflows | Workflow Studio assistant (candidate) |

## 2. Agent file contract

Each agent is one Markdown file with frontmatter (`name`, `display_name`, `examples`, `description`, `disallowedTools`, `tier`), followed by a persona body. Example: `aidlc-architect-agent.md` declares `disallowedTools: Task`, so the agent cannot spawn other agents.

Lessons:
- Persona text is **data loaded at dispatch**. Agents do not invoke each other: "Agents never invoke each other, only the conductor delegates" (`conductor.md`).
- Knowledge is **separated from persona**. A knowledge folder per agent (`core/knowledge/<agent>/`) is loaded according to a knowledge-loading order in the stage protocol. This keeps personas short and lets knowledge be reused.
- `tier` (e.g. `judgment`) is a routing hint for model choice.

## 3. Independent review

This is the most important pattern in the reference for our requirement "creation and review must be separate".

- Reviewer is a **separate sub-agent** dispatched by the conductor, after the lead produces artifacts and before the gate (`stage-protocol-reviewer.md` section 12a).
- Review classes: `adversarial` (refute-and-repair loop, up to N passes with lead fixes between them) for construction; `advisory` (one pass, decision support) for prose stages.
- Reviewer verdicts are recorded with **the artifact fingerprint** (`sha256` over the bytes reviewed) and request id. If the artifacts change after the review, the receipt is invalidated (`aidlc-review-freeze.ts`).
- Reviewer findings are structured (`review record` JSON with severity and finding IDs).
- The reviewer has its own persona and brief; it is not given the lead's private reasoning.

**Our adoption.** Reviewer independence is enforced by the backend, not by a prompt: the dispatcher refuses a review when the reviewer `AgentConfiguration` equals the generating one, or shares its context session. Verdicts bind to `artifact_version_id` plus content hash.

## 4. Ensembles and swarms

The reference supports multi-agent stages (`stage-protocol-ensemble.md`, `stage-protocol-swarm.md`): a lead plus support agents contribute evidence, the lead owns final `produces[]`, and objections are triaged. Swarms run work units in parallel worktrees.

For us: multi-agent stages are valuable, but "the lead owns final output" must become a backend rule: the stage's produced artifact is written by the lead agent's run, and support outputs are stored as evidence (`AgentRun` children), never as artifacts.

## 5. Knowledge and skills

- `core/knowledge/aidlc-shared/` contains cross-agent guidance (principles, audit format, brownfield, verification, rules reading).
- `core/skills/` contains reusable skills (`aidlc-knowledge`, `aidlc-replay`, `aidlc-session-cost`, `aidlc-issue-report`), each with `SKILL.md` and scripts.

Our design: knowledge documents and skills become versioned `Skill` records with `required_tools`, `compatible_profiles`, `compatible_stages`, `version`. They are attached to agent configurations, not injected globally. Agents receive only the context and skills their stage authorizes (least privilege, master prompt Part 10).

## 6. Context policy

The reference gives each subagent only the prompt it is dispatched with ("subagents cannot see conversation history"). We adopt the same rule and make it explicit: every `AgentRun` has a **context manifest** listing the artifact versions, rules and conversation excerpts it received. The manifest is stored, so context leakage is auditable.

## 7. Gaps we will fill

| Gap in reference | Our approach |
|---|---|
| No end-user persona; agents are developer-facing | Professional identities (`ProfessionalRepresentative`) that map to profiles, with a communication layer (see portal module) |
| Agent permissions come from the host harness | Explicit `ToolPermission` set per agent configuration, least privilege, never inherited from the human |
| No provider abstraction; a harness picks the model | Provider adapter layer with per-stage model routing and fallback that preserves schema |
| No cost or token accounting per agent run | `TokenUsage` and `AgentRun` rows with provider, model, tokens, cost estimate, latency, retries |
