# syntax=docker/dockerfile:1
# shopfront/worker - one image, two entrypoints:
#   python -m worker.fulfillment   (SQS consumer, port 8082)  <- default CMD
#   python -m worker.analytics     (Kafka consumer, port 8083)
#
# Build:  docker build -t shopfront/worker:dev .
# Multi-arch: docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/shopfront/worker:sha-<gitsha> .
#
# Base image pinned by tag; digest verified 2026-09-30:
#   python:3.12-slim-bookworm  sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ---- builder: resolve and install pinned dependencies into a relocatable venv ----------------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime: same base, no compiler, no pip cache, non-root, read-only rootfs friendly -------
FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=dev
ARG REVISION=unknown
ARG SOURCE=https://github.com/ErickrU/containers-on-aws
LABEL org.opencontainers.image.title="shopfront/worker" \
      org.opencontainers.image.description="shopfront fulfillment (SQS) and analytics (Kafka) workers" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="MIT"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

# Fixed, unprivileged uid/gid so Kubernetes runAsNonRoot and ECS user: "10001" line up with the image.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY worker/ ./worker/

USER 10001:10001
EXPOSE 8082 8083

# No HEALTHCHECK instruction on purpose: ECS and Kubernetes probe /healthz and /readyz themselves.
CMD ["python", "-m", "worker.fulfillment"]
