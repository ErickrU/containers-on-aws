# syntax=docker/dockerfile:1
# shopfront/orders - Node.js 22 / TypeScript / Fastify orders API (labs/CONTRACT.md).
#
# Build:      docker build -t shopfront/orders:dev .
# Multi-arch: docker buildx build --platform linux/amd64,linux/arm64 \
#               --build-arg VERSION=sha-<gitsha> --build-arg REVISION=<gitsha> \
#               -t <registry>/shopfront/orders:sha-<gitsha> --push .
#
# Base image pinned by tag; manifest-list digest verified 2026-09-30 (docker buildx imagetools inspect):
#   node:22-bookworm-slim  sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c

ARG NODE_IMAGE=node:22-bookworm-slim

# ---- build: compile TypeScript, then keep only production dependencies ---------------------------
FROM ${NODE_IMAGE} AS build

ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

WORKDIR /build

# Dependencies first so they are cached until the lockfile changes.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY tsconfig.json ./
COPY src ./src
RUN npm run build \
 && rm -rf node_modules \
 && npm ci --omit=dev

# ---- runtime: same base, production dependencies and compiled JavaScript only --------------------
FROM ${NODE_IMAGE}

ARG VERSION=dev
ARG REVISION=unknown
ARG SOURCE=https://github.com/ErickrU/containers-on-aws
LABEL org.opencontainers.image.title="shopfront/orders" \
      org.opencontainers.image.description="shopfront orders API (Node.js 22, Fastify, PostgreSQL, SQS, Kafka)" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="MIT"

ENV NODE_ENV=production \
    HOME=/tmp

# Fixed unprivileged uid/gid so Kubernetes runAsNonRoot and ECS user: "10001" line up with the image.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app

WORKDIR /app
# Files stay owned by root and read-only for the app user; the process needs no writable path.
COPY --from=build /build/package.json ./package.json
COPY --from=build /build/node_modules ./node_modules
COPY --from=build /build/dist ./dist

USER 10001:10001
EXPOSE 8080

# No HEALTHCHECK instruction on purpose: ECS and Kubernetes probe /healthz and /readyz themselves.
ENTRYPOINT ["node", "dist/index.js"]
