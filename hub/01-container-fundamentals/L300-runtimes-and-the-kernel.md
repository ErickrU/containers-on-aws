# Container fundamentals · L300 — Runtimes and the kernel

**Level:** 300 · **Time:** ~120 min · **Prerequisites:**
[L200 Images, builds and registries](L200-images-builds-and-registries.md), Linux command line,
[ECS L200](../03-ecs/L200-task-definitions-services-and-scaling.md) or
[EKS L200](../04-eks/L200-cluster-components-and-add-ons.md)

**After this document you can:**

- Name the kernel features a container is made of and inspect each one on a running process.
- Draw the process tree from Docker Engine or kubelet down to your application and say what each
  layer does.
- Explain why ECS on EC2 still runs Docker Engine while EKS nodes run containerd, and what Fargate's
  Firecracker and Bottlerocket change.
- Describe an image pull byte by byte and what SOCI lazy loading changes.
- Read `cpu.stat` and `memory.events` and know whether a container is throttled or about to be
  OOM-killed.

## 1. Mental model

```mermaid
flowchart TB
  subgraph ecs[ECS on EC2 node]
    A1[ecs-agent] -->|Docker Engine API| D[dockerd]
    D --> CD1[containerd]
    CD1 --> S1[containerd-shim-runc-v2]
    S1 --> R1[runc]
    R1 --> P1[orders process<br/>namespaces + cgroup + caps + seccomp]
  end
  subgraph eks[EKS node]
    K[kubelet] -->|CRI gRPC| CD2[containerd + CRI plugin]
    CD2 --> S2[shim per pod sandbox]
    S2 --> R2[runc]
    R2 --> P2[pause + app processes]
  end
  subgraph fg[Fargate task]
    FC[Firecracker microVM] --> CD3[runtime inside guest]
    CD3 --> P3[task containers]
  end
```

A container is an ordinary Linux process started with a particular set of kernel options: its own
view of process IDs, network, mounts and hostnames (namespaces), a cap on CPU, memory and I/O
(cgroups), a reduced set of privileges (capabilities), and a filter on which syscalls it may make
(seccomp, LSMs). The image is the root filesystem for that process, assembled from layers by a
snapshotter. Everything above the kernel — runc, containerd, Docker Engine, kubelet, the ECS agent —
exists to translate an image plus a specification into those kernel calls and to keep the process
supervised. Once you can see the layers, most "container problems" become "process problems" with
familiar Linux tools.

## 2. Concepts

### 2.1 Namespaces

| Namespace | Isolates | Inspect |
| --- | --- | --- |
| `pid` | process IDs (PID 1 inside is the entrypoint) | `ls -l /proc/<pid>/ns/pid`; `nsenter -t <pid> -p ps -ef` |
| `net` | interfaces, routes, iptables, sockets | `nsenter -t <pid> -n ip addr`; `nsenter -t <pid> -n ss -tlnp` |
| `mnt` | mount table (the image rootfs, volumes) | `nsenter -t <pid> -m cat /proc/mounts` |
| `uts` | hostname | `nsenter -t <pid> -u hostname` |
| `ipc` | System V IPC, POSIX queues | `nsenter -t <pid> -i ipcs` |
| `user` | uid/gid mapping (rootless, userns) | `cat /proc/<pid>/uid_map` |
| `cgroup` | cgroup root view | `cat /proc/<pid>/cgroup` |
| `time` | boot/monotonic clock offsets | rarely used by runtimes |

Kubernetes pods share `net`, `ipc` and (optionally) `pid` namespaces among their containers through
the `pause` container, which is why sidecars see `localhost` ports of the application. `lsns` on a
node lists every namespace with its owning PID; `nsenter` lets you run host tools (which the
distroless image lacks) inside a container's namespaces without installing anything in it.

```bash
PID=$(docker inspect --format '{{.State.Pid}}' shopfront-orders-1)     # local compose container
sudo lsns -p "$PID"
sudo nsenter -t "$PID" -n ss -tlnp          # who listens on 8080 in that netns
sudo nsenter -t "$PID" -m -p ps -ef         # processes as the container sees them
```

### 2.2 cgroups v2

Every current AMI (AL2023, Bottlerocket) and Docker Engine/containerd release uses the unified
cgroup v2 hierarchy at `/sys/fs/cgroup`. Kubelet places pods under
`/sys/fs/cgroup/kubepods.slice/kubepods-<qos>.slice/kubepods-<qos>-pod<uid>.slice/cri-containerd-<cid>.scope`;
Docker Engine under `/sys/fs/cgroup/system.slice/docker-<cid>.scope`; the ECS agent's tasks appear
under a per-task cgroup (`ecs/<task-id>` naming; verify the exact path for your agent version).

