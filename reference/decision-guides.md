# Decision guides

Each guide is a table you can read in two minutes, followed by the default choice for a team like
the one running shopfront. The trade-offs behind each row are argued in the hub
([12 · L400](../hub/12-well-architected/L400-trade-offs-and-anti-patterns.md) holds the decision records).
"Default" means "pick this unless a row in the table applies to you", not "always".

## ECS vs EKS

| Consider | ECS | EKS |
| --- | --- | --- |
| Team's Kubernetes experience | none needed; AWS-native API | required; the API surface is Kubernetes plus AWS |
| Portability / ecosystem | AWS-only; fewer third-party tools | CNCF ecosystem (Helm, Argo, KEDA, Cilium, operators) |
| Operational surface | cluster is a namespace; no versions to upgrade | control plane and add-on versions every ~4 months; node lifecycle |
| Cost | no control plane fee; Fargate premium; Express Mode for simple web apps | cluster fee + Auto Mode fee or node management; better bin-packing at scale |
| Advanced scheduling, sidecar patterns, custom controllers | limited (task definition model) | native |
| Batch / stateful / GPU workloads | via Batch, EBS volumes limited | StatefulSets, operators, device plugins |
| Multi-tenancy | account/cluster boundaries | namespaces + policies + RBAC inside one cluster |
| Delivery | CloudFormation/CDK/Terraform + native blue/green | GitOps (Argo CD, Capability), Rollouts |

Default: ECS on Fargate for a team without Kubernetes skills running HTTP services and workers;
EKS when you need the ecosystem, run many teams on one platform, or already operate Kubernetes.
Both in one company is normal; both for one team is a tax. Mechanisms: [03 · L100](../hub/03-ecs/L100-ecs-basics.md), [04 · L100](../hub/04-eks/L100-kubernetes-and-eks-basics.md).

## Fargate vs EC2 vs ECS Managed Instances vs EKS Auto Mode

| Consider | Fargate | EC2 (self-managed nodes / ASG) | ECS Managed Instances | EKS Auto Mode |
| --- | --- | --- | --- | --- |
| Who patches the host | AWS | you | AWS (instances in your account) | AWS (Bottlerocket, ≤ 21-day nodes) |
| Isolation | microVM per task/pod | shared kernel per instance | shared kernel, AWS-managed | shared kernel, AWS-managed |
| Price per vCPU-hour | highest; Spot available | lowest with Savings Plans/Spot | EC2 price + management fee | EC2 price + Auto Mode fee |
| Bin-packing | one task = one VM; no waste inside the task, no sharing | you (Karpenter/capacity providers) | AWS | AWS (Karpenter) |
| Daemons, privileged, GPUs, host access | no | yes | limited | limited (no DaemonSet control on managed components) |
| Start-up latency | 30–60 s (image pull dominates; SOCI helps) | seconds when a node has room; minutes for new nodes | minutes for new instances | minutes for new nodes; consolidation moves pods |
| Networking | ENI per task (IPs) | ENI trunking / prefix delegation | AWS-configured | VPC CNI managed |

Default: Fargate for services and workers under a few hundred vCPUs or where isolation matters;
Managed Instances / Auto Mode when the bill or start-up latency argues for shared hosts but you do not
want to patch them; raw EC2 only for daemons, GPUs, kernel tuning or very large steady fleets with
Savings Plans. [03 · L400 §2.3](../hub/03-ecs/L400-ecs-at-scale.md), [04 · L400 §2.3](../hub/04-eks/L400-eks-at-scale.md).

## ALB vs NLB vs API Gateway vs VPC Lattice (ingress)

| Consider | ALB | NLB | API Gateway (HTTP API + VPC Link) | VPC Lattice |
| --- | --- | --- | --- | --- |
| Layer | 7 HTTP/HTTPS/gRPC | 4 TCP/UDP/TLS | 7 with API features | 7 service network across VPCs/accounts |
| Routing | host/path/header/query/weighted | port only | routes, stages | service network, auth policies |
| Auth at the edge | OIDC/Cognito, WAF | none (TLS termination) | JWT/IAM/Lambda authorizers, throttling, keys | IAM auth policies |
| Static IP / PrivateLink | no (use NLB in front) | yes | edge-optimised or Regional | internal only |
| Latency / cost | ms; per LCU | lowest; per NLCU | higher per request; per million requests | per GB + per hour |
| Kubernetes integration | Ingress / Gateway API via LBC | Service type LoadBalancer | outside the cluster | Gateway API controller |

Default: ALB for HTTP services (shopfront); NLB for non-HTTP, static IPs or PrivateLink; API Gateway
when you need API management features or Lambda mixing; Lattice for service-to-service across VPCs
and accounts without a mesh. [05 · L200](../hub/05-networking/L200-load-balancing-ingress-and-discovery.md).

