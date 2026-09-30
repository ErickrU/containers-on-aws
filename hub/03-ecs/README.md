# 03 · Amazon ECS

Amazon ECS is the AWS-native container orchestrator: you describe a group of containers in a task
definition, ECS runs copies of it as tasks on capacity you choose (Fargate, EC2 you manage, ECS
Managed Instances, or your own machines through ECS Anywhere) and keeps the right number alive
behind a load balancer as a service. There is no control plane for you to operate, the API is the
AWS API, and every object is an IAM-governed, CloudTrail-logged resource. This domain is its own
because ECS has a vocabulary, a scheduler, an agent and a set of deployment mechanics that are
different from Kubernetes in ways that matter when you build, operate and scale on it. Everything
here uses the `shopfront` system from [`labs/CONTRACT.md`](../../labs/CONTRACT.md) as the running
example.

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 ECS basics](L100-ecs-basics.md) | The object model (cluster, task definition, task, service, scheduled task); what Fargate, EC2, Managed Instances and Express Mode are and how each is billed; what "Docker for ECS" means and which tools were retired; a first deployment behind an ALB; when ECS rather than EKS |
| 200 | [L200 Task definitions, services and scaling](L200-task-definitions-services-and-scaling.md) | Every task definition field that matters, with a complete annotated `orders` example; task role vs execution role; network modes; Service Connect vs Cloud Map vs ALB; target groups and the shutdown timeline; service auto scaling; capacity providers; every deployment type; ECS Exec; scheduled tasks; placement |
| 300 | [L300 ECS internals](L300-ecs-internals.md) | Task lifecycle states and the `stoppedReason`/`stopCode` catalog; the ECS agent and Docker Engine on EC2; task metadata and credentials at `169.254.170.2`; IMDS rules; Fargate and Firecracker; Managed Instances internals; ENI trunking; Service Connect proxy and Cloud Map DNS internals; deregistration vs SIGTERM; the placement engine; forensics commands |
| 400 | [L400 ECS at scale](L400-ecs-at-scale.md) | Multi-account, multi-Region and cell-based ECS; capacity planning and a cost model with numbers; deployment safety for large fleets; App Mesh end-of-support migration; failure stories; DR posture; a Well-Architected review; when to move to EKS |

## Components covered

- Cluster, task definition (family and revision), container definition, task, service, deployment,
  scheduled task, container instance, capacity provider, namespace — L100 §2, L200 §2
- Capacity: AWS Fargate and Fargate Spot, EC2 launch type and Auto Scaling group capacity providers
  (managed scaling, managed draining, managed termination protection), ECS Managed Instances,
  ECS Anywhere (`EXTERNAL`), ECS Express Mode — L100 §2, L200 §2.7, L300 §2.5–2.7
- "Docker for ECS": ECS agent driving Docker Engine on ECS-optimized Amazon Linux 2023 and
  Bottlerocket AMIs; Firecracker microVMs and containerd on Fargate; the retired Docker Compose ECS
  integration and Copilot CLI and what replaces them — L100 §2.4, L300 §2.2 and §2.5
- Task definition fields: `cpu`/`memory` at task and container level, `essential`, `dependsOn`,
  `healthCheck`, `stopTimeout`, `ulimits`, `linuxParameters`, `user`, `readonlyRootFilesystem`,
  `portMappings` (`name`, `appProtocol`), `environment` vs `secrets`, `logConfiguration` (`awslogs`,
  FireLens), `ephemeralStorage`, volumes (bind, EFS, EBS), `runtimePlatform`, `restartPolicy`,
  `versionConsistency` — L200 §2.1
- Task role vs task execution role; infrastructure roles — L200 §2.2
- Network modes `awsvpc`, `bridge`, `host`, `none`; ENI trunking (`awsvpcTrunking`) — L200 §2.3,
  L300 §2.7
- Service Connect (Envoy agent, Cloud Map namespace, `portName`, `discoveryName`, `clientAliases`,
  timeouts, TLS with AWS Private CA, metrics) — L200 §2.4, L300 §2.8
- Cloud Map service discovery (A and SRV records, TTLs, health) — L200 §2.4, L300 §2.9
- ALB and NLB target groups, health checks, `healthCheckGracePeriodSeconds`, deregistration delay
  and its interaction with SIGTERM and `stopTimeout` — L200 §2.5, L300 §2.10
