# Quotas and limits that bite

Default values as of September 2026 in a mature Region such as `us-east-1`. Many are adjustable
through Service Quotas (**A**), some are hard (**H**). Always confirm with
`aws service-quotas get-service-quota --service-code <code> --quota-code <code>` or the console;
defaults differ per account age and Region. The failure column is what you see when you hit it.

## Networking (`vpc`, `ec2`)

| Quota | Default | Adj. | Failure you see |
| --- | --- | --- | --- |
| IPv4 addresses per subnet | CIDR size − 5 reserved | H | `InsufficientFreeAddressesInSubnet`, pods `ContainerCreating`, tasks `unable to attach ENI` |
| ENIs per instance / IPs per ENI | per instance type (m7g.large: 3 ENIs × 10 IPs; prefix delegation: 16 IPs per slot) | H | max-pods reached, `Too many pods` |
| Network interfaces per Region | 5 000 | A | ENI creation fails during large scale-outs (Fargate: one ENI per task) |
| Security groups per ENI | 5 | A (to 16) | task/pod SG assignment fails |
| Rules per security group | 60 inbound + 60 outbound | A | `RulesPerSecurityGroupLimitExceeded` (security groups for pods, many ports) |
| VPCs per Region | 5 | A | `VpcLimitExceeded` |
| Elastic IPs per Region | 5 | A | NAT gateway creation fails |
| NAT gateway bandwidth | 5 Gbps burst to 100 Gbps; 55 000 simultaneous connections to one destination | H | `ErrorPortAllocation` metric > 0, connection resets to one endpoint |
| Route 53 Resolver | 1 024 packets/s per ENI | H | DNS `SERVFAIL`/timeouts from busy nodes ([dns-failures](../playbooks/incidents/dns-failures.md)) |
| VPC endpoints per VPC | 50 (interface) | A | endpoint creation fails |
| Interface endpoint bandwidth | 10 Gbps per AZ, bursts to 100 Gbps | H | slow pulls/logs at very high volume |
| Transit Gateway attachments per TGW | 5 000; routes 10 000 | A | attachment fails |

## Load balancers (`elasticloadbalancing`)

| Quota | Default | Adj. | Failure |
| --- | --- | --- | --- |
| ALBs per Region | 50 | A | `TooManyLoadBalancers` (Ingress without `group.name` creates one ALB each) |
| Target groups per Region | 3 000 | A | `TooManyTargetGroups` |
| Targets per ALB | 1 000 | A | registration fails; large HPA max on one ALB |
| Targets per target group per Region | 1 000 | A | |
| Listeners per ALB | 50 | A | |
| Rules per ALB | 100 | A | `TooManyRules` (many Ingress paths in one group) |
| Certificates per ALB (SNI) | 25 | A | |
| ALB idle timeout | 1–4 000 s (default 60) | config | 504 for slow responses |
| Header size | 64 KB total | H | 400/502 |
| NLB targets per AZ per NLB | 500 | A | |
| ALB scaling | LCUs scale in minutes; sudden 10× spikes see 503/`RejectedConnectionCount` | H | pre-warm via support for planned events |

## ECS (`ecs`, `fargate`)

