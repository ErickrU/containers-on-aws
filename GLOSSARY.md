# Glossary

One-line definitions of the terms used across the hub, labs, playbooks and reference tables.
Alphabetical; acronyms are listed under their letters. Where a term has a deeper treatment, the
domain and level are given in brackets.

## A

- **Access entry** — EKS API object that maps an IAM principal to Kubernetes groups or an access policy; replaces the `aws-auth` ConfigMap [04 L200].
- **Access policy (EKS)** — AWS-managed permission set (`AmazonEKSViewPolicy`, `EditPolicy`, `AdminPolicy`, `ClusterAdminPolicy`) attached to an access entry with a cluster or namespace scope [04 L200].
- **ACK (AWS Controllers for Kubernetes)** — controllers that manage AWS resources from Kubernetes custom resources; available as an EKS Capability [04 L300].
- **ACU (Aurora Capacity Unit)** — the scaling unit of Aurora Serverless v2 (about 2 GiB of memory with matching CPU) [09 L200].
- **ADOT (AWS Distro for OpenTelemetry)** — AWS's build of the OpenTelemetry collector and SDK components with exporters for X-Ray, CloudWatch EMF and AMP [07 L200].
- **Admission controller / policy** — API server hook that validates or mutates objects before they are stored (ValidatingAdmissionPolicy, Kyverno, Gatekeeper, webhooks) [06 L300].
- **AL2023 (Amazon Linux 2023)** — the current Amazon Linux; the EKS and ECS optimized AMIs are built on it since AL2 left support [04 L200].
- **ALB (Application Load Balancer)** — layer-7 load balancer with host/path routing, weighted target groups and OIDC authentication [05 L200].
- **AMP / AMG** — Amazon Managed Service for Prometheus / Amazon Managed Grafana [07 L200].
- **AnalysisTemplate** — Argo Rollouts object that defines metric queries and success conditions used to promote or abort a canary [08 L300].
- **API server (kube-apiserver)** — the Kubernetes control plane's front door; every read and write goes through it; EKS runs it in AWS-owned accounts [04 L200].
- **App Mesh** — AWS service mesh; end of support 2026-09-30; replaced by Service Connect, Cilium/Istio or VPC Lattice [03 L400].
- **Application Signals** — CloudWatch feature that builds SLOs and a service map from OTel telemetry [07 L200].
- **ApplicationSet** — Argo CD generator that creates one Application per cluster or environment from a template [08 L400].
- **ARC (Application Recovery Controller)** — zonal shift/autoshift and routing controls for AZ and Region evacuation [10 L200].
- **Argo CD** — GitOps controller that syncs Kubernetes objects from git and detects drift; also offered as an EKS Capability [08 L200].
- **Argo Rollouts** — progressive-delivery controller (canary, blue/green) that shifts ALB weights and runs analyses [08 L300].
- **Attestation** — signed statement about an artifact (SBOM, provenance) stored as an OCI referrer [01 L400].
- **Auto Mode (EKS)** — AWS-managed data plane: Karpenter, VPC CNI, CoreDNS, kube-proxy, EBS CSI, load balancing and Pod Identity as built-in capabilities on Bottlerocket nodes [04 L200].
- **Auto scaling (service)** — Application Auto Scaling changing an ECS service's desired count on target-tracking, step or scheduled policies [03 L200].
- **AvailabilityZoneRebalancing** — ECS service setting that moves tasks to rebalance AZs after a zone recovers [03 L200].
- **awsvpc network mode** — ECS mode where each task gets its own ENI, private IP and security groups; required on Fargate [03 L200].
- **AZ (Availability Zone)** — isolated data-center group within a Region; the unit of "multi-AZ" [10 L100].

## B

- **Backlog per task/consumer** — queue depth divided by consumer count; the target-tracking metric for queue workers [09 L200].
- **Bake time** — period after a deployment reaches steady state during which alarms can still trigger a rollback [08 L300].
- **Base image** — the `FROM` image a Dockerfile builds on (distroless, Alpine, Debian slim, Chainguard) [01 L200].
- **Batch (AWS Batch)** — managed job queues, scheduling and compute environments on ECS/Fargate or EKS [09 L200].
- **Blue/green deployment** — two full environments with an instant traffic switch; ECS native or Argo Rollouts [08 L300].
- **Bottlerocket** — minimal, API-driven, read-only-root Linux for containers; used by Auto Mode and available for node groups and ECS [01 L300].
- **BuildKit** — Docker's build engine: parallel stages, cache mounts, remote cache, multi-arch, SBOM and provenance attestations [01 L200].
- **Burn rate** — how fast an SLO's error budget is being consumed; the basis of multi-window alerts [07 L300].

