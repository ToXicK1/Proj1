# Dependency and licence register

The platform is a commercial product (licensing policy: prefer MIT, Apache-2.0 and BSD; review MPL-2.0 and LGPL;
explicit approval for GPL, AGPL, BSL, proprietary SDKs, or unclear licences). Each entry below was verified against
the npm or PyPI registry on the date shown. Exact versions are pinned. An SBOM and automated licence scanning are still
to be added (open item).

## Frontend: Phase 2, the Developer IDE (added 2026-11-25)

| Package | Version | Licence (SPDX) | Repository | Why | Notes |
|---|---|---|---|---|---|
| `monaco-editor` | 0.57.0 (2026-09-24) | MIT | github.com/microsoft/monaco-editor | Code editor and diff editor | 0.58.0 was two days old, so a version more than two weeks old was chosen. **Bundled locally by Vite**, never loaded from a CDN. |
| `@monaco-editor/react` | 4.7.0 (2025-02-13) | MIT | github.com/suren-atoyan/monaco-react | React wrapper for Monaco | Peer support includes React 18. Its loader defaults to jsDelivr; it is configured to use the local `monaco-editor`. |
| `@xterm/xterm` | 6.0.0 (2025-12-22) | MIT | github.com/xtermjs/xterm.js | Browser terminal display | No dependencies. |
| `@xterm/addon-fit` | 0.11.0 (2025-12-22) | MIT | github.com/xtermjs/xterm.js | Fits the terminal to its panel | No dependencies. |
| `@dagrejs/dagre` | 1.1.4 (2024-08-15) | MIT | github.com/dagrejs/dagre | Codebase Explorer: lays the dependency graph out left to right | Brings `@dagrejs/graphlib` 2.2.4 (MIT, 2024-08-15). |
| `marked` (via monaco-editor) | 14.0.0 | MIT | github.com/markedjs/marked | Markdown in hovers | Transitive. |
| `dompurify` (via monaco-editor) | **3.4.17** (npm override; 2026-10-12) | MPL-2.0 OR Apache-2.0 | github.com/cure53/DOMPurify | HTML sanitising in Monaco | **Used under Apache-2.0**, the policy's preferred option. Overridden from 3.4.15 to fix five advisories affecting ≤3.4.16; same 3.4 line. |
| `@monaco-editor/loader` (via @monaco-editor/react) | ^1.5.0 | MIT | github.com/suren-atoyan/monaco-loader | Loader | Transitive. |

## Backend: Phase 1 (added 2026-11-25)

| Package | Version | Licence (SPDX) | Why | Notes |
|---|---|---|---|---|
| `docker` (Docker SDK for Python) | 7.1.0 | Apache-2.0 | The executor service starts job containers | Used only by the executor, never by the API or worker. Brings `requests`, `urllib3` (MIT) and, on Windows, `pywin32` (PSF). |
| `websockets` | >=14,<18 (17.4 installed) | BSD-3-Clause | Phase 2d terminal: the API's relay client and the executor's internal terminal server | Already installed through `uvicorn[standard]`; now declared directly. No new transitive packages. |

## Images

| Image | Base | Contents | Notes |
|---|---|---|---|
| `aidlc-runner` (Codebase Explorer) | adds `typescript` **5.5.4** (Apache-2.0), installed at image build time from a `node:20-bookworm-slim` build stage | The TypeScript compiler's parser, for deterministic import analysis of TS/JS in the `git.index` job | Same version as the frontend's. Job containers have no network; nothing is installed at run time. |
| `aidlc-runner` | `python:3.12-slim` (Debian) | Python with pytest 8.3.3 (MIT), Node.js and git from Debian packages (git: GPL-2.0, run as a separate program, not linked) | Image licensing to be reviewed with the SBOM work. |

## Known findings in existing dependencies (not introduced by Phase 2)

`npm audit` on 2026-11-25 reports 10 findings in packages that predate Phase 2: react-router-dom 6.26.2 (high: open
redirects); vite 5 and esbuild (high and moderate: dev server); vitest and tinypool (critical: test runner and its UI
server). Most concern the development server and test runner, not the built app. Fixing them needs major-version
upgrades, which are a separate piece of work.
