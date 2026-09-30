# File manifest and topic assignment

Every file in the repository, what it must cover, and where each topic lives so that documents
can link to each other without guessing. Paths are relative to the repository root. A topic listed
under a document is **owned** by it; other documents link there instead of re-explaining.

## Root

| File | Scope |
| --- | --- |
| `README.md` | Front door: purpose, the level ladder, the domain map table, quick start for labs, how to read, boundaries |
| `LEARNING_PATHS.md` | Four ordered paths (100/200/300/400): reading order across domains, labs to run, checkpoint questions |
| `GLOSSARY.md` | One-line definitions of every term used (alphabetical, ~150 entries) |
| `CONTRIBUTING.md` | How to add a document, run `make check`, the review bar |
| `LICENSE` | MIT |
| `Makefile` | `check`, `build-images`, `up`, `down`, `smoke` targets |

## hub/01-container-fundamentals

| File | Owns |
| --- | --- |
| `README.md` | Level map, component checklist |
| `L100-containers-explained.md` | Process vs VM vs container; image vs container; layers; registries; Dockerfile anatomy; `docker build/run/push`; ports and volumes; why containers on AWS; the ECS-vs-EKS one-paragraph orientation (details in 03/04) |
| `L200-images-builds-and-registries.md` | OCI image/distribution specs; manifests, indexes, digests vs tags; multi-stage builds; BuildKit cache mounts and remote cache; `.dockerignore`; multi-arch (amd64/arm64, Graviton); base image choice (distroless, Alpine, Debian slim, Chainguard, Bottlerocket admin); PID 1, signals, tini/`initProcessEnabled`; health checks; twelve-factor config; SBOM generation; image size and start-up |
| `L300-runtimes-and-the-kernel.md` | Namespaces (pid, net, mnt, uts, ipc, user, cgroup, time); cgroups v2 (cpu.max, memory.max, PSI); capabilities; seccomp; AppArmor/SELinux; OCI runtime spec; containerd architecture (client, shim v2, snapshotters, CRI plugin, `ctr`/`nerdctl`/`crictl`); runc; how Docker Engine wraps containerd; why ECS EC2 still uses Docker Engine and EKS uses containerd; Firecracker microVMs on Fargate; Bottlerocket; image pull mechanics (registry auth, layer fetch, unpack, overlayfs); lazy loading with SOCI; CPU throttling mechanics (CFS quota) and memory accounting (RSS vs page cache, OOM killer) |
| `L400-hardening-supply-chain-and-performance.md` | Threats (escape, supply chain, secrets in layers); rootless and user namespaces; read-only rootfs; distroless at scale; image signing (Notation + AWS Signer, Sigstore cosign) and admission verification; SLSA levels, provenance, attestations, OCI referrers; SBOM policy; vulnerability management flow with ECR enhanced scanning; performance: JVM/Node/Go container awareness, CPU limits debate, memory limits, startup time, ephemeral storage, ulimits, kernel tuning; sustainability (Graviton, right-sizing) |

