# Networking · L300 — Container networking internals

**Level:** 300 · **Time:** ~120 min · **Prerequisites:**
[L200 Load balancing, ingress and discovery](L200-load-balancing-ingress-and-discovery.md),
[EKS L300](../04-eks/L300-eks-internals-and-operations.md), [ECS L300](../03-ecs/L300-ecs-internals.md)

**After this document you can:**

- Explain every link-local address a container may talk to and what answers there.
- Describe the IMDSv2 token exchange, why the hop limit blocks containers, and how to block or allow
  IMDS on ECS EC2, Fargate, EKS nodes and Auto Mode.
- Do the ENI/IP arithmetic for any instance type, with and without prefix delegation, custom
  networking and IPv6.
- Read kube-proxy/conntrack, VPC CNI network policy and Cilium datapaths well enough to diagnose
  drops.
- List the PrivateLink endpoints a fully private ECS or EKS environment needs, and place VPC Lattice
  and service meshes correctly.

## 1. Mental model

```mermaid
sequenceDiagram
  autonumber
  participant C as client (internet)
  participant ALB as ALB node (public subnet)
  participant SG as security groups
  participant N as node / task ENI (private subnet)
  participant P as pod / container netns
  C->>ALB: TLS 443 (SG alb: 443 from 0.0.0.0/0)
  ALB->>SG: new TCP to 10.42.18.77:8080
  SG-->>ALB: allowed (target SG: 8080 from sg-alb)
  ALB->>N: packet arrives on the ENI owning 10.42.18.77
  N->>P: host ip rule/route -> veth -> pod eth0 (EKS) or the task ENI is the pod's (Fargate/awsvpc)
  P-->>ALB: response; conntrack on the host maps the reply
  Note over P: outbound to AWS APIs: pod IP -> ENI -> VPC endpoint or NAT; SNAT unless EXTERNALSNAT
  Note over P: link-local 169.254.x.x never leaves the host: IMDS, ECS/Pod Identity agents
```

Every packet a container sends or receives crosses three layers you can inspect: the container's
network namespace (its own `eth0`, routes and iptables), the host's namespace (veths, policy routes,
conntrack, the CNI's rules, kube-proxy chains), and the VPC (ENIs, security groups, route tables,
NACLs, endpoints). Link-local addresses are the exception that proves the model: they are answered
by something on the host (IMDS via the hypervisor, the ECS agent, the Pod Identity agent) and are
governed by hop limits and host rules rather than by VPC routing. Most "networking is broken"
incidents are a mismatch between two layers: a security group that allows the node but not the pod,
a conntrack table that is full while the VPC is fine, or an IMDS hop limit that is one too high.

## 2. Concepts

### 2.1 Link-local addresses

| Address | Answered by | Who uses it | Notes |
| --- | --- | --- | --- |
| `169.254.169.254` (IPv6 `fd00:ec2::254`) | EC2 Instance Metadata Service (hypervisor) | instance-level agents: SSM, ECS agent, kubelet/nodeadm, cloud-init | credentials of the **instance role**; must not be reachable from workloads |
| `169.254.170.2` | ECS agent (EC2) or Fargate task metadata service | every ECS container: `ECS_CONTAINER_METADATA_URI_V4`, `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` | task-role credentials, task metadata and stats ([ECS L300 §2.3](../03-ecs/L300-ecs-internals.md)) |
| `169.254.170.23` (IPv6 `fd00:ec2::23`) | `eks-pod-identity-agent` DaemonSet (hostNetwork) | pods with a Pod Identity association: `AWS_CONTAINER_CREDENTIALS_FULL_URI` | pod-role credentials ([EKS L300 §2.3](../04-eks/L300-eks-internals-and-operations.md)) |
| `169.254.169.253` | Route 53 Resolver (also reachable at VPC base + 2, e.g. `10.42.0.2`) | anything resolving DNS in the VPC; CoreDNS forwards here | 1024 packets/s per ENI limit |
| `169.254.169.123` | Amazon Time Sync Service | chrony/ntpd on instances and in containers that run their own clock sync | prefer it over public NTP |
| `169.254.20.10` (conventional) | NodeLocal DNSCache | pods on nodes with the cache | dummy interface on the node |
| `169.254.0.0/16` in general | link-local per RFC 3927; never routed off the host/subnet | | a NetworkPolicy egress rule to `169.254.169.254/32` is how you block IMDS at L3 in Kubernetes |

Fargate tasks have `169.254.170.2` but **no** `169.254.169.254`: the microVM exposes no IMDS.

### 2.2 IMDSv2 mechanics and the hop limit

IMDSv2 is a session protocol: a client first `PUT`s to `/latest/api/token` with a TTL header and
receives a token; every subsequent `GET` presents it. The instance option `HttpTokens=required`
disables IMDSv1's plain `GET`s. The option `HttpPutResponseHopLimit` sets the IP TTL of the PUT
**response** packet.

