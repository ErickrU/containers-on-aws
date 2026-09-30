# 10 · Resilience and disaster recovery

Resilience is what a container platform does when something fails without anyone deciding anything:
a task dies and is replaced, an AZ degrades and traffic moves, a dependency slows and callers back off.
Disaster recovery is what the organisation does when the automatic mechanisms are not enough: a
Region is impaired, data is corrupted, a cluster is lost. Containers make the compute half of both
problems easy — stateless, replaceable, rebuildable from images and code — and push the hard half
into data, DNS and the discipline of rehearsing. This domain owns the mechanisms (replicas, spread,
disruption budgets, probes, graceful shutdown, autoscaling layers, retries and circuit breakers,
fault injection, zonal shift), the strategies (backup/restore, pilot light, warm standby,
active/active), the plan (tiers, RTO/RPO, roles, failover criteria) and the game days that prove it.
`shopfront` is the worked example throughout.

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 Resilience basics](L100-resilience-basics.md) | AZs and Regions; why multi-AZ is the default; health checks and restarts; replicas; RTO and RPO; the four DR strategies by name |
| 200 | [L200 Designing for failure](L200-designing-for-failure.md) | Replicas and spread, PDBs, the autoscaling layers on EKS and ECS, the graceful-shutdown timeline, probes and health checks, retries/timeouts/circuit breakers/bulkheads, dependency failure handling, AWS FIS, ARC zonal shift |
| 300 | [L300 DR strategies for container platforms](L300-dr-strategies-for-container-platforms.md) | The four strategies applied to ECS and EKS; what state exists and where; ECR replication, Velero, snapshots, MSK Replicator, secrets and KMS; Route 53 and ARC; cluster rebuild automation; RTO/RPO math |
| 400 | [L400 DR plan and game days](L400-dr-plan-and-game-days.md) | The DR plan document itself, runbook structure, failover and failback, game-day design, multi-Region reference architectures, pitfalls, cost, readiness metrics |

## Components covered

- Availability Zones, Regions, the shared-responsibility split for resilience on Fargate/EC2/EKS/Auto
  Mode — L100 §2.1–2.2
- Health checks and restarts: ECS container/ELB health checks and `healthCheckGracePeriodSeconds`;
  Kubernetes startup/readiness/liveness probes — L100 §2.3, L200 §2.4
- Replicas, topology spread constraints, anti-affinity, ECS placement strategies, three-AZ headroom —
  L200 §2.1
- PodDisruptionBudgets and voluntary disruption (drains, Karpenter, Auto Mode node replacement) —
  L200 §2.2
- Autoscaling layers: HPA, VPA, KEDA, Cluster Autoscaler, Karpenter, Auto Mode; ECS service auto
  scaling and capacity providers — L200 §2.3
- Graceful shutdown: SIGTERM, `preStop`, `terminationGracePeriodSeconds`, ECS `stopTimeout`, ALB
  deregistration delay, connection draining — L200 §2.5
- Client resilience: timeouts, retries with jitter, circuit breakers, bulkheads, rate limiting,
  idempotency, fallbacks — L200 §2.6–2.7
- AWS Fault Injection Service (ECS, EKS, EC2, network actions) — L200 §2.8, L400 §2.5
- Amazon Application Recovery Controller: zonal shift and autoshift, readiness checks, routing
  controls — L200 §2.9, L300 §2.6
- DR strategies: backup and restore, pilot light, warm standby, multi-site active/active — L100 §2.5,
  L300 §2.1
- State inventory: images (ECR replication), IaC and GitOps repos, Kubernetes objects and PVs (Velero,
  EBS snapshots), secrets (Secrets Manager replication, KMS multi-Region keys), certificates (ACM,
  Private CA), databases (RDS/Aurora), caches, queues (SQS regional scope), streams (MSK Replicator),
  S3 (CRR), DNS — L300 §2.2–2.5
- Route 53 health checks and failover routing; Global Accelerator — L300 §2.6
- Cluster and environment rebuild automation and timing — L300 §2.7
- RTO/RPO arithmetic per tier — L300 §2.8
- The DR plan: tiers, dependency map, roles, communications, decision criteria, failover and
  failback procedures — L400 §2.1–2.3
- Game days: design, cadence, scoring, follow-ups — L400 §2.4–2.5
- Multi-Region reference architectures for ECS and EKS; pitfalls (quotas, AMIs, IAM/OIDC per Region,
  secrets, data reconciliation); cost of DR; readiness metrics — L400 §2.6–2.9

## Related

- Labs: [`labs/ecs/cloudformation/`](../../labs/ecs/cloudformation/) (multi-AZ layout, deployment
  configuration, alarms) and [`labs/eks/manifests/base/`](../../labs/eks/manifests/base/) (PDBs,
  topology spread, probes, `preStop`), [`labs/local/compose.yaml`](../../labs/local/compose.yaml)
  (graceful shutdown with `stop_grace_period`).
- Playbooks: [DR plan template](../../playbooks/dr/dr-plan-template.md),
  [Region failover runbook](../../playbooks/dr/region-failover-runbook.md),
  [Cluster rebuild runbook](../../playbooks/dr/cluster-rebuild-runbook.md),
  [Data recovery runbook](../../playbooks/dr/data-recovery-runbook.md),
  [Game-day guide](../../playbooks/dr/game-day-guide.md),
  [ALB 5xx and unhealthy targets](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md),
  [Pending pods and capacity](../../playbooks/incidents/pending-pods-and-capacity.md).
- Reference: [decision guides](../../reference/decision-guides.md), [metrics catalog](../../reference/metrics-catalog.md),
  [quotas and limits](../../reference/quotas-and-limits.md).
- Neighbouring domains: [03 ECS](../03-ecs/README.md) and [04 EKS](../04-eks/README.md)
  (deployment and scheduling mechanics), [05 Networking](../05-networking/README.md) (zonal
  isolation, DNS), [07 Observability](../07-observability/README.md) (the alarms that trigger
  everything here), [09 Data, messaging and batch](../09-data-messaging-and-batch/README.md) (where
  RPO lives), [11 Testing workloads](../11-testing-workloads/README.md) (chaos and DR tests).