| File | Meaning | What to look for |
| --- | --- | --- |
| `cpu.max` | `quota period` in µs; `max 100000` = unlimited | `50000 100000` = 0.5 CPU limit |
| `cpu.weight` | proportional share when contended (Kubernetes requests → 1–10000) | relative to siblings |
| `cpu.stat` | `usage_usec`, `nr_periods`, `nr_throttled`, `throttled_usec` | `nr_throttled/nr_periods` high = throttling |
| `memory.max`, `memory.high` | hard limit (OOM above), soft limit (throttled reclaim above) | Kubernetes limit → `memory.max` |
| `memory.current` | current charged bytes (RSS + page cache + kernel) | compare with `memory.max` |
| `memory.stat` | `anon`, `file`, `kernel`, `shmem`, … | `anon` ≈ RSS; `file` is reclaimable cache |
| `memory.events` | `low`, `high`, `max`, `oom`, `oom_kill` counters | `oom_kill > 0` = container killed |
| `pids.max`, `pids.current` | process count limit | fork bombs, thread leaks |
| `io.max`, `io.stat` | block I/O limits and counters | EBS throughput contention |
| `cpu.pressure`, `memory.pressure`, `io.pressure` | PSI: time tasks stalled waiting for the resource | `some avg10 > 20` on memory = reclaim thrash |

```bash
CG=$(cat /proc/"$PID"/cgroup | cut -d: -f3); echo "$CG"
cat /sys/fs/cgroup"$CG"/cpu.max /sys/fs/cgroup"$CG"/cpu.stat
cat /sys/fs/cgroup"$CG"/memory.max /sys/fs/cgroup"$CG"/memory.current /sys/fs/cgroup"$CG"/memory.events
cat /sys/fs/cgroup"$CG"/memory.pressure
```

### 2.3 Capabilities, seccomp, LSMs

Root inside a container is not root on the host because of three filters. **Capabilities** split
root's power into ~40 bits; Docker/containerd keep a default set (`CHOWN`, `DAC_OVERRIDE`, `FOWNER`,
`FSETID`, `KILL`, `SETGID`, `SETUID`, `SETPCAP`, `NET_BIND_SERVICE`, `NET_RAW`, `SYS_CHROOT`,
`MKNOD`, `AUDIT_WRITE`, `SETFCAP`) and drop the dangerous ones (`SYS_ADMIN`, `SYS_MODULE`,
`SYS_PTRACE`, `NET_ADMIN`, …); the shopfront manifests drop `ALL`. **seccomp** filters syscalls;
the `RuntimeDefault` profile blocks about 40 (mount, kexec, ptrace variants, module loading,
clock settime…). **LSMs**: AppArmor (Ubuntu/Debian hosts, the `docker-default` profile) and
SELinux (Bottlerocket enforcing, AL2023 depending on configuration) add mandatory access control on
files and sockets.

```bash
grep -E 'CapEff|Seccomp|NoNewPrivs' /proc/"$PID"/status
capsh --decode=$(grep CapEff /proc/"$PID"/status | awk '{print $2}')
cat /proc/"$PID"/attr/current 2>/dev/null       # AppArmor/SELinux label
```

`Seccomp: 2` means a filter is active; `NoNewPrivs: 1` is what `allowPrivilegeEscalation: false`
sets. A container with `CapEff: 0000000000000000` and a seccomp filter running as uid 10001 has very
little to escalate with; that is the shopfront baseline.

### 2.4 The OCI runtime spec and runc

A runtime bundle is a directory with `config.json` (the OCI runtime spec: `process` with args,
env, uid/gid, capabilities, `noNewPrivileges`; `root.path`; `mounts`; `linux.namespaces`,
`linux.resources` for cgroups, `linux.seccomp`, `linux.maskedPaths`/`readonlyPaths`) and a
`rootfs`. `runc create` reads it, forks a process, unshares the requested namespaces, sets up the
cgroup, mounts the rootfs and pivots into it, applies capabilities, seccomp and LSM labels, and
waits; `runc start` executes the entrypoint. Higher layers never talk to the kernel directly; they
write `config.json` and call runc (or another OCI runtime such as gVisor's `runsc` or Kata for
VM-isolated containers).

