# Security Architecture

Status: Proposed (Milestone 1). Implementation starts in Milestone 2; security tests in every milestone.

## 1. Threat model summary

| Actor | Trust level | Main threats |
|---|---|---|
| Platform administrator | High, audited | Misconfiguration, credential exposure |
| Organization administrator | High within tenant | Cross-tenant access attempts, privilege escalation |
| Project owner (end user) | Medium | Bypassing gates, reading internal prompts, injecting instructions |
| Internal human reviewer | Medium | Unauthorized approval, self-approval |
| AI agent | **Untrusted for decisions** | Prompt injection, tool misuse, data exfiltration, self-approval attempts |
| LLM provider | External, untrusted for data handling policy | Data sent beyond policy, outputs that fail schema |
| Uploaded documents, web content, MCP outputs | **Untrusted input** | Indirect prompt injection, malicious files |
| Network attacker | Untrusted | Session theft, CSRF, replay |

## 2. Authentication

- **M2:** email and password. Passwords hashed with Argon2id (per OWASP parameters). Login rate limited per account and per IP. Account lockout with backoff rather than permanent lock.
- **Sessions:** server-side session records; opaque random ID in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie; rotated on login and privilege change; idle and absolute timeouts; logout invalidates server-side.
- **CSRF:** synchronizer token on every state-changing request, tied to the session.
- **Later (M10 or customer request):** OIDC/SAML SSO. The identity module keeps a provider interface so this is additive.
- **API tokens:** for integrations, scoped and hashed at rest, shown once; no agent receives a user token.
- **MFA:** TOTP supported before production; required for platform and organization administrators.

## 3. Authorization

Layers, all enforced server-side:

1. **Tenant scope.** Every tenant row carries `organization_id`. The repository base class requires a tenant context and appends the filter; code that bypasses it fails review and a test. PostgreSQL row-level security is planned as defense in depth (M10).
2. **Project membership.** Project-scoped rows require membership; roles are per project.
3. **Role permissions.** Roles: `platform_admin`, `org_admin`, `project_owner`, `internal_reviewer`, `team_member`, `viewer`. Permission strings like `approval:decide`, `workflow:start`, `agent:configure`, `rule:propose`, `rule:approve`.
4. **Profile and stage permissions.** Each stage lists who may view, act and approve. Checked in the engine.
5. **Tool permissions.** Classes READ/WRITE/EXECUTE/ADMINISTRATIVE/EXTERNAL_SIDE_EFFECT per agent grant (section 7).
6. **Resource-level checks.** Object ownership checks on every ID in a request (IDOR tests).

### Role matrix (summary)

| Capability | Platform admin | Org admin | Project owner | Internal reviewer | Team member | AI agent |
|---|---|---|---|---|---|---|
| Create project | yes (own org) | yes | yes | no | no | no |
| View internal prompts/traces | yes (support, audited) | no | **no** | no | limited | n/a |
| Manage provider keys | yes | yes (own org) | no | no | no | no |
| Edit profiles/workflows | yes | yes | no | no | no | no |
| Edit rules | yes | yes | proposes only | proposes only | proposes | proposes only |
| Approve owner-gated deliverable | n/a | n/a | yes (configured gates) | n/a | n/a | **never** |
| Approve internal gate | n/a | policy-based | n/a | yes (slot) | yes (slot) | **never** |
| Start workflow stage | yes | yes | no | no | per profile role | no |
| Modify engine state | only via API commands | same | no | no | no | **never** |
| View audit | own org | own org | project events subset | project subset | project subset | no |

"Never" means enforced by the server regardless of UI.

## 4. Input and output validation

- All request bodies: Pydantic models with `extra = forbid`, length limits, enum types, and size limits on uploads.
- File uploads: content-type sniffing, extension allow-list, size limit, malware scan hook (pluggable; ClamAV in production), stored outside web root with randomized keys, served with `Content-Disposition: attachment` unless previewed through a sanitizing renderer.
- LLM outputs: validated against JSON Schema before any use; unknown fields rejected; outputs never executed as code or SQL; outputs rendered as text with escaping in the UI (no raw HTML from models).
- Routing outputs (portal): the classifier returns a typed enum and a target ID; the backend resolves the target from the database and checks permissions. Model output never names a tool or a raw endpoint.