| Quota | Default | Adj. | Failure |
| --- | --- | --- | --- |
| Clusters per account | 10 000 | A | |
| Services per cluster | 5 000 | A | |
| Tasks per service (desired count) | 5 000 | A | |
| Container instances per cluster | 5 000 | A | |
| Task definition size | 64 KiB | H | `register-task-definition` rejected (big env blocks; use `environmentFiles`) |
| Containers per task definition | 10 | H | |
| Fargate On-Demand vCPUs per Region | 6 (new accounts) → thousands after increases | A | `Capacity is unavailable`/`VcpuLimitExceeded` on scale-out |
| Fargate Spot vCPUs per Region | same shape | A | |
| Fargate task size | 0.25–16 vCPU, 0.5–120 GB; fixed pairs; ephemeral storage 20–200 GiB | H | invalid task definition |
| ECS Exec sessions | via SSM: 1 per container at a time recommended | H | |
| `RunTask` count per call | 10 | H | loops needed for larger batches |
| Service Connect | services per namespace 1 000 (Cloud Map) | A | |
| ENI trunking | task ENIs per instance depends on type (e.g. c6i.large 10, m5.4xlarge 54) | H | `RESOURCE:ENI` |
| Deployment circuit breaker threshold | max(10, 0.5 × desired) failures, capped at 200 | H | rollback timing |
| `stopTimeout` maximum | 120 s (Fargate), configurable on EC2 | H | SIGKILL before drain finishes |
| Task ephemeral storage default | 20 GiB (Fargate), 21+ to bill extra | H | `no space left on device` |

## EKS (`eks`) and Kubernetes internals

| Quota | Default | Adj. | Failure |
| --- | --- | --- | --- |
| Clusters per Region | 100 | A | `ResourceLimitExceeded` |
| Managed node groups per cluster | 30; nodes per group 450 | A | |
| Nodes per cluster | practical thousands; control plane scales automatically; API server rate limits apply | H | slow API, `429 Too Many Requests` |
| Pods per node | `max-pods` from ENI math; 110/250 with prefix delegation | H | `Too many pods` |
| Fargate profiles per cluster | 10; selectors per profile 5 | A | |
| Pod Identity associations per cluster | 1 000 | A | |
| Access entries per cluster | 1 000 | A | |
| etcd database size | 8 GiB | H | cluster read-only, `etcdserver: mvcc: database space exceeded` |
| Object size | 1.5 MiB per object (etcd) | H | `Request entity too large` (ConfigMaps, Helm release Secrets) |
| Control plane log types | 5 | H | |
| API server request timeout | 60 s (LIST of huge collections) | H | `context deadline exceeded` |
| Priority and fairness | default flow schemas; per-client concurrency shares | config | 429s for noisy controllers |
| Auto Mode node lifetime | ≤ 21 days | H | nodes replaced (plan PDBs) |
| Kubernetes version support | 14 months standard + 12 months extended (fee) | H | forced upgrades |
| Service ClusterIP range | `/16` default `10.100.0.0/16` or `172.20.0.0/16` | H at creation | Service creation fails when exhausted |

## ECR (`ecr`)

| Quota | Default | Adj. | Failure |
| --- | --- | --- | --- |
| Repositories per Region | 100 000 | A | |
| Images per repository | 10 000 | A | push fails |
| Layer size | 52 000 MiB (single) | H | |
| Image size (manifest) | 20 000 MiB | H | |
| Layers per image | 127 | H | |
| Tags per image | 1 000 | H | |
| `GetAuthorizationToken` | 500 TPS | A | `ThrottlingException` on mass node join |
| `BatchGetImage` / `GetDownloadUrlForLayer` | 2 000 / 3 000 TPS | A | pull storms throttled |
| Pull-through cache rules per registry | 50 | A | |
| Replication destinations per rule | 25 | H | |
| Lifecycle policy rules | 50 per repository | H | |
| Registry-level scanning filters | 100 | H | |
| Repository policy size | 10 240 characters | H | |

## SQS, MSK, RDS/Aurora, ElastiCache, Batch, Secrets, CloudWatch

