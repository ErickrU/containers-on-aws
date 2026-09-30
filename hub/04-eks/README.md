# 04 · Amazon EKS

Amazon Elastic Kubernetes Service runs the Kubernetes control plane for you (kube-apiserver, etcd,
scheduler, controller managers, spread over three Availability Zones) and gives you four ways to
attach compute to it: managed node groups on EC2, Fargate, EKS Auto Mode and Hybrid Nodes. What
makes it a domain of its own is everything that sits between the API server and a running `shopfront`
pod: the kubelet and containerd on every node, kube-proxy and the Service abstraction, CoreDNS, the
VPC CNI (or Cilium) that hands VPC addresses to pods, the add-ons that have to be upgraded in the
right order, IRSA and Pod Identity, access entries, the AWS Load Balancer Controller, Karpenter or
Auto Mode deciding which instance to buy, and the version clock that forces an upgrade every fourteen
months. The documents below go from "what is a Deployment" to "how many clusters should a company of
forty teams run, and what breaks first". Terms are defined once in the [glossary](../../GLOSSARY.md);
time-sensitive facts (1.36 is the newest EKS version, 1.33 is in extended support, AL2 AMIs ended
2025-11-26) are pinned in [`docs/FACTS-2026-09.md`](../../docs/FACTS-2026-09.md).

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 · Kubernetes and EKS basics](L100-kubernetes-and-eks-basics.md) | The Kubernetes object model; control plane vs data plane and what EKS manages; standard vs Auto Mode; the five node options at a glance; `kubectl` and `eksctl` first steps; versions, support windows and what a cluster costs |
| 200 | [L200 · Cluster components and add-ons](L200-cluster-components-and-add-ons.md) | Every component between API server and pod and how to configure it: kubelet, kube-proxy modes and Service types, CoreDNS and `ndots`, VPC CNI warm pools and prefix delegation, managed add-ons, node groups, Fargate profiles, Auto Mode `NodePool`/`NodeClass`, Karpenter, EBS/EFS CSI, the Load Balancer Controller, access entries, IRSA vs Pod Identity, HPA/VPA, PDBs, probes, QoS |
| 300 | [L300 · EKS internals and operations](L300-eks-internals-and-operations.md) | Packets and API calls: control-plane ENIs and endpoints, the `get-token` → STS → authenticator → RBAC chain, ipamd and the ENI/IP state machine, iptables vs IPVS vs nftables, CoreDNS failure mechanics (`ndots`, UDP truncation, conntrack races, the 1,024 pps Resolver limit), Auto Mode internals, containerd forensics, Cilium datapaths, EKS Capabilities, upgrade mechanics, Windows/GPU, Hybrid Nodes |
| 400 | [L400 · EKS at scale](L400-eks-at-scale.md) | Multi-cluster topologies, scaling limits and IP exhaustion, capacity design with Karpenter and Auto Mode, the cost model with numbers, hardening at scale, DR for clusters, zonal shift, fleet upgrade cadences, a Well-Architected review, when EKS is the wrong tool |

## Components covered

- Kubernetes objects: Pod, Deployment, ReplicaSet, Service, Ingress, ConfigMap, Secret, Namespace,
  Job/CronJob, DaemonSet, StatefulSet, PersistentVolumeClaim — L100
- Control plane: kube-apiserver, etcd, kube-scheduler, kube-controller-manager,
  cloud-controller-manager; how EKS runs them across AZs and scales them; control-plane ENIs,
  cluster security group, public/private endpoint; control plane log types — L100 (what), L200
  (configuration), L300 (internals)
- Versions and support: standard and extended support, platform versions `eks.N`, Kubernetes 1.36
  highlights, the 7-day rollback window, upgrade insights — L100, L300, L400
- kubelet and containerd: node bootstrap (`nodeadm`, Bottlerocket settings), kubelet configuration,
  image pull settings, `crictl`, containerd config and registry mirrors, node forensics — L200, L300
- kube-proxy: iptables, IPVS and nftables modes, conntrack, Service types, `externalTrafficPolicy`,
  EndpointSlices, traffic distribution — L200, L300
- CoreDNS: Corefile, `ndots:5`, autopath, NodeLocal DNSCache, add-on autoscaling, UDP truncation,
  conntrack races, Route 53 Resolver limits — L200, L300
- Amazon VPC CNI: `aws-node`, ipamd, `WARM_*` and `MINIMUM_IP_TARGET`, prefix delegation, custom
  networking with `ENIConfig`, IPv6, security groups for pods, the eBPF network policy engine,
  max-pods arithmetic — L200, L300 (IP-level packet walk in
  [05 · L300](../05-networking/L300-container-networking-internals.md))
- Cilium on EKS: ENI mode, overlay, chaining with the VPC CNI, kube-proxy replacement, Hubble,
  Hybrid Nodes — L300
- Managed add-ons and community add-ons: versions, configuration schemas, conflict resolution,
  upgrade order — L200, L300
