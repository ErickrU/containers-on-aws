# Lifecycle and deprecations

Dates that decide what you may still build on and what you must migrate off. Everything here is
taken from [`docs/FACTS-2026-09.md`](../docs/FACTS-2026-09.md) (verified 2026-09-29); when this file
and a vendor page disagree, the vendor page is newer. Re-verify before planning: version calendars
move.

## Kubernetes versions on EKS

Standard support lasts 14 months from the EKS release; extended support adds 12 months at an
extra hourly fee per cluster. Clusters at end of extended support are upgraded automatically.

| Version | Kubernetes release | EKS release | End of standard support | End of extended support | State on 2026-09-29 |
| --- | --- | --- | --- | --- | --- |
| 1.36 | 2026-04-22 | 2026-06-02 | 2027-08-02 | 2028-08-02 | newest; default for new clusters in the labs |
| 1.35 | 2025-12-17 | 2026-01-27 | 2027-03-27 | 2028-03-27 | standard |
| 1.34 | 2025-08-27 | 2025-10-02 | 2026-12-02 | 2027-12-02 | standard; plan the upgrade |
| 1.33 | 2025-04-23 | 2025-05-29 | 2026-07-29 | 2027-07-29 | **extended (fee)** |
| 1.32 | 2024-12-11 | 2025-01-23 | 2026-03-23 | 2027-03-23 | **extended (fee)** |
| 1.31 | 2024-08-13 | 2024-09-26 | 2025-11-26 | 2026-11-26 | **extended; forced upgrade in two months** |

Migration pointer: [eks-version-upgrade runbook](../playbooks/upgrades/eks-version-upgrade.md); one
minor per step; check `aws eks list-insights` and removed APIs first. Note that 1.33 made the nftables
kube-proxy backend GA and 1.36 made in-place pod resize and PSI metrics available; upgrades change
behaviour, not only version numbers ([04 · L300](../hub/04-eks/L300-eks-internals-and-operations.md)).

## Operating systems and AMIs

| Item | Date | Consequence | Migrate to |
| --- | --- | --- | --- |
| EKS-optimized Amazon Linux 2 AMIs | end of support **2025-11-26** | no new AMIs, no patches, unsupported on new Kubernetes versions | AL2023 (`nodeadm`-based bootstrap) or Bottlerocket; managed node group `amiFamily: AmazonLinux2023` |
| ECS-optimized Amazon Linux 2 AMIs | end of standard support **2026-06-30** | agent version pinned, no OS patches afterwards | ECS-optimized AL2023 or Bottlerocket ([ecs-ami runbook](../playbooks/upgrades/ecs-ami-agent-and-platform.md)) |
| AWS Batch default AMI | AL2023 for new EKS compute environments since 2025-10-27 and new ECS compute environments since 2026-01-12 | existing environments keep their AMI until you update them | recreate compute environments or update the launch template |
| EKS Auto Mode EBS volume-modification annotations | stop working after **2026-10-31** | `ebs.csi.aws.com/...` annotations on PVCs are ignored | `VolumeAttributesClass` objects |

## Services and features reaching end of support