## hub/02-ecr

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-ecr-basics.md` | Registry/repository/image; private vs public (ECR Public gallery); authentication (`get-login-password`, credential helper, token lifetime 12 h); push/pull; tags; URI anatomy; first lifecycle policy; cost basics |
| `L200-lifecycle-scanning-access-and-endpoints.md` | Lifecycle policy rules and evaluation order; tag immutability; basic vs enhanced scanning (Inspector), scan on push and continuous; findings to EventBridge/Security Hub; repository policies vs IAM identity policies; cross-account pull (ECS/EKS/Lambda); KMS encryption; VPC endpoints (`ecr.api`, `ecr.dkr`, S3 gateway) and endpoint policies; registry permissions; IAM actions map (`ecr:GetAuthorizationToken`, `BatchGetImage`, `GetDownloadUrlForLayer`) |
| `L300-pull-through-cache-replication-and-limits.md` | Pull-through cache rules: upstream list, credentials in Secrets Manager, repository prefix, first-pull vs cached behaviour, sync semantics, repository creation templates, IAM (`ecr:CreateRepository`, `ecr:BatchImportUpstreamImage`); replication rules (cross-Region, cross-account, filters, destination registry permissions, timing, what is not replicated); throttling and service quotas (pull rate, image size, layer size, manifests per repo); pull performance (layer parallelism, SOCI index, Fargate/EKS image pull timeouts); auditing with CloudTrail |
| `L400-supply-chain-and-multi-account-registries.md` | Central vs per-account registries; org-wide replication topology; signing/verification at scale; policy as code for registries; DR for the registry (replication + immutable tags + rebuild from source); incident: quota exceeded, upstream outage (Docker Hub rate limits), lifecycle deleted a running image; cost model at scale; migration of images between registries (`crane`/`skopeo`) |

## hub/03-ecs

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-ecs-basics.md` | Cluster, task definition, task, service, scheduled task; launch types / capacity: Fargate, EC2, Managed Instances; ECS Express Mode; `awsvpc`; ALB in front; first deployment walkthrough; pricing model; when ECS instead of EKS |
| `L200-task-definitions-services-and-scaling.md` | Task definition fields (family, cpu/memory at task and container level, essential, dependsOn, healthCheck, stopTimeout, ulimits, linuxParameters, user, readonlyRootFilesystem, portMappings/appProtocol, environment vs secrets from SSM/Secrets Manager, logConfiguration awslogs/FireLens, ephemeralStorage, volumes EFS/EBS/bind, runtimePlatform for arm64/Windows); task role vs execution role; network modes; Service Connect vs Cloud Map service discovery configuration; ALB/NLB target groups, health checks, deregistration delay; service auto scaling (target tracking, step, scheduled, predictive); capacity providers (Fargate, Fargate Spot, ASG with managed scaling/draining, Managed Instances); deployment configuration (rolling, circuit breaker, alarms, native blue/green, canary, lifecycle hooks, pause/continue); ECS Exec; scheduled tasks with EventBridge Scheduler; placement strategies/constraints |
| `L300-ecs-internals.md` | Control plane (cluster/task state machine, task lifecycle states and `stoppedReason` codes, `stopCode`); ECS agent (Docker Engine, agent config, `ECS_*` variables, container instance registration, 51678 introspection); task metadata endpoint v4 and credentials at 169.254.170.2; IMDS access rules (Fargate none; EC2 `ECS_AWSVPC_BLOCK_IMDS`, hop limit); Fargate internals (Firecracker, platform versions, ENI per task, ephemeral storage, no privileged/host); Managed Instances internals (AWS-managed instances in your account, instance selection, patching/rotation, capacity provider attributes); ENI trunking density; Service Connect proxy internals (Envoy agent container, ports, Cloud Map namespace, client alias DNS, TLS with Private CA, timeouts, retries, outlier detection, metrics); Cloud Map DNS (A vs SRV, TTLs, health checks); how ALB deregistration interacts with SIGTERM/stopTimeout; scheduling and placement engine; daemon scheduling strategy; ECS Anywhere; CloudWatch Container Insights for ECS |
| `L400-ecs-at-scale.md` | Multi-account/multi-Region ECS; cell-based services; capacity planning (Fargate vs EC2 vs Managed Instances vs Spot with capacity rebalance); cost model with numbers; large-fleet deployment safety (bake time, alarms, canary math); App Mesh end-of-support migration to Service Connect / VPC Lattice; failure stories (ENI exhaustion, ALB target limits, deployment storms, log driver blocking); DR posture for ECS (stateless rebuild, task definition as code, image replication); Well-Architected review of an ECS platform; when to leave ECS for EKS and vice versa |

