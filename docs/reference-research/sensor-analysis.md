# Sensor Analysis

Source: `core/sensors/` (6 definitions), `core/tools/aidlc-sensor-*.ts`, `protocols/stage-protocol-sensors.md`, `docs/reference/07-sensor-system.md`.

## AWS sensors

Each is a contract: `id`, `kind: deterministic`, `command`, `default_severity`, `fire_on` (gate), `category`, `matches` (file glob), input and output schemas, `timeout_seconds`.

| Sensor | Checks |
|---|---|
| required-sections | Documents contain mandated sections |
| upstream-coverage | Every upstream element is covered downstream |
| traceability | Element-level coverage table: gaps, orphans, invalid targets |
| claim-sources | Claims cite their sources |
| linter | Code lint |
| type-check | Code type check |

## Our sensors

18 built: required sections, JSON schema, requirement traceability, missing dependencies, duplicate requirements, broken references, architecture consistency, API contract, code lint, type check, unit tests, integration tests, security scan, secret detection, dependency vulnerabilities, artifact version, approval verification, and code builds (real sandbox build). Code and test sensors read evidence; the sandbox now produces real build and unit test evidence that people cannot override.

## Gaps against the rebuild prompt

- Results must record sensor version, inputs, outputs, evidence, execution time and the artifact version. Version and artifact version are recorded; input and output digests and duration are not.
- Add: document completeness, artifact consistency across departments, security configuration checks, deployment readiness, claim sources (from AWS).
- Lint, type check, integration tests and dependency scanning should run in the sandbox for real. Dependency scanning needs an offline vulnerability database because the sandbox has no network.

Decision: ADAPT (contract fields, claim sources, upstream coverage); REWRITE implementations in Python.
