# Amazon ECS · L300 — ECS internals

**Level:** 300 · **Time:** ~90 min · **Prerequisites:**
[L200 Task definitions, services and scaling](L200-task-definitions-services-and-scaling.md),
[Container fundamentals L300](../01-container-fundamentals/L300-runtimes-and-the-kernel.md),
[Networking L300](../05-networking/L300-container-networking-internals.md)

**After this document you can:**

- Narrate what happens, second by second, between `RunTask` and a healthy target, and between
  `StopTask` and `STOPPED`.
- Read a `stopCode`/`stoppedReason` pair and know which component failed and what to check first.
- Explain how a container gets AWS credentials on ECS and why it must never reach IMDS.
- Describe what Fargate, Managed Instances and the EC2 agent each do underneath a task.
- Explain how the Service Connect agent, Cloud Map and the ALB interact during a deployment.

## 1. Mental model

```mermaid
sequenceDiagram
  autonumber
  participant S as Service scheduler
  participant CP as Capacity (Fargate / agent on EC2)
  participant NET as VPC (ENI)
  participant ER as Execution role
  participant ECR as ECR + Secrets Manager
  participant C as Containers
  participant TG as ALB target group
  S->>CP: place task (strategy, constraints, capacity provider)
  CP->>NET: create/attach task ENI in subnet with task SG (PROVISIONING)
  CP->>ER: assume execution role
  ER->>ECR: GetAuthorizationToken, BatchGetImage, layers from S3; GetSecretValue
  CP->>C: create containers, inject secrets, start in dependsOn order (PENDING -> ACTIVATING)
  C-->>CP: container health checks pass
  CP->>TG: RegisterTargets(ip:8080) (ACTIVATING -> RUNNING)
  TG-->>TG: ALB health checks /readyz x2 -> healthy
  Note over S,TG: task counts toward runningCount and receives traffic
```

Every ECS task goes through the same pipeline: a placement decision, network identity, an
authenticated fetch of images and secrets, an ordered start of containers, health evaluation, and
registration with whatever fronts it. The control plane records each transition as a task state;
when a step fails, the task stops with a `stopCode` and a `stoppedReason` that name the step. The
data plane doing the work is either the ECS agent driving Docker Engine on an instance you or AWS
own, or the Fargate substrate running the containers inside a Firecracker microVM. Understanding
which party owns each step is what turns a `stoppedReason` into a fix.

## 2. Concepts

### 2.1 Task lifecycle, `stopCode` and `stoppedReason`

States, in order: `PROVISIONING` (ENI, storage), `PENDING` (image pull, secrets, container
creation), `ACTIVATING` (containers starting, health checks, target/Service Connect registration),
`RUNNING`, `DEACTIVATING` (deregistration from targets and Cloud Map), `STOPPING` (SIGTERM,
`stopTimeout`, SIGKILL), `DEPROVISIONING` (ENI detach), `STOPPED`. `desiredStatus` and
`lastStatus` differ while a transition is in progress; `describe-tasks` shows both.

| `stopCode` | Meaning | First check |
| --- | --- | --- |
| `TaskFailedToStart` | never reached `RUNNING`; look at `stoppedReason` and container `reason` | execution role, endpoints, image, secrets, logging |
| `EssentialContainerExited` | an `essential: true` container exited | container `exitCode` (137 OOM/kill, 143 SIGTERM, 1 app error, 126/127 entrypoint) |
| `UserInitiated` | `StopTask` by a principal | CloudTrail `StopTask` |
| `ServiceSchedulerInitiated` | the service stopped it: deployment, scale-in, failed health checks, AZ rebalancing | service events |
| `SpotInterruption` | Fargate Spot / EC2 Spot reclaimed | capacity strategy `base` |
| `TerminationNotice` | the instance is terminating (ASG scale-in, Managed Instances patching) | draining configuration |

