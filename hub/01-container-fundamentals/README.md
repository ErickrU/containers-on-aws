# 01 · Container fundamentals

Everything in this repository ends as a Linux process started from an image: a Fargate task, an
EKS pod, a Batch job and a Jenkins agent are all the same mechanism with different schedulers in
front of it. This domain covers that mechanism on its own, before any AWS service is layered on
top: what an image is (OCI manifests, layers, digests), how one is built well (multi-stage,
BuildKit, multi-arch for Graviton, distroless bases), what a runtime does with it (containerd,
runc, Docker Engine, the Firecracker microVMs under Fargate, Bottlerocket), what the kernel
enforces (namespaces, cgroups v2, capabilities, seccomp), why CPU throttling and OOM kills happen
the way they do, and how to trust what you run (signing, SBOMs, SLSA provenance, vulnerability
management). It is its own domain because every incident in `playbooks/incidents/` that mentions
exit code 137, `ImagePullBackOff`, `exec format error` or a slow Fargate start is explained here,
not in the ECS or EKS documents. Terms are defined once in the [glossary](../../GLOSSARY.md).

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 · Containers explained](L100-containers-explained.md) | Process vs VM vs container; image vs container; layers and the build cache; registries, tags and digests; Dockerfile anatomy; `docker build/run/push`; ports, volumes and environment configuration; why containers on AWS and how ECS and EKS differ in one paragraph |
| 200 | [L200 · Images, builds and registries](L200-images-builds-and-registries.md) | The OCI image and distribution specs (manifest, index, config, layers, media types, referrers); multi-stage builds for Go, Node.js and Python; BuildKit cache mounts, secrets and remote cache in ECR; `.dockerignore`; multi-arch images for Graviton; base image choice; PID 1, signals and `tini`; health checks; twelve-factor configuration; SBOM generation; image size and start-up time |
| 300 | [L300 · Runtimes and the kernel](L300-runtimes-and-the-kernel.md) | The eight namespaces; cgroups v2 files and what Docker, Kubernetes and ECS write into them; CFS quota throttling and memory accounting with the OOM killer; capabilities, seccomp, AppArmor and SELinux; the OCI runtime spec and what `runc` does step by step; containerd architecture (content store, snapshotters, shim v2, CRI plugin, `ctr`/`nerdctl`/`crictl`); how Docker Engine wraps containerd; why ECS on EC2 drives Docker Engine and EKS nodes run containerd; Firecracker microVMs under Fargate; Bottlerocket; image pull mechanics, overlayfs and SOCI lazy loading |
| 400 | [L400 · Hardening, supply chain and performance](L400-hardening-supply-chain-and-performance.md) | A threat model for images and runtimes; rootless and user namespaces; read-only root filesystems and distroless at scale; signing with Notation + AWS Signer and Sigstore cosign and verifying at admission; SLSA levels, provenance and attestations as OCI referrers; SBOM policy; the vulnerability management loop with ECR enhanced scanning; JVM, Node.js and Go container awareness; the CPU limits debate with numbers; memory limits, start-up time, ephemeral storage, ulimits and kernel tuning; Graviton and right-sizing for cost and sustainability; migration paths and failure stories |

## Components covered

- Linux process model, virtual machines vs containers, images vs containers, layers, the build
  cache, registries, tags and digests — L100
- Dockerfile instructions (`FROM`, `ARG`, `ENV`, `WORKDIR`, `COPY`, `RUN`, `USER`, `EXPOSE`,
  `ENTRYPOINT`, `CMD`, `LABEL`, `HEALTHCHECK`, `STOPSIGNAL`), exec vs shell form — L100 (anatomy),
  L200 (every instruction that matters in production)
- `docker build`, `docker run`, `docker push`, `docker inspect`, `docker history`, `docker stats`,
  ports (`-p`), volumes, bind mounts, tmpfs — L100, L200
- OCI Image Format Specification (manifest, image index, config, layers, media types,
  annotations, `subject` and artifacts), OCI Distribution Specification (`/v2/` API, referrers),
  OCI Runtime Specification (`config.json`, lifecycle, hooks) — L200 (image and distribution),
  L300 (runtime)
- Multi-stage builds, BuildKit (`# syntax`, `RUN --mount=type=cache|secret|ssh`, remote cache
  `type=registry` in ECR, `type=gha`, `type=s3`), `.dockerignore`, `COPY --link`, heredocs,
  provenance and SBOM attestations at build time — L200
