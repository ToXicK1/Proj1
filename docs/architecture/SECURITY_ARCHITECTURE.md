# Security Architecture (target)

Supersedes `docs/SECURITY_ARCHITECTURE.md` where they differ.

## Identity and access

- Argon2id passwords, HttpOnly SameSite session cookies, CSRF tokens, rate limits (move to a shared store if the API scales out).
- Permission-based access: roles map to permissions; every endpoint checks a named permission against organization and project membership. Professional review permission requires an active reviewer assignment for that profile and project.
- Separation of duties: authors cannot approve their own versions; reviewers cannot approve profiles they are not assigned to; self role changes are refused.

## Tenant isolation

Every query filters by organization and project. Identifiers from another tenant return "not found". Isolation tests cover every table.

## Secrets

Provider keys are encrypted with AES-256-GCM and never returned, logged or sent to the browser. Production keys come from environment or a secrets manager. The sandbox and the browser never receive secrets.

## AI-specific controls

- Owner text, uploads, retrieved chunks and tool results are untrusted and passed as tagged data.
- Agents cannot change state, approve, edit rules, or reach other projects. Tool grants are explicit per agent version.
- Owner-facing wording is allow-listed and filtered for internal terms.
- Model output is schema-validated; failures are recorded, not hidden.

## Code execution

The sandbox has no network, a read-only root, dropped capabilities, a separate unprivileged user, per-job private workspaces, process, CPU, file-size and time limits, and reaped orphans. Results come only from the sandbox and cannot be overridden by hand. Previews of generated front ends are served from an isolated origin with no access to platform cookies or APIs.

## Files

Type and size allow-lists, malware scanning (ClamAV in the processing container when available; files stay quarantined until scanned), extraction in the worker, signed short-lived download URLs, per-department visibility.

## External side effects

Production deployment, external messages, infrastructure changes and publishing require an explicit, recorded human authorization by a person with release permission. Failed mandatory security checks cannot be approved past.

## Audit

Hash-chained, append-only audit events with correlation IDs for every important action. Approval decisions, evidence, artifact versions and transitions are append-only.

## Operations

Dependency and secret scanning in CI, backups with a tested restore, encrypted transport in deployment, least-privilege database roles.