| `stoppedReason` (prefix) | Owner | Typical cause | Confirm |
| --- | --- | --- | --- |
| `ResourceInitializationError: unable to pull secrets or registry auth` | execution role / network | missing `secretsmanager:GetSecretValue`, `kms:Decrypt`, `ecr:GetAuthorizationToken`; no route to endpoints | CloudTrail `AccessDenied` for the execution role; VPC endpoints |
| `ResourceInitializationError: failed to validate logger args` | execution role / network | `awslogs-create-group` without `logs:CreateLogGroup`; `logs` endpoint unreachable | execution role policy |
| `ResourceInitializationError: failed to invoke EFS utils` | EFS | mount target SG, access point, IAM auth | EFS mount target reachability |
| `CannotPullContainerError: pull access denied` / `repository does not exist` | image ref / ECR policy | wrong account/region in URI, cross-account repository policy missing | `aws ecr describe-images`; repository policy |
| `CannotPullContainerError: ... i/o timeout` | network | no NAT/endpoint from the task subnet; SG egress blocked | Reachability Analyzer to `ecr.dkr` |
| `CannotPullContainerError: ... toomanyrequests` | upstream registry | Docker Hub rate limit | pull-through cache ([02 L300](../02-ecr/L300-pull-through-cache-replication-and-limits.md)) |
| `OutOfMemoryError: Container killed due to memory usage` | task sizing | container `memory` hard limit or task memory exceeded | exit code 137; Container Insights `MemoryUtilized` |
| `Task failed container health checks` | health command | wrong command, image lacks the tool, `startPeriod` too short | `describe-tasks … containers[].healthStatus` |
| `Task failed ELB health checks in (target-group …)` | ALB path/SG | `/readyz` returns non-200, SG blocks ALB, port mismatch | `aws elbv2 describe-target-health` |
| `Essential container in task exited` | application | crash, configuration error (exit 2 in shopfront) | container logs |
| `Scaling activity initiated by (deployment ecs-svc/…)` | scheduler | normal replacement during deployment or scale-in | none |
| `Host EC2 (instance i-…) terminated` | capacity | ASG scale-in without managed draining; Spot | ASG activity history |

Forensics:

```bash
aws ecs list-tasks --cluster shopfront-dev --service-name orders --desired-status STOPPED --query 'taskArns[:5]'
aws ecs describe-tasks --cluster shopfront-dev --tasks <task-id> \
  --query 'tasks[0].{last:lastStatus,code:stopCode,reason:stoppedReason,stoppedAt:stoppedAt,
           containers:containers[].{name:name,exit:exitCode,reason:reason,health:healthStatus}}'
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].events[:10].message'
```

Stopped tasks stay visible for about an hour; export `ECS Task State Change` events through
EventBridge to CloudWatch Logs so the reasons survive.

### 2.2 The ECS agent on EC2

On an ECS-optimized AL2023 or Bottlerocket (`aws-ecs-2`) instance, systemd starts the agent as a
container (`amazon-ecs-agent`). The agent registers the instance in the cluster (`RegisterContainerInstance`,
with attributes such as `ecs.instance-type`, `ecs.availability-zone`, `ecs.capability.*`), then holds
long-lived websocket sessions to the control plane: one to receive task instructions and report
state, one to ship telemetry (the agent calls them ACS and TCS; verify current names in the agent
repository). It executes instructions through the Docker Engine API on the local socket, which is
why EC2 tasks run under Docker Engine and appear in `docker ps` on the instance, while EKS nodes
run containerd only ([01 L300](../01-container-fundamentals/L300-runtimes-and-the-kernel.md)).

`/etc/ecs/ecs.config` keys that matter:

| Key | Effect | Recommended |
| --- | --- | --- |
| `ECS_CLUSTER` | cluster to join | set in user data by the launch template |
| `ECS_ENABLE_TASK_IAM_ROLE` | credentials proxy for task roles | `true` (default on ECS AMIs) |
| `ECS_AWSVPC_BLOCK_IMDS` | drop task traffic to `169.254.169.254` in `awsvpc` mode | `true` |
| `ECS_ENABLE_SPOT_INSTANCE_DRAINING` | drain on the 2-minute Spot notice | `true` on Spot |
| `ECS_IMAGE_PULL_BEHAVIOR` | `default`, `always`, `once`, `prefer-cached` | `prefer-cached` for fleets that pull the same digest |
| `ECS_ENGINE_TASK_CLEANUP_WAIT_DURATION` | how long stopped containers linger for debugging | `1h` in dev, shorter in prod |
| `ECS_RESERVED_MEMORY` | memory kept for the agent and OS | `256` MiB or more on small instances |
| `ECS_CONTAINER_STOP_TIMEOUT` | default `stopTimeout` when the task definition sets none | `30s` |
| `ECS_ENABLE_CONTAINER_METADATA` | writes a metadata file into the container | `true` for debugging |
| `ECS_LOG_LEVEL` | agent verbosity | `info`; `debug` during incidents |

Introspection from the instance:

```bash
curl -s localhost:51678/v1/metadata | jq          # cluster, container instance ARN, agent version
curl -s localhost:51678/v1/tasks | jq '.Tasks[] | {Arn, KnownStatus, Containers: [.Containers[].Name]}'
sudo journalctl -u ecs --since -30min             # agent unit logs; also /var/log/ecs/ecs-agent.log
sudo ecs-logs-collector                            # bundle for AWS Support
```