```bash
docker inspect shopfront-orders-1 | jq '.[0].HostConfig | {CapDrop, SecurityOpt, ReadonlyRootfs, NanoCpus, Memory}'
sudo cat /run/containerd/io.containerd.runtime.v2.task/moby/<cid>/config.json | jq '.process.capabilities, .linux.seccomp.defaultAction'
```

### 2.5 containerd

containerd is the daemon that owns images, snapshots and containers on a node. Its pieces:

| Component | Role | Tool |
| --- | --- | --- |
| content store | blobs by digest (manifests, configs, layers) | `ctr -n k8s.io content ls` |
| snapshotter | assembles layers into a rootfs (`overlayfs` default; `soci` for lazy loading; `stargz`) | `ctr -n k8s.io snapshots ls` |
| image service | manifests, platform resolution, pull/unpack | `ctr -n k8s.io images ls`; `crictl images` |
| runtime + shim v2 | one `containerd-shim-runc-v2` per pod sandbox (or container in Docker); survives containerd restarts | `ps -ef | grep shim` |
| CRI plugin | the gRPC API kubelet speaks (RunPodSandbox, CreateContainer, PullImage, ContainerStats) | `crictl` |
| namespaces | `k8s.io` for kubelet, `moby` for Docker Engine, `default` for `ctr` | `ctr namespaces ls` |

```bash
sudo crictl ps -a                                    # CRI view
sudo crictl pods --namespace shopfront
sudo crictl inspect <cid> | jq '.info.runtimeSpec.linux.resources'
sudo crictl stats <cid>
sudo ctr -n k8s.io images ls | grep shopfront
sudo cat /etc/containerd/config.toml | grep -A3 registry
sudo journalctl -u containerd --since -30min | tail
```

Configuration that matters: `plugins."io.containerd.grpc.v1.cri".registry.config_path` for mirrors
(`/etc/containerd/certs.d/docker.io/hosts.toml` → your ECR pull-through cache),
`image_pull_progress_timeout` (aborts stalled pulls), `sandbox_image` (the pause image, pulled from
ECR on EKS AMIs), and the snapshotter selection.

### 2.6 Docker Engine, the ECS agent and why EKS dropped Docker

Docker Engine (`dockerd`) is a client-facing daemon with its own API, image build support and
networking; since 2017 it runs containers through containerd and runc. Kubernetes talked to Docker
through a shim (dockershim) inside kubelet; that adapter was removed in Kubernetes 1.24, so EKS nodes
run containerd with the CRI plugin and no `dockerd` — `docker ps` does not exist on an EKS node,
`crictl ps` does.

ECS made a different choice: the ECS agent was built on the Docker Engine API (container creation,
log drivers, volume plugins, `docker stats` for telemetry) and the ECS-optimized AL2023 and
Bottlerocket ECS variants still ship Docker Engine for the agent to drive. Tasks on EC2 are Docker
containers (`docker ps` works on an ECS instance), which is why Docker log drivers and
`dockerVolumeConfiguration` appear in task definitions. On Fargate, AWS runs the runtime inside the
microVM; the task definition is the only interface and the engine is not observable.

| | ECS on EC2 | EKS node | Fargate |
| --- | --- | --- | --- |
| Engine | Docker Engine → containerd → runc | containerd (CRI) → runc | AWS-managed runtime in a Firecracker guest |
| Inspect containers | `docker ps`, `docker inspect`, `docker stats` | `crictl ps`, `crictl inspect`, `ctr` | task metadata endpoint, ECS Exec |
| Log path | Docker log driver (`awslogs`, `fluentd`, `awsfirelens`) | kubelet reads container stdout files under `/var/log/pods`; agents ship them | `awslogs`/FireLens via the platform |
| Registry auth | agent (`ECS_ENGINE_AUTH_DATA`, execution role for ECR) | kubelet credential providers (ECR via node role/Pod Identity) | execution role |

### 2.7 Firecracker and Fargate

Firecracker is a minimal virtual machine monitor (KVM-based, written in Rust) that boots a microVM
in about 125 ms with a tiny device model (virtio net/block/vsock, a serial console) and runs under a
`jailer` that applies cgroups, seccomp and chroot to the VMM process itself. Fargate gives each task
its own microVM: the task's containers share a guest kernel with each other but not with other
tasks, and the guest is disposable. Consequences: no host access (no SSH/SSM to a host, ECS Exec
into containers instead), no privileged containers or kernel modules, `SYS_PTRACE` as the only
addable capability, fixed CPU/memory shapes, an ENI per task, and a security boundary that is a
hypervisor rather than namespaces. Cold start includes microVM boot plus image pull, which is why
image size and SOCI matter more on Fargate than on a warm EC2 node.