```mermaid
sequenceDiagram
  autonumber
  participant P as process in container
  participant H as host network namespace
  participant I as IMDS 169.254.169.254
  P->>H: PUT /latest/api/token (X-aws-ec2-metadata-token-ttl-seconds: 21600)
  H->>I: forwarded (routed hop: TTL decremented on the way back)
  I-->>H: 200 token, IP TTL = HttpPutResponseHopLimit (1)
  Note over H: TTL 1 packet is consumed by the host; forwarding into the container netns would need TTL >= 2
  H--xP: dropped (TTL exceeded) -> client times out
  Note over P: hostNetwork pods and the node itself sit in H, so they still get the token
```

Why this blocks containers: a pod behind a veth (VPC CNI) or a task in `bridge` mode is one routed
hop away from the host namespace; the kernel decrements TTL when forwarding and drops a packet whose
TTL reaches zero. With hop limit 1 the token response can reach processes in the host namespace
(kubelet, SSM agent, the ECS agent) but not the container. Because IMDSv2 requires the token, the
container can never read `/latest/meta-data/iam/security-credentials/`, so the instance role is out
of reach. `hostNetwork: true` pods are not protected by this and need RBAC/admission to be rare.

```bash
# from an instance or a hostNetwork pod
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
curl -sH "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/
# enforce on an instance (launch templates do this at scale)
aws ec2 modify-instance-metadata-options --instance-id i-0123456789abcdef0 \
  --http-tokens required --http-put-response-hop-limit 1 --http-endpoint enabled
# account-level defaults for new instances in a Region
aws ec2 modify-instance-metadata-defaults --http-tokens required --http-put-response-hop-limit 1
aws ec2 get-instance-metadata-defaults
```

| Platform | Workload reach to IMDS | How to block | How to allow deliberately |
| --- | --- | --- | --- |
| ECS on EC2, `awsvpc` | yes by default (task ENI namespace routes to the host) | `ECS_AWSVPC_BLOCK_IMDS=true` in `ecs.config` (agent inserts a drop rule) | leave unset (rare; prefer task roles) |
| ECS on EC2, `bridge` | yes through docker0 | hop limit 1 (bridge is a routed hop); iptables rule from the ECS docs for `host` mode | hop limit 2 |
| ECS Fargate | none | nothing to do | not possible |
| EKS managed/self-managed nodes | yes by default (eksctl sets hop limit 2 for managed groups; verify) | launch template `HttpPutResponseHopLimit: 1` + `HttpTokens: required`; plus NetworkPolicy egress deny to `169.254.169.254/32` | hop limit 2 for a node group that must run IMDS-dependent legacy pods |
| EKS Fargate | none | nothing to do | not possible |
| EKS Auto Mode nodes | AWS-managed launch settings; pods should rely on Pod Identity | verify the current default in the Auto Mode docs; add the NetworkPolicy | n/a |
| Karpenter nodes | `EC2NodeClass.spec.metadataOptions` | `httpTokens: required, httpPutResponseHopLimit: 1` | per NodeClass |

IMDS also carries `instance-identity` documents and user data; blocking it from workloads protects
against SSRF-to-credential-theft, the attack behind several public breaches
([06 L400](../06-identity-and-security/L400-security-architecture-and-incident-response.md)).

### 2.3 ENI and IP arithmetic

Each instance type has a maximum number of ENIs and of IPv4 addresses per ENI. One address per ENI
is the ENI's primary (the node's own on the primary ENI, unused by pods on secondaries in the
default VPC CNI mode), and the node itself uses two pods' worth for `hostNetwork` DaemonSets in the
formula:

```text
max pods (secondary IP mode)   = ENIs × (IPv4 per ENI − 1) + 2
m5.large   : 3 × (10 − 1) + 2 = 29
m5.xlarge  : 4 × (15 − 1) + 2 = 58
c5.large   : 3 × (10 − 1) + 2 = 29
m7g.large  : 3 × (10 − 1) + 2 = 29

max pods (prefix delegation)   = min(110 or 250, ENIs × (IPv4 per ENI − 1) × 16 + 2)
m5.large   : min(110, 3 × 9 × 16 + 2 = 434) = 110      (110 for < 30 vCPU, 250 for ≥ 30 vCPU)
```

Prefix delegation assigns `/28` blocks (16 addresses) to ENI slots on Nitro instances; the subnet
must have contiguous `/28` space, which fragmented subnets lack (`InsufficientCidrBlocks`). IP
consumption per node changes shape: a node with two pods still holds at least one `/28` per ENI slot
it warmed, so plan subnets by nodes × warm prefixes × 16, not by pods.