Port 51679 is the credentials proxy: in `bridge` mode the agent rewrites `169.254.170.2:80` to
`127.0.0.1:51679` with iptables; in `awsvpc` mode the task ENI's network namespace routes
`169.254.170.2` to the agent directly. Draining (`update-container-instances-state --status
DRAINING`) tells the scheduler to move tasks away, respecting `minimumHealthyPercent`; managed
draining on capacity providers does this automatically before the ASG terminates an instance.

### 2.3 Task metadata and credentials at 169.254.170.2

Every container gets two environment variables from the platform:

- `ECS_CONTAINER_METADATA_URI_V4=http://169.254.170.2/v4/<id>` — `GET` it for the container,
  `…/task` for the task, `…/stats` and `…/task/stats` for Docker-style CPU/memory/network counters.
  Fields worth knowing: `Cluster`, `TaskARN`, `Family`, `Revision`, `DesiredStatus`, `KnownStatus`,
  `LaunchType`, `AvailabilityZone`, `Containers[].Networks[].IPv4Addresses`,
  `Containers[].Limits`, `PullStartedAt`/`PullStoppedAt` (image pull duration).
- `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI=/v2/credentials/<uuid>` — the SDK credential chain
  checks this variable before IMDS and calls `http://169.254.170.2$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`,
  receiving temporary credentials for the **task role**, refreshed by the agent/Fargate before
  expiry. The response carries `RoleArn`, `AccessKeyId`, `SecretAccessKey`, `Token`, `Expiration`.

```bash
# from inside a task (ECS Exec, worker image)
curl -s "$ECS_CONTAINER_METADATA_URI_V4/task" | jq '{Cluster, Family, Revision, LaunchType, AvailabilityZone, KnownStatus}'
curl -s "http://169.254.170.2$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI" | jq '{RoleArn, Expiration}'
curl -s "$ECS_CONTAINER_METADATA_URI_V4/task/stats" | jq 'to_entries[0].value.memory_stats.usage'
```

The SDK order is: explicit configuration → environment keys → web identity → the container
credentials endpoint → IMDS. If a container on EC2 can reach IMDS and the task has **no** task
role, the SDK silently uses the **instance role**, which is usually far more privileged. That is
why `ECS_AWSVPC_BLOCK_IMDS=true` is not optional on shared instances, and why every service gets a
task role even when it needs no permissions (an empty role blocks the fallback).

### 2.4 IMDS access rules per platform

| Platform | Can a container reach `169.254.169.254`? | How to block or why not needed |
| --- | --- | --- |
| Fargate | no; the microVM has no IMDS route | nothing to do |
| EC2 `awsvpc` | yes by default through the task ENI's namespace | `ECS_AWSVPC_BLOCK_IMDS=true` in `ecs.config` |
| EC2 `bridge`/`host` | yes through the instance's stack | IMDSv2 required with `HttpPutResponseHopLimit=1` (bridge: the PUT response's TTL expires at the bridge hop) plus the iptables rule from the ECS docs for `host` mode |
| Managed Instances | AWS-managed instance; tasks are `awsvpc` | verify the platform's default in the current docs |

IMDSv2 mechanics (token PUT, TTL, hop limit) are in
[Networking L300 §2.2](../05-networking/L300-container-networking-internals.md).

### 2.5 Fargate internals

Each Fargate task runs in its own Firecracker microVM (platform version 1.4.0, `LATEST`, since
2020): a minimal Linux guest with the container runtime, the task's containers, and virtio devices
for the ENI and ephemeral storage. Consequences:

- One ENI per task in the subnet you choose, with the task's security groups; the task has a
  private IP and optionally a public IP (`assignPublicIp`). No ENI trunking, no `bridge`.
- Ephemeral storage 20 GiB by default (image layers plus writable layers plus bind volumes),
  configurable to 200 GiB, encrypted with an AWS-managed key by default. EBS volumes can be created
  and attached per task at launch (`volumeConfigurations` on the service or `run-task`).
- No `privileged`, no `hostNetwork`/`hostPort` other than the container port, no GPUs, no
  `--device`; `linuxParameters.capabilities.add` allows only `SYS_PTRACE`; kernel `sysctls` limited
  to a documented allowlist (verify in the current docs).
- Two task sizes share nothing: noisy-neighbour effects are limited to the underlying host's
  network and disk bandwidth, which scale with task size.