## VPC CNI vs Cilium (EKS standard clusters)

| Consider | VPC CNI (+ network policy agent) | Cilium (ENI mode) |
| --- | --- | --- |
| Support | AWS-managed add-on, default | AWS-supported on Hybrid Nodes; community/Isovalent elsewhere |
| Pod IPs | VPC-routable | VPC-routable in ENI mode (overlay optional) |
| Network policy | Kubernetes NetworkPolicy (eBPF) | NetworkPolicy + CiliumNetworkPolicy (L7, FQDN, cluster-wide) |
| kube-proxy | separate add-on | replaced (eBPF), no conntrack table growth per Service |
| Observability | flow logs via policy event logs | Hubble flows, DNS, HTTP metrics |
| mTLS / mesh | none | optional (SPIFFE) |
| Operational risk | lowest | you own the CNI upgrades; Auto Mode does not support it |

Default: VPC CNI with prefix delegation and network policy on. Cilium when you need L7/FQDN policy,
Hubble-level visibility or kube-proxy replacement at scale, and you accept owning it.
[04 · L300 §2.8](../hub/04-eks/L300-eks-internals-and-operations.md), [05 · L300 §2.6–2.7](../hub/05-networking/L300-container-networking-internals.md).

## IRSA vs EKS Pod Identity

| Consider | IRSA | Pod Identity |
| --- | --- | --- |
| Setup per cluster | OIDC provider + trust policy per role with the cluster's issuer | one agent add-on; associations by API |
| Role reuse across clusters | trust policy edits per cluster | same role, one association per cluster |
| Session tags / ABAC | no | yes (cluster, namespace, SA tags) |
| Fargate profiles | yes | no |
| Cross-account roles | trust policy | association + role chaining |
| Mechanism | projected token → `AssumeRoleWithWebIdentity` | projected token → agent (`169.254.170.23`) → `AssumeRoleForPodIdentity` |

Default: Pod Identity; IRSA for Fargate profiles and charts that require an annotation.
[06 · L200 §2.3](../hub/06-identity-and-security/L200-iam-for-containers.md).

## Service Connect vs Cloud Map DNS vs a mesh (ECS)

| Consider | Service Connect | Cloud Map (service discovery) | App Mesh (end of support 2026-09-30) / Istio / Lattice |
| --- | --- | --- | --- |
| Discovery | alias names via a managed Envoy per task | DNS A/SRV records with TTL | sidecar mesh or Lattice service network |
| Traffic features | retries, timeouts, outlier detection, HTTP metrics, TLS | none (client-side) | full L7 policy, mTLS |
| Client changes | none (plain HTTP to an alias) | handle DNS TTL and retries yourself | sidecar injection / SDK |
| Cost / complexity | proxy CPU/memory per task | free | highest |

Default: Service Connect. Cloud Map only for non-HTTP or when the proxy overhead is unacceptable;
Lattice for cross-VPC/account service networking; migrate off App Mesh now.
[03 · L300 §2.7](../hub/03-ecs/L300-ecs-internals.md).

## X-Ray SDK vs OpenTelemetry

| Consider | X-Ray SDK / daemon | OpenTelemetry SDK + ADOT collector |
| --- | --- | --- |
| Direction of AWS investment | maintenance; migration guidance published | primary path (Application Signals, Transaction Search built on OTel) |
| Backends | X-Ray | X-Ray, AMP, third parties, all from one pipeline |
| Context propagation | X-Ray header | W3C `traceparent` (+ X-Ray header via propagator) |
| Sampling | SDK rules | collector tail sampling |

Default: OpenTelemetry everywhere (the shopfront apps do), ADOT collector as the gateway.
[07 · L200 §2.4](../hub/07-observability/L200-tooling-on-aws.md).

## Jenkins vs Argo CD vs CodePipeline vs GitHub Actions

| Consider | GitHub Actions | Jenkins | CodePipeline/CodeBuild | Argo CD |
| --- | --- | --- | --- | --- |
| Role | CI (+ deploy) | CI (+ deploy) | CI + CD orchestration | CD (GitOps) for Kubernetes only |
| Runs where | GitHub-hosted or self-hosted runners | your controller + agents | AWS-managed | in your cluster or as an EKS Capability |
| Identity to AWS | OIDC role | Pod Identity/IRSA on agents | service roles | Pod Identity for image updater etc. |
| Ops burden | lowest | highest | low | medium (state, upgrades) unless Capability |
| Strength | ecosystem, PR integration | flexibility, plugins, on-prem | IAM-native, no external SaaS | drift detection, declarative, multi-cluster |

