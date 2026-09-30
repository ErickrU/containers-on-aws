# Container fundamentals · L100 — Containers explained

**Level:** 100 · **Time:** ~40 min · **Prerequisites:** none; Docker Engine or Colima on your machine and `make up` from the repository root working ([labs/README.md](../../labs/README.md))

**After this document you can:**

- explain, in one sentence each, what separates a process, a virtual machine and a container,
  and what separates an image from a container
- read a Dockerfile, predict which layers it produces and why the build cache hits or misses
- build, run, inspect and push one of the `shopfront` images, and read its name, tag and digest
- publish a port, mount a volume and configure a container through environment variables
- say why containers are the default packaging unit on AWS and place ECS and EKS in one paragraph

## 1. Mental model

```mermaid
flowchart LR
  df[Dockerfile + source] -->|docker build| img["Image<br/>config + ordered layers<br/>addressed by sha256 digest"]
  img -->|docker push| reg["Registry (Amazon ECR)<br/>123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/catalog"]
  reg -->|pull| rt["Runtime on a Linux host<br/>Docker Engine · containerd · Fargate microVM"]
  rt -->|start| c1["Container = process tree<br/>own view of pids, network, filesystem<br/>bounded CPU and memory"]
  rt -->|start| c2[another container, same image]
  kern[shared Linux kernel] --- c1
  kern --- c2
```

A container is an ordinary Linux process (or a small tree of them) that the kernel has been told
to lie to: it sees its own process IDs, its own network interfaces, its own root filesystem and a
CPU and memory budget, while sharing the host kernel with everything else. An image is the frozen
filesystem and the start command that process is launched from, packaged as a stack of read-only
layers and named by the hash of its contents. The problem containers solve is not isolation, which
virtual machines did first and stronger; it is packaging: one artifact that carries the
application, its runtime and its libraries, builds the same everywhere, starts in under a second
and is identified by a digest that nobody can quietly change. AWS builds schedulers around that
artifact: ECS and EKS decide where and when the process runs; the artifact and the process are
what this domain is about.

## 2. Concepts

### 2.1 Process, virtual machine, container

| | Process on a host | Virtual machine | Container |
| --- | --- | --- | --- |
| What is isolated | nothing beyond Unix permissions | a whole machine: virtual CPUs, memory, devices, its own kernel | the process's *view* of the system: pids, mounts, network, hostname, IPC, users; its resources are metered by cgroups |
| Kernel | host kernel | guest kernel per VM | host kernel, shared |
| Start time | milliseconds | tens of seconds (a Firecracker microVM: about 125 ms, see L300) | milliseconds after the image is on disk |
| Density | high | tens per host | hundreds per host |
| You patch | the application and the host OS | the guest OS in every image and the hypervisor | the image (base OS packages plus your code) and the host kernel |
| On AWS | EC2 instance | EC2 instance, Firecracker microVM under Fargate | ECS task, EKS pod, Batch job |

Two consequences drive most of the later material. Because the kernel is shared, a container is
only as isolated as the kernel features that confine it (L300 §2.1–2.6), which is why Fargate
adds a microVM per task (L300 §2.12). Because the image carries the OS userland, "patching the
OS" means rebuilding and redeploying the image, not logging into a machine (L400 §2.7).

### 2.2 Image vs container

An image is immutable: a JSON *config* (the command, environment, working directory, user,
exposed ports, labels) plus an ordered list of *layers*, each a compressed tar archive of
filesystem changes, all referenced by SHA-256 digest from a *manifest*. A container is one running
(or stopped) instance: the image's layers stacked read-only, a thin writable layer on top, a
process started from the config. Delete the container and the writable layer goes with it; the
image is untouched. Start the image twice and you have two containers that share every read-only
byte on disk.

```bash
docker images                       # images on this machine: repository, tag, image id, size
docker ps -a                        # containers, running and exited, with their exit codes
docker inspect shopfront/catalog:dev --format '{{.Config.User}} {{.Config.Cmd}} {{.RootFS.Layers | len}} layers'
```