- Fargate Spot sends a `SIGTERM` and a task state change with `stopCode: SpotInterruption` two
  minutes before reclaiming; `stopTimeout` still applies within that window.
- Image pulls happen from inside the microVM through the task ENI, so private subnets need NAT or
  the ECR/S3 endpoints; the pull time is visible as `PullStartedAt`→`PullStoppedAt`. SOCI indexes
  in ECR let Fargate start containers before the whole image is downloaded.

Platform version differences are documented per version; `LATEST` is the right value unless you
need a pinned behaviour during an investigation.

### 2.6 ECS Managed Instances internals

A Managed Instances capacity provider makes AWS responsible for EC2 instances that still live in
your account and VPC: you supply instance requirements (families, sizes, architecture, Spot or
on-demand) and network settings; ECS launches, patches (by replacing instances) and scales them,
and drains tasks before replacement. Tasks run in `awsvpc` with the same task definition you use on
EC2, so instance-level features (specific families, GPUs with the management fee reductions from
2026, local NVMe) become available without an ASG, an AMI pipeline or agent upgrades. Compared with
an ASG capacity provider: you lose SSH/SSM to the host and custom AMIs, you gain AWS-operated
patching and instance selection; the management fee is a percentage of the instance price (verify
the current pricing and rotation cadence). EC2 Capacity Reservations are supported since 2026-02.

### 2.7 ENI trunking

In `awsvpc` on EC2 every task needs an ENI; a c5.large supports 3 ENIs, one for the instance, so
2 tasks. With `awsvpcTrunking` enabled at the account level and a Nitro instance, the agent creates
one trunk ENI and attaches branch ENIs for tasks: c5.large → 10 tasks, c5.xlarge → 20, m5.large →
10 (verify exact numbers in the current table). Requirements: the instance role can
`ec2:CreateNetworkInterface`/`AttachNetworkInterface` through the ECS service-linked role, the
agent is recent, and the instance is not in a shared VPC subnet without permissions. Trunking does
not apply to Fargate.

### 2.8 Service Connect internals

When a service has `serviceConnectConfiguration.enabled`, ECS injects an `ecs-service-connect-agent`
container (Envoy-based) into every task and rewrites the task's network namespace so that:

1. Outbound connections to a client alias (`orders:8080`) resolve locally (the agent answers the
   name inside the task) and are redirected by iptables to the agent's outbound listener.
2. The agent looks up the destination in the Cloud Map namespace (`shopfront.local`, service
   `orders`, instances = task IPs and ports registered by ECS), picks a healthy endpoint, applies
   retries and outlier detection, and connects to the destination task's **inbound** agent
   listener, not directly to the application port.
3. The destination agent forwards to the local application port.

TLS with AWS Private CA is started by the client agent and terminated by the server agent; ECS
issues and rotates the certificates through the role you name. The application sees plaintext on
`127.0.0.1`. Timeouts (`idleTimeoutSeconds`, `perRequestTimeoutSeconds`) are enforced by the agents.
During a deployment the old task's agent stops accepting new inbound connections when the task is
`DEACTIVATING` and drains existing ones, which is why Service Connect deployments show fewer
connection resets than raw Cloud Map DNS.

Cost and limits: the agent consumes CPU/memory from the task's allocation (about 0.25 vCPU and
64–128 MiB is a common reservation; size the task accordingly); metrics for each client→server
pair are published through Container Insights (request count, 5xx counts, target response time,
active connections, TLS negotiation errors; verify exact names in the metrics reference). Agent
logs go where `serviceConnectConfiguration.logConfiguration` points.

### 2.9 Cloud Map DNS internals

Service discovery without Service Connect uses the same namespace: ECS registers each task as a
Cloud Map instance and Cloud Map writes A (awsvpc) or SRV (bridge with dynamic ports) records into
a Route 53 private hosted zone associated with the VPC. Resolution is ordinary VPC DNS, so any
client in the VPC can resolve `orders.shopfront.local`. Trade-offs: TTL (10–15 s) versus stale
answers, client-side caching in runtimes (the JVM caches positive answers for 30 s by default),
and health: Cloud Map can use ECS container health (`healthCheckCustomConfig`) so unhealthy tasks
drop out of answers, but a client with a cached answer keeps trying until the TTL expires. This is
the mechanism behind connection errors "for a few seconds" during deployments on DNS-based
discovery.

### 2.10 The stop timeline in detail

Deployment replacing one `orders` task; values from the contract.

