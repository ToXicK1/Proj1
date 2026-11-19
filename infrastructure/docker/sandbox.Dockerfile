# Sandbox for generated code. It is started with no network, a read-only root and dropped capabilities
# (see docker-compose.yml). Only Python with pytest and Node.js are available to generated projects.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "pytest==8.3.3" \
    && groupadd --gid 2000 code && useradd --uid 2000 --gid 2000 --no-create-home --shell /usr/sbin/nologin code

COPY sandbox/runner.py /opt/sandbox/runner.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "/opt/sandbox/runner.py"]