- Service auto scaling: target tracking (CPU, `ALBRequestCountPerTarget`, SQS backlog per task),
  step, scheduled, predictive — L200 §2.6
- Deployments: rolling (`minimumHealthyPercent`/`maximumPercent`), deployment circuit breaker,
  CloudWatch alarm rollback, native blue/green with lifecycle hooks, canary, pause/continue,
  CodeDeploy (legacy), `EXTERNAL` task sets — L200 §2.8, L400 §2.5
- ECS Exec over SSM Session Manager — L200 §2.9
- Scheduled and standalone tasks: EventBridge Scheduler, `run-task` — L200 §2.10
- Placement strategies and constraints, cluster query language, daemon scheduling, Availability
  Zone rebalancing — L200 §2.11, L300 §2.11
- Task lifecycle states, `stopCode` and `stoppedReason` catalog, exit codes — L300 §2.1
- ECS agent: `ECS_*` configuration, container instance registration, introspection port 51678,
  credentials proxy port 51679, draining — L300 §2.2
- Task metadata endpoint v4 and task-role credentials at link-local `169.254.170.2`;
  `ECS_CONTAINER_METADATA_URI_V4`, `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` — L300 §2.3
- IMDS access rules per platform (`ECS_AWSVPC_BLOCK_IMDS`, hop limit) — L300 §2.4
- Fargate internals: platform versions, task ENI, ephemeral storage 20–200 GiB, EBS attach, what is
  not supported, Fargate Spot interruption — L300 §2.5
- Managed Instances internals: AWS-operated instances in your account, instance selection,
  patching by replacement, capacity provider attributes — L300 §2.6
- Container Insights for ECS, ADOT and X-Ray sidecar patterns — L300 §2.14 (depth in domain 07)
- AWS App Mesh end of support (2026-09-30) and migration to Service Connect or VPC Lattice — L400 §2.6
- Multi-account/multi-Region topology, cells, capacity planning, cost model, DR posture,
  Well-Architected review, ECS-to-EKS triggers — L400

## Related

- Labs: [`labs/ecs/cloudformation/`](../../labs/ecs/cloudformation/) (network, cluster, data,
  services, observability, batch stacks with a confirmation-gated `deploy.sh`),
  [`labs/ecs/taskdefs/`](../../labs/ecs/taskdefs/) (one annotated task definition per service),
  [`labs/batch/`](../../labs/batch/) (AWS Batch on ECS/Fargate for `report-job`),
  [`labs/local/compose.yaml`](../../labs/local/compose.yaml) (the same system on your laptop).
- Playbooks: [ECS task stopped reasons](../../playbooks/incidents/ecs-task-stopped-reasons.md),
  [ECS deployment stuck or rolled back](../../playbooks/incidents/ecs-deployment-stuck-or-rolled-back.md),
  [ALB 5xx and unhealthy targets](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md),
  [IAM AccessDenied from containers](../../playbooks/incidents/iam-accessdenied-from-containers.md),
  [Image pull failures](../../playbooks/incidents/image-pull-failures.md),
  [OOM and CPU throttling](../../playbooks/incidents/oom-and-cpu-throttling.md),
  [ECS AMI, agent and platform upgrades](../../playbooks/upgrades/ecs-ami-agent-and-platform.md),
  [Region failover runbook](../../playbooks/dr/region-failover-runbook.md).
- Reference: [decision guides](../../reference/decision-guides.md) (ECS vs EKS, Fargate vs EC2 vs
  Managed Instances, Service Connect vs Cloud Map vs mesh),
  [metrics catalog](../../reference/metrics-catalog.md),
  [quotas and limits](../../reference/quotas-and-limits.md),
  [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md),
  [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md),
  [CLI cheat sheet](../../reference/cli-cheatsheet.md).
- Neighbouring domains: [02 ECR](../02-ecr/README.md) for the images ECS pulls,
  [05 Networking](../05-networking/README.md) for VPC, ELB and link-local depth,
  [06 Identity and security](../06-identity-and-security/README.md) for roles and secrets,
  [07 Observability](../07-observability/README.md) for Container Insights and OpenTelemetry,
  [08 Delivery](../08-delivery-cicd-gitops/README.md) for pipelines that deploy to ECS,
  [10 Resilience and DR](../10-resilience-and-dr/README.md) for the strategies ECS DR builds on.
