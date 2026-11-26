# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
ARG INSTALL_ML=false
COPY --from=deps /opt/venv /opt/venv
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_ML" = "true" ]; then uv sync --frozen --no-dev --extra ml; else uv sync --frozen --no-dev; fi \
    && useradd --create-home --uid 10001 meetmind && mkdir -p /app/data && chown -R meetmind /app/data
ENV PATH="/opt/venv/bin:$PATH"
USER meetmind
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
    CMD curl -fsS http://localhost:8000/health || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