| Service | Quota | Default | Adj. | Failure |
| --- | --- | --- | --- | --- |
| SQS standard | throughput | nearly unlimited | H | |
| SQS FIFO | 300 msg/s (3 000 batched; high-throughput mode per partition higher) | 300/3 000 | A (HT mode) | throttling |
| SQS | message size 256 KiB (1 MiB with extended client/S3); retention 14 days max; visibility timeout 12 h max; in-flight 120 000 (standard) / 20 000 (FIFO) | | H | `OverLimit` on receive |
| SQS | `send-message-batch` 10 messages | 10 | H | |
| MSK Serverless | 200 MBps ingress / 400 MBps egress per cluster; 5 MBps in / 10 MBps out per partition; 2 400 partitions; 120 partitions per topic default | | H/A | `ThrottledRequests`, `FetchThrottleTime` |
| MSK Provisioned | partitions per broker by size (kafka.m5.large 1 000); storage per broker 16 TiB | | H | |
| Aurora Serverless v2 | 0–256 ACUs per instance (0.5 min for older versions); 15 readers | | H | `ACUUtilization` 100%, connections refused |
| Aurora PostgreSQL | `max_connections` = `LEAST({DBInstanceClassMemory/9531392}, 5000)` (ACU-dependent for Serverless v2) | | H | `remaining connection slots are reserved` |
| RDS Proxy | 20 proxies per account; connection multiplexing pinned by session state | | A | pinned sessions defeat pooling |
| ElastiCache Serverless | 5 TB storage, 15 000 000 ECPUs/s per cache; connections 65 000 | | H | `ThrottledCmds` |
| AWS Batch | compute environments 50, job queues 50, job definitions per revision 1 000 000; `maxvCpus` per CE you set; array job size 10 000; job dependencies 20 | | A | jobs `RUNNABLE` (CE at max) |
| Secrets Manager | 500 000 secrets; 65 536 bytes per secret; 10 000 `GetSecretValue`/s | | A | throttling on mass task start |
| SSM Parameter Store | 10 000 standard parameters; 40 TPS standard throughput (1 000 with higher throughput enabled, billed) | | A/config | `ThrottlingException` at task start |
| CloudWatch Logs | `PutLogEvents` 5 requests/s per stream; 1 MB batch; 10 000 events; metric filters 100 per group | | H/A | awslogs non-blocking drops (`max-buffer-size`) |
| CloudWatch metrics | 30 dimensions per metric; `PutMetricData` 1 000 TPS (adjustable); EMF 100 metrics per log event | | A | |
| CloudWatch alarms | 5 000 per Region; composite alarms 100 children | | A | |
| X-Ray | 50 sampling rules; trace document 500 KB per segment; retention 30 days | | H | segments dropped |
| EventBridge | `PutEvents` 10 000 TPS (us-east-1) ; rules per bus 2 000; targets per rule 5 | | A | events delayed/throttled |
| IAM | roles per account 1 000; managed policies per role 10 (20 with increase); inline policy size 10 240 chars per role | | A | role creation fails (one role per workload × clusters) |
| STS | `AssumeRole` rate limits per account (not published) | | H | `Rate exceeded` on massive concurrent pod starts with IRSA (Pod Identity caches) |
| Service Quotas usage alarms | `AWS/Usage` metrics exist for many services | | | alarm at 80% |

## How to check and raise

```bash
aws service-quotas list-service-quotas --service-code fargate --query 'Quotas[*].[QuotaCode,QuotaName,Value,Adjustable]' --output table
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A --query 'Quota.Value'          # Running On-Demand Standard instances (vCPUs)
aws service-quotas request-service-quota-increase --service-code fargate --quota-code L-3032A538 --desired-value 1000
aws service-quotas list-requested-service-quota-change-history --service-code fargate --query 'RequestedQuotas[*].[QuotaName,DesiredValue,Status]'
# Usage vs quota as a CloudWatch metric (where supported): namespace AWS/Usage, e.g. Fargate vCPUs, ENIs, IAM roles
aws cloudwatch list-metrics --namespace AWS/Usage --dimensions Name=Service,Value=Fargate --query 'Metrics[*].Dimensions'
```

Quota increases in the **recovery Region** are part of the DR plan ([dr-plan-template](../playbooks/dr/dr-plan-template.md) §8);
the day of the failover is the wrong time to discover a 6-vCPU Fargate default.
