# Design System (mandatory, platform-wide)

Adopted 2026-11-19 from your UI/UX design specification (decision RD-11). Every page uses these tokens. No page defines its own palette.

## Identity

Premium, warm, modern enterprise: forest green carries the identity, beige is the warm neutral, electric purple marks AI and key accents. Relative emphasis is green 55, beige 30, purple 25 (normalised; not literal screen area).

## Tokens

Source of truth: `frontend/src/tokens.css`. Components use semantic tokens (`--page`, `--surface`, `--action`, `--identity-ai`, `--status-*`), never raw hex values.

| Group | Tokens |
|---|---|
| Forest green | `--green-900` #103629, `--green-700` #174B38 (primary), `--green-500` #28684F, `--green-100` #DCE9E1 |
| Beige | `--beige-300` #D6C8AC, `--beige-200` #E9DFC9, `--beige-100` #F5F0E5 (page), `--beige-50` #FAF7F0 (surface) |
| Electric purple | `--purple-700` #7736C8 (text-safe accent), `--purple-500` #A855F7 (focus, indicators), `--purple-400` #B96CFF, `--purple-100` #EBDDFA |
| Status | success, warning, error, info, blocked, pending approval, in progress, neutral, each with text and background tokens, all distinct from the brand |

Contrast: white text sits only on `--green-700` or `--purple-700`. `--purple-500` is used for focus rings and dots, not for small text.

## Layout

- Forest-green sidebar: logo, project switcher, workspace sections (overview, lifecycle, team conversations, deliverables, testing, notifications), the six professional profiles, and settings for administrators.
- Warm beige workspace with beige-50 cards, subtle borders and minimal shadow.
- Below 900px the sidebar becomes a stacked header with wrapping links.

## Identity markers

| Who | Marker |
|---|---|
| AI departments and agents | Purple `IdentityTag kind="ai"`; AI messages have a purple left edge |
| Human professionals and owners | Forest-green `IdentityTag kind="human"` |
| Automated system events | Neutral `IdentityTag kind="system"` |

Markers always carry a text label (AI, Person, System), so colour is never the only signal. They are used the same way in conversations, team cards, deliverables, activity, and later in review queues and approval screens.

## Components

`StatusPill` (status to tone mapping), `IdentityTag`, primary (green), accent (purple, for AI-specific actions), and secondary (beige outline) buttons; cards; tabs; form controls with purple focus rings. Typography: Inter with system fallbacks; JetBrains Mono for code.

## Profile workspaces

All six share these tokens and components but get their own layout in Phase 10: document-oriented (BA), diagram-oriented (Architect), visual and prototype-oriented (Designer), code-oriented (Developer), evidence and defect-oriented (QA), pipeline and infrastructure-oriented (DevOps). Until then, each profile link opens that department's deliverables.

## Not allowed

Unrelated palettes, per-page hex colours, heavy gradients, glass effects, glowing borders, decorative animation, purple or green as status colours.

## Fluid layout and motion (added 2026-11-19)

- Spacing, type and the sidebar width scale smoothly with the screen using `clamp()` tokens (`--space-*`, `--text-*`, `--sidebar-width`). Content fills the screen up to 1440px.
- Grids reflow by available width: six team cards settle as 3 by 2, 2 by 3 or a single column.
- On wide screens the sidebar can be hidden and shown again (remembered per browser). On phones it folds behind a Menu button.
- Motion is short and purposeful: hover, press, focus, tab and progress transitions, a gentle page and tab entrance, shimmer placeholders while loading, and a pulsing "Live" dot on pages that refresh themselves. All motion stops when the system asks for reduced motion.
