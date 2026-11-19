# Rules Analysis

Source: `core/memory/` (`org.md`, `team.md`, `project.md`, `phases/*.md`), `harness/claude/rules-aidlc.md`, `protocols/stage-protocol-learnings.md`, `docs/reference/08-rule-system.md`.

## AWS model

- Rules are markdown files in layers: framework defaults (`org.md`), team, project and per phase. Narrower layers add specialisation and are read first.
- A resolver loads every applicable layer for the active stage, and a hook delivers required stage rules across the sub-agent boundary.
- The learnings ritual asks the person whether a correction should become a rule. A deterministic tool writes it only after consent.
- Rules are text the model reads. Enforcement of anything critical lives in hooks and sensors.

## Our model (built in Milestone 7)

Organization → Team → Project → Profile → Stage → Agent. Rules are versioned, additive, with mandatory and prohibited kinds that lower levels cannot redefine. Proposals from AI or people take effect only after an administrator approves. Running workflows keep the rule versions they started with.

## Gaps against the rebuild prompt

- "Tested before activation": add a dry-run that shows which stages and agents a rule would reach and flags conflicts before publishing.
- Rules that affect security, progression, permissions or mandatory validation must require a named approver with the right permission, not any administrator.

Decision: REFERENCE ONLY. The concept is already built; two extensions planned for Phase 12.
