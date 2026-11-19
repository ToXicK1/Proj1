# Protocol Analysis

Source: `core/aidlc-common/protocols/` (17 files, the main protocol is 1,156 lines).

| Module | Rule it enforces | How AWS enforces it | How we enforce it |
|---|---|---|---|
| `stage-protocol.md` §1 Approval Gates | Every non-initialization stage needs explicit approval; the assistant must stop at the gate | Prompt instruction plus engine `report` verbs | Backend state machine; only a human decision record moves AWAITING to APPROVED (built) |
| Voice contract | Plain language to the person; internal terms hidden | Prompt instruction | Owner wording guard and allow-listed responses (built); extend to department representatives |
| Structured questions | One clear question with options | Question files with `[Answer]:` tags | Intake and clarification questions stored as records with options |
| `-reviewer.md` §12a | Reviewer runs as a separate execution after the artifact exists, bounded iterations, receipts | Sub-agent dispatch, review records | Separate reviewer run with its own context (built); add review package and iteration receipts |
| `-sensors.md` | A blocking sensor keeps the gate shut | Engine refuses the report | Gate checks sensors before approval (built) |
| `-ensemble.md`, `-collaborators.md` | Support agents contribute; lead collates; objections triaged | Contribution files | Collaboration hub: contribution messages, positions and objections linked to the stage |
| `-loopback.md` | Build-and-test failures go back to code generation with diagnosis | Engine loop-back directive | Rework transition with sandbox evidence as feedback (partly built) |
| `-recovery.md` | Resume and re-run safely after interruption | State and audit files | Durable jobs and idempotent steps (to build) |
| `-learnings.md` | Turn corrections into rules only with consent | Learnings tool | Rule proposals (built) |
| `-governance.md` | Verify at phase boundaries | Prompt checklist | Phase transition hooks (to build) |
| `-checkpoint.md`, `-swarm.md`, `-wave.md` | Units of work, parallel batches, checkpoints | Git worktrees and checkpoints | Parallel stage branches and per-unit tasks (to build), without git worktrees |
| `-summary.md` | Plain completion summary | Prompt | Review package summary |

Key lesson: AWS enforces many rules through prompt text plus harness hooks, because it runs inside an assistant. We are a server, so every rule that matters is enforced in backend code, and prompt text is only guidance. Decision: ADAPT.