| t (s) | ALB / target group | ECS control plane | Task | Application |
| --- | --- | --- | --- | --- |
| 0 | `DeregisterTargets`; target → `draining`; new requests stop being routed within a few seconds | task `DEACTIVATING` | | still serving |
| 0–2 | | Cloud Map / Service Connect instance deregistered | | |
| ~2 | | task `STOPPING`; SIGTERM to essential containers; `stopTimeout` (30) starts | agent forwards SIGTERM | `shutdown signal received`; stops accepting, drains in-flight (≤20 s) |
| 2–20 | draining continues for the deregistration delay (20) | | | in-flight requests complete |
| ~12 | | | | exits 0 (`stopped`) |
| 20 | target removed | | | |
| 32 | | if still running: SIGKILL | | |
| ~35 | | `DEPROVISIONING` → `STOPPED` (`ServiceSchedulerInitiated`) | ENI detached | |

The invariant: application drain budget ≤ `stopTimeout`, and the application must not close its
listener before the load balancer has stopped routing to it. With Service Connect the agent stops
accepting inbound at `DEACTIVATING`, so the application's drain only needs to finish requests
already accepted.

### 2.11 Placement engine and daemon strategy

For EC2 and Managed Instances, the scheduler filters instances by constraints (`memberOf`
expressions, `distinctInstance`), then by resources (`CPU`, `MEMORY`, `PORTS`, `ENI` with
trunking, `GPU`), then applies strategies in order (`spread`, `binpack`, `random`). Failure
messages are specific: `RESOURCE:CPU` or `RESOURCE:MEMORY` means no instance has room;
`RESOURCE:ENI` means trunking or a larger instance is needed; `AGENT` means the instance's agent is
disconnected; `ATTRIBUTE` means a constraint filtered everything out. The `DAEMON` scheduling
strategy runs one task per instance that matches the constraints, starts tasks on new instances
automatically and does not use a load balancer or auto scaling; it is how you run log shippers and
node agents on EC2 clusters. Since 2024 the service scheduler also rebalances tasks across AZs
after an AZ recovers (`availabilityZoneRebalancing: ENABLED`).

### 2.12 ECS Anywhere

`EXTERNAL` container instances are on-premises or edge machines with the SSM agent and the ECS
agent installed through an activation. The control plane schedules tasks onto them like EC2
instances, with limits: `bridge`/`host` networking only, no ALB/NLB target registration through
ECS, no Service Connect, no service discovery integration; you bring your own ingress. Useful for
hybrid rollouts of the same task definitions.

### 2.13 Observability hooks

Container Insights with enhanced observability (cluster setting `containerInsights: enhanced`)
collects task- and container-level CPU, memory, network, storage and restart metrics into the
`ECS/ContainerInsights` namespace plus performance log events. Traces come from an ADOT collector
sidecar (as in the L200 task definition) or a shared collector service, exporting to X-Ray /
CloudWatch Transaction Search and Application Signals; the application only speaks OTLP to
`127.0.0.1:4318`. Details in [07 L200](../07-observability/L200-tooling-on-aws.md).

## 3. How it interacts with the rest of AWS

| Component | Talks to | Protocol/API | Prerequisite (IAM, network, DNS) | What breaks if missing |
| --- | --- | --- | --- | --- |
| ECS agent (instance role) | ECS control plane | HTTPS + websockets to `ecs.<region>.amazonaws.com` | instance role `AmazonEC2ContainerServiceforEC2Role`; `ecs`, `ecs-agent`, `ecs-telemetry` endpoints or NAT | instance never registers; tasks stuck `PENDING` with `AGENT` |
| Agent / Fargate (execution role) | ECR, Secrets Manager, SSM, CloudWatch Logs, KMS | HTTPS | execution role; `ecr.api`, `ecr.dkr`, S3 gateway, `secretsmanager`, `ssm`, `logs`, `kms` endpoints | `ResourceInitializationError`, `CannotPullContainerError` |
| Credentials endpoint | STS (on behalf of the task) | agent/Fargate assume the task role | task role trusts `ecs-tasks.amazonaws.com` | SDK falls back to IMDS or fails with no credentials |
| Service Connect agent | Cloud Map, AWS Private CA (via role) | discovery API; certificate issuance | namespace; TLS role with `acm-pca:IssueCertificate`, `GetCertificate` | `ResourceInitializationError` naming Service Connect |
| Service scheduler | ELB | `RegisterTargets`/`DeregisterTargets` through the ECS service-linked role | target type `ip`; SG from ALB to task | tasks unhealthy, deployments stall |
| Fargate | EC2 networking | ENI create/attach in your subnet | subnet capacity (free IPs), ENI quota | `PROVISIONING` failures: `insufficient free addresses` |
| Task (ECS Exec) | SSM | `ssmmessages` | task role; endpoint | `TargetNotConnectedException` |
| EventBridge | task state changes | `ECS Task State Change` events | rule + target | you lose `stoppedReason` history after an hour |