| Item | Date | What stops | Migrate to |
| --- | --- | --- | --- |
| AWS App Mesh | end of support **2026-09-30** (tomorrow relative to the facts date) | console and resources go away; Envoy sidecars keep running until you remove them | ECS Service Connect ([03 · L300 §2.7](../hub/03-ecs/L300-ecs-internals.md)); Cilium or Istio mesh on EKS; VPC Lattice for cross-VPC/account ([05 · L300 §2.9](../hub/05-networking/L300-container-networking-internals.md), [03 · L400 §2.5](../hub/03-ecs/L400-ecs-at-scale.md)) |
| AWS Copilot CLI | end of support **2026-06-12**; repository archived 2026-06-22 | no releases, no fixes | CloudFormation/CDK/Terraform with ECS native deployments (`labs/ecs/cloudformation`), ECS Express Mode for simple web services |
| Docker Compose ECS integration (`docker context create ecs`) | retired **2023-11**; compose-cli end of life 2024-01-01 | `docker compose up` cannot target ECS | Compose stays a local tool (`labs/local/compose.yaml`); deploy with IaC |
| `aws-auth` ConfigMap authentication | superseded by access entries (2023-12); still works in `API_AND_CONFIG_MAP` mode | new clusters should not use it; lock-outs are hard to recover | `authenticationMode: API` and access entries ([eks-auth runbook](../playbooks/incidents/eks-auth-and-access.md)) |
| IRSA as the default pod identity | not deprecated, but Pod Identity (2023-11) is the recommended path | IRSA still required for Fargate profiles | EKS Pod Identity ([06 · L200 §2.3](../hub/06-identity-and-security/L200-iam-for-containers.md)) |
| X-Ray SDKs and daemon | maintenance; AWS published migration guidance to ADOT/OpenTelemetry (2025-11) | new features (Application Signals, Transaction Search) land on OTel | OpenTelemetry SDKs + ADOT collector ([07 · L200 §2.4](../hub/07-observability/L200-tooling-on-aws.md)) |
| CodeDeploy blue/green for ECS | still supported, but ECS native blue/green (2025-07) with lifecycle hooks, canary (2025-11) and pause/continue (2026-05) covers the same needs inside ECS | two systems to reason about | ECS native deployment strategies ([08 · L300 §2.1](../hub/08-delivery-cicd-gitops/L300-progressive-delivery-and-gitops-internals.md)) |
| Cluster Autoscaler on EKS | not deprecated; superseded in practice | ASG-bound scaling, slower and coarser | Karpenter or EKS Auto Mode ([decision guide](decision-guides.md)) |
| ECS Fargate platform version 1.3.0 (Linux) | retired; `1.4.0` is `LATEST` | tasks pinned to old versions were migrated by AWS | keep `PlatformVersion: LATEST` unless pinning for a rollback window |
| Redis OSS 7.x on ElastiCache | supported, but Valkey (since 2024-10) is the default engine for new caches with lower pricing | none forced | Valkey (`labs/ecs/cloudformation/03-data.yaml` uses it) |
| MSK ZooKeeper-mode clusters | KRaft is the default for new Provisioned clusters; Express brokers (2024-11) and Serverless are KRaft-only | ZooKeeper metrics and ports disappear | KRaft clusters; `labs/local/compose.yaml` runs Kafka 3.9 in KRaft mode |
| Kubernetes `v1beta1` APIs removed across 1.25–1.36 (PodSecurityPolicy, `batch/v1beta1` CronJob, `autoscaling/v2beta2`, `policy/v1beta1` PDB, `flowcontrol` betas, `resource.k8s.io` alphas) | removed at their announced versions | manifests and Helm charts fail to apply after upgrade | `kubent`/`pluto` before each upgrade; `apiserver_requested_deprecated_apis` metric |

## Newer building blocks and when they arrived (so you know what to expect in older documentation)

| Feature | Available since | Where the lab uses it |
| --- | --- | --- |
| EKS Auto Mode | GA 2024-12; 2026 additions (zonal shift, EFA, node-local DNS, separate pod subnets, KMS full-disk encryption) | `labs/eks/cluster/eksctl-auto-mode.yaml` |
| EKS Capabilities (Argo CD, ACK, kro) | 2025-11; `argocd-cm` customisation 2026-08 | `labs/eks/gitops/` targets either self-managed Argo CD or the capability |
| EKS Hybrid Nodes | GA 2024-12 | not used in the lab |
| ECS Managed Instances | 2025-09/10; Capacity Reservations 2026-02 | discussed in [03 · L300 §2.5](../hub/03-ecs/L300-ecs-internals.md) |
| ECS Express Mode | 2025-11; GovCloud 2026-06 | [03 · L100 §2.4](../hub/03-ecs/L100-ecs-basics.md) |
| ECS native blue/green, canary, pause/continue, real-time deployment view | 2025-07, 2025-11, 2026-05, 2026-09 | `04-services.yaml` uses rolling + circuit breaker + alarms; L300 covers the rest |
| Service Connect timeouts and TLS with Private CA | 2024-01 | `04-services.yaml` `Timeout` block |
| Container Insights with enhanced observability | EKS 2023-11, ECS 2024-12 | `02-cluster.yaml` (`containerInsights: enhanced`), CloudWatch Observability add-on |
| ECR pull-through cache upstreams in GovCloud / European Sovereign Cloud | 2026-05 | [02 · L300](../hub/02-ecr/L300-pull-through-cache-replication-and-limits.md) |
| Kubernetes 1.36 (in-place resize beta, PSI GA, MutatingAdmissionPolicy GA) | 2026-04 | `eksctl-*.yaml` `version: "1.36"` |

## How to keep this table honest

```bash
aws eks describe-addon-versions --kubernetes-version 1.36 --query 'addons[*].[addonName,addonVersions[0].addonVersion]' --output table
aws eks describe-cluster-versions --query 'clusterVersions[*].[clusterVersion,status,endOfStandardSupportDate,endOfExtendedSupportDate]' --output table
aws ssm get-parameter --name /aws/service/eks/optimized-ami/1.36/amazon-linux-2023/arm64/standard/recommended/release_version --query Parameter.Value --output text
aws ssm get-parameter --name /aws/service/ecs/optimized-ami/amazon-linux-2023/arm64/recommended --query Parameter.Value --output text
aws health describe-events --filter eventTypeCategories=scheduledChange --query 'events[*].[service,eventTypeCode,startTime]' --output table   # deprecation notices land here
```

Review this file at every quarterly game day ([game-day-guide](../playbooks/dr/game-day-guide.md)) and
whenever `docs/FACTS-2026-09.md` is superseded by a newer facts sheet.
