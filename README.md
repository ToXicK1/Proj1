# AI-DLC Orchestration Platform

A configurable, governed platform that runs a software project through a professional AI-assisted lifecycle (Business Analysis, Architecture, UI/UX Design, Development, QA & Security, DevOps & Release). AI agents generate and review work, deterministic sensors validate it, humans authorize every protected transition, and the workflow engine advances the state.

**Status: Milestone 2 (foundation) implemented.** Sign up, verify email, sign in, and create projects. The delivery lifecycle and AI agents arrive in later milestones. See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

## Layout

```
backend/         FastAPI service, bounded contexts under backend/app, Alembic migrations, pytest suite
frontend/        React + TypeScript app (Vite)
shared/          JSON schemas, API contracts, workflow templates (empty until used)
infrastructure/  Dockerfiles and deployment (see docker-compose.yml)
tests/           integration, end-to-end and security suites (planned)
docs/            research, architecture, plan, decisions, known issues
```

## Run the backend locally (Windows PowerShell)

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```powershell
cd backend
uv sync
uv run pytest
```

The tests start an embedded PostgreSQL server (no Docker or system database needed).

To run the API against your own PostgreSQL:

```powershell
$env:AIDLC_DATABASE_URL = "postgresql+pg8000://USER:PASSWORD@localhost:5432/aidlc"
$env:AIDLC_SECRET_KEY = "a-long-random-string"
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --port 8000
```

## Run the frontend locally

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server forwards `/api` to the backend on port 8000.

## Email verification in development

Email is not sent yet. The verification message is stored in the `email_outbox` table. To get the link, query that table (kind `verify_email`) and open the URL it contains.

## Docker Compose

Verified on Docker Engine 29.5.2. The stack is defined in `docker-compose.yml`:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

## Principles

1. The workflow engine is the only writer of stage state.
2. Only authenticated humans can approve; approvals are bound to exact artifact versions.
3. Mandatory validations fail closed.
4. Secrets are never sent to the browser, logged, or committed.
5. Configuration is versioned data; running executions keep their pinned version.