### 2.3 Layers and the build cache

Every `FROM`, `RUN`, `COPY` and `ADD` instruction produces a layer; the other instructions only
change the config. Layers are content-addressed, so a layer whose inputs did not change is
reused from the cache and, in a registry, shared between images and between builds. The rule that
follows: order instructions from least to most frequently changing. Copy the dependency manifest
and install dependencies before copying the source, so that editing one file rebuilds one layer
instead of re-downloading every package. `docker history` shows the layers and which
instruction created each:

```bash
docker history shopfront/worker:dev
# IMAGE          CREATED BY                                      SIZE
# <missing>      COPY worker/ ./worker/ # buildkit                58kB
# <missing>      COPY /opt/venv /opt/venv # buildkit              41MB
# <missing>      RUN groupadd --system --gid 10001 app && ...     2kB
# ...
```

A file deleted in a later layer still exists in the earlier one, and anyone who pulls the image
can read it. That is the reason secrets never go into a build step (L200 §2.9, L400 §2.1).

### 2.4 Registries, names, tags and digests

A registry stores images and serves them over HTTPS with a small standard API (L200 §2.2). A full
image reference is `registry/repository:tag@sha256:digest`:

```text
123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/catalog:sha-3f2a9c1@sha256:6c3a1f0e9b7d2c4a5e8f1b3d7c9e2a4f6b8d0c1e3a5f7b9d2c4e6a8f0b1d3c5e
```

A *tag* is a mutable pointer that anyone with push rights can move; `latest` is a tag like any
other, with the extra trap that it is what you get when you name no tag. A *digest* is the hash of
the manifest and cannot change. `shopfront` therefore tags each build `sha-<gitsha>` and deploys
by digest ([contract §8](../../labs/CONTRACT.md)). When you omit the registry, Docker assumes
Docker Hub (`docker.io/library/…`), which is rate-limited for anonymous pulls; on AWS the registry
is Amazon ECR, covered in [02 · L100](../02-ecr/L100-ecr-basics.md).

### 2.5 Dockerfile anatomy

The [`report-job` Dockerfile](../../labs/apps/report-job/Dockerfile) is small enough to read
whole. Annotated, with the lines that matter:

```dockerfile
# syntax=docker/dockerfile:1                     # use the current BuildKit Dockerfile frontend
ARG PYTHON_IMAGE=python:3.12-slim-bookworm      # build-time variable, overridable with --build-arg

FROM ${PYTHON_IMAGE} AS builder                 # stage 1: has pip, compilers, caches
RUN python -m venv /opt/venv                    # one layer: create the virtual environment
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY requirements.txt ./                        # dependencies first: this layer changes rarely
RUN pip install --no-cache-dir -r requirements.txt

FROM ${PYTHON_IMAGE} AS runtime                 # stage 2: a fresh base, nothing from stage 1 unless copied
LABEL org.opencontainers.image.source="https://github.com/ErickrU/containers-on-aws"
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 HOME=/tmp
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv         # only the installed packages cross over
COPY report.py ./report.py                      # source last: this layer changes on every commit
USER 10001:10001                                # every later instruction and the process run unprivileged
ENTRYPOINT ["python", "/app/report.py"]         # exec form: python is PID 1 and receives signals
```