## C

- **Canary deployment** — routing a small traffic percentage to the new revision and analysing metrics before promoting [08 L300].
- **Capabilities (Linux)** — fine-grained root privileges; containers should drop `ALL` [01 L300].
- **Capabilities (EKS)** — fully managed off-cluster Argo CD, ACK and kro [04 L300].
- **Capacity provider** — ECS abstraction for where tasks run: `FARGATE`, `FARGATE_SPOT`, an ASG with managed scaling, or Managed Instances [03 L200].
- **CFS quota (CPU throttling)** — kernel mechanism that enforces a CPU limit per 100 ms period; causes latency without CPU saturation [01 L300].
- **cgroups v2** — kernel resource accounting and limits (`cpu.max`, `memory.max`, PSI) that containers are built on [01 L300].
- **Chainguard images** — minimal, frequently rebuilt distroless-style base images with SBOMs [01 L200].
- **Cilium** — eBPF-based CNI with network policy, kube-proxy replacement and Hubble observability [04 L300].
- **Circuit breaker (ECS deployment)** — stops and optionally rolls back a deployment after repeated task launch failures [03 L200].
- **Circuit breaker (application)** — client-side pattern that stops calling a failing dependency for a while [10 L200].
- **Cloud Map** — service discovery registry with DNS and API lookup; the namespace behind Service Connect [03 L300].
- **CloudFormation** — AWS IaC service; the ECS lab's templates (`labs/ecs/cloudformation`) [03 L200].
- **Cluster (ECS)** — logical grouping of tasks, services and capacity; free [03 L100].
- **Cluster (EKS)** — a Kubernetes control plane plus its data plane; billed per hour [04 L100].
- **Cluster security group** — EKS-created security group allowing control plane and nodes to talk [04 L300].
- **CNI (Container Network Interface)** — plugin standard for pod networking; VPC CNI and Cilium implement it [04 L200].
- **CodeBuild / CodePipeline / CodeDeploy** — AWS-native build, pipeline orchestration and deployment services [08 L200].
- **Composite alarm** — CloudWatch alarm whose state is a boolean expression over other alarms [07 L200].
- **Compute environment (Batch)** — the pool Batch schedules jobs into (Fargate, Fargate Spot, EC2, EKS) [09 L200].
- **conntrack** — kernel connection-tracking table used by NAT and iptables; exhaustion drops packets [05 L300].
- **Container Insights** — CloudWatch metrics and logs for ECS/EKS clusters, services, tasks, pods and nodes; "enhanced observability" adds per-container detail [07 L200].
- **containerd** — the container runtime under Docker and on Kubernetes nodes; talks CRI to the kubelet and runs containers through shims and runc [01 L300].
- **Control plane** — the components that decide what runs where (API server, etcd, scheduler, controllers; the ECS scheduler) [04 L200].
- **CoreDNS** — cluster DNS server for Kubernetes; resolves Services and forwards to the VPC resolver [04 L200].
- **CRI (Container Runtime Interface)** — gRPC API between kubelet and the runtime [01 L300].
- **crictl** — CLI that speaks CRI to containerd on a node [01 L300].
- **CronJob** — Kubernetes object that creates Jobs on a schedule [09 L200].
- **Custom networking (VPC CNI)** — pods get IPs from different subnets (often a secondary CIDR) than the node [05 L300].

## D

- **DaemonSet** — Kubernetes object that runs one pod per node (CNI, kube-proxy, agents) [04 L100].
- **Data plane** — where workloads run: nodes, Fargate microVMs, their networking [04 L200].
- **Deployment (Kubernetes)** — declarative replica set management with rolling updates [04 L100].
- **Deregistration delay** — time an ALB keeps sending in-flight requests to a target after deregistering it [05 L200].
- **Digest** — content hash (`sha256:...`) that identifies an image immutably; tags are mutable pointers to digests [01 L200].
- **Distroless** — base images without a shell or package manager [01 L200].
- **DLQ (dead-letter queue)** — SQS queue receiving messages that exceeded `maxReceiveCount` [09 L200].
- **DORA metrics** — deployment frequency, lead time, change failure rate, time to restore [08 L400].
- **Drift (Karpenter)** — nodes whose spec no longer matches the NodePool/NodeClass; replaced within disruption budgets [04 L300].