## hub/04-eks

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-kubernetes-and-eks-basics.md` | Kubernetes objects (Pod, Deployment, Service, Ingress, ConfigMap, Secret, Namespace, Job/CronJob, DaemonSet, StatefulSet); control plane vs data plane; what EKS manages; EKS standard vs EKS Auto Mode; node options at a glance (managed node groups, Fargate, Auto Mode, self-managed, Hybrid Nodes); `kubectl` and `eksctl` first steps; versions and support policy; pricing |
| `L200-cluster-components-and-add-ons.md` | Control plane components (kube-apiserver, etcd, scheduler, controller-manager, cloud-controller-manager) and how EKS runs them; kubelet; kube-proxy (iptables/ipvs/nftables) and Services (ClusterIP, NodePort, LoadBalancer, headless); CoreDNS (Corefile, `ndots:5`, autopath, NodeLocal DNSCache, add-on autoscaling); VPC CNI configuration (warm targets, prefix delegation, custom networking, IPv6, security groups for pods, network policy); managed add-ons and community add-ons; managed node groups (AL2023/Bottlerocket, launch templates, update strategies, taints/labels); Fargate profiles and their limits; Auto Mode `NodePool`/`NodeClass`; Karpenter on standard clusters; storage (EBS CSI, EFS CSI, StorageClass, VolumeAttributesClass); AWS Load Balancer Controller (Ingress → ALB, Service → NLB, target types, IngressGroup, IngressClass, Gateway API) and Auto Mode's built-in load balancing; authentication (access entries, access policies, RBAC); IRSA vs Pod Identity (details in domain 06); HPA/VPA/metrics-server; PDB; probes; resource requests/limits and QoS |
| `L300-eks-internals-and-operations.md` | Cluster networking internals (control-plane ENIs in your subnets, cluster security group, public/private endpoint, `/28` control-plane subnets recommendation); authentication flow (`aws eks get-token` → STS presigned `GetCallerIdentity` → authenticator → access entry → RBAC); OIDC issuer, projected tokens, pod-identity-webhook, Pod Identity agent flow (169.254.170.23, `eks-auth:AssumeRoleForPodIdentity`); VPC CNI internals (aws-node DaemonSet, ipamd, L-IPAM warm pools, ENI attach limits, `max-pods`, trunk ENIs, network policy agent eBPF maps); kube-proxy internals (conntrack, iptables chains vs nftables, IPVS, `externalTrafficPolicy`); CoreDNS internals and failure modes (`ndots`, UDP truncation, conntrack races, upstream throttling to Route 53 Resolver at 1024 pps per ENI); Auto Mode internals (Karpenter consolidation, drift, 21-day node lifetime, Bottlerocket node OS, built-in capabilities, what you cannot change); upgrade mechanics (control plane, add-ons order, node groups, PDB interplay, API deprecations, `kubent`/`pluto`); containerd on nodes (`crictl`, config, registry mirrors); Cilium on EKS (ENI mode vs overlay, chaining with VPC CNI, kube-proxy replacement, Hubble, Hybrid Nodes support); EKS Capabilities (Argo CD, ACK, kro) architecture; control plane logging types; Windows and GPU nodes basics; Hybrid Nodes |
| `L400-eks-at-scale.md` | Multi-cluster topologies (per env, per team, cells); scaling limits (etcd size, API server QPS, pods per cluster, IP exhaustion) and how EKS control plane auto-scales; capacity design (Karpenter/Auto Mode NodePools, Spot diversification, consolidation policies, bin-packing); cost model (cluster fee, Auto Mode fee, extended support, data transfer); security hardening at scale (PSS/PSA, network policies, IMDS hop limit, image policy, admission); GitOps platform (details in 08); DR (Velero, etcd snapshots AWS-managed, rebuild-from-git, stateful workloads); observability at scale (details in 07); ARC zonal shift; upgrade cadences for a fleet; Well-Architected review of an EKS platform; when EKS is the wrong tool |

## hub/05-networking

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-vpc-for-containers.md` | VPC, subnets (public/private/isolated), route tables, IGW/NAT, security groups vs NACLs, ELB family overview, DNS in a VPC, how a task/pod gets an IP (`awsvpc` ENI, VPC CNI), typical three-tier layout for a container platform |
| `L200-load-balancing-ingress-and-discovery.md` | ALB vs NLB vs GWLB; listeners, rules, target groups (ip vs instance), health checks, slow start, deregistration delay, stickiness, cross-zone; ALB Ingress via AWS Load Balancer Controller (annotations, IngressGroup, TLS with ACM, WAF), NLB Service annotations, Gateway API; API Gateway HTTP API + VPC Link; CloudFront in front; service discovery options: Cloud Map DNS, ECS Service Connect, Kubernetes Services + CoreDNS, headless Services; VPC endpoints needed by containers |
| `L300-container-networking-internals.md` | Link-local addresses table and semantics (IMDS 169.254.169.254, ECS 169.254.170.2, Pod Identity 169.254.170.23, Resolver 169.254.169.253, Time Sync 169.254.169.123); IMDSv2 mechanics (PUT token, TTL, hop limit, IMDSv2-only enforcement, account defaults, blocking from containers per platform); ENI/IP arithmetic (max pods, prefix delegation, custom networking, secondary CIDR 100.64/16), IPv6 dual-stack/IPv6-only, egress-only IGW, NAT64/DNS64; security groups for pods; network policies (VPC CNI engine vs Cilium); kube-proxy modes and conntrack limits; Cilium eBPF datapath; MTU/jumbo frames; SNAT rules (`AWS_VPC_K8S_CNI_EXTERNALSNAT`); PrivateLink endpoints list for private clusters; VPC Lattice; service mesh options (Istio, Cilium mesh, App Mesh end-of-support) |
| `L400-network-architecture-at-scale.md` | IP planning for fleets; shared VPC and Transit Gateway; multi-account networking; egress control (NAT, Network Firewall, proxies, FQDN filtering); private clusters; zonal isolation (cross-zone off, zonal shift, per-AZ cells); DNS at scale (Route 53 Resolver limits, CoreDNS/NodeLocal DNS tuning); data-transfer cost model (NAT, cross-AZ, cross-Region); mesh decision record; VPC Flow Logs, Hubble, Traffic Mirroring; failure stories (IP exhaustion, conntrack exhaustion, DNS throttling) |