| Instruction | Effect | Layer? | Beginner rule |
| --- | --- | --- | --- |
| `FROM` | base image, or start of a new stage | yes (the base's layers) | pin a tag such as `python:3.12-slim-bookworm`; never bare `python` |
| `ARG` | build-time variable | no | not for secrets; values end up in `docker history` |
| `ENV` | environment for the build and the running container | no | defaults only; real configuration comes from the platform at run time |
| `WORKDIR` | working directory (created if missing) | no | use it instead of `RUN cd` |
| `COPY` / `ADD` | files from the build context (or another stage) into the image | yes | `COPY`; `ADD` only for the tar-extraction and checksum features |
| `RUN` | executes a command in a temporary container, keeps the filesystem result | yes | chain related commands with `&&`; clean caches in the same `RUN` |
| `USER` | uid (and gid) for later instructions and the process | no | a fixed numeric uid (`10001:10001`) so the platform can verify it |
| `EXPOSE` | documents a port | no | it publishes nothing; `-p` and the orchestrator do |
| `ENTRYPOINT` / `CMD` | the process to start; `CMD` supplies default arguments to `ENTRYPOINT`, or the whole command when there is no `ENTRYPOINT` | no | exec (JSON array) form so the process is PID 1 and sees SIGTERM |
| `LABEL` | metadata in the config | no | `org.opencontainers.image.*` keys: source, version, revision |
| `HEALTHCHECK` | a command Docker runs periodically | no | leave it out when ECS or Kubernetes probe the container (L200 §2.8) |

`ENTRYPOINT` in exec form plus `CMD` for arguments is the shape to remember. The shell form
(`CMD python app.py`) wraps the command in `/bin/sh -c`, so the shell is PID 1 and, in many
shells, SIGTERM never reaches Python; the container is then killed after the grace period instead
of shutting down cleanly (L200 §2.7).

### 2.6 Build, run, push

```bash
docker build -t shopfront/report-job:dev labs/apps/report-job         # context = that directory
docker run --rm -e DATABASE_URL=postgres://app:app@localhost:5432/shopfront \
  -e REPORT_OUTPUT=file:///tmp -e AWS_REGION=us-east-1 shopfront/report-job:dev
docker tag shopfront/report-job:dev 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/report-job:sha-3f2a9c1
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/report-job:sha-3f2a9c1
```

`docker build` sends the *build context* (the directory you name, minus `.dockerignore` matches)
to the builder; `COPY` can only see files inside it. `docker run` creates and starts a container;
`--rm` deletes it on exit, `-e` sets environment variables, `-d` detaches, `-p` publishes ports,
`-v` mounts storage. `docker push` uploads the layers the registry does not already have, then the
manifest. Authentication to ECR is an IAM exchange, not a password
([02 · L100 §2.3](../02-ecr/L100-ecr-basics.md)).

### 2.7 Ports and volumes

A container has its own network namespace, so a process listening on `:8081` inside is not
reachable from the host until you publish the port: `-p 8081:8081` maps host port 8081 to
container port 8081. `EXPOSE 8081` in the Dockerfile is documentation for tools; it opens
nothing. On ECS and EKS the equivalent is `portMappings` and `containerPort`, and traffic usually
arrives through a load balancer ([05 · L100](../05-networking/L100-vpc-for-containers.md)).

Everything a container writes goes into its writable layer and disappears with the container.
Persistent or shared data therefore lives outside it:

| Mount | `docker run` flag | What it is | Typical use |
| --- | --- | --- | --- |
| Named volume | `-v postgres-data:/var/lib/postgresql/data` | Docker-managed directory that outlives containers | the local PostgreSQL in [`compose.yaml`](../../labs/local/compose.yaml) |
| Bind mount | `-v ./schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro` | a host path mapped into the container | configuration files, local development |
| tmpfs | `--tmpfs /tmp` | memory-backed, gone at exit | scratch space for a container whose root filesystem is read-only |

The `shopfront` services run with `--read-only` and a tmpfs `/tmp`, so the only writable place
is memory. On AWS the same roles are played by EFS and EBS volumes, ephemeral task storage and
`emptyDir` ([03 · L200](../03-ecs/L200-task-definitions-services-and-scaling.md),
[04 · L200](../04-eks/L200-cluster-components-and-add-ons.md)).

### 2.8 Configuration through the environment

The image is built once and runs in every environment, so nothing environment-specific is baked
in. `shopfront` reads everything from environment variables listed in
[`labs/CONTRACT.md` §2](../../labs/CONTRACT.md): `DATABASE_URL`, `CATALOG_URL`, `SQS_QUEUE_URL`,
`OTEL_EXPORTER_OTLP_ENDPOINT`. Locally Compose sets them; on ECS the task definition does; on
EKS a ConfigMap does. Secrets travel the same way but come from Secrets Manager or SSM at start
time, never from the image or a plain task definition
([06 · L100](../06-identity-and-security/L100-security-basics-for-containers.md)).

### 2.9 Why containers on AWS, and ECS or EKS in one paragraph

Containers give AWS compute a common unit: the same image runs on an EC2 instance you manage, on
Fargate where AWS manages the host, in AWS Batch for jobs and even in Lambda. Deployments become
"run digest X with N copies", rollbacks become "run the previous digest", and the platform can
pack many services onto shared hosts, start replacements in seconds and bill for what runs.

You still need a scheduler that decides where the copies run, replaces failed ones, wires load
balancers and hands out IAM credentials. Amazon ECS is the AWS-native one: tasks and services
described in AWS APIs, simple to operate, with Fargate as the default capacity and the smallest
surface to learn ([03 · L100](../03-ecs/L100-ecs-basics.md)). Amazon EKS is managed Kubernetes:
the same API and ecosystem as every other Kubernetes cluster, far more extensible and far more to
operate, with EKS Auto Mode taking over the node layer
([04 · L100](../04-eks/L100-kubernetes-and-eks-basics.md)). Both run the images this domain
teaches you to build; the choice is about your team and portability needs, and the
[decision guide](../../reference/decision-guides.md) lays it out.

## 3. How it interacts with the rest of AWS

| Component | Talks to | Protocol/API | Prerequisite (IAM, network, DNS) | What breaks if missing |
| --- | --- | --- | --- | --- |
| `docker` CLI | Docker Engine (`dockerd`) | Unix socket `/var/run/docker.sock`, REST API | user in the `docker` group, or Docker Desktop/Colima running | `Cannot connect to the Docker daemon` |
| Docker Engine / BuildKit | base image registry (Docker Hub, ECR Public, ECR) | HTTPS 443, OCI distribution API | internet or VPC endpoints; credentials for private registries | `pull access denied`, `toomanyrequests` from Docker Hub |
| Developer or CI runner | Amazon ECR | `ecr:GetAuthorizationToken`, push actions | IAM identity with push rights on `shopfront/*` | `no basic auth credentials`, `denied` |
| ECS agent / Fargate | Amazon ECR | pull actions with the task **execution role** | execution role policy, route to ECR and S3 | `CannotPullContainerError` |
| EKS node (kubelet + containerd) | Amazon ECR | pull actions with the **node role** | node role with `AmazonEC2ContainerRegistryPullOnly` | `ImagePullBackOff` |
| Running container | CloudWatch Logs | `awslogs` log driver or Fluent Bit | execution role or node role with `logs:PutLogEvents` | the container starts but no logs appear, or fails to start when the driver cannot connect |
| Running container | other AWS services | SDK calls with task role / pod role credentials | task role, IRSA or Pod Identity | `AccessDenied`, or the node role being used by accident |

Three interactions surprise beginners. The image is pulled by the platform's identity (execution
role on ECS, node role on EKS), not by the identity your application uses at run time. Layers are
downloaded from S3 through presigned URLs, so a private subnet needs an S3 route even with ECR
endpoints. And `docker build` on an Apple Silicon or Graviton machine produces an `arm64` image by
default, which an `amd64` Fargate task refuses with `exec format error` (L200 §2.5).