## E

- **EBS CSI driver** — provisions and attaches EBS volumes for PersistentVolumeClaims [04 L200].
- **ECR (Elastic Container Registry)** — AWS OCI registry: private and public, scanning, lifecycle, replication, pull-through cache [02].
- **ECS (Elastic Container Service)** — AWS-native container orchestrator: clusters, task definitions, tasks, services [03].
- **ECS Anywhere** — ECS tasks on customer-managed hosts registered through SSM [03 L300].
- **ECS Exec** — interactive shell into a running container through SSM Session Manager [03 L200].
- **ECS Express Mode** — one-step creation of an internet-facing ECS web service with AWS defaults [03 L100].
- **EKS (Elastic Kubernetes Service)** — AWS-managed Kubernetes control plane with several data-plane options [04].
- **eksctl** — CLI that creates and manages EKS clusters from a ClusterConfig file [04 L100].
- **EMF (Embedded Metric Format)** — CloudWatch log format that turns structured log lines into metrics [07 L400].
- **Endpoint (VPC interface/gateway)** — private connectivity to an AWS service without NAT or IGW [05 L200].
- **ENI (Elastic Network Interface)** — virtual NIC with private IPs; the unit of pod/task networking [05 L300].
- **ENI trunking** — ECS feature multiplying `awsvpc` tasks per EC2 instance through a trunk interface [03 L300].
- **Ephemeral storage** — task/pod scratch disk (Fargate 20 GiB default, up to 200) [03 L200].
- **etcd** — the Kubernetes control plane's key-value store; AWS-managed on EKS, 8 GiB limit [04 L300].
- **EventBridge / Scheduler** — event bus for AWS service events; Scheduler triggers targets (ECS tasks, Batch jobs) on a cron [09 L200].
- **Execution role (ECS)** — IAM role the ECS agent uses to pull images, read secrets and write logs for a task [06 L200].
- **External Secrets Operator (ESO)** — controller that syncs Secrets Manager/SSM values into Kubernetes Secrets [06 L200].
- **Expand/contract** — schema-migration pattern compatible with two running code versions [08 L300].

## F

- **Fargate** — serverless compute for ECS tasks and EKS pods: one Firecracker microVM per task/pod [03 L300].
- **Fargate profile (EKS)** — selector that sends matching pods to Fargate [04 L200].
- **Fargate Spot** — interruptible Fargate capacity at a discount with a two-minute warning [03 L200].
- **Firecracker** — microVM technology under Fargate [01 L300].
- **FireLens** — ECS log routing through a Fluent Bit sidecar [07 L200].
- **FIS (Fault Injection Service)** — managed chaos experiments (stop tasks, terminate nodes, disrupt AZ networking) [11 L300].
- **Fluent Bit** — lightweight log shipper used by FireLens and the CloudWatch Observability add-on [07 L200].

## G

- **Game day** — rehearsed failure injection with observers, scoring and follow-ups [10 L400].
- **Gateway API** — Kubernetes routing API succeeding Ingress; implemented by the load balancer controller and VPC Lattice [05 L200].
- **GitOps** — desired state in git, a controller reconciles the cluster to it [08 L200].
- **Graceful shutdown** — SIGTERM → stop accepting → drain in-flight → exit, inside the platform's grace period [10 L200].
- **Graviton** — AWS ARM64 processors (`m7g`, `c7g`, `r7g`); cheaper per vCPU; needs `linux/arm64` images [01 L200].
- **GuardDuty Runtime Monitoring** — threat detection agent for EKS, ECS and Fargate workloads [06 L300].

## H

- **Hop limit (IMDS)** — `HttpPutResponseHopLimit`; 1 stops containers in their own network namespace from reaching IMDS [05 L300].
- **HPA (Horizontal Pod Autoscaler)** — scales replicas on CPU/memory or external metrics [04 L200].
- **Hubble** — Cilium's flow observability (DNS, HTTP, drops) [05 L400].
- **Hybrid Nodes (EKS)** — on-premises or edge machines joined to an EKS control plane [04 L300].

## I

