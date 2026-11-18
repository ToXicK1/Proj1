# Backend API image. Dependencies are locked by uv.lock; production installs exclude the dev group.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN pip install --no-cache-dir "uv==0.5.*"

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --no-dev --frozen --no-install-project
COPY backend/ ./
RUN uv sync --no-dev --frozen

EXPOSE 8000
# Call the venv binaries directly: `uv run` would re-sync the dev group at start-up.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
