# Build context: repository root (configs are taken from analytics/artifacts, not duplicated).
ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM deps AS deps-test
RUN uv sync --frozen --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANALYTICS_ARTIFACTS_DIR=/app/analytics/artifacts
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY analytics/artifacts/scorecard.v1.json analytics/artifacts/policy.v1.json analytics/artifacts/demo_users.json analytics/artifacts/demo_companies.json analytics/artifacts/synthetic_applications.json /app/analytics/artifacts/
COPY services/api/alembic.ini /app/alembic.ini
COPY services/api/migrations /app/migrations
COPY services/api/app /app/app
USER 10001:10001
EXPOSE 8000 9100
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=2)"]
CMD ["python", "-m", "app.cli", "api"]

# test image: same code plus pytest, the golden file and the mock (started in-process by the tests)
FROM runtime AS test
USER root
COPY --from=deps-test /opt/venv /opt/venv
COPY analytics/artifacts/expected_outcomes.json /app/analytics/artifacts/
COPY analytics/src/__init__.py analytics/src/mockgen.py /app/analytics/src/
COPY analytics/src/oracle /app/analytics/src/oracle
COPY services/integrations-mock/app /app/mock/app
COPY services/api/pyproject.toml /app/pyproject.toml
COPY services/api/tests /app/tests
ENV MOCK_APP_DIR=/app/mock ANALYTICS_DIR=/app/analytics
USER 10001:10001
HEALTHCHECK NONE
CMD ["python", "-m", "pytest"]