## hub/06-identity-and-security

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-security-basics-for-containers.md` | Shared responsibility for Fargate/EC2/EKS/Auto Mode; identities in play (instance role, task/pod role, execution role, human access); secrets (never in images or plain env); image scanning; least privilege; TLS; the ten-line checklist |
| `L200-iam-for-containers.md` | ECS task role vs execution role (what each is used for, trust policies); EKS IRSA end to end (OIDC provider, trust policy with `sub`/`aud` conditions, annotation, SDK behaviour) vs Pod Identity end to end (association, agent, `TagSession`, session tags for ABAC); node/instance roles and why pods must not use them; access entries and RBAC; human access (Identity Center, `kubectl` auth, ECS Exec); secrets delivery (Secrets Manager, SSM Parameter Store, Secrets Store CSI driver, External Secrets Operator, ECS `secrets[]`); KMS envelope encryption of EKS secrets; IMDSv2 basics |
| `L300-hardening-workloads-and-clusters.md` | Pod Security Standards/Admission, `securityContext` fields and what each blocks; seccomp/AppArmor profiles; read-only rootfs and writable volumes; capabilities to drop/keep; network policies as security control; admission policy engines (ValidatingAdmissionPolicy/MutatingAdmissionPolicy, Kyverno, Gatekeeper); image signature verification (Notation/Signer, cosign); GuardDuty Runtime Monitoring (EKS and ECS/Fargate), Inspector, Security Hub, EKS audit logs and CloudTrail for ECS; Fargate isolation model; private endpoints; egress restriction; secrets rotation; ECS Exec auditing; IMDS blocking per platform (EKS hop limit, ECS agent flag, Fargate) |
| `L400-security-architecture-and-incident-response.md` | Threat model for a container platform (supply chain, escape, lateral movement, credential theft via IMDS/SSRF, token exfiltration, noisy-neighbor, control-plane abuse); multi-tenancy tiers (namespace, node, cluster, account); Zero Trust and mTLS options (Service Connect TLS, Cilium/Istio mTLS, VPC Lattice auth policies); compliance mapping (PCI DSS, HIPAA, SOC 2) to controls; incident response for containers (isolate node/task, preserve evidence, Fargate constraints, credential revocation via role policy `aws:TokenIssueTime`); security metrics; Well-Architected security pillar checklist |

## hub/07-observability

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-observability-basics.md` | Logs/metrics/traces/events; CloudWatch basics (log groups, metrics, alarms, dashboards); `awslogs`; Container Insights at a glance; what to look at first when a container is unhealthy |
| `L200-tooling-on-aws.md` | Container Insights (enhanced observability for EKS and ECS, cost); CloudWatch agent vs Fluent Bit/FireLens vs ADOT collector; OpenTelemetry (SDKs, collector, OTLP); X-Ray today and the OTel direction; Application Signals (SLOs, service map) and Transaction Search; Amazon Managed Prometheus + Grafana; kube-state-metrics, metrics-server, node-exporter; OpenSearch for logs; log routing patterns and retention; EKS control plane logs; ECS service events; alarms and composite alarms; a starter dashboard |
| `L300-metrics-that-matter-and-alerting.md` | Per-component metric catalog with meaning and thresholds: control plane (apiserver latency/errors, etcd size, admission latency), nodes (CPU/memory/disk/PID pressure, PSI), pods (restarts, OOMKilled, CFS throttling, pending time), CoreDNS (latency, errors, cache hit, upstream failures), VPC CNI (ipamd IPs available, ENI attach errors), ALB/NLB (TargetResponseTime, 5XX split, UnHealthyHostCount, RequestCountPerTarget, RejectedConnectionCount), ECS (CPU/Memory utilization vs reservation, RunningTaskCount, deployment metrics, Service Connect metrics, capacity provider reservation), Fargate, ECR (pull errors via CloudTrail), SQS (ApproximateAgeOfOldestMessage), RDS/Aurora, ElastiCache/Valkey, MSK (consumer lag, under-replicated partitions), Batch; RED/USE/golden signals; SLOs and burn-rate alerts; anomaly detection; alarm hygiene |
| `L400-observability-at-scale.md` | OpenTelemetry pipeline design (agent vs gateway collectors, tail sampling, batching, resource attributes); context propagation across HTTP, SQS attributes and Kafka headers; cardinality control and cost (EMF, metric filters, log retention, sampling); central observability across accounts (CloudWatch cross-account, AMP workspaces, Grafana data sources); synthetic monitoring; profiling; audit log analytics; eBPF observability (Hubble); observability for DR and game days; on-call design (runbooks, alert routing, DORA/SRE metrics) |