Default: GitHub Actions for CI and ECS deploys; Argo CD (EKS Capability) for EKS CD; CodePipeline
where policy forbids external CI; Jenkins where it already exists and is well run.
[08 · L200](../hub/08-delivery-cicd-gitops/L200-pipelines-on-aws.md), [08 · L400 §2.6](../hub/08-delivery-cicd-gitops/L400-platform-engineering-and-delivery-at-scale.md).

## SQS vs Kafka (MSK)

| Consider | SQS | MSK / Kafka |
| --- | --- | --- |
| Model | queue, per-message ack, at-least-once (FIFO for ordering) | log, partitions, consumer groups, replay |
| Consumers | many independent consumers on one queue share work | each group reads everything; replay from offsets |
| Ordering | FIFO queues (300–3000 msg/s per group) | per partition |
| Retention | up to 14 days, no replay after delete | days to forever; replay |
| Ops | none | Serverless: little; Provisioned/Express: brokers, partitions, lag |
| Cost at low volume | cents | dollars/hour minimum |

Default: SQS for work queues (fulfilment); Kafka when multiple consumers need the same events,
replay, or ordering at high throughput (analytics). [09 · L200 §2.3–2.5](../hub/09-data-messaging-and-batch/L200-integration-patterns.md).

## AWS Batch vs Kubernetes Jobs/CronJobs vs ECS scheduled tasks vs Step Functions

| Consider | Batch | K8s Job/CronJob | ECS scheduled task | Step Functions |
| --- | --- | --- | --- | --- |
| Queues, priorities, retries, array jobs | yes | no (Jobs are individual) | no | orchestration, not a queue |
| Compute | Fargate, EC2, EKS nodes; Spot with retry | cluster nodes | Fargate/EC2 | invokes ECS/EKS/Lambda |
| Scheduling | EventBridge Scheduler → SubmitJob | cron in-cluster | EventBridge Scheduler → RunTask | schedule → state machine |
| Dependencies between jobs | yes | no | no | yes (workflows) |

Default: Batch for compute jobs with queues; CronJob when the job belongs with the services in git and
has no queue semantics; ECS scheduled task for a single cron on ECS; Step Functions for multi-step
workflows. [09 · L200 §2.7](../hub/09-data-messaging-and-batch/L200-integration-patterns.md).

## Karpenter vs Cluster Autoscaler vs Auto Mode

| Consider | Karpenter (self-managed) | Cluster Autoscaler | EKS Auto Mode |
| --- | --- | --- | --- |
| Node provisioning | direct EC2 Fleet, any instance type per pod needs | ASG-based, fixed node groups | Karpenter run by AWS |
| Consolidation | yes | limited | yes |
| Control | full (NodePool, EC2NodeClass, AMI, user data) | ASG settings | NodePool/NodeClass subset; AMI and kubelet managed |
| Ops | you upgrade it | you upgrade it | AWS |

Default: Auto Mode for new clusters unless you need custom AMIs/user data/DaemonSet-level control;
otherwise Karpenter; Cluster Autoscaler only for legacy fixed groups. [04 · L200 §2.7](../hub/04-eks/L200-cluster-components-and-add-ons.md).

## Blue/green vs canary vs rolling (deployment)

| Consider | Rolling | Blue/green | Canary |
| --- | --- | --- | --- |
| Capacity needed | +surge | 2× briefly | +small |
| Blast radius | proportional to surge | all-or-nothing switch, instant rollback | smallest, statistical |
| Needs | health checks, circuit breaker | second target group/listener, hooks | traffic weighting (ALB), metrics analysis |
| Where | ECS default, Kubernetes Deployment | ECS native blue/green, Argo Rollouts | ECS canary (0.1%–99.9%), Argo Rollouts + AnalysisTemplate |

Default: rolling with circuit breaker + alarm rollback (ECS) or Deployment + readiness gates (EKS) for
most services; canary for the customer-facing API once you have the metrics; blue/green when you
need an instant switch or a test listener. [08 · L300 §2.1–2.3](../hub/08-delivery-cicd-gitops/L300-progressive-delivery-and-gitops-internals.md).

## One cluster vs many

| Consider | Few large clusters | Many small clusters |
| --- | --- | --- |
| Blast radius of a bad upgrade or control-plane incident | large | small |
| Cost | shared fixed costs, better packing | more control planes and add-on copies |
| Tenancy | namespaces + policies + quotas | hard isolation per team/env |
| Ops | fewer upgrades, more coordination | more upgrades (automate with GitOps + ApplicationSets) |

Default: one cluster per environment per Region for a product team; per team or per compliance
boundary for a platform team; never one cluster for everything. [04 · L400 §2.1](../hub/04-eks/L400-eks-at-scale.md).