### 2.8 Bottlerocket

Bottlerocket is a Linux distribution built only to run containers: an immutable, dm-verity-verified
root filesystem, no shell or package manager on the host, settings through an API (`apiclient set
kubernetes.max-pods=110`), atomic image-based updates with rollback, SELinux enforcing, and two
optional host containers: `control` (SSM agent) and `admin` (a privileged container with a shell
for break-glass). Variants exist for EKS (`aws-k8s-1.36`), ECS (`aws-ecs-2`) and NVIDIA. It is the
node OS under EKS Auto Mode. Practical effects: the attack surface of the node is small, patching is
"reboot into the new image", and debugging goes through `kubectl debug node/` or the admin
container rather than `ssh`.

### 2.9 Image pull, byte by byte

```mermaid
sequenceDiagram
  autonumber
  participant K as kubelet / ECS agent
  participant C as containerd (or dockerd)
  participant ECR as ECR API (ecr.api)
  participant REG as registry endpoint (ecr.dkr)
  participant S3 as S3 (layer blobs)
  K->>C: PullImage(123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders@sha256:…)
  C->>ECR: GetAuthorizationToken (via credential provider / execution role)
  ECR-->>C: token (12 h)
  C->>REG: GET /v2/shopfront/orders/manifests/sha256:… (Accept: index, manifest)
  REG-->>C: image index -> pick linux/arm64 manifest
  C->>REG: GET manifest -> config digest + layer digests
  loop layers in parallel (max concurrency configurable)
    C->>REG: GET /v2/.../blobs/sha256:layer
    REG-->>C: 307 redirect to presigned S3 URL
    C->>S3: GET blob (gzip/zstd)
    C->>C: verify digest, unpack into snapshotter (overlayfs)
  end
  C-->>K: image ready; create rootfs snapshot; start container
```

Where time goes: authentication (fast), manifest resolution (fast), layer download (bandwidth from
the task/node ENI, parallelism, presigned S3 redirects — the S3 gateway endpoint matters in private
subnets), and unpack (CPU-bound decompression, disk write). kubelet's `serializeImagePulls` (true by
default on some configurations) pulls one image at a time per node; `registryPullQPS`/`registryBurst`
throttle requests (Auto Mode raised them to 25/50). containerd aborts a pull that makes no progress
for `image_pull_progress_timeout`. `imagePullPolicy: IfNotPresent` with digests avoids re-pulls; ECS
`ECS_IMAGE_PULL_BEHAVIOR=prefer-cached` does the same on EC2.

**SOCI (Seekable OCI)** stores a zTOC index next to the image in ECR; a SOCI-aware snapshotter mounts
layers lazily and fetches only the ranges the process reads, so the container starts before the whole
image arrives. Fargate uses it automatically when an index exists; EKS Auto Mode enables SOCI
parallel pull and unpack by default on GPU/accelerated instance families with local NVMe
([FACTS](../../docs/FACTS-2026-09.md)). Build indexes in CI with the `soci` CLI for images above a
few hundred MiB ([02 L300](../02-ecr/L300-pull-through-cache-replication-and-limits.md)).

### 2.10 CPU: shares, quotas and throttling

Kubernetes `requests.cpu` becomes `cpu.weight` (proportional share under contention, otherwise
ignored); `limits.cpu` becomes `cpu.max` quota: with a 500m limit the cgroup may run 50 ms of CPU
time per 100 ms period across all its threads. A Node.js process with a libuv thread pool or a JVM
with GC threads can burn the quota in the first 20 ms of a period and then stall for 80 ms — that
is throttling, and it shows as latency with low average CPU. ECS container `cpu` is shares on EC2;
on Fargate it is also a ceiling per container within the task size.

```bash
cat /sys/fs/cgroup"$CG"/cpu.stat
# nr_periods 12000  nr_throttled 4800  throttled_usec 210000000  -> throttled in 40% of periods
```

Metrics: `container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total` and
`container_cpu_cfs_throttled_seconds_total`. The remedy is in [L400 §2.6](L400-hardening-supply-chain-and-performance.md)
(raise or remove CPU limits, size thread pools to the limit, `GOMAXPROCS`/`UV_THREADPOOL_SIZE`).