## hub/08-delivery-cicd-gitops

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-cicd-basics.md` | Build → test → scan → push → deploy; tags vs digests in deploys; environments and promotion; the difference between CI and CD and GitOps; where Jenkins, GitHub Actions, CodePipeline, Argo CD fit |
| `L200-pipelines-on-aws.md` | GitHub Actions with OIDC to AWS (no long-lived keys, trust policy `sub` conditions, SHA-pinned actions); CodePipeline/CodeBuild/CodeDeploy (buildspec, ECR push, ECS deploy actions, CodeDeploy ECS blue/green vs ECS native); Jenkins on EKS (Kubernetes plugin, pod templates, JCasC, controller HA basics) and on ECS (ECS Fargate agents plugin); in-cluster image builds (BuildKit, kaniko) vs CodeBuild vs GitHub runners; Helm and Kustomize; Argo CD basics (Application, Project, sync policy, health, App of Apps, ApplicationSet); EKS Capability for Argo CD; Flux mention; ECR lifecycle in pipelines |
| `L300-progressive-delivery-and-gitops-internals.md` | ECS deployment strategies in depth (rolling parameters, circuit breaker, alarm rollback, native blue/green, canary percentages and bake time, lifecycle hooks with Lambda, pause/continue) vs Kubernetes rolling updates (maxSurge/maxUnavailable, minReadySeconds, PDB, readiness gates, `pod-readiness-gate-inject` for ALB); Argo Rollouts (canary/blue-green with ALB traffic routing, AnalysisTemplates against CloudWatch/Prometheus); Flagger; feature flags with AppConfig; database migrations in pipelines; Argo CD internals (repo-server, application-controller sharding, redis, SSO, RBAC, notifications, image updater, secrets with ESO/Sealed Secrets); Jenkins internals (ephemeral agents, shared libraries, credentials binding, controller backup); supply-chain in pipelines (SBOM, provenance, signing, admission); pipeline security (least privilege, OIDC, environment protection, artifact immutability) |
| `L400-platform-engineering-and-delivery-at-scale.md` | Platform teams and golden paths; multi-cluster GitOps (hub-spoke Argo CD, cluster generators, EKS Capability vs self-managed Argo CD); policy as code in the pipeline; developer portal (Backstage) mention; release trains and environments at scale; DR of the delivery system (Argo CD state, Jenkins state, ECR replication, runners); SLSA levels and attestations; build performance and cost (pull-through cache, remote cache, Graviton builders, ephemeral runners); DORA metrics; anti-patterns |

## hub/09-data-messaging-and-batch

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-stateful-dependencies.md` | Containers are ephemeral; state belongs in managed services: RDS/Aurora, ElastiCache (Valkey/Redis), DynamoDB, S3, EFS/EBS, SQS/SNS/EventBridge, MSK/Kafka; connecting from a container (endpoints, security groups, secrets); what the shopfront system uses each for |
| `L200-integration-patterns.md` | RDS/Aurora from containers (connection pooling in ephemeral fleets, RDS Proxy, IAM DB auth, Secrets Manager rotation, TLS); ElastiCache Valkey (cluster mode, Serverless, TLS/auth tokens, cache-aside/TTL); SQS (visibility timeout, long polling, DLQ/redrive, batch, FIFO, scaling consumers with KEDA or ECS target tracking on queue depth); SNS fan-out, EventBridge; MSK (Provisioned/Express/Serverless, IAM auth, topics/partitions/consumer groups, lag); AWS Batch (compute environments on ECS/Fargate/EKS, job queues, job definitions, array jobs, retries, dependencies); Step Functions `ecs:runTask` and `eks:runJob`; Kubernetes Jobs/CronJobs vs ECS scheduled tasks vs Batch decision |
| `L300-messaging-and-data-deep-dive.md` | At-least-once consumers, idempotency keys, poison messages, exactly-once boundaries; ordering and partitions; Kafka on Kubernetes (Strimzi) vs MSK; schema registry (Glue) and compatibility; connection storms during deployments and how to shape them; cache stampede and probabilistic early expiration; Valkey eviction and memory; KEDA scalers internals (SQS, Kafka lag, Prometheus, CloudWatch); Batch on EKS internals (Batch-launched nodes, `aws-batch` namespace RBAC, node selectors, no Fargate); fair-share scheduling, Spot for Batch, GPU jobs; data DR: RDS Multi-AZ/Global Database, ElastiCache Global Datastore, MSK Replicator, SQS regional scope |
| `L400-event-driven-architecture-at-scale.md` | Outbox pattern with RDS + Kafka/SQS; CQRS; sagas with Step Functions; backpressure and load shedding; multi-Region data (active/passive vs active/active, conflict handling); cost model of messaging; observability of async flows (trace propagation through SQS attributes/Kafka headers); testing async systems; anti-patterns |