## 4. Use it when / avoid it when

Use these internals when:

- Diagnosing a task that will not start: read `stoppedReason`, map it to the owner in §2.1.
- Choosing between Fargate and EC2 for a workload with kernel, GPU or density needs: §2.5–2.7.
- Deciding whether Service Connect is worth the agent overhead: §2.8 versus §2.9.
- Tuning the deployment timeline after seeing 5xx during rollouts: §2.10.

Avoid:

- Depending on the instance role from a task (§2.3); block IMDS.
- Running Service Connect for workloads that are pure batch or that non-ECS clients call.
- `ECS_ENGINE_TASK_CLEANUP_WAIT_DURATION` of hours on small instances (disk pressure).
- Treating `LATEST` platform version as fixed behaviour across Regions and time.

Alternatives at this depth: EKS gives you kubelet, kube-proxy and CNI internals you can inspect
and change ([04 L300](../04-eks/L300-eks-internals-and-operations.md)); ECS trades that
transparency for fewer moving parts.

## 5. Well-Architected view

| Pillar | What the internals give you | What they cost you | Practice |
| --- | --- | --- | --- |
| Operational Excellence | deterministic state machine; `stoppedReason` catalog; introspection endpoints | you must export task events to keep history | EventBridge → CloudWatch Logs for task state changes; runbook keyed by `stoppedReason` |
| Security | credentials endpoint per task; Fargate microVM isolation; agent IMDS blocking | EC2 hosts share a kernel across tasks | `ECS_AWSVPC_BLOCK_IMDS=true`; a task role on every service; Fargate for untrusted code |
| Reliability | ordered start, health evaluation, drain-aware stop, AZ rebalancing | timeline invariants are yours to keep | drain ≤ `stopTimeout`; `healthCheckGracePeriodSeconds`; `base` on-demand under Spot |
| Performance Efficiency | ENI trunking, prefer-cached pulls, SOCI, Graviton | Service Connect agent per task | trunking on EC2, SOCI indexes for large images, right-size with Container Insights |
| Cost Optimization | Fargate Spot with interruption handling; Managed Instances fee vs ops time | agent overhead; data transfer between AZs through the ALB | AZ-affine routing where possible; scale-in tuned |
| Sustainability | bin-packing on EC2; scale to zero in dev | none | `binpack` strategy with managed scaling |

## 6. Failure modes and troubleshooting

| Symptom | Likely cause | How to confirm (command/metric) | Fix |
| --- | --- | --- | --- |
| Tasks stop within seconds, `TaskFailedToStart`, `ResourceInitializationError` | execution role or endpoint path | `describe-tasks`; CloudTrail for the execution role; Reachability Analyzer to endpoints | fix role/endpoints ([playbook](../../playbooks/incidents/ecs-task-stopped-reasons.md)) |
| Task `RUNNING` but ALB target `unhealthy` | `/readyz` 503 (dependency down), SG, wrong port | `aws elbv2 describe-target-health` reason codes (`Target.ResponseCodeMismatch`, `Target.Timeout`) | fix dependency or SG ([playbook](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md)) |
| Application uses instance role permissions unexpectedly | IMDS reachable and no task role | CloudTrail `userIdentity.arn` shows the instance profile | task role + `ECS_AWSVPC_BLOCK_IMDS` ([playbook](../../playbooks/incidents/iam-accessdenied-from-containers.md)) |
| Deployment completes but clients see connection resets | Cloud Map TTL caching; app closes listener early | client errors align with `DEACTIVATING`; TTL value | Service Connect, or lower TTL and fix drain order |
| `PENDING` tasks on EC2 with `RESOURCE:ENI` | ENI limit without trunking | service events | enable `awsvpcTrunking`, larger instances |
| Spot tasks vanish, `SpotInterruption` | capacity reclaimed | task state change events | `base` on-demand, diversify, checkpoint work |
| Service Connect `503 UF` / `upstream connect error` in agent logs | destination not registered, SG between tasks, TLS role missing | agent log group; `aws servicediscovery discover-instances` | allow task SG ↔ task SG on the port; fix TLS role |
| Container exit 137 without `OutOfMemoryError` | SIGKILL after `stopTimeout` | timing vs SIGTERM in logs | drain faster or raise `stopTimeout` (≤120) ([playbook](../../playbooks/incidents/crashloop-and-exit-codes.md)) |
| Agent disconnected, tasks stuck | instance cannot reach ECS endpoints; agent OOM | `curl localhost:51678/v1/metadata`; `journalctl -u ecs` | endpoints; `ECS_RESERVED_MEMORY` |