### 2.11 Memory: accounting and the OOM killer

`memory.current` charges anonymous memory (heap, stacks), page cache from files the container
read or wrote (reclaimable), kernel memory (sockets, dentries) and shmem/tmpfs (`emptyDir` in
memory counts). Kubernetes' `container_memory_working_set_bytes` is `memory.current` minus inactive
file cache, and that is what the kubelet compares against the limit for eviction decisions and what
the OOM killer effectively enforces at `memory.max`. When the cgroup cannot reclaim enough, the
kernel OOM killer picks the process with the highest `oom_score` inside the cgroup (usually the
biggest one, adjusted by `oom_score_adj`, which Kubernetes sets per QoS class: `BestEffort` 1000,
`Burstable` between, `Guaranteed` −997) and SIGKILLs it: exit code 137, `Reason: OOMKilled`,
`memory.events oom_kill` incremented, `dmesg` line `Memory cgroup out of memory: Killed process`.

```bash
cat /sys/fs/cgroup"$CG"/memory.stat | grep -E '^(anon|file|kernel|shmem) '
cat /sys/fs/cgroup"$CG"/memory.events
sudo dmesg -T | grep -i 'out of memory' | tail -3
kubectl -n shopfront describe pod <pod> | grep -A3 'Last State'     # Reason: OOMKilled, Exit Code: 137
```

A container killed at exactly its limit with a small heap is usually page cache plus a runtime that
does not know the limit (JVM defaults to a quarter of *host* memory unless container-aware);
[L400 §2.6](L400-hardening-supply-chain-and-performance.md) covers the flags.

### 2.12 Walkthroughs

Local (compose stack running):

```bash
docker run -d --name cat-limits --cpus 0.5 -m 256m -e DATABASE_URL=postgres://app:app@postgres:5432/shopfront \
  --network shopfront shopfront/catalog:dev
PID=$(docker inspect --format '{{.State.Pid}}' cat-limits)
CG=$(cut -d: -f3 /proc/"$PID"/cgroup)        # on Colima/Linux VM: run these inside the VM (colima ssh)
cat /sys/fs/cgroup"$CG"/cpu.max               # 50000 100000
cat /sys/fs/cgroup"$CG"/memory.max            # 268435456
docker stats --no-stream cat-limits
docker rm -f cat-limits
```

EKS node (through a debug pod; the node has no shell for you otherwise):

```bash
NODE=$(kubectl -n shopfront get pod -l app.kubernetes.io/name=orders -o jsonpath='{.items[0].spec.nodeName}')
kubectl debug node/"$NODE" -it --image=busybox:1.36 --profile=sysadmin -- chroot /host sh -c '
  crictl ps --name orders -q | head -1 | xargs -I{} sh -c "crictl inspect {} | grep -E \"cgroupsPath|memory\\\"|quota\""
  ls /sys/fs/cgroup/kubepods.slice | head'
```

## 3. How it interacts with the rest of AWS

| Component | Talks to | Protocol/API | Prerequisite (IAM, network, DNS) | What breaks if missing |
| --- | --- | --- | --- | --- |
| containerd/dockerd | ECR (`ecr.api`, `ecr.dkr`) and S3 | HTTPS; presigned S3 redirects | node role or execution role with ECR read; endpoints or NAT | pull failures, `ImagePullBackOff`, `CannotPullContainerError` |
| kubelet | containerd | CRI gRPC over a Unix socket | matching CRI version | node `NotReady`, `PLEG is not healthy` |
| ECS agent | Docker Engine | Docker API over Unix socket | agent/Docker versions from the AMI | tasks stuck `PENDING` |
| runc | kernel | syscalls (clone, unshare, cgroup fs, seccomp) | cgroup v2 mounted; kernel features | containers fail to start with EPERM/ENOSYS |
| SOCI snapshotter | ECR (index artifacts) | HTTPS | index pushed by CI | falls back to full pull |
| Bottlerocket updates | TUF repository / SSM | HTTPS | `control` container/SSM | nodes stay unpatched |
| Firecracker (Fargate) | AWS substrate | internal | none | n/a |

## 4. Use it when / avoid it when

Use these internals when:

- A container is slow with low CPU: check `cpu.stat` throttling before anything else.
- Exit code 137: distinguish OOM (`memory.events oom_kill`) from SIGKILL after `stopTimeout`.
- Image pulls dominate start time: measure pull vs unpack, then SOCI/smaller images/mirrors.
- Debugging distroless containers: `nsenter`/`kubectl debug --target` instead of adding a shell to
  the image.