## hub/10-resilience-and-dr

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-resilience-basics.md` | AZs and Regions; multi-AZ by default for tasks/pods/ALB; health checks and restarts; replicas; RTO/RPO; the four DR strategies named |
| `L200-designing-for-failure.md` | Replicas and spread (topology spread, anti-affinity, ECS placement); PDBs; autoscaling layers (HPA/VPA/Karpenter/Cluster Autoscaler/Auto Mode; ECS service auto scaling and capacity providers); graceful shutdown timeline (SIGTERM → preStop/`stopTimeout` → ALB deregistration → `terminationGracePeriodSeconds`); probes and ECS health checks; retries, timeouts, circuit breakers, bulkheads, rate limiting; dependency failure handling; AWS FIS basics; ARC zonal shift/autoshift |
| `L300-dr-strategies-for-container-platforms.md` | Backup & restore, pilot light, warm standby, active/active for ECS and EKS; what state exists and where (ECR images, IaC/GitOps repos, Kubernetes objects, PVs, secrets, databases, queues, DNS); tools (ECR replication, Velero for EKS, EBS/RDS/ElastiCache snapshots, MSK Replicator, cross-Region secrets replication, KMS multi-Region keys); Route 53 health checks and failover, ARC readiness/routing controls; cluster rebuild automation; testing DR; RTO/RPO math per tier |
| `L400-dr-plan-and-game-days.md` | The DR plan document itself (tiers, RTO/RPO per service, dependency map, roles, communications, decision criteria to fail over, failback); runbook structure; game-day design and cadence; multi-Region ECS/EKS reference architectures; pitfalls (quotas, AMIs, IAM/OIDC per Region, cross-Region secrets, data reconciliation); cost of DR; metrics for DR readiness |

## hub/11-testing-workloads

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-testing-basics.md` | Test pyramid for container services; unit vs integration with Docker Compose; container structure tests; health endpoint tests; smoke tests after deploy |
| `L200-testing-in-pipelines-and-clusters.md` | Testcontainers; Compose in CI; LocalStack/ElasticMQ; contract tests; ephemeral environments (namespace per PR, ECS service per PR); kind/minikube; manifest and template validation (kubeconform, cfn-lint, hadolint, trivy, checkov, kube-linter); load tools (k6, Locust, Artillery, Distributed Load Testing on AWS); test data |
| `L300-performance-and-chaos-testing.md` | Load test design (open vs closed models, SLO thresholds, warm-up, soak, spike, capacity tests that measure HPA/Karpenter reaction), right-sizing (VPA, Compute Optimizer for Fargate/EC2), Graviton vs x86 benchmarking, chaos with AWS FIS (ECS stop tasks, EKS pod delete/node termination, AZ impairment, network latency), Litmus/Chaos Mesh, DNS/dependency failure injection, game days, what to record |
| `L400-verification-at-scale.md` | Testing in production (canary analysis, shadow traffic, synthetics), continuous verification (Argo Rollouts analysis, ECS lifecycle hooks with test suites), DR tests, security testing (kube-bench, Inspector, Trivy Operator, pen tests), compliance-as-code, metrics-driven quality gates, anti-patterns |

## hub/12-well-architected