- **IaC (Infrastructure as Code)** — CloudFormation, CDK, Terraform, eksctl config, Kustomize [08 L100].
- **Idempotency** — processing the same message twice has the same effect as once; required for at-least-once queues [09 L300].
- **IMDS / IMDSv2** — EC2 instance metadata at `169.254.169.254`; v2 requires a session token via `PUT` [05 L300].
- **Image index (manifest list)** — OCI object pointing to per-platform manifests; what a multi-arch tag resolves to [01 L200].
- **Ingress** — Kubernetes object describing HTTP routing; the AWS Load Balancer Controller turns it into an ALB [05 L200].
- **IngressGroup** — annotation grouping several Ingresses onto one ALB [05 L200].
- **Inspector (enhanced scanning)** — vulnerability scanning of ECR images, continuous or on push [02 L200].
- **IRSA (IAM Roles for Service Accounts)** — pods assume IAM roles through a projected OIDC token and `AssumeRoleWithWebIdentity` [06 L200].
- **Istio** — sidecar-based service mesh; an option on EKS [05 L300].

## J

- **JCasC** — Jenkins Configuration as Code [08 L200].
- **Job (Kubernetes)** — run-to-completion pod controller with retries [09 L200].
- **Job definition / queue (Batch)** — what to run and where jobs wait for compute [09 L200].

## K

- **Karpenter** — node autoscaler that launches right-sized EC2 instances per pending pods and consolidates; the engine inside Auto Mode [04 L200].
- **KEDA** — event-driven autoscaler that feeds queue depth, lag or metrics into an HPA [09 L200].
- **KMS envelope encryption (EKS secrets)** — Kubernetes Secrets encrypted with a KMS key at rest in etcd [06 L200].
- **kro** — Kube Resource Orchestrator; composes resources from a graph definition; an EKS Capability [04 L300].
- **kube-proxy** — programs Service virtual IPs into iptables/IPVS/nftables on each node [04 L200].
- **kubeconform** — validates Kubernetes manifests against schemas offline [11 L200].
- **kubelet** — node agent that runs pods through the CRI and reports status [04 L200].
- **Kustomize** — template-free manifest customisation with bases and overlays [08 L200].
- **Kyverno / Gatekeeper** — policy engines for admission control [06 L300].

## L

- **Layer** — a tar diff in an image; shared between images with the same content [01 L100].
- **Lifecycle hook (ECS deployment)** — Lambda invoked at deployment stages (blue/green) that can fail the deployment [08 L300].
- **Lifecycle policy (ECR)** — rules that expire images by age or count [02 L200].
- **Link-local address** — `169.254.0.0/16`; per-host services such as IMDS and the ECS credentials endpoint [05 L300].
- **Liveness / readiness / startup probe** — kubelet checks: restart when dead, remove from endpoints when not ready, hold other probes during start [04 L200].
- **Load Balancer Controller (AWS)** — Kubernetes controller creating ALBs/NLBs from Ingress, Service and Gateway objects [05 L200].

## M

- **Managed Instances (ECS)** — AWS-operated EC2 instances in your account as an ECS capacity provider [03 L300].
- **Managed node group** — EKS-managed ASG of nodes with rolling updates that respect PDBs [04 L200].
- **Manifest (OCI)** — JSON describing an image's config and layers [01 L200].
- **max-pods** — kubelet's per-node pod limit, derived from ENI/IP math [05 L300].
- **Metric math** — CloudWatch expressions over metrics (ratios, `FILL`, `IF`) used in alarms and scaling [07 L300].
- **microVM** — lightweight VM (Firecracker) giving each Fargate task its own kernel [01 L300].
- **MSK (Managed Streaming for Apache Kafka)** — Provisioned (Standard/Express brokers) or Serverless Kafka [09 L200].
- **mTLS** — mutual TLS between services; Service Connect, Cilium mesh, Istio, Lattice [06 L400].
- **Multi-arch image** — image index with `linux/amd64` and `linux/arm64` manifests [01 L200].

## N