**Custom networking**: with `AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG=true` and an `ENIConfig` per AZ,
pod ENIs come from a different subnet (typically a secondary VPC CIDR from `100.64.0.0/10`, which
is non-routable across the internet and often unused on-premises). Nodes keep their primary ENI in
the node subnet; the primary ENI no longer hosts pods, reducing max pods by one ENI.

**IPv6 clusters** (`ipFamily: ipv6` at creation): each pod gets a globally unique IPv6 address from
the subnet's `/64` (a `/80` prefix per ENI), IP exhaustion disappears, and IPv4-only destinations
are reached through NAT64/DNS64 (the subnet's `enable-dns64` and a NAT gateway with `nat64`) or an
egress-only internet gateway for IPv6 egress. Services still get IPv6 ClusterIPs; ALBs run
dual-stack. ECS Fargate tasks can be dual-stack when the VPC and subnets are.

**Security groups for pods**: `ENABLE_POD_ENI=true` makes the CNI attach a trunk ENI and give
selected pods (matched by `SecurityGroupPolicy`) their own branch ENI with its own security group.
Density is bounded by the branch ENI limit of the instance; `hostNetwork` pods and pods without a
policy keep the node's group. Use it for pods that must appear as distinct principals to RDS or
ElastiCache security group rules.

### 2.4 Network policy: VPC CNI engine and Cilium

Kubernetes `NetworkPolicy` is an intent; an engine enforces it. The VPC CNI's engine
(`enableNetworkPolicy: true`) runs `aws-eks-nodeagent`, which compiles policies into eBPF programs
attached to each pod's veth (ingress and egress maps keyed by CIDR/port/protocol). Cilium enforces
with its own eBPF datapath and adds identity-based (label) selectors at L3–L7, DNS-aware egress and
`CiliumNetworkPolicy`. The default-deny pattern every namespace should start with:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny, namespace: shopfront }
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-dns-and-aws, namespace: shopfront }
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to: [{ namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: kube-system } }, podSelector: { matchLabels: { k8s-app: kube-dns } } }]
      ports: [{ port: 53, protocol: UDP }, { port: 53, protocol: TCP }]
    - to: [{ ipBlock: { cidr: 0.0.0.0/0, except: [169.254.169.254/32, 10.42.0.0/16] } }]   # AWS APIs via endpoints/NAT, never IMDS
      ports: [{ port: 443, protocol: TCP }]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: orders-to-catalog, namespace: shopfront }
spec:
  podSelector: { matchLabels: { app.kubernetes.io/name: catalog } }
  policyTypes: [Ingress]
  ingress:
    - from: [{ podSelector: { matchLabels: { app.kubernetes.io/name: orders } } }]
      ports: [{ port: 8081, protocol: TCP }]