| File | Owns |
| --- | --- |
| `README.md` | Level map |
| `L100-pillars-for-containers.md` | The six pillars restated for container workloads; the Container Build Lens; the EKS and ECS best-practices guides; how a review works |
| `L200-pillar-checklists-ecs-and-eks.md` | Per-pillar checklists for ECS and for EKS, each item linking to the hub document that explains it |
| `L300-running-a-review.md` | How to run a Well-Architected review of a container workload using the shopfront lab as the example: questions, evidence to collect, risk rating, improvement plan |
| `L400-trade-offs-and-anti-patterns.md` | The hard trade-offs (Fargate vs EC2 vs Managed Instances vs Auto Mode; one big cluster vs many; mesh or not; multi-Region or not; managed vs self-managed add-ons; cost vs resilience) with decision records, and the anti-pattern catalog with the failure each causes |

## labs

| Path | Scope |
| --- | --- |
| `labs/README.md` | Architecture of shopfront, how to run locally, how to deploy to ECS/EKS/Batch, cost warning |
| `labs/CONTRACT.md` | Service contract: ports, env vars, endpoints, schema, queues, topics, telemetry, shutdown |
| `labs/apps/catalog/` | Go service (Postgres + Valkey cache), Dockerfile (distroless), tests |
| `labs/apps/orders/` | Node.js/TypeScript service (Postgres, calls catalog, publishes SQS + Kafka), Dockerfile, tests |
| `labs/apps/worker/` | Python package with two entrypoints: `fulfillment` (SQS consumer) and `analytics` (Kafka consumer); one Dockerfile; tests |
| `labs/apps/report-job/` | Python batch job (Postgres → S3 or local file), Dockerfile |
| `labs/local/` | `compose.yaml` (postgres, valkey, kafka KRaft, elasticmq, otel-collector, jaeger, services), `schema.sql`, `seed.sql`, `smoke.sh`, `otel-collector.yaml`, `elasticmq.conf` |
| `labs/ecs/cloudformation/` | `01-network.yaml`, `02-cluster.yaml`, `03-data.yaml`, `04-services.yaml`, `05-observability.yaml`, `06-batch.yaml`; `parameters/dev.json`; `deploy.sh`/`destroy.sh` with confirmation gate |
| `labs/ecs/taskdefs/` | Standalone task definition JSON per service (documented field by field) |
| `labs/eks/cluster/` | `eksctl-standard.yaml` (managed node groups AL2023 + add-ons + Pod Identity), `eksctl-auto-mode.yaml`, `karpenter-nodepool.yaml`, `auto-mode-nodepool-nodeclass.yaml` |
| `labs/eks/manifests/` | Kustomize `base/` (namespace, deployments, services, ingress, HPA, PDB, network policies, service accounts, KEDA ScaledObject, CronJob) and `overlays/dev`, `overlays/prod` |
| `labs/eks/addons/` | Helm values: `aws-load-balancer-controller`, `adot-collector` config, `keda`, `argo-rollouts`, `cilium` (standard clusters), `coredns-autoscaler`; Pod Identity association script |
| `labs/eks/gitops/` | Argo CD `Project`, `Application`, `ApplicationSet`; Argo Rollouts canary example |
| `labs/batch/` | Batch job definition JSON for report-job (ECS/Fargate and EKS variants), submit script |
| `labs/pipelines/github-actions/` | `ci.yml` (build multi-arch, scan, SBOM, sign, push to ECR via OIDC), `deploy-ecs.yml`, `deploy-eks.yml` (image tag bump for GitOps) |
| `labs/pipelines/jenkins/` | `Jenkinsfile` with Kubernetes agents, `jcasc.yaml`, Helm values for Jenkins on EKS |
| `labs/pipelines/codepipeline/` | `buildspec.yml`, `pipeline.yaml` CloudFormation (CodePipeline → CodeBuild → ECS deploy) |

## playbooks