- Multi-architecture images (`linux/amd64` and `linux/arm64`), `docker buildx`, QEMU vs native
  builders, cross-compiling Go, `TARGETARCH`, Graviton on Fargate, EKS and Batch — L200 (build),
  L400 (migration and price-performance)
- Base images: `scratch`, distroless (`static`, `base`, `cc`, language variants), Alpine and
  musl, Debian slim, Ubuntu, Amazon Linux 2023 minimal, Chainguard; the Bottlerocket admin
  container as a host tool — L200 (choice), L400 (at scale)
- PID 1, signal handling, zombie reaping, `tini`, Docker `--init`, ECS
  `linuxParameters.initProcessEnabled`, Kubernetes `shareProcessNamespace`, `STOPSIGNAL`,
  `docker stop` grace period — L200
- Health checks: Dockerfile `HEALTHCHECK` vs ECS `healthCheck` vs Kubernetes probes — L200
- Twelve-factor configuration, `ENV` vs `ARG`, secrets never in layers — L200, L400
- SBOMs: syft, `docker buildx build --sbom`, Trivy, SPDX and CycloneDX — L200 (generation), L400
  (policy and querying)
- Namespaces: pid, net, mnt, uts, ipc, user, cgroup, time; `unshare`, `nsenter`, `lsns`,
  `/proc/<pid>/ns` — L300
- cgroups v2: `cpu.max`, `cpu.weight`, `cpu.stat`, `memory.max`, `memory.high`,
  `memory.current`, `memory.stat`, `memory.events`, `pids.max`, `io.max`, PSI files; how `docker
  run` flags, Kubernetes requests/limits and ECS `cpu`/`memory` map to them; the systemd cgroup
  driver and cgroup paths — L300
- CFS bandwidth control (period, quota, throttling, burst), `cpuset` and the static CPU manager
  policy; memory accounting (anon, file, shmem, kernel), working set, the OOM killer,
  `memory.oom.group`, exit codes 137/139/143 — L300 (mechanism), L400 (tuning debate)
- Capabilities (bounding, permitted, effective sets; the Docker default set; `capsh`), seccomp
  (Docker default profile, `RuntimeDefault`), AppArmor and SELinux on AL2023, Bottlerocket,
  Debian and Ubuntu hosts — L300
- `runc` and alternative runtimes (crun, youki, gVisor, Kata); the container creation sequence
  (clone, cgroups, `pivot_root`, masked paths, capabilities, seccomp, `execve`) — L300
- containerd: daemon, gRPC API, containerd namespaces (`moby`, `k8s.io`), content store,
  metadata, snapshotters (overlayfs, proxy plugins), shim v2, the CRI plugin, `config.toml`
  versions 2 and 3, `ctr`, `nerdctl`, `crictl` — L300
- Docker Engine: `dockerd`, image store (`overlay2` graphdriver vs containerd image store),
  networking, logging drivers, `HEALTHCHECK` execution, the Docker API — L300
- Why ECS on EC2 uses Docker Engine through the ECS agent and EKS nodes use containerd
  (dockershim removed in Kubernetes 1.24); Bottlerocket ECS and Kubernetes variants — L300
- Firecracker microVMs under Fargate (one microVM per task, platform versions, what a task
  cannot do and why) — L300 (mechanics), L400 (isolation trade-offs)
- Bottlerocket: image-based OS, A/B partitions, dm-verity, SELinux enforcing, API-driven
  settings, admin and control containers, updates; the node OS of EKS Auto Mode — L300
- Image pull mechanics: token, manifest, config, layers, digest verification, decompression
  (gzip vs zstd), overlayfs snapshots, whiteouts, kubelet and containerd parallelism, image
  garbage collection — L300; lazy loading with SOCI (zTOC, index as referrer, soci-snapshotter,
  Fargate automatic use, parallel pull mode) — L300
- Threat model (escape, supply chain, secrets in layers, mutable tags, credential theft) — L400
- Rootless Docker and containerd, `userns-remap`, Kubernetes user namespaces (`hostUsers`) — L400
- Image signing and verification: Notation with AWS Signer (profiles, trust policies,
  revocation), Sigstore cosign (KMS keys, keyless with Fulcio and Rekor), signatures as OCI
  referrers, Kyverno `verifyImages`, Ratify with Gatekeeper, ECS pipeline and lifecycle-hook
  verification — L400 (mechanics); registry-side operation in [02 · L400](../02-ecr/L400-supply-chain-and-multi-account-registries.md)
