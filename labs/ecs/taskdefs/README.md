# Standalone task definitions

The four JSON files here are the `register-task-definition` form of the task definitions that
`labs/ecs/cloudformation/04-services.yaml` and `06-batch.yaml` create. They exist so you can read a
complete, hardened task definition field by field without CloudFormation intrinsics in the way, and
so you can register one by hand when experimenting:

```bash
aws ecs register-task-definition --cli-input-json file://orders.json
aws ecs run-task --cluster shopfront-dev --launch-type FARGATE --task-definition shopfront-dev-report-job \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-0a1b2c3d4e5f6a7b8],securityGroups=[sg-0123456789abcdef0],assignPublicIp=DISABLED}"
```

Replace `123456789012`, the `@sha256:000…` digests and the Valkey endpoint with your values (the
CloudFormation templates fill them in for you; these files are documentation-grade copies).

| File | Family | Runs as | Notes |
| --- | --- | --- | --- |
| `orders.json` | `shopfront-dev-orders` | ECS service behind the ALB | Node 22; container health check with `node -e fetch(...)`; OTel sidecar |
| `catalog.json` | `shopfront-dev-catalog` | ECS service behind the ALB | Go on distroless; no container health check (no shell in the image), the ALB target health on `/readyz` is the health signal |
| `worker.json` | `shopfront-dev-fulfillment-worker` | ECS service, Fargate Spot weighted | Python SQS consumer; `command` selects the entrypoint of the shared worker image |
| `report-job.json` | `shopfront-dev-report-job` | one-off task or AWS Batch job | Run-to-completion; no port, no health check, longer `stopTimeout` |

## Field by field

| Field | Value here | Why |
| --- | --- | --- |
| `family` | `shopfront-<env>-<service>` | Revisions are numbered inside a family; services reference `family:revision` |
| `networkMode` | `awsvpc` | Required on Fargate; each task gets its own ENI, security group and private IP (hub/03 L200 §2.3) |
| `requiresCompatibilities` | `["FARGATE"]` | Validates the definition against Fargate constraints at registration time |
| `runtimePlatform` | `ARM64` / `LINUX` | Graviton is cheaper per vCPU; all four images are multi-arch (hub/01 L200 §2.4) |
| `cpu` / `memory` (task) | `512`/`1024` etc. | Fargate bills on these; valid pairs only (0.25 vCPU with 0.5–2 GB, 0.5 vCPU with 1–4 GB, ...) |
| `ephemeralStorage.sizeInGiB` | `21` | Fargate default is 20 GiB; 21 makes the setting explicit and shows where to grow it |
| `executionRoleArn` | `shopfront-<env>-task-execution` | Used by the ECS agent: ECR pull, CloudWatch Logs, Secrets Manager reads (hub/06 L200 §2.1) |
| `taskRoleArn` | per service | Credentials your code receives through `169.254.170.2`; least privilege per service |
| `volumes` + `mountPoints` | `tmp` at `/tmp` | The root filesystem is read-only; the process still needs a writable scratch directory |
| `containerDefinitions[].cpu` | `384` for orders | CPU shares between containers of the same task; the OTel sidecar gets the rest |
| `memoryReservation` | `512` for orders | Soft limit used for placement; the task `memory` is the hard limit that triggers OOM kills |
| `portMappings[].name` + `appProtocol` | `http` | Service Connect discovers ports by name and applies HTTP-aware metrics and retries |
| `environment` | contract variables | Non-secret configuration from `labs/CONTRACT.md` |
| `secrets[].valueFrom` | Secrets Manager ARN | Injected at start by the agent using the execution role; never in `environment` |
| `dependsOn` | `otel-collector: HEALTHY` | The app starts after the collector is healthy so the first spans are not lost |
| `healthCheck` | `/healthz` probe | Container-level liveness; ECS restarts (replaces) the task when it fails `retries` times |
| `stopTimeout` | `30` (job: `60`) | Time between SIGTERM and SIGKILL; must exceed the app's 20 s drain plus the ALB deregistration delay (hub/10 L200 §2.4) |
| `user` | `10001:10001` | Matches the uid in the Dockerfiles; a numeric id is required for `runAsNonRoot`-style guarantees |
| `readonlyRootFilesystem` | `true` | Blocks writes outside declared volumes; a compromised process cannot drop binaries |
| `linuxParameters.initProcessEnabled` | `true` | Runs a tiny init as PID 1 so zombies are reaped and signals are forwarded (hub/01 L200 §2.6) |
| `linuxParameters.capabilities.drop` | `ALL` | None of these services needs a Linux capability |
| `ulimits.nofile` | `65536` | Node keeps many sockets open under load; the Fargate default soft limit of 1024 (hard 65535) is low for a busy HTTP server |
| `logConfiguration` | `awslogs`, `non-blocking`, `25m` buffer | Blocking mode stalls the app when CloudWatch Logs is slow; non-blocking drops logs instead, which is the better failure |
| `tags` | `Project`, `Environment`, `Service` | Propagated to tasks by the service (`propagateTags: SERVICE`) for cost allocation |

## What is different on Kubernetes

The same intent expressed as a Pod spec lives in `labs/eks/manifests/base/`. The mapping:
`taskRoleArn` becomes a ServiceAccount with a Pod Identity association; `readonlyRootFilesystem`,
`user` and `capabilities` become `securityContext`; `healthCheck` becomes `livenessProbe` and the
ALB health check becomes `readinessProbe`; `stopTimeout` becomes `terminationGracePeriodSeconds`;
`cpu`/`memory` become `resources.requests` and `resources.limits`.