```

Policies apply to pod veths, so `hostNetwork` pods are outside them; ALB `ip` targets need an
ingress rule from the ALB's subnet CIDRs (or the ALB security group through security groups for
pods). Verify with `kubectl -n shopfront get networkpolicy` and the node agent logs
(`kubectl -n kube-system logs ds/aws-node -c aws-eks-nodeagent`); Cilium adds `hubble observe
--verdict DROPPED`.

### 2.5 kube-proxy, conntrack and the host datapath

Service traffic from a pod hits the host's `nat` table (iptables mode): `KUBE-SERVICES` →
`KUBE-SVC-*` (random endpoint selection) → `KUBE-SEP-*` (DNAT to pod IP). Conntrack records the
translation so replies are un-NATed. Three consequences worth remembering:

- Conntrack has a fixed size (`net.netfilter.nf_conntrack_max`, kube-proxy defaults to
  `maxPerCore` × cores with a floor); when full, new connections are dropped with
  `nf_conntrack: table full, dropping packet` in `dmesg`. Symptom: random connection timeouts on a
  busy node while the VPC is fine. Check `conntrack -S` and `cat /proc/sys/net/netfilter/nf_conntrack_count`.
- UDP has no handshake, so two DNS queries racing for the same conntrack entry expose the kernel race
  described in [EKS L300 §2.6](../04-eks/L300-eks-internals-and-operations.md).
- Established connections keep their endpoint until closed; scaling out does not rebalance gRPC or
  database pools.

IPVS mode uses hash tables instead of chain walks; nftables mode (GA since 1.33) is the modern
backend; Cilium's kube-proxy replacement removes the iptables path entirely and does socket-level
load balancing for ClusterIP with eBPF.

On Fargate and ECS `awsvpc`, there is no kube-proxy: the task's ENI is the container's network,
and Service Connect (Envoy) does the local routing when enabled.

### 2.6 Cilium datapath on EKS

| Mode | Pod addressing | Datapath | When |
| --- | --- | --- | --- |
| ENI IPAM (`ipam.mode=eni`) | VPC secondary IPs (prefix delegation supported) | eBPF on veth; native routing in the VPC | the default recommendation on EKS EC2 nodes |
| Overlay (VXLAN/Geneve, `routingMode=tunnel`) | cluster CIDR not known to the VPC | encapsulation between nodes (MTU minus 50 bytes) | very high pod density; multi-cloud parity; pods invisible to VPC security groups and to `ip` target groups |
| Chaining (`cni.chainingMode=aws-cni`) | VPC CNI assigns IPs | Cilium adds policy/observability on top | incremental adoption |

Cilium replaces kube-proxy (`kubeProxyReplacement=true`), enforces `CiliumNetworkPolicy` with L7
awareness (HTTP paths, Kafka topics, DNS names), provides Hubble flow logs and service maps, and can
enforce mutual authentication between identities. It is AWS-supported on Hybrid Nodes and
self-supported on EC2 nodes; it is unavailable for Fargate pods and not a customisation Auto Mode
allows. Operational cost: another DaemonSet on the upgrade path, MTU planning in overlay mode, and
careful coexistence with the VPC CNI during migration.

### 2.7 MTU

The VPC supports 9001-byte jumbo frames between instances in the same Region; traffic through an
internet gateway, VPC peering across Regions, VPN and some endpoints is limited to 1500. Instances
default to 9001; the VPC CNI sets pod veth MTU to 9001 (`AWS_VPC_ENI_MTU`), overlays subtract their
header (VXLAN 50 bytes). Path MTU discovery normally handles the drop to 1500, but ICMP-blocking
security groups or NACLs turn it into a black hole: small requests work, large responses hang. Allow
ICMP `Destination Unreachable` (type 3) inbound where you have jumbo frames, or set 1500 on
workloads that talk to the internet heavily.

### 2.8 SNAT rules

By default the VPC CNI SNATs pod traffic leaving the VPC to the node's primary IP (so NAT gateways
and peers see the node). `AWS_VPC_K8S_CNI_EXTERNALSNAT=true` disables it when the pod CIDR is
routable end to end (Transit Gateway, Direct Connect with pod CIDRs advertised);
`AWS_VPC_K8S_CNI_EXCLUDE_SNAT_CIDRS` exempts specific ranges. With custom networking using
`100.64.0.0/16`, keep SNAT on unless the peers route that range. Fargate tasks have their own ENI and
never SNAT.

### 2.9 PrivateLink endpoints for private environments

A fully private subnet (no NAT) needs interface endpoints for every AWS API the platform touches.
Gateway endpoints (S3, DynamoDB) are free and route through prefix lists; interface endpoints are
ENIs with private DNS (`enable private DNS` so the public hostname resolves to them).

| Endpoint (`com.amazonaws.us-east-1.…`) | Needed by | Why |
| --- | --- | --- |
| `s3` (gateway) | everything that pulls images | ECR stores layers in S3 |
| `ecr.api`, `ecr.dkr` | ECS agent/Fargate, kubelet/containerd | image manifests and auth; layer redirects |
| `sts` | tasks/pods (task roles, Pod Identity, IRSA), nodes | credential exchange; `sts.us-east-1.amazonaws.com` regional endpoint |
| `logs` | awslogs driver, Fluent Bit, CloudWatch agent | log delivery |
| `monitoring` | CloudWatch agent, ADOT metrics | metrics |
| `xray` | ADOT/X-Ray exporters | traces |
| `ec2` | VPC CNI (ENI/IP management), Karpenter, controllers | ENI operations |
| `ecs`, `ecs-agent`, `ecs-telemetry` | ECS EC2 instances | agent control and telemetry channels |
| `eks`, `eks-auth` | nodes (`nodeadm` DescribeCluster), Pod Identity agent | bootstrap; `AssumeRoleForPodIdentity` |
| `elasticloadbalancing` | load balancer controller | ALB/NLB management |
| `autoscaling` | cluster autoscaler, managed node groups | ASG operations |
| `ssm`, `ssmmessages`, `ec2messages` | ECS Exec, SSM agent on nodes, Session Manager | remote commands |
| `secretsmanager`, `kms` | ECS `secrets[]`, Secrets Store CSI, External Secrets | secret fetch and decrypt |
| `sqs`, `kafka` (MSK), `rds`? (data plane not needed; RDS uses VPC IPs) | shopfront services | queue and broker APIs; RDS/ElastiCache/MSK brokers are already VPC-native |
| `guardduty-data` | GuardDuty runtime agents | findings delivery |
| `application-autoscaling`? | not needed (control plane side) | |

Endpoint policies restrict which principals or resources an endpoint serves (e.g. only your
account's ECR repositories); security groups on endpoints must allow 443 from the workload subnets;
watch the per-endpoint bandwidth and connection limits for ECR-heavy fleets. Reachability Analyzer
(`aws ec2 create-network-insights-path`) proves a path from a task ENI to an endpoint ENI.

### 2.10 VPC Lattice and service meshes

**VPC Lattice** is an application-layer network across VPCs and accounts: a *service network*
shared through RAM, *services* with listeners and rules, *target groups* of instances, IPs, Lambda
functions, ALBs or Kubernetes Services (through the Gateway API controller on EKS), and *auth
policies* evaluated with SigV4 identity. Clients reach services through a link-local-like managed
prefix (`169.254.171.0/24` range and IPv6) routed by the VPC association; no peering or Transit
Gateway needed. It fits cross-account service-to-service traffic and replaces App Mesh for that
use; it does not do east-west inside one cluster as cheaply as ClusterIP or Service Connect.

**Service meshes**: Istio and Cilium (mesh features) give mTLS with workload identity, L7 policy,
retries, traffic shifting and telemetry, at the cost of sidecars or an eBPF datapath to operate.
AWS App Mesh reaches end of support on 2026-09-30 and must be replaced by Service Connect (ECS),
VPC Lattice (cross-account/any compute) or a self-managed mesh (EKS)
([ECS L400 §2.5](../03-ecs/L400-ecs-at-scale.md)). Adopt a mesh for identity-based mTLS and L7
policy requirements, not for retries you can add at the client or load balancer.

### 2.11 Forensics block

```bash
# inside a pod (netshoot) / task (ECS Exec)
ip -4 addr; ip route; cat /etc/resolv.conf
curl -m 2 -s http://169.254.169.254/latest/api/token -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || echo "IMDS blocked"
curl -s "$ECS_CONTAINER_METADATA_URI_V4/task" | jq '.Containers[0].Networks'          # ECS
dig +short catalog.shopfront.svc.cluster.local; dig +short catalog.shopfront.local     # EKS / Cloud Map
# on the node
ip rule; ip route show table main; ip -d link show | grep -E 'veth|eni'
conntrack -S | head -3; cat /proc/sys/net/netfilter/nf_conntrack_max /proc/sys/net/netfilter/nf_conntrack_count
iptables-save -t nat | grep -c KUBE-SVC; iptables -t nat -L PREROUTING -n | head
curl -s localhost:61679/v1/enis | jq '.ENIs | length'
sudo tcpdump -ni any host 169.254.169.254 -c 5
# in the VPC
aws ec2 describe-network-interfaces --filters Name=addresses.private-ip-address,Values=10.42.18.77 \
  --query 'NetworkInterfaces[0].{eni:NetworkInterfaceId,sg:Groups[].GroupId,subnet:SubnetId,desc:Description}'