| Path | Scope |
| --- | --- |
| `playbooks/README.md` | Index by symptom; triage flow diagram |
| `playbooks/incidents/image-pull-failures.md` | ImagePullBackOff, `CannotPullContainerError`, ECR auth/throttle/endpoint/VPC endpoint problems |
| `playbooks/incidents/crashloop-and-exit-codes.md` | CrashLoopBackOff, essential container exited, exit codes 1/137/139/143, entrypoint mistakes |
| `playbooks/incidents/oom-and-cpu-throttling.md` | OOMKilled (exit 137), memory limits vs JVM/Node, CFS throttling |
| `playbooks/incidents/pending-pods-and-capacity.md` | Pending pods: IP exhaustion, insufficient capacity, taints/affinity, Karpenter/Auto Mode not scaling, ECS `RESOURCE:CPU` placement failures |
| `playbooks/incidents/node-not-ready.md` | NotReady, kubelet/PLEG, disk pressure, ENI attach failures, IMDS/hop-limit surprises |
| `playbooks/incidents/dns-failures.md` | CoreDNS latency/errors, `ndots`, conntrack, Resolver throttling, Cloud Map TTLs |
| `playbooks/incidents/alb-5xx-and-unhealthy-targets.md` | 502/503/504 taxonomy, target health, deregistration vs SIGTERM, security groups, readiness gates |
| `playbooks/incidents/ecs-task-stopped-reasons.md` | `stoppedReason` catalog: `ResourceInitializationError`, `CannotPullContainerError`, `OutOfMemoryError`, health check failed, essential container exited, Spot interruption |
| `playbooks/incidents/ecs-deployment-stuck-or-rolled-back.md` | Circuit breaker, alarms, blue/green hook failures, insufficient capacity, Service Connect misconfiguration |
| `playbooks/incidents/iam-accessdenied-from-containers.md` | Task role vs execution role confusion, IRSA trust/`sub` mismatch, Pod Identity association missing, SDK credential chain order, IMDS blocked |
| `playbooks/incidents/eks-auth-and-access.md` | `Unauthorized`, `You must be logged in`, access entries, `aws-auth`, kubeconfig/STS issues |
| `playbooks/incidents/upgrade-breakage.md` | Removed APIs, add-on incompatibility, node group failures, PDB blocking drain |
| `playbooks/incidents/queue-backlog-and-consumer-lag.md` | SQS age growing, Kafka lag, DLQ filling, KEDA not scaling, RDS connection exhaustion under load |
| `playbooks/dr/dr-plan-template.md` | Fill-in DR plan for a container platform |
| `playbooks/dr/region-failover-runbook.md` | Steps to fail shopfront over to a second Region and back |
| `playbooks/dr/cluster-rebuild-runbook.md` | Rebuild an EKS cluster / ECS environment from code |
| `playbooks/dr/data-recovery-runbook.md` | RDS, Valkey, SQS, MSK recovery steps |
| `playbooks/dr/game-day-guide.md` | Planning, scenarios, scoring, follow-ups |
| `playbooks/upgrades/eks-version-upgrade.md` | Control plane → add-ons → nodes; pre-flight checks; rollback window |
| `playbooks/upgrades/ecs-ami-agent-and-platform.md` | AMI rotation, agent updates, Fargate platform versions, Managed Instances patching |
| `playbooks/upgrades/addon-and-controller-upgrades.md` | VPC CNI, CoreDNS, kube-proxy, LB controller, Karpenter, Cilium |

## reference

| File | Scope |
| --- | --- |
| `reference/README.md` | Index |
| `reference/metrics-catalog.md` | Every metric named in the hub: component, metric, source, meaning, starting threshold |
| `reference/ports-addresses-and-endpoints.md` | Link-local table, ports per component, VPC endpoints for private ECS/EKS |
| `reference/service-interaction-map.md` | Who talks to whom (ECS/EKS/ECR/IAM/ELB/Cloud Map/CloudWatch/…), protocol, prerequisites; Mermaid diagrams |
| `reference/decision-guides.md` | ECS vs EKS; Fargate vs EC2 vs Managed Instances vs Auto Mode; ALB vs NLB vs API Gateway vs Lattice; VPC CNI vs Cilium; IRSA vs Pod Identity; Service Connect vs Cloud Map vs mesh; X-Ray SDK vs OTel; Jenkins vs Argo CD vs CodePipeline vs GitHub Actions; SQS vs Kafka; Batch vs Jobs; Karpenter vs Cluster Autoscaler vs Auto Mode |
| `reference/quotas-and-limits.md` | The quotas that bite (ENIs, IPs, tasks per service, pods per node, ECR pulls, ALB targets, Fargate vCPU, EKS nodes, SQS, MSK) |
| `reference/lifecycle-and-deprecations.md` | Dates table from `docs/FACTS-2026-09.md` with migration pointers |
| `reference/cli-cheatsheet.md` | `aws ecs/eks/ecr`, `kubectl`, `eksctl`, `docker`, `ctr`, `nerdctl`, `crictl`, `helm`, `kustomize`, `argocd` |
