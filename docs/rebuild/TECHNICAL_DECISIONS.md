# Rebuild Technical Decisions

Earlier decisions remain in `docs/DECISIONS.md` (ADR-001 to ADR-055). Rebuild decisions are numbered RD-n. RD-1 to RD-8 were answered on 2026-11-19.

| ID | Decision | Status | Rationale |
|---|---|---|---|
| RD-1 (D1) | Default lifecycle follows the rebuild prompt's department stage lists; AWS 33-stage lifecycle kept as an importable template; AWS scopes become applicability profiles | Accepted | The prompt is explicit and says not to copy the AWS lifecycle blindly |
| RD-2 (D2) | Only the assigned human professional gives final approval. The owner sees the work and gives input to that professional, who reviews it and decides what to send to the AI. The prompt's user approval stages become owner input steps | Accepted (user's own model, not the recommendation) | Keeps one accountable approver per department while keeping the owner involved |
| RD-3 (D3) | Evolve the modular monolith | Accepted (default) | Core modules are tested and sound |
| RD-4 (D4) | PostgreSQL job queue and a worker process | Accepted | Durable, transactional with state, no new service |
| RD-5 (D5) | MinIO for files and large artifacts | Accepted | S3-compatible locally and in production |
| RD-6 (D6) | Tailwind during the workspace rebuild | Accepted (default) | Prompt default; pages are being rebuilt anyway |
| RD-7 (D7) | Local Ollama for the first end-to-end proof; cloud key later | Accepted (default) | No credentials needed now |
| RD-8 (D8) | Commit the current tree to main and push as the baseline | Accepted (user chose main and push) | Protects existing work |
| RD-9 | Agents never call each other; the orchestrator routes all collaboration | Proposed | AWS principle, keeps every exchange recorded and permission-checked |
| RD-10 | Conditions are deterministic expressions, never model text | Proposed | The engine must decide transitions |
| RD-11 | Mandatory design system: forest green identity, beige workspaces, electric purple for AI and accents, separate status colours, central tokens (`docs/architecture/DESIGN_SYSTEM.md`) | Accepted (your specification) | Applies to every page and replaces Tailwind-first styling in RD-6: Tailwind, if added, must read these tokens |