- Choosing Fargate vs EC2: kernel-level features you need (or must forbid) decide it.

Avoid:

- Privileged containers to "fix" a permission problem; find the capability or mount instead.
- Running `docker` on EKS nodes (it is not there) or writing runbooks that assume it.
- Overlay-in-image tricks (chmod loops) that duplicate layers; fix ownership in the Dockerfile.
- `emptyDir` in memory (`medium: Memory`) without a `sizeLimit`: it counts against the memory
  limit.

Alternatives for stronger isolation on EC2: gVisor (`runsc`, user-space kernel) or Kata Containers
(lightweight VMs) as additional OCI runtimes via `RuntimeClass`; Fargate provides this by default.

## 5. Well-Architected view

| Pillar | What the layer gives you | Cost | Practice (Container Build Lens) |
| --- | --- | --- | --- |
| Operational Excellence | uniform forensics (`crictl`, cgroup files) across nodes | operator skill | runbooks with the commands in §2.12 |
| Security | namespaces, capabilities, seccomp, LSMs, microVMs | nothing when defaults are kept | drop ALL, `RuntimeDefault`, non-root; Fargate for untrusted |
| Reliability | cgroup limits prevent one container from starving a node | OOM/throttling if mis-sized | requests everywhere; memory limit = request; PDBs |
| Performance Efficiency | shares vs quota; SOCI; prefer-cached pulls | measurement | remove CPU limits where throttling hurts; size thread pools |
| Cost Optimization | bin-packing via correct requests | over-requesting | VPA recommendations |
| Sustainability | higher density per node | none | right-size |

## 6. Failure modes and troubleshooting

| Symptom | Likely cause | How to confirm (command/metric) | Fix |
| --- | --- | --- | --- |
| Latency spikes, CPU "low" | CFS throttling under a CPU limit | `cpu.stat nr_throttled`; `container_cpu_cfs_throttled_periods_total` | raise/remove limit, size threads ([playbook](../../playbooks/incidents/oom-and-cpu-throttling.md)) |
| Exit 137, `OOMKilled` | limit below working set; runtime unaware of limit; page cache from large file writes | `memory.events oom_kill`; `dmesg` | raise limit; container-aware flags; stream instead of buffer ([playbook](../../playbooks/incidents/oom-and-cpu-throttling.md)) |
| Exit 137 without OOM | SIGKILL after grace period/`stopTimeout` | timing vs SIGTERM in logs; no `oom_kill` | drain faster; raise grace ([playbook](../../playbooks/incidents/crashloop-and-exit-codes.md)) |
| `ImagePullBackOff`, `context deadline exceeded` | slow/large pull; progress timeout | `crictl` events; pull duration | SOCI, smaller image, mirrors ([playbook](../../playbooks/incidents/image-pull-failures.md)) |
| `exec format error` at start | wrong architecture image on arm64/amd64 node | `docker manifest inspect`; node `kubernetes.io/arch` | multi-arch build ([L200](L200-images-builds-and-registries.md)) |
| `permission denied` binding port 80 as non-root | no `NET_BIND_SERVICE` | `capsh --decode` | listen on 8080; add only that capability if unavoidable |
| `operation not permitted` on mount/ptrace | seccomp/capabilities | `Seccomp` in `/proc/<pid>/status`; audit log | fix the need, not the filter |
| `PLEG is not healthy`, node `NotReady` | containerd overloaded, too many containers, disk pressure | `journalctl -u kubelet`; `crictl ps -a | wc -l` | reduce churn; larger nodes ([playbook](../../playbooks/incidents/node-not-ready.md)) |
| Read-only filesystem errors | `readOnlyRootFilesystem` without volumes | container logs | `emptyDir` for writable paths |
| PID exhaustion | thread/process leak; `pids.max` | `pids.current`; `container_processes` | fix leak; set `pids.max` per pod (`podPidsLimit`) |

## 7. Signals: metrics, logs, traces

- `container_cpu_cfs_throttled_periods_total` / `container_cpu_cfs_periods_total` (ratio above
  25% on a latency-sensitive service means the limit is wrong); `container_cpu_cfs_throttled_seconds_total`.
- `container_memory_working_set_bytes` vs limit; `container_memory_rss`; `container_memory_cache`;
  `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`;
  `container_oom_events_total`.