## 5. Prompt-injection defenses

Documents and user content are wrapped with delimiters and labeled as untrusted data in every prompt. Defense in depth, none of which is relied on alone:

1. **Structural separation:** system instructions and data are separate message roles; data is never concatenated into instruction text.
2. **Least privilege:** an agent that reads untrusted content has no WRITE to protected state and no EXTERNAL_SIDE_EFFECT grant.
3. **Output constraints:** strict schemas; a stage cannot produce an approval, a state change or a tool call that its grant does not allow.
4. **Deterministic gates:** injected instructions cannot satisfy a sensor or approval; both are computed outside the model.
5. **Canary tests:** a test corpus of injection payloads (in `tests/security/`) runs against each adapter with the mock provider and asserts no state change or permission change.
6. **Monitoring:** attempts that trigger refusals are audited with `security.suspected_injection`.

Prompt injection can still cause a bad artifact. The human approval and sensors exist for that reason.

## 6. Secrets management

- Provider keys, webhook secrets and integration tokens are stored **encrypted** (AES-256-GCM envelope encryption). Data-encryption keys are wrapped by a key-encryption key (KEK) from an environment-provided key in development and a KMS in production.
- The `secret_references` table stores metadata and ciphertext reference, never plaintext. Display in the admin UI shows last four characters at most, and only to org admins.
- Secrets are decrypted only inside the provider adapter or integration client at call time; they are never placed in prompts, logs, audit metadata, error messages or API responses.
- Log and audit redaction runs on every write with a pattern set (keys, bearer tokens, private key blocks, connection strings).
- Rotation: key versioning on ciphertext; re-encryption job; admin action audited.
- Repository: no credentials in source. `gitleaks` runs in pre-commit and CI. `.env.example` contains placeholder names only.

## 7. Tool execution and sandboxing

- Tools run in the worker, never in the API process.
- Code execution (tests, linters, builds, code generation runs) runs in a container sandbox per run: non-root user, read-only root filesystem except the workspace, CPU/memory/PID/time limits, no host mounts, no Docker socket, network disabled unless the stage grants a named allow-list.
- The Developer profile's sandbox has no production credentials and cannot reach production networks.
- Imported MCP servers run in their own sandbox with explicit tool allow-lists, and are disabled until an administrator authorizes each tool version.

## 8. Hooks and rules abuse

- Hooks are declarative. Built-in actions only. Organization-defined code hooks are disabled in M7; if added later they run in the sandbox with a signed manifest and admin approval.
- AI-generated hooks or rules are proposals. Activation requires an authorized human, and the proposal records the source conversation IDs.
- Conflicts with policy (e.g., a rule that disables a mandatory sensor) are detected by the policy checker and block activation.

## 9. Audit and tamper evidence

Covered in `docs/research/STATE_AND_AUDIT_ANALYSIS.md` and `WORKFLOW_ENGINE.md`. Summary: append-only table, hash chain per organization, verification endpoint, DB role separation (application can insert, cannot update or delete), periodic signed checkpoint of the chain head.

## 10. Rate limiting and abuse

- Per-IP and per-account limits on auth endpoints.
- Per-organization and per-user limits on AI-invoking endpoints (cost control and abuse).
- Per-provider concurrency and token budgets configurable by org admins; budget exhaustion blocks new runs with a clear status.

## 11. Concurrency and replay

- Optimistic version checks on mutable rows.
- Idempotency keys on approvals, transitions, uploads and provider-invoking commands; keys stored with a result hash and expiry.
- Request timestamps and nonces on approval submissions (see `APPROVAL_GOVERNANCE.md`).

## 12. Dependency and supply chain

- Lockfiles committed (`uv.lock`, `pnpm-lock.yaml`).
- `pip-audit` and `npm audit --omit=dev` in CI; critical findings block merges.
- Container base images pinned by digest.
- Dependabot or equivalent on the repository when hosted.
- New dependency requires justification in `DECISIONS.md`.

## 13. Security checklist for each milestone exit

- Authorization negative tests for each new endpoint.
- Cross-tenant test for each new table.
- Secret exposure test: response and log scan for seeded canary secrets.
- Input-validation fuzz or property test for each new request model.
- Updated threat notes in this document where the change affects trust boundaries.