## 7. Signals: metrics, logs, traces

- `ECS/ContainerInsights PendingTaskCount` sustained > 0: placement or start failures; read
  `stoppedReason`.
- Task-level `PullStartedAt`→`PullStoppedAt` (metadata) and Container Insights `ContainerInstanceCount`:
  image pull time and capacity headroom.
- `AWS/ECS/ManagedScaling CapacityProviderReservation` > 100: instances not keeping up.
- Service Connect per-pair metrics (5xx, response time, active connections, TLS errors): the
  client-side truth during deployments.
- `AWS/ApplicationELB UnHealthyHostCount`, `TargetConnectionErrorCount`, `HTTPCode_ELB_502_Count`
  vs `HTTPCode_Target_5XX_Count`.
- Agent logs (`/var/log/ecs/ecs-agent.log`) and `ECS Task State Change` / `ECS Container Instance
  State Change` events exported to CloudWatch Logs.
- Enhanced observability performance log events (`/aws/ecs/containerinsights/<cluster>/performance`)
  for per-container CPU/memory over time.
- Traces via the ADOT sidecar with `aws.ecs.task.arn`, `aws.ecs.launchtype` resource attributes.

Full table: [`reference/metrics-catalog.md`](../../reference/metrics-catalog.md).

## 8. Testing and DR notes

Testing:

- Fault injection with AWS FIS: `aws:ecs:stop-task` on a percentage of a service's tasks to verify
  replacement time and zero client errors; `aws:ecs:task-cpu-stress`, `task-io-stress`,
  `task-network-latency` (SSM-based actions inside tasks) to verify limits and timeouts.
- Deployment rehearsal: deploy a revision whose `/readyz` fails; confirm the circuit breaker's
  failure threshold and rollback time match expectations for your `desiredCount`.
- Credentials negative test: from ECS Exec, `curl -m 2 http://169.254.169.254/latest/meta-data/`
  must fail on Fargate and on EC2 with IMDS blocked.
- Service Connect drain test: run a load generator through a client alias during a deployment and
  count non-2xx.
- Locally, `make up` and `docker compose stop orders` reproduce the SIGTERM → drain → exit 0
  sequence with the same timeouts.

DR: nothing in this document is state. Task definitions, services, capacity providers and
namespaces are reproducible from CloudFormation; the only Region-bound artifacts are images
(replicate with ECR rules), Private CA (per Region), secrets (replicate) and the Cloud Map
namespace (recreated by the stack). A Region failover rebuilds the ECS layer in minutes; the data
tier decides the real RTO ([10 L300](../10-resilience-and-dr/L300-dr-strategies-for-container-platforms.md),
[region failover runbook](../../playbooks/dr/region-failover-runbook.md)).

## 9. Hands-on

```bash
# Local: watch the stop timeline with timestamps
make up
docker compose -f labs/local/compose.yaml logs -f orders &
docker compose -f labs/local/compose.yaml stop orders
# Observe: "shutdown signal received" then "stopped" within ~1 s (no in-flight work); compose
# waited up to stop_grace_period 30 s, the ECS equivalent of stopTimeout.

# AWS (after deploying labs/ecs/cloudformation with deploy.sh; billable):
# 1. Task start timeline from metadata timestamps
TASK=$(aws ecs list-tasks --cluster shopfront-dev --service-name orders --query 'taskArns[0]' --output text)
aws ecs describe-tasks --cluster shopfront-dev --tasks "$TASK" \
  --query 'tasks[0].{created:createdAt,pullStart:pullStartedAt,pullStop:pullStoppedAt,started:startedAt,connectivity:connectivityAt}'
# Observe: pull duration and the gap to startedAt (container start + health checks).

# 2. Credentials and metadata from inside the worker task
WT=$(aws ecs list-tasks --cluster shopfront-dev --service-name fulfillment-worker --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster shopfront-dev --task "$WT" --container worker --interactive \
  --command "sh -c 'curl -s http://169.254.170.2\$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI | python -c \"import sys,json; print(json.load(sys.stdin)[\\\"RoleArn\\\"])\"; curl -m 2 -s http://169.254.169.254/latest/meta-data/ || echo IMDS-blocked'"
# Observe: the task role ARN; IMDS-blocked on Fargate.

# 3. Stopped task forensics
aws ecs list-tasks --cluster shopfront-dev --desired-status STOPPED --query 'taskArns' --output text | tr '\t' '\n' | head -3 \
  | xargs -I{} aws ecs describe-tasks --cluster shopfront-dev --tasks {} \
      --query 'tasks[0].{code:stopCode,reason:stoppedReason,exit:containers[0].exitCode}'

# 4. Service Connect view
aws servicediscovery list-namespaces --query 'Namespaces[?Name==`shopfront.local`]'
aws servicediscovery discover-instances --namespace-name shopfront.local --service-name orders \
  --query 'Instances[].Attributes.AWS_INSTANCE_IPV4'
# Observe: one IP per RUNNING orders task; the list shrinks during a deployment before the tasks stop.
```

