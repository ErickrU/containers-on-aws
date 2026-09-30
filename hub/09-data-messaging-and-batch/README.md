# 09 · Data, messaging and batch

Containers are disposable; the things they compute over are not. Every container platform therefore
leans on a set of stateful neighbours — relational databases (RDS, Aurora), caches (ElastiCache with
Valkey), object storage (S3), shared filesystems (EFS, EBS), queues and buses (SQS, SNS, EventBridge),
streams (MSK/Kafka), and a batch scheduler (AWS Batch) — and most container incidents that are not
about the container itself are about how it talks to one of these: connection pools that explode when
tasks scale, caches that stampede, consumers that reprocess or lose messages, jobs that starve for
capacity. This domain owns those integrations: how to connect from ephemeral fleets, how to consume
at-least-once safely, how to scale on backlog, how to run batch on ECS and EKS, and how event-driven
architectures behave at scale. `shopfront` uses all of them: PostgreSQL, Valkey, SQS, Kafka, S3 and a
report job ([`labs/CONTRACT.md`](../../labs/CONTRACT.md)).

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 Stateful dependencies](L100-stateful-dependencies.md) | Why state lives outside containers; what RDS/Aurora, ElastiCache Valkey, DynamoDB, S3, EFS/EBS, SQS/SNS/EventBridge and MSK are for; how a container connects to each; the shopfront mapping |
| 200 | [L200 Integration patterns](L200-integration-patterns.md) | Connection pooling and RDS Proxy, IAM database auth, secrets rotation; Valkey cluster/serverless and cache-aside; SQS visibility/DLQ/long polling and scaling consumers with KEDA or ECS target tracking; SNS/EventBridge; MSK provisioned/Express/Serverless with IAM auth; AWS Batch compute environments, queues, job definitions, array jobs; Step Functions; Jobs vs scheduled tasks vs Batch |
| 300 | [L300 Messaging and data deep dive](L300-messaging-and-data-deep-dive.md) | At-least-once correctness and idempotency, poison messages, ordering and partitions; Strimzi vs MSK; schema registry; connection storms; cache stampedes; Valkey memory; KEDA scaler internals; Batch on EKS internals; fair-share and Spot for Batch; data DR |
| 400 | [L400 Event-driven architecture at scale](L400-event-driven-architecture-at-scale.md) | Outbox, CQRS, sagas with Step Functions, backpressure and load shedding, multi-Region data, messaging cost, async observability, testing async systems, anti-patterns |

## Components covered

- Amazon RDS and Aurora (PostgreSQL): connections from ephemeral fleets, RDS Proxy, IAM database
  authentication, Secrets Manager managed credentials and rotation, TLS, Multi-AZ, read replicas,
  Aurora Serverless v2, Aurora Global Database — L100 §2.1, L200 §2.1, L300 §2.5, §2.9
- Amazon ElastiCache (Valkey, Redis OSS): node-based and Serverless, cluster mode, TLS and auth,
  cache-aside/TTL, eviction policies, memory, Global Datastore — L100 §2.2, L200 §2.2, L300 §2.6, §2.9
- Amazon DynamoDB, Amazon S3, EFS and EBS as container storage — L100 §2.3–2.4
- Amazon SQS: standard vs FIFO, visibility timeout, long polling, batching, dead-letter queues and
  redrive, scaling consumers on backlog per task with KEDA (`ScaledObject`) or ECS target tracking —
  L100 §2.5, L200 §2.3, L300 §2.1–2.2
- Amazon SNS fan-out and Amazon EventBridge rules, schedules and pipes — L200 §2.4
- Amazon MSK (Provisioned Standard and Express brokers, Serverless), IAM authentication, topics,
  partitions, consumer groups, lag, MSK Replicator, Strimzi on EKS as the self-managed alternative,
  AWS Glue Schema Registry — L100 §2.6, L200 §2.5, L300 §2.3–2.4
- AWS Batch: compute environments on ECS (EC2, Fargate) and EKS, job queues, job definitions, array
  jobs, multi-node parallel jobs, retries and dependencies, fair-share scheduling, Spot, Batch on EKS
  internals — L200 §2.6, L300 §2.8
- AWS Step Functions with `ecs:runTask` and `eks:runJob`; Kubernetes Jobs/CronJobs vs ECS scheduled
  tasks vs Batch — L200 §2.7–2.8
- Correctness: idempotency, exactly-once boundaries, ordering, poison messages — L300 §2.1–2.2
- Operational failure modes: connection storms during deployments, cache stampedes, thundering herds,
  consumer rebalances — L300 §2.5–2.7
- Architecture: outbox pattern, CQRS, sagas, backpressure and load shedding, multi-Region data
  strategies, cost, async observability and testing — L400

## Related

- Labs: [`labs/local/compose.yaml`](../../labs/local/compose.yaml) (PostgreSQL, Valkey, Kafka in
  KRaft mode, ElasticMQ as SQS), [`labs/apps/worker/`](../../labs/apps/worker/) (SQS and Kafka
  consumers), [`labs/apps/report-job/`](../../labs/apps/report-job/) (batch job),
  [`labs/ecs/cloudformation/03-data.yaml`](../../labs/ecs/cloudformation/03-data.yaml) (RDS,
  ElastiCache, SQS, MSK), [`labs/ecs/cloudformation/06-batch.yaml`](../../labs/ecs/cloudformation/06-batch.yaml)
  and [`labs/batch/`](../../labs/batch/), [`labs/eks/manifests/base/`](../../labs/eks/manifests/base/)
  (KEDA `ScaledObject`, CronJob).
- Playbooks: [Queue backlog and consumer lag](../../playbooks/incidents/queue-backlog-and-consumer-lag.md),
  [Data recovery runbook](../../playbooks/dr/data-recovery-runbook.md),
  [Region failover runbook](../../playbooks/dr/region-failover-runbook.md).
- Reference: [decision guides](../../reference/decision-guides.md) (SQS vs Kafka; Batch vs Jobs),
  [metrics catalog](../../reference/metrics-catalog.md) (SQS, RDS, ElastiCache, MSK, Batch metrics),
  [quotas and limits](../../reference/quotas-and-limits.md).
- Neighbouring domains: [03 ECS](../03-ecs/README.md) and [04 EKS](../04-eks/README.md) (where the
  consumers run), [05 Networking](../05-networking/README.md) (security groups and endpoints to the
  data tier), [06 Identity and security](../06-identity-and-security/README.md) (IAM auth to
  databases, queues and brokers), [07 Observability](../07-observability/README.md) (the data-tier
  metrics), [10 Resilience and DR](../10-resilience-and-dr/README.md) (data is where RPO lives).