aws ec2 create-network-insights-path --source eni-0123456789abcdef0 --destination vpce-0123456789abcdef0 --protocol tcp --destination-port 443
```

## 3. How it interacts with the rest of AWS

| Component | Talks to | Protocol/API | Prerequisite (IAM, network, DNS) | What breaks if missing |
| --- | --- | --- | --- | --- |
| Pod/task SDK | STS (via `169.254.170.2` / `169.254.170.23` agents or IRSA token) | HTTPS | endpoint or NAT to `sts`; agents running | no credentials; fallback to IMDS if reachable |
| ipamd / ECS agent | EC2 | ENI and IP APIs | node/instance role; `ec2` endpoint | pods stuck; tasks `PROVISIONING` fail |
| Node/task | ECR + S3 | HTTPS | `ecr.api`, `ecr.dkr`, `s3` endpoints or NAT; SG egress 443 | image pull failures |
| CoreDNS / task DNS | Route 53 Resolver | UDP/TCP 53 to `169.254.169.253` or VPC+2 | `enableDnsSupport` | no external names |
| Network policy agent | kernel eBPF | — | `enableNetworkPolicy` | policies silently unenforced |
| ALB | pod/task IP | TCP 8080 | target SG allows ALB SG; NetworkPolicy allows ALB subnets | `Target.Timeout` |
| VPC Lattice | targets across VPCs | HTTP via managed prefix | service network association; auth policy; IAM SigV4 on clients | 403 from Lattice |
| Interface endpoints | AWS APIs | HTTPS | endpoint SG 443 from workloads; private DNS enabled | calls hang or resolve to public IPs |

## 4. Use it when / avoid it when

Use these internals when:

- A container gets credentials it should not have (IMDS reachable): §2.2.
- Pods or tasks cannot get IPs at scale: §2.3 arithmetic and subnet planning.
- A busy node shows random timeouts with a healthy VPC: conntrack (§2.5).
- Designing a private environment: endpoint table (§2.9) before the first task starts.
- Cross-account service calls: Lattice (§2.10) instead of peering everything.

Avoid:

- Hop limit 2 on node groups "so a legacy pod can use IMDS": give it Pod Identity instead.
- Overlay Cilium when you need VPC-native addressing for `ip` targets and security groups.
- Blocking ICMP type 3 on jumbo-frame paths (PMTU black holes).
- Custom networking without disabling the primary ENI for pods, or without SNAT considerations.

Alternatives: Fargate sidesteps IMDS, kube-proxy and node-level networking entirely at the cost of
per-task ENIs; Auto Mode keeps VPC CNI semantics but manages the node side.

## 5. Well-Architected view

| Pillar | Internals that help | Cost | Practice |
| --- | --- | --- | --- |
| Operational Excellence | deterministic IP planning; endpoint inventory; forensics commands | planning effort | subnet capacity alarms; endpoint list in IaC |
| Security | IMDS hop limit 1, `ECS_AWSVPC_BLOCK_IMDS`, default-deny policies, endpoint policies | policy authoring | Pod/task roles everywhere; NetworkPolicy templates; private DNS endpoints |
| Reliability | prefix delegation headroom; conntrack sizing; MTU discipline | tuning | `MINIMUM_IP_TARGET`; `nf_conntrack_max` monitoring; allow ICMP 3 |
| Performance Efficiency | nftables/IPVS/Cilium eBPF; jumbo frames inside the VPC | migration effort | measure before switching kube-proxy modes |
| Cost Optimization | endpoints instead of NAT for high-volume AWS API traffic; SNAT choices | endpoint hourly cost | ECR/S3/STS/logs endpoints first |
| Sustainability | higher pod density per node | none | prefix delegation |

## 6. Failure modes and troubleshooting

| Symptom | Likely cause | How to confirm (command/metric) | Fix |
| --- | --- | --- | --- |
| Pod reads instance role credentials | hop limit 2 or IMDSv1 allowed; no NetworkPolicy | `curl` token PUT from a pod succeeds | hop limit 1 + `HttpTokens=required`; NetworkPolicy deny to `169.254.169.254/32` ([playbook](../../playbooks/incidents/iam-accessdenied-from-containers.md)) |
| `failed to assign an IP address to container` | subnet exhausted, ENI limit, `InsufficientCidrBlocks` for prefixes | ipamd log; `awscni_total_ip_addresses`; subnet free IPs | bigger/more subnets, custom networking, IPv6 ([playbook](../../playbooks/incidents/pending-pods-and-capacity.md)) |
| Random connection timeouts on one node | conntrack table full | `dmesg | grep conntrack`; `conntrack -S` `drop` | raise `nf_conntrack_max`; spread load; Cilium |
| Small requests fine, large responses hang | PMTU black hole (jumbo → 1500 with ICMP blocked) | `tracepath`; `ping -M do -s 8000` | allow ICMP type 3; set MTU 1500 where needed |
| Pods cannot reach AWS APIs in a private cluster | missing endpoint or private DNS off; endpoint SG | `dig sts.us-east-1.amazonaws.com` resolves public IP; Reachability Analyzer | add endpoint, enable private DNS, fix SG |
| NetworkPolicy has no effect | engine not enabled; `hostNetwork` pod; policy in wrong namespace | node agent logs; `kubectl get networkpolicy -A` | `enableNetworkPolicy: true`; fix selectors |
| ALB targets unhealthy after adding default-deny | policy blocks ALB subnets | `describe-target-health` `Target.Timeout` | ingress rule from ALB subnet CIDRs or SG-for-pods ([playbook](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md)) |
| DNS 5 s spikes | UDP conntrack race | `conntrack -S` insert_failed | NodeLocal DNS ([playbook](../../playbooks/incidents/dns-failures.md)) |
| Pods work, `hostNetwork` pods cannot resolve | `dnsPolicy` default for hostNetwork uses node DNS | `cat /etc/resolv.conf` in pod | `dnsPolicy: ClusterFirstWithHostNet` |
| Node `NotReady` after hop limit 1 | not caused by hop limit (node is in the host namespace); look elsewhere | `journalctl -u kubelet` | SG/endpoint/DNS ([playbook](../../playbooks/incidents/node-not-ready.md)) |

## 7. Signals: metrics, logs, traces

- VPC CNI: `awscni_assigned_ip_addresses`, `awscni_total_ip_addresses`, `awscni_eni_allocated`,
  `awscni_eni_max`, `awscni_ipamd_error_count`, `awscni_ec2api_error_count`,
  `awscni_add_ip_req_count`/`del_ip_req_count`; subnet free IPs (custom metric from
  `describe-subnets`).
- Conntrack: `node_nf_conntrack_entries` vs `node_nf_conntrack_entries_limit` (node exporter),
  `conntrack -S` `insert_failed`, `drop`.
- Network errors: `container_network_receive_errors_total`, `node_network_receive_drop_total`,
  `node_netstat_TcpExt_TCPSynRetrans`.
- NAT gateway: `ErrorPortAllocation`, `PacketsDropCount`, `BytesOutToDestination` (cost).
- Endpoints: `AWS/PrivateLinkEndpoints` `ActiveConnections`, `BytesProcessed`,
  `RstPacketsReceived`.
- VPC Flow Logs (`REJECT` by SG/NACL), Route 53 Resolver query logs, Hubble flows (Cilium),
  network policy agent logs.
- IMDS: CloudTrail `userIdentity` for instance profiles used by unexpected callers; GuardDuty
  `UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration`.

Full table: [`reference/metrics-catalog.md`](../../reference/metrics-catalog.md).

## 8. Testing and DR notes

Testing: negative tests from a pod and a task (`curl` the IMDS token PUT must fail; `curl` a denied
namespace must time out; `curl` the Pod Identity/ECS credentials endpoint must succeed); Reachability
Analyzer paths from a task ENI to each endpoint in §2.9 as part of environment provisioning;
`dnsperf` and `iperf3` between pods across AZs to baseline; FIS `aws:network:disrupt-connectivity`
on a subnet to see how clients and health checks behave; a conntrack stress test (`ab`/`wrk` with
many short connections) on one node to find the limit before production does.

DR: nothing in this layer holds state; it is reproduced by IaC. What must be planned per Region:
non-overlapping CIDRs (so Regions can peer or attach to a Transit Gateway later), the same endpoint
set, the same IMDS defaults, and IP headroom for failover load (the DR Region must absorb 100% of
traffic, so its subnets and ENI quotas must match production)
([10 L300](../10-resilience-and-dr/L300-dr-strategies-for-container-platforms.md)).

## 9. Hands-on

```bash
# ECS network stack: subnets, endpoints, security groups
grep -nE 'AWS::EC2::VPCEndpoint|ServiceName|SecurityGroupIngress' labs/ecs/cloudformation/01-network.yaml | head -30
# Observe: endpoints for ecr.api, ecr.dkr, s3 (gateway), sts, logs, secretsmanager, ssmmessages and more.