- **Namespace (Kubernetes)** — logical partition for objects, policies and quotas [04 L100].
- **Namespace (Linux)** — kernel isolation of pid, net, mnt, uts, ipc, user, cgroup, time views [01 L300].
- **NAT gateway** — managed IPv4 egress for private subnets; billed per hour and per GB [05 L100].
- **ndots** — `resolv.conf` option; Kubernetes default 5 turns short names into several cluster lookups before the external one [04 L300].
- **NetworkPolicy** — Kubernetes object restricting pod ingress/egress; enforced by the VPC CNI agent or Cilium [05 L300].
- **NLB (Network Load Balancer)** — layer-4 load balancer with static IPs and PrivateLink support [05 L200].
- **NodeClass / EC2NodeClass** — AWS-specific node template for Auto Mode (`eks.amazonaws.com`) or Karpenter (`karpenter.k8s.aws`) [04 L200].
- **NodeLocal DNSCache** — per-node DNS cache DaemonSet that avoids conntrack races and CoreDNS load [04 L300].
- **NodePool** — Karpenter/Auto Mode scheduling constraints, limits and disruption policy for a class of nodes [04 L200].
- **Notation / AWS Signer** — image signing and verification tooling; the AWS-native alternative to cosign [01 L400].

## O

- **OCI (Open Container Initiative)** — image, distribution and runtime specifications [01 L200].
- **OIDC (OpenID Connect)** — identity federation protocol behind IRSA, GitHub Actions to AWS, and ALB authentication [06 L200].
- **OOMKilled** — the kernel killed a process for exceeding its memory limit; exit code 137 [01 L300].
- **OpenTelemetry (OTel) / OTLP** — vendor-neutral telemetry SDKs and the protocol the collector receives [07 L200].
- **Outbox pattern** — write events to a table in the same transaction as the data, relay them to the broker afterwards [09 L400].
- **Outlier detection** — Service Connect/Envoy ejecting an unhealthy endpoint from the pool [03 L300].

## P

- **PDB (PodDisruptionBudget)** — limits voluntary evictions (drains, consolidation) of a workload [10 L200].
- **Pilot light / warm standby / active-active / backup-and-restore** — the four DR strategies in ascending cost and descending RTO [10 L300].
- **Placement strategy / constraint (ECS)** — how tasks spread over container instances (`spread`, `binpack`, attributes) [03 L200].
- **PLEG (Pod Lifecycle Event Generator)** — kubelet loop watching the runtime; "PLEG is not healthy" means the runtime is slow [04 L300].
- **Pod** — smallest Kubernetes unit: one or more containers sharing network and storage [04 L100].
- **Pod Identity (EKS)** — association of a service account to an IAM role, served by an agent at `169.254.170.23` [06 L200].
- **Pod Security Standards / Admission (PSS/PSA)** — built-in profiles (privileged, baseline, restricted) enforced per namespace [06 L300].
- **Prefix delegation** — VPC CNI assigns `/28` prefixes per ENI slot, raising max-pods [05 L300].
- **PrivateLink** — private connectivity to services through interface endpoints [05 L300].
- **Provenance (SLSA)** — attestation of how and from what an artifact was built [01 L400].
- **PSI (Pressure Stall Information)** — kernel metrics of time spent waiting on CPU/memory/IO [01 L300].
- **Pull-through cache** — ECR rule that fetches and caches images from an upstream registry on first pull [02 L300].

## Q

- **QoS class** — Kubernetes Guaranteed/Burstable/BestEffort from requests and limits; decides eviction order [04 L200].
- **Quota (service)** — account-level limits, many adjustable through Service Quotas [reference].

## R

- **RDS Proxy** — connection pooler in front of RDS/Aurora; multiplexes unless sessions are pinned [09 L200].
- **Readiness gate** — pod readiness condition injected by the load balancer controller, true once the ALB target is healthy [08 L300].
- **Redrive** — moving messages from a DLQ back to the source queue [09 L200].
- **Replication rule (ECR)** — automatic cross-Region or cross-account copying of pushed images [02 L300].
- **Requests / limits** — Kubernetes resource declarations: requests drive scheduling, limits are enforced (memory kill, CPU throttle) [04 L200].
- **Rolling update** — replacing instances gradually under `maxSurge`/`maxUnavailable` or `MinimumHealthyPercent`/`MaximumPercent` [08 L300].
- **RTO / RPO** — recovery time objective / recovery point objective [10 L100].
- **runc** — the reference OCI runtime that creates the container process [01 L300].

## S