- `container_processes`, `container_threads` vs `pids.max`.
- Node PSI: `node_pressure_cpu_waiting_seconds_total`, `node_pressure_memory_stalled_seconds_total`
  (memory stall = reclaim thrash before OOM); kubelet `MemoryPressure`/`DiskPressure` conditions.
- Image pulls: `kubelet_image_pull_duration_seconds` (verify exact name for your version),
  `PullStartedAt`/`PullStoppedAt` in ECS task metadata, containerd `image_pull_progress_timeout`
  events.
- Runtime health: `kubelet_pleg_relist_duration_seconds`, `kubelet_runtime_operations_errors_total`,
  containerd/dockerd journal errors; ECS agent log.

Full table: [`reference/metrics-catalog.md`](../../reference/metrics-catalog.md).

## 8. Testing and DR notes

Testing: reproduce limits locally with `docker run --cpus 0.5 -m 256m` and a load generator, then
read `cpu.stat`/`memory.events` to see throttling and OOM before production does; in a cluster, run
`stress-ng --cpu 4 --timeout 60s` in a pod with a 500m limit and watch
`container_cpu_cfs_throttled_periods_total`; run a pod that writes a 1 GiB file to `emptyDir` under a
256 MiB limit and observe the OOM (page cache counts); test image pull timeouts by pulling a large
image through a throttled path; verify seccomp/capabilities with a pod that tries `mount` and
`ptrace` (must fail). Container structure tests assert the image's user, entrypoint and absence of a
shell ([11 L100](../11-testing-workloads/L100-testing-basics.md)).

DR: the runtime layer holds no durable state — nodes and tasks are replaced from AMIs/images. The
only DR-relevant facts are that images must exist in the DR Region (ECR replication) and that any
node-level configuration (containerd mirrors, kubelet flags, agent config) lives in launch templates
or Bottlerocket settings under version control ([10 L200](../10-resilience-and-dr/L200-designing-for-failure.md)).

## 9. Hands-on

```bash
# 1. Read the labs' Dockerfiles with the kernel in mind: non-root uid, no shell, static binary
sed -n '/runtime/,$p' labs/apps/catalog/Dockerfile
grep -nE 'USER|ENTRYPOINT|FROM' labs/apps/orders/Dockerfile labs/apps/worker/Dockerfile

# 2. Start the stack and look at the processes from the host side (Colima: colima ssh first)
make up
docker inspect shopfront-orders-1 | jq '.[0].HostConfig | {ReadonlyRootfs, CapDrop, SecurityOpt, Tmpfs}'
docker top shopfront-orders-1            # uid 10001, node dist/index.js as PID 1 inside
docker stats --no-stream                  # cgroup-derived CPU/memory per container

# 3. Namespaces and cgroups of the catalog container (inside the Colima VM / Linux host)
PID=$(docker inspect --format '{{.State.Pid}}' shopfront-catalog-1)
sudo lsns -p "$PID" | head
sudo nsenter -t "$PID" -n ss -tlnp        # 8081 listening; no shell needed in the distroless image
CG=$(cut -d: -f3 /proc/"$PID"/cgroup); cat /sys/fs/cgroup"$CG"/cpu.stat /sys/fs/cgroup"$CG"/memory.current
grep -E 'CapEff|Seccomp|NoNewPrivs|Uid' /proc/"$PID"/status
# Observe: CapEff all zeros (cap_drop ALL), Seccomp 2, NoNewPrivs 1, Uid 10001.

# 4. Throttling and OOM on purpose
docker run --rm --cpus 0.5 -m 128m --name stress alpine:3.20 sh -c 'apk add -q stress-ng && stress-ng --cpu 2 --vm 1 --vm-bytes 200M --timeout 20s' ; echo "exit $?"
# Observe: exit 137 when the vm worker exceeds 128m (OOM); check `docker inspect stress` State.OOMKilled if you drop --rm.

# 5. On an EKS node (billable): containerd view of the same containers
NODE=$(kubectl -n shopfront get pod -l app.kubernetes.io/name=orders -o jsonpath='{.items[0].spec.nodeName}')
kubectl debug node/"$NODE" -it --image=busybox:1.36 --profile=sysadmin -- chroot /host sh -c 'crictl ps --name orders; crictl stats --name orders 2>/dev/null | head -3; ls /var/log/pods | head -3'
```

## 10. Check yourself

1. A Node.js container with a 500m CPU limit shows p99 latency of 800 ms while average CPU is 30%.
   What is the mechanism and how do you confirm it?