# EKS manifests: default-deny and allow rules
cat labs/eks/manifests/base/networkpolicies.yaml
kubectl apply -k labs/eks/manifests/overlays/dev && kubectl -n shopfront get networkpolicy

# Negative tests from a pod (billable cluster)
kubectl -n shopfront run nettest --rm -it --image=nicolaka/netshoot:v0.13 --restart=Never -- bash -c '
  curl -m 2 -sX PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" && echo IMDS-REACHABLE || echo IMDS-blocked;
  curl -m 2 -s http://catalog.shopfront.svc.cluster.local:8081/healthz || echo "catalog blocked by policy (expected unless allowed for this pod)";
  ip route; cat /etc/resolv.conf'
# Observe: IMDS-blocked; DNS points at the kube-dns ClusterIP; the pod IP is a VPC address.

# IP arithmetic against a real node
kubectl get nodes -o custom-columns=NAME:.metadata.name,TYPE:.metadata.labels.node\\.kubernetes\\.io/instance-type,PODS:.status.allocatable.pods
NODE=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
kubectl debug node/"$NODE" -it --image=curlimages/curl:8.10.1 -- sh -c 'curl -s http://localhost:61679/v1/enis | head -c 800'
# Observe: allocatable pods 110 with prefix delegation, 29 without (m5/m7g.large).

