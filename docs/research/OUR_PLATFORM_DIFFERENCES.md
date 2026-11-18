# Our Platform vs. the Reference

Status: Research, Milestone 1

| Dimension | AWS AI-DLC reference | Our platform |
|---|---|---|
| Form | Prompts + TypeScript tools inside a coding assistant | Web application: API service, workers, web UI |
| Users | One developer per repo | Multi-tenant organizations, teams, project owners, professional reviewers, administrators |
| Authority | Local harness hooks | Server-side policy engine, DB constraints, transactional state machine |
| State | Markdown `aidlc-state.md` | Relational schema with migrations, optimistic concurrency |
| Audit | Shard files, not tamper-evident | Append-only hash-chained table per organization |
| Professional profiles | Coding-assistant personas (product, architect, design, developer, quality, devsecops, pipeline, ...) | Six configurable profiles as first-class objects, with stages and agents assigned per profile; admins can add profiles without code |
| Workflow configuration | Scopes and stage YAML, edited as files | Visual Workflow Studio, versioned JSON/YAML import/export, compiler validation |
| End user | Developer is the user | Project Owner portal, conversational intake, routed professional communication, end-user approvals of configured gates |
| Approvals | Single approver per gate, human turn in host | Multi-approver policies, RBAC, version-bound approvals, invalidation on change, risk acceptance records |
| Model providers | Chosen by the host harness | Provider abstraction: Anthropic, OpenAI, Gemini, OpenAI-compatible, local; fallback preserving schema; per-stage routing |
| Secrets | Host-managed | Encrypted secret store, references only in DB, never in frontend |
| Tools | Host tools (shell, file edit) | Registry with classification (READ / WRITE / EXECUTE / ADMINISTRATIVE / EXTERNAL_SIDE_EFFECT), authorization per agent, sandboxed execution |
| Hooks | Harness hooks in local settings | Declarative DB hooks with policy, timeouts, failure policies; AI-authored hooks require human approval |
| Sensors | Markdown manifests + local scripts | Typed registry with statuses PASS/FAIL/WARNING/NOT_APPLICABLE/ERROR |
| Rules | Memory files, hierarchical | DB-backed hierarchical rules with versions, change history, governed proposals |
| Multi-user concurrency | Not applicable | Transactions, idempotency keys, unique constraints, concurrent-approval tests |
| Testing | Large Bun/TS test suite | Pytest (backend), Vitest (frontend), Playwright (E2E), security test suite |
| Deployment | Installer for developer machines | Docker Compose for dev; documented production deployment |
| Stakeholder | Developers | Business users, architects, designers, QA, DevOps, owners; developers are one of six profiles |

## Improvements we intend to make, in priority order

1. **Enforce on the server.** Authority never depends on a client hook.
2. **Version-bound approvals.** Approvals are tied to content hashes, and changes invalidate them automatically.
3. **Tenant and project isolation** in every query and every audit row.
4. **Provider independence** with schema-preserving fallback.
5. **Configuration without code changes.** Profiles, workflows, rules, hooks and sensors are data with versions.
6. **Professional end-user experience.** The LLM and the workflow are hidden behind named professional representatives.
7. **Tamper-evident audit** with a verification endpoint.

## Things we will keep from the reference

- Engine-owned lifecycle with LLM as judge, not authority.
- Independent reviewers with fingerprint-bound verdicts.
- Fail-closed mandatory sensors.
- Compiled, validated stage definitions.
- Audit-first atomicity and an emitter drift test.
- Scope-like presets for different ceremony levels.
