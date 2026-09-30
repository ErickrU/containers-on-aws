# Ports, link-local addresses and VPC endpoints

Lookup tables for the numbers that keep showing up in container networking on AWS. Mechanisms are
in [05 · L300](../hub/05-networking/L300-container-networking-internals.md) (link-local, IMDSv2,
ENI arithmetic) and [05 · L200 §2.6](../hub/05-networking/L200-load-balancing-ingress-and-discovery.md) (endpoints).

## Link-local addresses (169.254.0.0/16, never routed, per-host semantics)

| Address | Who answers | Used by | Notes |
| --- | --- | --- | --- |
| `169.254.169.254` | EC2 Instance Metadata Service (IMDS) | the instance; pods/tasks only if allowed | IMDSv2: `PUT /latest/api/token` with `X-aws-ec2-metadata-token-ttl-seconds`, then `GET` with the token. Hop limit 1 blocks containers in their own network namespace (pods, `awsvpc` tasks); `hostNetwork` pods still reach it. Fargate: not reachable at all |
| `169.254.170.2` | ECS agent (EC2) / Fargate task metadata and credentials | every container in an ECS task | Credentials at `$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`; task metadata v4 at `$ECS_CONTAINER_METADATA_URI_V4` (`/task`, `/stats`). Blocked by `ECS_AWSVPC_BLOCK_IMDS` only for IMDS, not this |
| `169.254.170.23` (IPv4), `fd00:ec2::23` (IPv6) | EKS Pod Identity agent (DaemonSet, hostNetwork) | pods with a Pod Identity association | `AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/v1/credentials` + `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE`; the agent calls `eks-auth:AssumeRoleForPodIdentity` |
| `169.254.169.253` | Amazon Route 53 Resolver (also VPC base + 2, e.g. `10.42.0.2`) | nodes, CoreDNS `forward`, tasks | 1024 packets/s per ENI limit; VPC Resolver query logging for forensics |
| `169.254.169.123` | Amazon Time Sync Service (NTP) | nodes, Bottlerocket, Fargate | chrony default on Amazon Linux; do not block in egress rules |
| `169.254.169.250`/`.251` | Windows KMS activation | Windows nodes | |
| `169.254.0.0/16` in general | link-local per RFC 3927 | security groups cannot filter it; NetworkPolicy/`iptables` can | `allow-egress-aws-apis-and-otlp` excludes `169.254.169.254/32` |
| `100.64.0.0/10` | not link-local: carrier-grade NAT range, used as a secondary VPC CIDR for pods | VPC CNI custom networking | routable inside the VPC only |
| `fd00:ec2::254` | IMDS over IPv6 | dual-stack instances | same token rules |

## Ports by component

| Component | Port(s) | Protocol | Direction / who talks | Notes |
| --- | --- | --- | --- | --- |
| kube-apiserver (EKS endpoint) | 443 | TCP | nodes, kubectl, controllers → control plane ENIs | Cluster security group must allow 443 from nodes; private endpoint resolves inside the VPC only |
| kubelet | 10250 | TCP | control plane → nodes (logs, exec, metrics) | Cluster SG allows it; blocking it breaks `kubectl logs/exec` and metrics-server |
| kubelet read-only | 10255 | TCP | disabled on EKS AMIs | |
| kube-proxy metrics | 10249 | TCP | scrapers | |
| kube-proxy health | 10256 | TCP | NLB health checks with `externalTrafficPolicy: Local` | |
| CoreDNS | 53 UDP+TCP, 9153 metrics, 8080/8181 health | | pods → `kube-dns` ClusterIP | NetworkPolicy must allow both UDP and TCP 53 |
| VPC CNI (`aws-node`) | 61678 metrics, 61679 introspection, 50051 gRPC (ipamd ↔ CNI) | TCP, localhost | node-local | |
| Network policy agent | 8162 metrics | TCP | | |
| EKS Pod Identity agent | 80 on `169.254.170.23` (hostNetwork), 2703 health, 2705 metrics | TCP | pods → agent | |
| ECS agent introspection (EC2) | 51678 (`/v1/metadata`, `/v1/tasks`), 51679 (credentials proxy) | TCP, localhost/docker0 | on the container instance | |
| ECS task metadata/credentials | 80 on `169.254.170.2` | TCP | containers → agent/Fargate | |
| Service Connect proxy (Envoy) | ephemeral listener per alias port; admin 4444 (localhost); default `ingressPortOverride` 15000+ | TCP | task-local | Uses ports 15000–15001 range when `ingressPortOverride` unset (verify per platform version) |
| NodeLocal DNSCache | 53 on `169.254.20.10` (link-local on the node) | UDP/TCP | pods → node cache → CoreDNS over TCP | |
| ALB → targets | container port (8080 orders, 8081 catalog), health check `traffic-port` | TCP | ALB nodes (VPC IPs) → task/pod IPs | Target SG must allow the ALB SG |
| NLB → targets | target port; health checks from NLB node IPs (client IP preservation on) | TCP/UDP | | Security groups on NLB (2023+) simplify rules |
| Argo Rollouts / LBC / Karpenter webhooks | 9443 / 9443 / 8443 | TCP | API server → webhook pods | Cluster SG must allow the control plane to reach pod IPs on those ports (add rule if you restrict) |
| Karpenter metrics | 8080 | TCP | scrapers | |
| KEDA metrics adapter | 6443 (API service), 8080 metrics | TCP | API server → adapter | |
| ADOT collector | 4317 gRPC, 4318 HTTP (OTLP), 8888 self metrics, 13133 health | TCP | apps → collector | `allow-egress-aws-apis-and-otlp` |
| X-Ray daemon (legacy) | 2000 | UDP/TCP | apps → daemon | replaced by OTLP → ADOT |
| Jenkins | 8080 UI, 50000 inbound agents (JNLP) | TCP | agents → controller | websocket mode removes 50000 |
| Argo CD | 443/80 server, 8082 repo-server, 6379 redis, 8083 metrics | TCP | in-cluster | |
| PostgreSQL / RDS Proxy | 5432 | TCP | tasks/pods → proxy (isolated subnets) | `rds.force_ssl` on; `sslmode=require` |
| Valkey / Redis | 6379 (TLS on Serverless), 6380 (TLS on some node-based) | TCP | catalog → cache | `rediss://` |
| Kafka / MSK | 9098 IAM (SASL/IAM TLS), 9094 TLS, 9096 SASL/SCRAM, 9092 plaintext (never in AWS), 2181/2182 ZooKeeper (legacy) | TCP | producers/consumers → brokers | Serverless: 9098 only |
| SQS / S3 / STS / ECR / Secrets Manager / CloudWatch | 443 | TCP | tasks/pods → endpoints or NAT | |
| EFS | 2049 | TCP | mount targets | |
| SSM Session Manager / ECS Exec | 443 to `ssm`, `ssmmessages`, `ec2messages` endpoints | TCP | agents → AWS | ECS Exec needs `ssmmessages` only |
| Amazon Time Sync | 123 to `169.254.169.123` | UDP | nodes | |
| IMDS | 80 on `169.254.169.254` | TCP | instance | |