<details><summary>Answer</summary>
CFS quota throttling: the cgroup may use 50 ms per 100 ms period across all threads; bursts from
the event loop plus libuv's thread pool exhaust the quota early in a period and the process stalls
until the next one. Confirm with `cpu.stat` (`nr_throttled`/`nr_periods` high, `throttled_usec`
growing) or `container_cpu_cfs_throttled_periods_total`. Fix by raising or removing the limit,
keeping the request for scheduling, and sizing `UV_THREADPOOL_SIZE` to the CPU actually available.
</details>

2. Why does `docker ps` fail on an EKS node but work on an ECS-optimized instance?

<details><summary>Answer</summary>
EKS nodes run containerd with the CRI plugin as the only runtime because kubelet's Docker adapter
(dockershim) was removed in Kubernetes 1.24; there is no `dockerd`, so `crictl` is the tool. The ECS
agent drives Docker Engine through its API (log drivers, volumes, stats), so ECS-optimized AMIs ship
Docker Engine, which itself runs containers through containerd and runc.
</details>

3. A container is OOM-killed at its 256 MiB limit although its heap never exceeds 120 MiB. What else
   is being charged to the cgroup?

<details><summary>Answer</summary>
Page cache from files the process reads or writes (large log files, downloaded artifacts, `emptyDir`
on disk under heavy write), tmpfs/`emptyDir` in memory, kernel memory (sockets, dentries), and
other processes in the container (a shell wrapper, child processes). `memory.stat` shows `anon` vs
`file` vs `shmem`; the working set that the kubelet and OOM killer act on includes active file cache
and shmem. Stream instead of buffering, size `emptyDir`, and set a limit with headroom.
</details>

4. What does Firecracker change about the security model compared with containers on a shared EC2
   node?

<details><summary>Answer</summary>
Each Fargate task runs in its own microVM with its own guest kernel; isolation between tasks is the
hypervisor boundary (KVM plus the jailer's cgroups/seccomp/chroot around the VMM), not Linux
namespaces. A kernel exploit inside a task compromises that guest only. The price is no host
access, no privileged containers or kernel modules, a fixed set of capabilities, and cold start that
includes microVM boot.
</details>

5. Describe where time goes in pulling a 900 MiB image on Fargate and what SOCI changes.

<details><summary>Answer</summary>
Authentication and manifest resolution are fast; most time is downloading layers from S3 through
the task ENI (bandwidth scales with task size) and decompressing/unpacking them onto ephemeral
storage before the container can start. With a SOCI index in ECR, the snapshotter mounts layers
lazily and fetches only the byte ranges the process actually reads, so the container starts after a
small fraction of the image has arrived and the rest streams in the background.
</details>

## 11. Sources

- Linux namespaces manual — https://man7.org/linux/man-pages/man7/namespaces.7.html
- Control Group v2 (kernel documentation) — https://docs.kernel.org/admin-guide/cgroup-v2.html
- Capabilities manual — https://man7.org/linux/man-pages/man7/capabilities.7.html
- Seccomp in containerd/Kubernetes — https://kubernetes.io/docs/tutorials/security/seccomp/
- OCI Runtime Specification — https://github.com/opencontainers/runtime-spec/blob/main/spec.md
- runc — https://github.com/opencontainers/runc
- containerd documentation (architecture, CRI, snapshotters, config) — https://containerd.io/docs/ and https://github.com/containerd/containerd/blob/main/docs/cri/config.md
- crictl user guide — https://github.com/kubernetes-sigs/cri-tools/blob/master/docs/crictl.md <!-- term-ok -->
- Kubernetes: Dockershim removal FAQ — https://kubernetes.io/blog/2022/02/17/dockershim-faq/
- Amazon ECS-optimized AMIs (Docker and agent versions) — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html
- Firecracker — https://firecracker-microvm.github.io/ and https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md
- Bottlerocket documentation — https://bottlerocket.dev/en/os/
- Kubernetes: resource management for pods and containers (CFS quota, QoS, OOM) — https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- Kubernetes node pressure eviction and PSI — https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/
- Seekable OCI (SOCI) — https://github.com/awslabs/soci-snapshotter and https://docs.aws.amazon.com/AmazonECS/latest/developerguide/container-considerations.html
- Amazon EKS node image pull settings (Auto Mode release notes) — https://docs.aws.amazon.com/eks/latest/userguide/auto-change.html
