# Knowledge Analysis

Source: `core/knowledge/` (61 files in 15 folders), `docs/guide/08-knowledge.md`, `docs/reference/10-knowledge-system.md`, `docs/harness-engineering/07-team-knowledge.md`.

## AWS model

- Each agent has a knowledge folder of practice guides. For example, the product agent has requirements elicitation, requirements guide, user story patterns, prioritization frameworks, market research methods, functional design guide and a corner-case checklist.
- `aidlc-shared` holds principles, audit format, verification, brownfield guidance and templates.
- A knowledge-loading order in the stage protocol decides what the model reads for a stage.
- Teams add their own knowledge, layered over the defaults.

## Our needs

The rebuild prompt asks for more than curated guides: uploaded project files with extraction, OCR, chunks, provenance, and stage-specific retrieval.

| Concept | Our design |
|---|---|
| Per-agent guides | Department skills (versioned, built in M6) carrying our own guidance text |
| Loading order | Context retrieval layer: brief, approved upstream artifacts, rules, relevant file chunks, findings, in priority order with a token budget |
| Team knowledge | Organization and project knowledge sources, approved before use |
| Project files | New file registry: upload, validation, scanning, extraction, chunks, provenance, authority status, per-department access |

Uploaded and retrieved content is always passed as tagged data, never as instructions.

Decision: REFERENCE ONLY for the guide texts (we write our own); ADAPT the loading-order idea into the retrieval layer.