## 4. Use it when / avoid it when

Use containers when:

- a service has runtime dependencies (interpreters, native libraries, CA bundles) that must
  ship with the code, and it should run identically on a laptop, in CI and on AWS
- you want fast, repeatable deployments and rollbacks by digest, and many services on shared
  capacity
- you need a portable unit across ECS, EKS, Batch and your local machine

Avoid, or look elsewhere, when:

- the workload is a short, event-driven function with no long-lived process: Lambda (which can
  also run container images, at a different cost and start-up model)
- you need a custom kernel, kernel modules or hardware pass-through the platform forbids:
  EC2 with an AMI
- the "container" would be a full OS with several daemons, SSH and cron: that is a VM, and
  packing it into an image inherits every drawback of both

Alternatives, one line each:

- AWS Lambda — per-invocation billing and scaling, 15-minute limit, cold starts
- EC2 with a baked AMI — full control of kernel and OS, slower deployments, you patch hosts
- AWS App Runner — containers with the least operations, the least control
- Unikernels and WebAssembly runtimes — smaller and faster to start, immature ecosystem on AWS

## 5. Well-Architected view

| Pillar | What containers give you | What it costs you | Practice |
| --- | --- | --- | --- |
| Operational Excellence | one artifact for every environment; rollbacks by digest | a build pipeline and a registry to operate | Dockerfile in the repository, `sha-<gitsha>` tags, `make check` on every change |
| Security | a small, rebuilt-often userland; a non-root process by default if you say so | secrets in layers, `latest` tags, root processes if you do nothing | `USER 10001`, pinned bases, secrets from the platform, scanning in ECR |
| Reliability | fast restarts and replacements; identical copies | shared kernel: one noisy container can affect neighbours without limits | set CPU and memory budgets; health endpoints; graceful shutdown |
| Performance Efficiency | millisecond start once the image is local | image pull and unpack before the first request | small images, multi-stage builds (L200) |
| Cost Optimization | dense packing, pay for what runs | forgotten images, oversized reservations | lifecycle rules in ECR, right-size requests (L400) |
| Sustainability | higher utilisation per host | idle replicas still burn energy | scale to demand, Graviton (`arm64`) images |

