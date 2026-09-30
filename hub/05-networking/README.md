# 05 · Networking

Everything a packet does between a client and a container on AWS, and everything a container
does to find, reach and trust another one. This is its own domain because the network is where
ECS, EKS, ECR, IAM, ELB, Cloud Map, Route 53 and the EC2 data plane meet, and because most
container incidents that are not "the image is broken" are network incidents in disguise: a task
that cannot pull because a private subnet has no route to ECR, a pod that cannot get an IP, an
ALB that returns 502 while every target looks healthy, a `curl` to `169.254.169.254` that hangs
for two seconds and makes an SDK fall back to the wrong credentials. The four levels go from the
VPC layout a beginner must get right, through load balancers and service discovery, into the
kernel and ENI mechanics an on-call engineer needs, and out to the multi-account, multi-Region
architecture and cost model a platform team owns.

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 — VPC for containers](L100-vpc-for-containers.md) | A VPC layout you can defend (public/private/isolated subnets, route tables, NAT, `/28` control-plane subnets), security groups vs NACLs, DNS in a VPC, the ELB family at a glance, and how an ECS task or an EKS pod obtains an IP address |
| 200 | [L200 — Load balancing, ingress and discovery](L200-load-balancing-ingress-and-discovery.md) | ALB vs NLB vs GWLB, every target-group setting that matters (target type, health checks, slow start, deregistration delay, stickiness, cross-zone), TLS with ACM and WAF, the AWS Load Balancer Controller and Auto Mode's built-in load balancing, Gateway API, API Gateway VPC links, CloudFront, and a comparison of Cloud Map, Service Connect, Kubernetes Services and headless Services |
| 300 | [L300 — Container networking internals](L300-container-networking-internals.md) | The link-local address table, IMDSv2 token and hop-limit mechanics, ENI and IP arithmetic (prefix delegation, custom networking, IPv6), security groups for pods, network policy engines, kube-proxy and conntrack, the Cilium datapath, MTU, SNAT rules, the PrivateLink endpoint list for private clusters, VPC Lattice and the service-mesh options after App Mesh |
| 400 | [L400 — Network architecture at scale](L400-network-architecture-at-scale.md) | IP planning for fleets, shared VPC and Transit Gateway, multi-account egress control, fully private clusters, zonal isolation with ARC zonal shift, DNS at scale, the data-transfer cost model with numbers, a mesh decision record, flow-log/Hubble/mirroring observability, and four failure stories (IP, conntrack, DNS, NAT ports) |

## Components covered

- Amazon VPC: CIDR planning, public/private/isolated subnets, route tables, internet gateway, NAT
  gateway, egress-only internet gateway, DHCP option sets, VPC DNS and the Route 53 Resolver
  (`10.42.0.2` / `169.254.169.253`) — L100; secondary CIDRs (`100.64.0.0/16`), IPv6 dual-stack
  and IPv6-only, NAT64/DNS64, subnet CIDR reservations — L300; VPC IPAM, shared VPC (RAM),
  Transit Gateway, VPC peering, Cloud WAN — L400
- Security groups and network ACLs: statefulness, SG references, quotas — L100; the Nitro
  connection-tracking allowance and untracked flows — L300
- Elastic network interfaces: `awsvpc` task ENIs, Fargate ENI-per-task, ENI trunking (trunk and
  branch ENIs), VPC CNI secondary IPs and `/28` prefixes, `max-pods` arithmetic — L100 and L300
- Elastic Load Balancing: ALB, NLB, GWLB (and why not CLB); listeners, rules, target groups
  (`ip` vs `instance`), health checks, slow start, deregistration delay, stickiness, cross-zone
  behaviour and its cost, target-group health thresholds, access and connection logs — L200
- AWS Certificate Manager and AWS WAF on load balancers; TLS policies; mTLS on ALB — L200
- AWS Load Balancer Controller: `Ingress`, `IngressClass`, `IngressClassParams`, `IngressGroup`,
  pod readiness gates, `TargetGroupBinding`, `Service` type `LoadBalancer` to NLB, Gateway API
  (`HTTPRoute`/`GRPCRoute` to ALB, `TCPRoute`/`UDPRoute`/`TLSRoute` to NLB) — L200
- EKS Auto Mode built-in load balancing (`eks.amazonaws.com/alb`, `eks.amazonaws.com/nlb`) — L200
- Amazon API Gateway HTTP APIs with VPC links; Amazon CloudFront (VPC origins, origin-facing
  prefix list, WAF) — L200
- Service discovery: AWS Cloud Map (A vs SRV records, TTLs, custom health), ECS Service Connect
  (Envoy agent, client aliases, TLS, timeouts), Kubernetes `Service` + CoreDNS, headless
  Services and EndpointSlices — L200; internals owned by domains 03 and 04
