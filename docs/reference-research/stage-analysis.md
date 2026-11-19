# Stage Analysis

Source: `core/aidlc-common/stages/` (33 files), `protocols/stage-definition.md`, `docs/guide/05-scopes-and-depth.md`.

## How an AWS stage is defined

Each stage file has YAML front matter and step prose. Example fields from `construction/nfr-requirements.md`:

- `slug`, `name`, `phase`, `execution` (ALWAYS or CONDITIONAL) with a plain-language `condition`
- `lead_agent`, `support_agents`, `mode` (inline, subagent, pipeline, mob)
- `reviewer`, `review_artifact`, `reviewer_max_iterations`
- `for_each: unit-of-work` (run once per unit)
- `produces` (artifact vocabulary names) and `produces_kinds`
- `consumes` with `required`, `conditional_on`
- `requires_stage` (explicit dependencies)
- `sensors` (required-sections, upstream-coverage, linter, type-check, traceability)
- `scopes` (which of the 11 scopes include it)
- `summary_confirmation: required`

Steps can run in a question-only mode first, then generate.

## Phases and stages

Initialization (3, no gate) → Ideation (7) → Inception (9) → Construction (7) → Operation (7). Every stage except Initialization ends at a human approval gate.

## Comparison with the rebuild prompt

The prompt defines stages per department instead of per phase:

| Department | Prompt stages | Closest AWS stages |
|---|---|---|
| Business Analyst | Intake Review, Discovery, Requirements Analysis, User Story Development, Scope Definition, Requirements Review, Human Professional Review, User Review and Approval | Intent Capture, Market Research, Scope Definition, Requirements Analysis, User Stories, Approval and Handoff |
| Solution Architect | Requirements Analysis, System Decomposition, Technology Selection, Data Architecture, API and Integration, Security and Infrastructure, Architecture Documentation, Independent Review, Human Review, User Review | Feasibility, Domain Design, Units Generation, Contract Design, Functional Design, NFR Requirements, NFR Design |
| UI/UX Designer | Design Discovery, Information Architecture, User Journey Mapping, Wireframes, Visual Design, Prototype and UI Specs, Independent Review, Human Review, User Design Review, Design Approval | Rough Mockups, Refined Mockups |
| Software Developer | Repository and Environment Analysis, Development Planning, Environment Setup, Implementation, Unit and Integration Testing, Independent Code Review, Developer Rework, Human Review, Development Handoff | Reverse Engineering, Delivery Planning, Code Generation |
| QA and Security | Test Strategy, Test Case Generation, Functional, Integration and Regression, Performance, Security Assessment, Defect Management, Independent QA Review, Human Review, UAT, Final Signoff | Practices Discovery (part), Build and Test, Performance Validation |
| DevOps and Release | Deployment Planning, Environment Setup, Infrastructure and Containerization, CI/CD, Deployment Preparation, Release Readiness Review, Human Release Approval, Deployment and Verification, Operational Handover | Infrastructure Design, CI Pipeline, Deployment Pipeline, Environment Provisioning, Deployment Execution, Observability, Incident Response, Feedback |

Observations:

1. The prompt makes review and approval explicit stages; AWS folds the reviewer and the gate into every stage. We keep the engine behaviour (every AI stage is reviewed and gated) and also model the prompt's named review stages as aggregate department gates, so a department's package is approved as a whole.
2. AWS has design work in two stages; the prompt gives design ten, including visual design and prototypes. This needs real visual artifacts (sandbox-rendered previews).
3. AWS runs construction per unit of work and in parallel; the prompt asks for parallel stages "where safe". Phase 5 adds parallel branches.
4. AWS conditions are prose for the model; ours must be deterministic expressions evaluated by the engine.

## What we adopt

Declarative stage specs with produces, consumes, dependencies, reviewer, sensors and applicability; stage applicability per project scope; question-first steps; one gate per AI stage; aggregate department gates. Decision: ADAPT. See `adaptation-decisions.md`.