The [Container Build Lens](https://docs.aws.amazon.com/wellarchitected/latest/container-build-lens/container-build-lens.html)
applies the six pillars to image building; [12 · L100](../12-well-architected/L100-pillars-for-containers.md)
introduces how a review works.

## 6. Failure modes and troubleshooting

| Symptom | Likely cause | How to confirm (command/metric) | Fix |
| --- | --- | --- | --- |
| `exec /app/catalog: exec format error` | image built for `arm64` runs on `amd64` (or the reverse) | `docker inspect <image> --format '{{.Os}}/{{.Architecture}}'` vs the host | build with `--platform linux/amd64,linux/arm64` (L200 §2.5) |
| Container exits immediately with code 0 | `CMD` ran a command that finishes (a shell, a one-off script) | `docker ps -a`, `docker logs <id>` | make the entrypoint the long-running server; jobs are supposed to exit |
| `permission denied` writing to `/app` or `$HOME` | process runs as `10001` and the directory is root-owned, or the root filesystem is read-only | `docker run --rm <image> id`; `docker inspect --format '{{.HostConfig.ReadonlyRootfs}}'` | write to `/tmp` (tmpfs) or a volume; set `HOME=/tmp` as the lab Dockerfiles do |
| `bind: address already in use` | another process or container publishes the same host port | `docker ps --format '{{.Names}} {{.Ports}}'`; `lsof -i :8081` | change the host side of `-p`; stop the other container |
| `COPY failed: file not found in build context` | the file is outside the context directory or excluded by `.dockerignore` | `docker build` context path; `cat .dockerignore` | run the build with the right context; adjust `.dockerignore` |
| Every code change rebuilds all dependencies | `COPY . .` before the dependency install | `docker history` shows one huge layer changing | copy manifests first, install, then copy source (§2.3) |
| `toomanyrequests: You have reached your pull rate limit` | anonymous Docker Hub pulls from CI or a NAT gateway | error text names `docker.io` | pull through ECR ([02 · L300](../02-ecr/L300-pull-through-cache-replication-and-limits.md)) |
| `no space left on device` on the build machine | dangling images and build cache | `docker system df` | `docker system prune`; `docker buildx prune` |
| Container killed after 10 s on `docker stop` | shell-form `CMD`, or the process ignores SIGTERM | `docker inspect --format '{{.Config.Cmd}}'` shows `/bin/sh -c` | exec form; handle SIGTERM (L200 §2.7) |
| Pod in `CrashLoopBackOff` / ECS task stops with exit code 1 | the process fails at start (missing environment variable, unreachable dependency) | `kubectl logs --previous`, `aws ecs describe-tasks … stoppedReason` | see [crashloop and exit codes](../../playbooks/incidents/crashloop-and-exit-codes.md) |

## 7. Signals: metrics, logs, traces

At this level the signals are the ones `docker` shows you, and their platform equivalents:

- CPU and memory per container: `docker stats` locally; on AWS, Container Insights
  `CpuUtilized`/`MemoryUtilized` (ECS) and `pod_cpu_utilization`/`pod_memory_working_set`
  (EKS). A container pinned at its memory limit is about to be OOM-killed (exit 137).
- Exit code and restart count: `docker ps -a`, `kubectl get pods` (`RESTARTS`), ECS
  `stoppedReason`. Non-zero exits and rising restarts are the first thing to look at.
- Image size: `docker images` (uncompressed on disk) and ECR `imageSizeInBytes` (compressed).
  Size sets the pull time, which sets how fast a service can scale out.
- Logs: one JSON line per event on stdout, which `docker logs`, `awslogs` and Fluent Bit all
  pick up without configuration inside the image; never write logs to files in the container.
- Health endpoints `/healthz` and `/readyz` ([contract §3](../../labs/CONTRACT.md)) are the
  signal the platform uses to decide between "restart" and "stop sending traffic".

The full table with sources and thresholds is [reference/metrics-catalog.md](../../reference/metrics-catalog.md);
the observability tooling on AWS is [07 · L100](../07-observability/L100-observability-basics.md).

## 8. Testing and DR notes

Testing an image means testing the artifact, not the source: build it, start it with the
environment the contract requires, hit `/healthz` and `/readyz`, run one business request, stop
it with SIGTERM and check the exit code is 0 within the shutdown budget. `make smoke` does this for
the whole system ([`labs/local/smoke.sh`](../../labs/local/smoke.sh)); a Dockerfile linter
(`hadolint`) and a container structure test (which user, which files, which ports) catch the rest
before a pipeline pushes anything ([11 · L100](../11-testing-workloads/L100-testing-basics.md)).

Disaster recovery for this layer is short: a container holds no state worth recovering. The
artifact does. An image can be rebuilt from the Dockerfile, the source and the pinned base image,
but a rebuild is rarely byte-identical, so the pushed image (its digest) is the thing to keep, in
a registry that is replicated where you need to recover
([02 · L300](../02-ecr/L300-pull-through-cache-replication-and-limits.md)). Everything else the
process needs (the database, the queue, secrets) belongs to the managed services around it, and
the DR posture for those is [10 · L100](../10-resilience-and-dr/L100-resilience-basics.md).

## 9. Hands-on

From the repository root, with Docker running:

```bash
make up                                                   # builds the five images, starts the system
docker images 'shopfront/*'                               # five images; note the sizes
docker history shopfront/worker:dev                       # layers, in reverse order of the Dockerfile
docker inspect shopfront/worker:dev --format '{{.Config.User}} {{json .Config.Cmd}} {{.Architecture}}'
docker compose -f labs/local/compose.yaml exec fulfillment-worker id       # uid=10001 gid=10001
docker compose -f labs/local/compose.yaml exec fulfillment-worker touch /app/x   # read-only root: fails
curl -s localhost:8082/healthz                            # {"status":"ok"}
docker compose -f labs/local/compose.yaml stop fulfillment-worker          # SIGTERM, exit 0 within 20 s
docker compose -f labs/local/compose.yaml ps -a --format '{{.Name}} {{.ExitCode}}'
docker compose -f labs/local/compose.yaml up -d fulfillment-worker
make report && ls labs/local/out                          # a run-to-completion container: exits when done
docker buildx build --platform linux/amd64,linux/arm64 -t shopfront/worker:multi labs/apps/worker
make down
```

Observe: `docker history` lists the `COPY worker/` layer above the `COPY /opt/venv` layer because
the Dockerfile copies dependencies first; `id` prints `uid=10001`; `touch` fails with
`Read-only file system`; the stopped worker's exit code is `0`; the multi-arch build produces two
platform manifests under one name (inspect them in L200 §9). Pushing to ECR is the hands-on of
[02 · L100 §9](../02-ecr/L100-ecr-basics.md).

## 10. Check yourself

1. A colleague says "the container has its own kernel, that is why it is secure." What is
   right and what is wrong in that sentence?

<details><summary>Answer</summary>
Wrong: containers share the host kernel; only their view of processes, mounts, network and
users is separated, and cgroups meter their resources. A VM (or a Firecracker microVM under
Fargate) has its own kernel. Right: the isolation features are kernel features, so a kernel bug
is a container-escape bug, which is why hardening (L300, L400) matters.
</details>

2. You edit one line of `report.py` and the rebuild re-installs every Python package. Why, and
   how do you fix the Dockerfile?

<details><summary>Answer</summary>
The source is copied before (or together with) the dependency install, so the changed layer
invalidates every layer after it. Copy <code>requirements.txt</code>, run <code>pip install</code>,
then copy the source, as <code>labs/apps/report-job/Dockerfile</code> does.
</details>

3. Two tasks started a minute apart run different code although both use
   `shopfront/orders:latest`. What happened?

<details><summary>Answer</summary>
<code>latest</code> is a mutable tag; CI moved it between the two pulls. Deploy by digest or by an
immutable <code>sha-&lt;gitsha&gt;</code> tag so every copy resolves to the same manifest.
</details>

4. `docker stop` takes ten seconds and the service logs no shutdown message. What is the most
   likely cause?

<details><summary>Answer</summary>
A shell-form <code>CMD</code> (or <code>ENTRYPOINT</code>): <code>/bin/sh -c</code> is PID 1 and
does not forward SIGTERM, so Docker waits for the grace period and sends SIGKILL. Use the exec
form and handle SIGTERM in the application.
</details>

5. Which identity pulls the `shopfront/catalog` image for a Fargate task, and which identity
   does the running catalog process use to call AWS?

<details><summary>Answer</summary>
The task <strong>execution role</strong> pulls the image (and fetches secrets and writes logs);
the <strong>task role</strong> is what the application's SDK uses. A pull failure after a role
change is an execution-role problem.
</details>

## 11. Sources

- Docker Docs: What is a container? — https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/
- Docker Docs: Dockerfile reference — https://docs.docker.com/reference/dockerfile/
- Docker Docs: Build context and `.dockerignore` — https://docs.docker.com/build/concepts/context/
- Docker Docs: Docker Hub usage and rate limits — https://docs.docker.com/docker-hub/usage/
- OCI Image Format Specification — https://github.com/opencontainers/image-spec/blob/main/spec.md
- OCI Distribution Specification — https://github.com/opencontainers/distribution-spec/blob/main/spec.md
- The Twelve-Factor App: Config — https://12factor.net/config
- Amazon ECR User Guide: Private registry authentication — https://docs.aws.amazon.com/AmazonECR/latest/userguide/registry_auth.html
- Amazon ECS Developer Guide: What is Amazon ECS? — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html
- Amazon EKS User Guide: What is Amazon EKS? — https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html
- Firecracker: Getting started (microVM boot characteristics) — https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md
- AWS Well-Architected Container Build Lens — https://docs.aws.amazon.com/wellarchitected/latest/container-build-lens/container-build-lens.html