## 10. Check yourself

1. A task stops with `stopCode: TaskFailedToStart` and `stoppedReason: ResourceInitializationError:
   unable to pull secrets or registry auth`. Which role and which network path do you check, and
   why is the application's own IAM policy irrelevant?

<details><summary>Answer</summary>
The execution role: it fetches `secrets[]` and the image before any container runs. Check its
`secretsmanager:GetSecretValue`, `kms:Decrypt`, `ecr:GetAuthorizationToken`/`BatchGetImage`/
`GetDownloadUrlForLayer` permissions and the path from the task subnet to Secrets Manager and ECR
(NAT or interface endpoints plus the S3 gateway endpoint). The task role is only used by the
application after start, so it cannot be the cause of a start failure.
</details>

2. Why can an EC2 task with no task role end up with the instance profile's permissions, and what
   two settings prevent it?

<details><summary>Answer</summary>
The SDK credential chain falls through to IMDS when the container credentials endpoint is not
configured. On EC2 the task's network namespace can reach `169.254.169.254` by default. Give every
task a task role (even an empty one) so the endpoint is configured, and set
`ECS_AWSVPC_BLOCK_IMDS=true` (awsvpc) or IMDSv2 hop limit 1 (bridge) so IMDS is unreachable.
</details>

3. During a deployment on Cloud Map DNS discovery, clients see connection errors for about 15
   seconds per replaced task. Service Connect removes most of them. Explain both behaviours.

<details><summary>Answer</summary>
With DNS discovery, Cloud Map deregisters the task, but clients that resolved the name keep the
cached answer until the TTL (10–15 s) expires and connect to a task that is stopping. With Service
Connect, the agent resolves at request time from Cloud Map and the destination's agent stops
accepting new connections at `DEACTIVATING` while draining existing ones, so clients are steered to
healthy tasks per request rather than per DNS answer.
</details>

4. A c5.large EC2 cluster reports `RESOURCE:ENI` placement failures at two tasks per instance.
   What limits you and what fixes it?

<details><summary>Answer</summary>
In `awsvpc` every task needs its own ENI; a c5.large supports three ENIs, one of which is the
instance's primary. Enable ENI trunking (`awsvpcTrunking` account setting) so the agent attaches
branch ENIs to a trunk (about ten tasks on a c5.large), use larger Nitro instances, or move the
service to Fargate where every task gets its own ENI without instance limits.
</details>

5. Where does TLS begin and end with Service Connect, and what does the application see?

<details><summary>Answer</summary>
The client task's Service Connect agent starts TLS and the destination task's agent terminates it,
using certificates issued and rotated by ECS from the AWS Private CA you configured. The
application connects to and listens on plaintext localhost ports; it never handles certificates.
</details>

## 11. Sources

- Amazon ECS task lifecycle — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-lifecycle-explanation.html
- View stopped task errors (`stoppedReason` reference) — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/stopped-task-error-codes.html
- Amazon ECS container agent configuration — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-agent-config.html
- Amazon ECS container agent introspection — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-agent-introspection.html
- Task metadata endpoint version 4 — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint-v4.html
- Task IAM role (credentials endpoint) — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html
- AWS Fargate platform versions — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/platform_versions.html
- Fargate task ephemeral storage and EBS volumes — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-storage.html
- Amazon ECS Managed Instances — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-instances-capacity-providers-concept.html
- Elastic network interface trunking — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/container-instance-eni.html
- Service Connect concepts and TLS — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-connect-concepts.html and https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-connect-tls.html
- Service discovery with AWS Cloud Map — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-discovery.html
- Task placement (strategies, constraints, error messages) — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-placement.html
- Amazon ECS Anywhere — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-anywhere.html
- Container Insights with enhanced observability for Amazon ECS — https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-ECS.html
- Amazon ECS events with EventBridge — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs_cwe_events.html
- AWS Fault Injection Service actions for ECS — https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html
