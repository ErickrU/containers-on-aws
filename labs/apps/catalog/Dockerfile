# syntax=docker/dockerfile:1
# shopfront/catalog - Go products API with Valkey cache-aside (labs/CONTRACT.md).
#
# Build:      docker build -t shopfront/catalog:dev .
# Multi-arch: docker buildx build --platform linux/amd64,linux/arm64 \
#               --build-arg VERSION=sha-<gitsha> --build-arg REVISION=<gitsha> \
#               -t <registry>/shopfront/catalog:sha-<gitsha> --push .
#
# Base images pinned by tag; manifest-list digests verified 2026-09-30 (docker buildx imagetools inspect):
#   golang:1.23-bookworm                      sha256:167053a2bb901972bf2c1611f8f52c44d5fe7e762e5cab213708d82c421614db
#   gcr.io/distroless/static-debian12:nonroot sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab

ARG GO_IMAGE=golang:1.23-bookworm
ARG RUNTIME_IMAGE=gcr.io/distroless/static-debian12:nonroot

# ---- build: runs on the build platform and cross-compiles for the target platform --------------
FROM --platform=$BUILDPLATFORM ${GO_IMAGE} AS build

ARG TARGETOS TARGETARCH
ARG VERSION=dev
# "|" (not ",") falls back to fetching from the VCS on any proxy error, including networks where
# proxy.golang.org is unreachable. Checksums are still verified against go.sum.
ARG GOPROXY="https://proxy.golang.org|direct"
ENV GOPROXY=${GOPROXY}

WORKDIR /src

# Dependencies first so they are cached until go.mod/go.sum change.
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/catalog .

# ---- runtime: static binary only, no shell, no package manager, non-root ------------------------
FROM ${RUNTIME_IMAGE}

ARG VERSION=dev
ARG REVISION=unknown
ARG SOURCE=https://github.com/ErickrU/containers-on-aws
LABEL org.opencontainers.image.title="shopfront/catalog" \
      org.opencontainers.image.description="shopfront products API (Go, PostgreSQL, Valkey cache-aside)" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY --from=build /out/catalog /app/catalog

# Fixed unprivileged uid/gid so Kubernetes runAsNonRoot and ECS user: "10001" line up with the image.
USER 10001:10001
EXPOSE 8081

# No HEALTHCHECK instruction on purpose: ECS and Kubernetes probe /healthz and /readyz themselves.
ENTRYPOINT ["/app/catalog"]
