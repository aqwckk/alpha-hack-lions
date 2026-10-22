# Build context: repository root (demo companies and the shared generator come from analytics/).
ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY services/integrations-mock/pyproject.toml services/integrations-mock/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ANALYTICS_DIR=/app/analytics
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY analytics/src/__init__.py analytics/src/mockgen.py /app/analytics/src/
COPY analytics/src/oracle /app/analytics/src/oracle
COPY analytics/artifacts/demo_companies.json /app/analytics/artifacts/
COPY services/integrations-mock/app /app/app
USER 10001:10001
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log", "--log-level", "warning"]
