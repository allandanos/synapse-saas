# Shared image for api / worker / migrate — uv multi-stage, non-root.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Local-disk storage fallback must be writable by the non-root user and live
# outside the read-only app tree. Production should set SYNAPSE_S3_BUCKET;
# with replicas>1 this directory is per-pod unless a volume is mounted here.
RUN useradd --create-home --uid 1001 synapse \
    && mkdir -p /data/storage && chown -R 1001:1001 /data/storage
ENV SYNAPSE_STORAGE_ROOT=/data/storage
USER synapse

EXPOSE 8000
CMD ["synapse-api"]
