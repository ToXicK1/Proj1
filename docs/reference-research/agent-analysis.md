# Agent Analysis

Source: `core/agents/` (14), `core/knowledge/` (61), `protocols/stage-protocol-ensemble.md`, `-collaborators.md`, `docs/reference/05-agent-system.md`.

## AWS agents

Product, Product Lead (reviewer), Architect, Architecture Reviewer, Design, Developer, Quality, DevSecOps, Delivery, Pipeline Deploy, AWS Platform, Operations, Compliance, Composer.

Each agent file has front matter (`name`, `display_name`, `description`, `tier`, `maxTurns`, `disallowedTools`) and a persona. Reviewers state that they did not design the work, must not call lifecycle commands, and return only a verdict and findings.

## Execution patterns

- **Inline**: the conductor adopts the lead's persona.
- **Subagent, pipeline, mob**: support agents run separately and each writes a contribution file. The lead collates and owns the final artifacts.
- **Agents never call each other.** The conductor is the only bus.
- Objections from support agents are triaged by the lead; unresolved ones are surfaced to the person.
- Model tier (fast, balanced, deep) is set per agent and mapped to each assistant's models.

## Mapping to six departments

| Department | Specialists from the prompt | AWS source concepts |
|---|---|---|
| Business Analyst | Intake Analysis, Business Discovery, Requirements Engineering, User Story, Acceptance Criteria, Scope Analysis, Traceability, Independent Requirements Reviewer | Product, Product Lead, Delivery |
| Solution Architect | Planning, Decomposition, Technology Selection, Database, API, Integration, Security, Infrastructure, Independent Reviewer | Architect, Architecture Reviewer, AWS Platform, Compliance |
| UI/UX Designer | UX Research, Information Architecture, User Journey, Wireframe, Visual Design, Design System, Prototype, Accessibility Review, Independent Reviewer | Design |
| Software Developer | Planning, Repository Analyst, Environment Setup, Frontend, Backend, Database, Integration, Unit Test, Independent Code Reviewer | Developer |
| QA and Security | QA Planning, Test Case Generation, Functional, API, Integration, Regression, Performance, Security Assessment, Defect Management, Independent Reviewer | Quality, DevSecOps |
| DevOps and Release | Infrastructure Planning, Environment Setup, Containerization, CI/CD, Deployment, Cloud Platform, Operations, Release Manager, Independent Reviewer | Pipeline Deploy, Operations, AWS Platform |

## What we adopt

- Specialist agents grouped under a department, with read-only, independent reviewers that never share lineage with the producer (our lineage check already enforces this).
- Contributions and lead collation for multi-agent stages, recorded as messages in the collaboration hub.
- Model tiers become routing policies by task type, not fixed models.
- Agents never move workflow state or call each other directly; the orchestrator routes every exchange.

Decision: ADAPT.