- **SBOM (Software Bill of Materials)** — inventory of packages in an image (SPDX, CycloneDX) [01 L400].
- **seccomp** — syscall filter; `RuntimeDefault` profile blocks dangerous calls [01 L300].
- **Security groups for pods** — VPC CNI feature attaching security groups to individual pods via branch ENIs [05 L300].
- **Service (Kubernetes)** — stable virtual IP and DNS name in front of pods (ClusterIP, NodePort, LoadBalancer, headless) [04 L200].
- **Service (ECS)** — keeps N copies of a task definition running and wires them to load balancers [03 L100].
- **Service Connect** — ECS service-to-service networking through a managed Envoy per task with aliases, retries and TLS [03 L300].
- **Service-linked role** — IAM role a service assumes to act in your account (ECS, Batch, Application Auto Scaling) [06 L200].
- **Session tags** — STS tags on assumed-role sessions; Pod Identity adds cluster/namespace/SA tags for ABAC [06 L200].
- **Sidecar** — helper container in the same task/pod (OTel collector, Envoy) [03 L200].
- **SIGTERM / SIGKILL** — polite stop signal, then forced kill after the grace period [10 L200].
- **SLO / SLI** — target for a measured indicator (availability, latency) over a window [07 L300].
- **SNAT** — source NAT; VPC CNI SNATs pod traffic to the node IP for off-VPC destinations by default [05 L300].
- **SOCI** — seekable OCI index enabling lazy loading of image layers on Fargate [02 L300].
- **Spot** — spare EC2/Fargate capacity, interruptible with a two-minute warning [03 L200].
- **SQS** — managed message queue (standard and FIFO) with visibility timeout and DLQs [09 L200].
- **Stampede (cache)** — many callers recomputing the same expired key at once; mitigated by TTL jitter [09 L300].
- **StatefulSet** — Kubernetes controller for ordered, identity-preserving pods with persistent volumes [04 L100].
- **stopTimeout** — ECS time between SIGTERM and SIGKILL (max 120 s on Fargate) [03 L200].
- **stoppedReason / stopCode** — ECS fields explaining why a task stopped [03 L300].
- **Supply chain security** — signing, provenance, SBOMs, scanning and admission verification of artifacts [01 L400].

## T

- **Tag immutability** — ECR setting preventing a tag from being re-pushed to a different digest [02 L200].
- **Target group** — set of ALB/NLB targets (IPs or instances) with a health check [05 L200].
- **Target tracking** — scaling policy that keeps a metric at a target value [03 L200].
- **Task / task definition (ECS)** — a running instance / the versioned blueprint of containers, resources, roles and networking [03 L100].
- **Task role (ECS)** — IAM role the application code inside a task uses [06 L200].
- **Task metadata endpoint** — `169.254.170.2/v4/...` with task, container and stats information [03 L300].
- **Testcontainers** — library that starts real dependencies in containers for tests [11 L200].
- **Topology spread constraints** — Kubernetes scheduling rule spreading pods across zones or nodes [10 L200].
- **Trace context propagation** — passing trace ids across HTTP headers, SQS attributes and Kafka headers [07 L400].
- **Transaction Search** — CloudWatch feature indexing 100 percent of spans for search [07 L200].

## U

- **ulimits** — per-process resource limits (`nofile`) set in task definitions [03 L200].
- **User namespaces / rootless** — mapping container root to an unprivileged host uid [01 L400].

## V

- **Valkey** — open-source Redis-compatible engine; ElastiCache's default for new caches [09 L200].
- **Velero** — backup/restore of Kubernetes objects and volumes [10 L300].
- **Visibility timeout** — time an SQS message is hidden after being received [09 L200].
- **VolumeAttributesClass** — Kubernetes object for modifying volume parameters (replaces Auto Mode EBS annotations) [04 L200].
- **VPA (Vertical Pod Autoscaler)** — recommends or sets requests from observed usage [04 L200].
- **VPC CNI** — the default EKS network plugin assigning VPC IPs to pods from ENIs [04 L200].
- **VPC Lattice** — application-layer service network across VPCs and accounts with IAM auth policies [05 L300].

## W

- **WAF (Web Application Firewall)** — request filtering attached to ALBs, API Gateway or CloudFront [05 L200].
- **Well-Architected Framework** — AWS's six pillars and lenses (Container Build Lens) for reviewing workloads [12].
- **Workload identity** — the IAM identity a running container has (task role, Pod Identity, IRSA) as opposed to node or human identity [06 L200].

## X

- **X-Ray** — AWS tracing backend; receives OTel traces through ADOT; SDKs in maintenance [07 L200].

## Z

- **Zonal shift / autoshift** — ARC operation moving traffic away from an impaired AZ [10 L200].
