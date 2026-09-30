# syntax=docker/dockerfile:1
# shopfront/report-job - run-to-completion batch job (ECS scheduled task, AWS Batch, Kubernetes CronJob).
#
# Build:  docker build -t shopfront/report-job:dev .
# Multi-arch: docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/shopfront/report-job:sha-<gitsha> .
#
# Base image pinned by tag; digest verified 2026-09-30:
#   python:3.12-slim-bookworm  sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=dev
ARG REVISION=unknown
ARG SOURCE=https://github.com/ErickrU/containers-on-aws
LABEL org.opencontainers.image.title="shopfront/report-job" \
      org.opencontainers.image.description="shopfront daily report batch job (PostgreSQL to S3 or local files)" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="MIT"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY report.py ./report.py

USER 10001:10001

# A job has no ports and no health endpoint; the scheduler watches the exit code (0 / 1 / 2).
ENTRYPOINT ["python", "/app/report.py"]