- Link-local addresses: IMDS `169.254.169.254` / `fd00:ec2::254`, ECS task metadata and
  credentials `169.254.170.2`, EKS Pod Identity agent `169.254.170.23` / `fd00:ec2::23`, Route 53
  Resolver `169.254.169.253`, Amazon Time Sync `169.254.169.123`, VPC Lattice `169.254.171.0/24`
  — L300
- IMDSv2: PUT token, TTL header, hop limit, `HttpTokens=required`, account-level defaults, how
  to block IMDS from containers on EKS, ECS EC2, Fargate and Auto Mode — L300
- Amazon VPC CNI internals: ipamd, warm pools, prefix delegation, custom networking (`ENIConfig`),
  security groups for pods (`SecurityGroupPolicy`), the eBPF network policy agent, SNAT rules
  (`AWS_VPC_K8S_CNI_EXTERNALSNAT`) — L300
- kube-proxy (iptables, IPVS, nftables) and Linux conntrack (`nf_conntrack_max`, `conntrack -S`,
  the UDP DNS race) — L300
- Cilium on EKS: ENI mode, overlay, chaining with VPC CNI, kube-proxy replacement, Hubble,
  cluster mesh, Hybrid Nodes — L300
- MTU and jumbo frames (9001 in a VPC, 1500 across an internet gateway, overlay overhead, PMTUD)
  — L300
- AWS PrivateLink: the interface and gateway endpoints a private ECS or EKS cluster needs, endpoint
  policies, private DNS — L200 (which ones) and L300 (complete list and policies)
- Amazon VPC Lattice: service networks, auth policies, the Gateway API controller, ECS
  integration — L300 and L400
- Service mesh: Istio, Cilium mesh, Linkerd, ECS Service Connect, VPC Lattice; AWS App Mesh end
  of support (2026-09-30) and migration paths — L300; decision record — L400
- Egress control: NAT-only, AWS Network Firewall, explicit proxies, Route 53 Resolver DNS
  Firewall, FQDN network policies — L400
- Zonal isolation: cross-zone off, per-AZ cells, Application Recovery Controller zonal shift and
  autoshift for ALB/NLB and EKS, `trafficDistribution` — L400
- DNS at scale: Resolver packet limits, CoreDNS sizing and autoscaling, NodeLocal DNSCache,
  `ndots`, Resolver endpoints, private hosted zone sharing — L400
- Network observability: VPC Flow Logs, Hubble, VPC Traffic Mirroring, ALB logs, Reachability
  Analyzer, Network Access Analyzer — L300 and L400
- Data-transfer pricing: NAT gateway, cross-AZ, cross-Region, internet egress, interface
  endpoints, Transit Gateway, load balancers — L400

## Related

- Labs: [`labs/ecs/cloudformation/01-network.yaml`](../../labs/ecs/cloudformation/01-network.yaml)
  (the VPC every lab uses), [`labs/eks/manifests/base/`](../../labs/eks/manifests/base/)
  (Ingress, Services, network policies), [`labs/eks/addons/`](../../labs/eks/addons/) (Load
  Balancer Controller and Cilium values), [`labs/CONTRACT.md`](../../labs/CONTRACT.md) (ports
  and endpoints of the shopfront services)
- Playbooks: [ALB 5xx and unhealthy targets](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md),
  [DNS failures](../../playbooks/incidents/dns-failures.md),
  [Pending pods and capacity](../../playbooks/incidents/pending-pods-and-capacity.md),
  [Node NotReady](../../playbooks/incidents/node-not-ready.md),
  [Image pull failures](../../playbooks/incidents/image-pull-failures.md),
  [IAM AccessDenied from containers](../../playbooks/incidents/iam-accessdenied-from-containers.md),
  [Region failover runbook](../../playbooks/dr/region-failover-runbook.md)
- Reference: [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md),
  [decision guides](../../reference/decision-guides.md),
  [metrics catalog](../../reference/metrics-catalog.md),
  [quotas and limits](../../reference/quotas-and-limits.md),
  [service interaction map](../../reference/service-interaction-map.md)
- Neighbouring domains: [03 · ECS](../03-ecs/README.md) (Service Connect and Cloud Map
  internals, task networking), [04 · EKS](../04-eks/README.md) (VPC CNI configuration, CoreDNS,
  kube-proxy, Auto Mode), [06 · Identity and security](../06-identity-and-security/README.md)
  (IMDS as a credential-theft path, network policies as a control), [10 · Resilience and
  DR](../10-resilience-and-dr/README.md) (zonal shift in the DR toolbox)