# ECS: prove Fargate has no IMDS and that the task metadata endpoint answers
WT=$(aws ecs list-tasks --cluster shopfront-dev --service-name fulfillment-worker --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster shopfront-dev --task "$WT" --container worker --interactive \
  --command "sh -c 'curl -m 2 -s http://169.254.169.254/ || echo no-IMDS; curl -s \$ECS_CONTAINER_METADATA_URI_V4 | head -c 200'"
```

## 10. Check yourself

1. A pod on a node with `HttpPutResponseHopLimit: 1` cannot get an IMDS token, but a pod with
   `hostNetwork: true` on the same node can. Explain.

<details><summary>Answer</summary>
The PUT response leaves IMDS with IP TTL 1. The host network namespace receives it directly (TTL
1 is enough to be delivered locally), so processes there, including `hostNetwork` pods, get the
token. A normal pod sits behind a veth in its own namespace; the host would have to forward the
packet, decrementing TTL to 0, so the kernel drops it. Hop limit is therefore a protection for pods
with their own network namespace only; `hostNetwork` pods need RBAC/admission restrictions.
</details>

2. How many pods can an m5.xlarge run with and without prefix delegation, and what changes in
   subnet planning?

<details><summary>Answer</summary>
Without: 4 ENIs × (15 − 1) + 2 = 58 pods. With prefix delegation: 110 (the cap for instances under
30 vCPU; the raw formula gives 4 × 14 × 16 + 2 = 898). Planning changes from "IPs per pod" to
"contiguous /28 blocks per warmed ENI slot": a node may hold 16 addresses per prefix it warmed even
with few pods, and fragmented subnets fail with `InsufficientCidrBlocks`.
</details>

3. A node shows random connection timeouts to a database while other nodes are fine; security
   groups and the VPC are unchanged. Where do you look first?

<details><summary>Answer</summary>
The host's conntrack table: `dmesg | grep conntrack` for `table full, dropping packet`,
`conntrack -S` for `drop`/`insert_failed`, and `nf_conntrack_count` versus `nf_conntrack_max`. A
node with many short-lived connections (or a leak of half-open connections) exhausts the table and
new flows are dropped before reaching the VPC. Raise the limit via kube-proxy `conntrack.maxPerCore`
or sysctls, fix the connection churn, or move to Cilium's eBPF datapath.
</details>

4. Which endpoints does a fully private ECS Fargate service need to start a task that pulls from
   ECR, reads a Secrets Manager secret and logs to CloudWatch?

<details><summary>Answer</summary>
`com.amazonaws.us-east-1.ecr.api`, `ecr.dkr`, the S3 gateway endpoint (layers), `secretsmanager`
(and `kms` if the secret uses a customer key), `logs`, and usually `sts` for the task role
exchange. Interface endpoints need private DNS enabled and a security group allowing 443 from the
task subnets; the task security group needs egress 443.
</details>

5. When is VPC Lattice the right east-west choice over Service Connect or ClusterIP Services?

<details><summary>Answer</summary>
When callers and services are in different VPCs or accounts, when clients are mixed compute (Lambda,
EC2, ECS, EKS) and you want one SigV4-based auth policy and one routing layer without peering or a
Transit Gateway, or when you need weighted routing between target groups across environments. Inside
one cluster or one ECS namespace, ClusterIP Services or Service Connect are cheaper and simpler.
</details>

## 11. Sources

- Instance Metadata Service Version 2 (tokens, hop limit, defaults) — https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html
- Amazon ECS task metadata endpoint v4 and `ECS_AWSVPC_BLOCK_IMDS` — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint-v4.html and https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-agent-config.html
- EKS Pod Identity agent (link-local address) — https://docs.aws.amazon.com/eks/latest/userguide/pod-id-agent-setup.html
- Amazon VPC DNS (Route 53 Resolver address and limits) — https://docs.aws.amazon.com/vpc/latest/userguide/vpc-dns.html and https://docs.aws.amazon.com/vpc/latest/userguide/amazon-dns-limits.html
- Amazon Time Sync Service — https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/set-time.html
- IP addresses per network interface per instance type — https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-eni.html#AvailableIpPerENI
- Assign more IP addresses to nodes with prefixes; custom networking; IPv6 — https://docs.aws.amazon.com/eks/latest/userguide/cni-increase-ip-addresses.html, https://docs.aws.amazon.com/eks/latest/userguide/cni-custom-network.html, https://docs.aws.amazon.com/eks/latest/userguide/cni-ipv6.html
- Security groups for pods — https://docs.aws.amazon.com/eks/latest/userguide/security-groups-for-pods.html
- Limit pod traffic with Kubernetes network policies (VPC CNI engine) — https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy.html
- Kubernetes virtual IPs and service proxies (kube-proxy modes) — https://kubernetes.io/docs/reference/networking/virtual-ips/
- Cilium on AWS: ENI mode, chaining, kube-proxy replacement — https://docs.cilium.io/en/stable/network/concepts/ipam/eni/ and https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/
- Network maximum transmission unit for EC2 instances — https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/network_mtu.html
- VPC CNI SNAT settings (`AWS_VPC_K8S_CNI_EXTERNALSNAT`) — https://docs.aws.amazon.com/eks/latest/userguide/external-snat.html
- AWS PrivateLink: interface endpoints and endpoint policies — https://docs.aws.amazon.com/vpc/latest/privatelink/create-interface-endpoint.html
- Private cluster requirements (EKS) and ECS interface endpoints — https://docs.aws.amazon.com/eks/latest/userguide/private-clusters.html and https://docs.aws.amazon.com/AmazonECS/latest/developerguide/vpc-endpoints.html
- Amazon VPC Lattice — https://docs.aws.amazon.com/vpc-lattice/latest/ug/what-is-vpc-lattice.html
- VPC Reachability Analyzer — https://docs.aws.amazon.com/vpc/latest/reachability/what-is-reachability-analyzer.html
