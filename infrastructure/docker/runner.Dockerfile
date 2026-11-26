# The image every execution job runs in (Phase 1, RD-30). The executor starts one container per job from it, with no
# network, a read-only root, dropped capabilities and hard limits. It holds the toolchains jobs need (Python with
# pytest, Node.js, git); nothing in a job can choose another image or command.
# The TypeScript compiler, for the Codebase Explorer's import analysis: pinned, installed at build time (the job
# containers have no network). Apache-2.0; the same version the frontend uses.
FROM node:20-bookworm-slim AS typescript
RUN mkdir /ts && cd /ts && npm init -y >/dev/null && npm install --no-audit --no-fund --ignore-scripts typescript@5.5.4

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends nodejs git && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "pytest==8.3.3" \
    && groupadd --gid 2000 code && useradd --uid 2000 --gid 2000 --no-create-home --shell /usr/sbin/nologin code

COPY sandbox/runner.py sandbox/job.py sandbox/gitjob.py sandbox/terminal_init.py sandbox/codeindex.py sandbox/tsimports.js /opt/runner/
COPY --from=typescript /ts/node_modules/typescript /opt/runner/node_modules/typescript
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SANDBOX_WORK=/work PYTHONPATH=/opt/runner
WORKDIR /opt/runner