- SLSA v1.0 build levels, in-toto provenance, BuildKit `--provenance`, GitHub artifact
  attestations, verification tools — L400
- Vulnerability management: ECR basic vs enhanced scanning (Amazon Inspector), continuous
  rescans, EventBridge and Security Hub, severity SLAs, base image freshness, exceptions — L400
- Runtime container awareness (JVM `MaxRAMPercentage`, Node.js `--max-old-space-size`, Go
  `GOMAXPROCS` and `GOMEMLIMIT`, Python worker counts), the CPU limits debate, memory limits,
  start-up time budgets, ephemeral storage, ulimits, `sysctls`, network and EBS baselines — L400
- Sustainability: Graviton, right-sizing, consolidation, image diet — L400
- The Well-Architected Container Build Lens applied to image builds — every level, §5

## Related

- Labs: the four Dockerfiles this domain dissects are [`labs/apps/catalog/`](../../labs/apps/catalog/)
  (Go, `gcr.io/distroless/static-debian12:nonroot`), [`labs/apps/orders/`](../../labs/apps/orders/)
  (`node:22-bookworm-slim`), [`labs/apps/worker/Dockerfile`](../../labs/apps/worker/Dockerfile) and
  [`labs/apps/report-job/Dockerfile`](../../labs/apps/report-job/Dockerfile) (`python:3.12-slim-bookworm`,
  virtual environment in `/opt/venv`). Image rules (non-root `10001`, read-only root filesystem,
  pinned bases, labels, `sha-<gitsha>` tags, deploy by digest) are [`labs/CONTRACT.md`](../../labs/CONTRACT.md) §8;
  the hardening flags applied at run time are in [`labs/local/compose.yaml`](../../labs/local/compose.yaml);
  the multi-arch build, scan, SBOM and signing pipeline is
  [`labs/pipelines/github-actions/ci.yml`](../../labs/pipelines/github-actions/ci.yml).
- Playbooks: [image pull failures](../../playbooks/incidents/image-pull-failures.md),
  [CrashLoopBackOff and exit codes](../../playbooks/incidents/crashloop-and-exit-codes.md),
  [OOM and CPU throttling](../../playbooks/incidents/oom-and-cpu-throttling.md),
  [node NotReady](../../playbooks/incidents/node-not-ready.md),
  [ECS task stopped reasons](../../playbooks/incidents/ecs-task-stopped-reasons.md),
  [ECS AMI, agent and platform upgrades](../../playbooks/upgrades/ecs-ami-agent-and-platform.md),
  [EKS version upgrade](../../playbooks/upgrades/eks-version-upgrade.md).
- Reference: [metrics catalog](../../reference/metrics-catalog.md),
  [CLI cheat sheet](../../reference/cli-cheatsheet.md) (`docker`, `ctr`, `nerdctl`, `crictl`),
  [decision guides](../../reference/decision-guides.md),
  [quotas and limits](../../reference/quotas-and-limits.md),
  [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md).
- Neighbouring domains: the registry side of pulls, caching, replication and scanning in
  [02 · Amazon ECR](../02-ecr/README.md); task definition fields, the ECS agent and Fargate
  platform versions in [03 · Amazon ECS](../03-ecs/README.md); kubelet, containerd on nodes,
  Auto Mode and upgrades in [04 · Amazon EKS](../04-eks/README.md); Pod Security Standards,
  `securityContext`, admission engines and GuardDuty Runtime Monitoring in
  [06 · Identity and security](../06-identity-and-security/README.md); the metrics behind
  throttling and OOM alarms in [07 · Observability](../07-observability/README.md); pipelines that
  build, scan and sign in [08 · Delivery](../08-delivery-cicd-gitops/README.md); the Container
  Build Lens and trade-off records in [12 · Well-Architected](../12-well-architected/README.md).
- Time-sensitive facts (Kubernetes and EKS versions, AMI end-of-support dates, Fargate platform
  version, Auto Mode node behaviour) are pinned in [`docs/FACTS-2026-09.md`](../../docs/FACTS-2026-09.md).