- Compute: managed node groups (AL2023, Bottlerocket, launch templates, update strategies, taints
  and labels, IMDS hop limit), self-managed nodes, Fargate profiles and their limits, EKS Auto Mode
  (`NodePool`, `NodeClass`, built-in capabilities, 21-day node lifetime, what you cannot change),
  Karpenter (`NodePool`, `EC2NodeClass`, consolidation, drift, disruption budgets), Hybrid Nodes,
  Windows and GPU nodes — L100 (overview), L200 (configuration), L300 (internals), L400 (design)
- Storage: EBS CSI, EFS CSI, StorageClass, VolumeSnapshot, `VolumeAttributesClass`, Auto Mode
  block storage and the 2026-10-31 annotation deadline — L200
- Load balancing: AWS Load Balancer Controller (Ingress → ALB, Service → NLB, target types,
  IngressGroup, IngressClass and IngressClassParams, readiness gates, Gateway API) and Auto Mode's
  built-in controller — L200 (ALB/NLB mechanics in
  [05 · L200](../05-networking/L200-load-balancing-ingress-and-discovery.md))
- Identity: access entries and access policies, RBAC, the authentication flow, OIDC issuer and
  IRSA, EKS Pod Identity — L200 (wiring), L300 (flow); full IAM treatment in
  [06 · L200](../06-identity-and-security/L200-iam-for-containers.md)
- Workload controls: metrics-server, HPA, VPA, KEDA pointer, PodDisruptionBudget, probes,
  requests/limits and QoS — L200
- EKS Capabilities (managed Argo CD, ACK, kro) — L300; GitOps use in
  [08 · L200](../08-delivery-cicd-gitops/L200-pipelines-on-aws.md)
- Scale and design: multi-cluster topologies, etcd and API server limits, IP exhaustion, Spot
  diversification, cost model, hardening at scale, DR, ARC zonal shift, fleet upgrades — L400

## Related

- Labs: the EKS path of `shopfront` starts with
  [`labs/eks/cluster/eksctl-standard.yaml`](../../labs/eks/cluster/eksctl-standard.yaml) (managed
  node groups on AL2023, managed add-ons, Pod Identity) and
  [`labs/eks/cluster/eksctl-auto-mode.yaml`](../../labs/eks/cluster/eksctl-auto-mode.yaml); the
  workloads are the Kustomize tree in [`labs/eks/manifests/`](../../labs/eks/manifests/), the Helm
  values and the Pod Identity association script live in [`labs/eks/addons/`](../../labs/eks/addons/),
  and the Argo CD objects in [`labs/eks/gitops/`](../../labs/eks/gitops/). The service contract every
  manifest must honour is [`labs/CONTRACT.md`](../../labs/CONTRACT.md).
- Playbooks: [pending pods and capacity](../../playbooks/incidents/pending-pods-and-capacity.md),
  [node NotReady](../../playbooks/incidents/node-not-ready.md),
  [DNS failures](../../playbooks/incidents/dns-failures.md),
  [EKS auth and access](../../playbooks/incidents/eks-auth-and-access.md),
  [upgrade breakage](../../playbooks/incidents/upgrade-breakage.md),
  [image pull failures](../../playbooks/incidents/image-pull-failures.md),
  [IAM AccessDenied from containers](../../playbooks/incidents/iam-accessdenied-from-containers.md),
  [ALB 5xx and unhealthy targets](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md);
  upgrade runbooks [EKS version upgrade](../../playbooks/upgrades/eks-version-upgrade.md) and
  [add-on and controller upgrades](../../playbooks/upgrades/addon-and-controller-upgrades.md);
  DR runbooks [cluster rebuild](../../playbooks/dr/cluster-rebuild-runbook.md) and
  [region failover](../../playbooks/dr/region-failover-runbook.md).
- Reference: [metrics catalog](../../reference/metrics-catalog.md),
  [quotas and limits](../../reference/quotas-and-limits.md),
  [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md),
  [decision guides](../../reference/decision-guides.md) (ECS vs EKS, Fargate vs EC2 vs Auto Mode,
  VPC CNI vs Cilium, IRSA vs Pod Identity, Karpenter vs Cluster Autoscaler vs Auto Mode),
  [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md),
  [CLI cheat sheet](../../reference/cli-cheatsheet.md).
- Neighbouring domains: what runs inside the pod (containerd, runc, cgroups) in
  [01 · Container fundamentals](../01-container-fundamentals/README.md); where the images come
  from in [02 · ECR](../02-ecr/README.md); the other orchestrator in [03 · ECS](../03-ecs/README.md);
  VPC design, ALB/NLB and link-local addresses in [05 · Networking](../05-networking/README.md);
  IAM, Pod Security and admission in [06 · Identity and security](../06-identity-and-security/README.md);
  Container Insights, ADOT and the metrics that matter in
  [07 · Observability](../07-observability/README.md); Argo CD, Argo Rollouts and pipelines in
  [08 · Delivery](../08-delivery-cicd-gitops/README.md); Batch on EKS and KEDA in
  [09 · Data, messaging and batch](../09-data-messaging-and-batch/README.md); Velero, zonal shift
  and DR plans in [10 · Resilience and DR](../10-resilience-and-dr/README.md).