## VPC endpoints for a private container platform (no NAT, no IGW)

Interface endpoints (`com.amazonaws.<region>.<service>`) unless noted; enable private DNS. Endpoint
security groups must allow 443 from the node/task subnets.

| Purpose | Endpoint services | Who needs it |
| --- | --- | --- |
| Pull images from ECR | `ecr.api`, `ecr.dkr`, **`s3` (gateway)** (layers live in S3) | ECS agent/Fargate, kubelet |
| Public ECR / Docker Hub through pull-through cache | same three (the cache is in your ECR) | |
| Logs | `logs` | awslogs driver, Fluent Bit, CloudWatch agent |
| Secrets and parameters | `secretsmanager`, `ssm`, `kms` (for CMKs) | ECS execution role at task start, ESO, Secrets Store CSI |
| Credentials | `sts` (for IRSA `AssumeRoleWithWebIdentity`; Pod Identity uses `eks-auth`) | pods |
| EKS Pod Identity | `eks-auth` | Pod Identity agent |
| EKS API from nodes | private cluster endpoint (not a VPC endpoint you create) + `eks` for `aws eks` CLI calls | nodes use the cluster endpoint |
| ECS control plane | `ecs`, `ecs-agent`, `ecs-telemetry` (EC2 launch type only) | ECS agent on container instances |
| Service Connect / Cloud Map | none of their own: DNS answers come from the VPC resolver and the ECS control plane registers instances through `ecs`; add `servicediscovery` only if your code calls the Cloud Map API (`DiscoverInstances`) | apps using the Cloud Map API |
| ECS Exec, SSM | `ssmmessages`, `ssm`, `ec2messages` | ECS Exec (only `ssmmessages`), SSM agent on nodes |
| Autoscaling and EC2 (Karpenter, CNI, Cluster Autoscaler, EBS CSI) | `ec2`, `autoscaling`, `elasticloadbalancing`, `pricing` (Karpenter, us-east-1 only), `sqs` (Karpenter interruption queue) | controllers |
| Application dependencies | `sqs`, `kafka` (MSK APIs; brokers are in your VPC), `xray`, `monitoring` (CloudWatch metrics), `application-signals`, `aps-workspaces` (AMP), `batch`, `scheduler` | apps, collectors |
| Container Insights / CloudWatch agent | `logs`, `monitoring` | agent |
| CodeBuild in VPC, Jenkins agents | `codebuild`, `codeconnections`/`codestar-connections`, `git-codecommit`, plus everything above | pipelines |
| S3 access from apps (reports) | `s3` gateway (free) or `s3` interface (cross-VPC/on-prem) | report-job |
| DynamoDB | `dynamodb` gateway (free) | apps |

Cost reminder: interface endpoints bill per AZ-hour plus per GB; a NAT gateway bills per hour plus
per GB. For low traffic NAT is cheaper; for image-heavy or log-heavy platforms endpoints win and
remove the public path ([05 · L400 §2.4](../hub/05-networking/L400-network-architecture-at-scale.md)).

## Address arithmetic quick reference

| Question | Formula / value |
| --- | --- |
| Max pods per node (VPC CNI, no prefix delegation) | `ENIs × (IPs per ENI − 1) + 2` (m7g.large: 3 × (10 − 1) + 2 = 29) |
| Max pods with prefix delegation | `min(110 for ≤ 30 vCPU / 250 above, ENIs × (IPs per ENI − 1) × 16 + 2)`; `max-pods` must be recomputed (eksctl/managed node groups do) |
| IPs a `/28` prefix consumes from the subnet | 16 contiguous addresses; fragmented subnets cannot hand out prefixes |
| Reserved IPs per subnet | 5 (network, router, DNS, future, broadcast) |
| Control plane ENIs | 2+ in the subnets you pass; keep `/28` subnets with ≥ 6 free IPs for upgrades |
| ECS `awsvpc` on EC2 without trunking | tasks per instance = ENIs − 1 (one for the instance) |
| ECS ENI trunking | up to 120 tasks per instance depending on type (`awsvpcTrunking` account setting) |
| Fargate | one ENI per task, one IP from the task subnet |
| IPv6 | `/64` per subnet, `/80` prefixes per node: exhaustion disappears; egress-only IGW and NAT64/DNS64 for IPv4 dependencies |
| ALB | at least 8 free IPs per subnet at creation; grows with traffic |
