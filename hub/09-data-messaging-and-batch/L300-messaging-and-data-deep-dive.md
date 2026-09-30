# Data, messaging and batch · L300 — Messaging and data deep dive

**Level:** 300 · **Time:** ~100 min · **Prerequisites:** [L200 Integration patterns](L200-integration-patterns.md),
[Observability L300](../07-observability/L300-metrics-that-matter-and-alerting.md)

**After this document you can:**

- Reason about at-least-once delivery, idempotency and exactly-once boundaries for SQS and Kafka
  consumers and prove a consumer is correct under redelivery, rebalance and crash.
- Explain ordering, partitions, rebalances, schema evolution and the Strimzi-vs-MSK trade-off.
- Diagnose connection storms, cache stampedes and Valkey memory pressure with the right metric.
- Describe KEDA's and Batch-on-EKS's internals well enough to debug them.
- State the DR properties of each data service and design around SQS's regional scope.

## 1. Mental model

```mermaid
sequenceDiagram
  autonumber
  participant Q as SQS
  participant W as worker (batch of 10)
  participant DB as PostgreSQL
  Q->>W: ReceiveMessage (visibility timeout starts, 30 s)
  W->>DB: UPDATE orders SET status='FULFILLED' WHERE id=$1 AND status='CREATED'
  alt rows = 1
    DB-->>W: fulfilled
    W->>Q: DeleteMessage
  else rows = 0 (redelivery)
    DB-->>W: already processed
    W->>Q: DeleteMessage
  else exception (DB down, chaos)
    W--xQ: no delete -> visible again after 30 s; receive count +1
    Note over Q: after maxReceiveCount 3 -> DLQ
  end
  Note over W: crash between UPDATE and Delete -> redelivery hits rows = 0 -> safe
```

Messaging systems promise delivery, not uniqueness: SQS standard and Kafka both deliver a message at
least once, and any consumer can be interrupted between doing the work and acknowledging it. The only
robust answer is to make the work idempotent (an update conditioned on state, an upsert keyed by the
event id) so that redelivery is harmless, and to treat acknowledgement as "I no longer need this
message", never as "this happened exactly once". Everything else in this document — ordering,
rebalances, stampedes, storms — follows from what the platform can and cannot guarantee.

## 2. Concepts

### 2.1 At-least-once, idempotency and exactly-once boundaries

| Guarantee | Who provides it | What you must do |
| --- | --- | --- |
| At-least-once delivery | SQS standard, Kafka with commit-after-process | idempotent effects |
| At-most-once | Kafka auto-commit before processing; SQS delete before processing | accept loss (rarely acceptable) |
| Exactly-once *processing* | nobody across system boundaries | idempotency keys + conditional writes; or a transactional outbox/inbox |
| Exactly-once *within Kafka* | Kafka transactions (read-process-write inside one cluster) | only for Kafka→Kafka pipelines |

Idempotency techniques by store: conditional update keyed on state (`WHERE status='CREATED'`),
upsert with a natural key (`ON CONFLICT (day)` — but note the analytics upsert *adds* to counters,
so a redelivered event double-counts; a correct version records processed event ids in an inbox
table and skips duplicates), DynamoDB conditional writes, S3 objects named by event id. Side effects
that cannot be made idempotent (sending an email) get an inbox table checked before the effect.
Visibility timeout must exceed processing time (heartbeat with `ChangeMessageVisibility` for long
work) or two consumers process the same message concurrently — still safe if idempotent, but wasteful.

**Poison messages**: a message that always fails (malformed, references missing data). SQS: the
redrive policy moves it to the DLQ after N receives; the worker logs the body hash and receive count.
Kafka: there is no DLQ; a consumer that raises on the same record blocks its partition forever, so
the analytics consumer commits past malformed records after logging them and could write them to a
dead-letter topic. Retry with backoff for transient failures (the analytics consumer seeks back and
waits) versus skip for permanent ones is a per-message decision.

### 2.2 Ordering

SQS standard: best-effort ordering, duplicates possible; FIFO: strict order per message group with
deduplication by id within 5 minutes, 300 messages/s per group (3,000 with batching; high-throughput
mode raises limits per partition — verify current numbers). Kafka: total order within a partition;
records with the same key land in the same partition, so `orderId` as key orders events per order;
across partitions there is no order. Consequences: parallelism equals message groups (FIFO) or
partitions (Kafka); a slow message blocks its group/partition; increasing partitions changes the
key→partition mapping (existing order for a key may interleave during the change). Choose keys that
spread load (hot keys create hot partitions).

### 2.3 Kafka consumers: groups, rebalances, offsets

A consumer group assigns each partition to exactly one member; joining/leaving triggers a rebalance
(eager: everyone stops; cooperative/incremental: only moved partitions pause). During a rolling
deployment of `analytics-consumer`, every pod restart triggers a rebalance — use cooperative
assignment (`partition.assignment.strategy=cooperative-sticky`), static group membership
(`group.instance.id`) with a `session.timeout.ms` that covers pod restarts, and few, longer-lived
consumers. Offsets are committed per partition; commit after processing; `max.poll.interval.ms`
bounds processing time per poll or the consumer is kicked out (and its partitions reassigned while it
may still be writing — another reason for idempotency). Lag = latest offset − committed offset; MSK
publishes `EstimatedMaxTimeLag`/`MaxOffsetLag` per group.

### 2.4 Strimzi on EKS versus MSK; schema registry

| | MSK | Strimzi (Kafka operator on EKS) |
| --- | --- | --- |
| Operations | AWS: brokers, storage, patching, ZooKeeper/KRaft, failover | you: operator upgrades, broker rolling, storage classes, rack awareness, PDBs |
| Auth | IAM, SASL/SCRAM, mTLS | mTLS, SCRAM, OAuth via the operator |
| Cost | brokers/serverless pricing | nodes + EBS + engineering time |
| Kubernetes-native | no (network reachable from pods) | yes (CRDs for topics, users) |
| Fits | almost everyone | teams needing Kafka features MSK lacks or strict in-cluster locality |

Schema evolution: register Avro/JSON Schema/Protobuf schemas in AWS Glue Schema Registry (or a
Confluent-compatible registry) with compatibility mode `BACKWARD` (consumers upgrade first) or
`FORWARD`; producers serialise with schema ids; consumers reject unknown incompatible changes at the
registry, not at 3 a.m. Version the event (`"version": 1` in shopfront's payload) even with JSON.

### 2.5 Connection storms and deployments

A rolling deployment of 50 tasks that each open a pool of 10 at start creates 500 new connections in
seconds; PostgreSQL forks a process per connection and TLS handshakes are CPU-heavy; Valkey and MSK
also see bursts (`NewConnections`, broker `ConnectionCreationRate`). Shape it: lazy pools (open on
first use), small `minimum` pool sizes, jittered start-up (the shopfront services retry with backoff
rather than hammering), `maximumPercent` below 200 for large fleets, RDS Proxy absorbing client
connections, and Kafka client `reconnect.backoff.ms` with jitter. Watch `DatabaseConnections` and
`CPUUtilization` on the database around deployment markers.

### 2.6 Cache stampedes and Valkey memory

When a hot key expires, every concurrent request misses and hits the database at once (stampede /
thundering herd). Mitigations: probabilistic early expiration (refresh slightly before TTL with a
probability that rises as expiry nears), request coalescing (single-flight per key in the process),
soft TTL with background refresh, or locks (`SET key:lock NX PX`) so one request rebuilds. Avoid
synchronised TTLs (all keys set at deploy time expire together — add jitter). Memory: `maxmemory` and
`maxmemory-policy` (`allkeys-lru` for caches; `noeviction` only for stores), `Evictions` as the
signal that the cache is too small or keys lack TTLs; big keys and `KEYS *` block the single-threaded
engine (`EngineCPUUtilization`); Serverless removes sizing but not the stampede logic.

### 2.7 KEDA internals

KEDA runs an operator (reconciles `ScaledObject`s, polls scalers every `pollingInterval`, default
30 s), a metrics API server (`external.metrics.k8s.io`) that the HPA controller queries, and an
optional admission webhook. For each `ScaledObject` KEDA creates an HPA with an external metric; the
scaler returns `queueLength` values and the HPA computes replicas = ceil(current / target). Scale to
zero is KEDA's own loop (`minReplicaCount: 0` with `activationQueueLength`): when zero, KEDA polls the
source and sets replicas to 1 on activation. `cooldownPeriod` governs scale-to-zero; scale-in between
1..N follows HPA behaviour (`stabilizationWindowSeconds`). Authentication: the operator's service
account with Pod Identity (`podIdentity.provider: aws`) or `TriggerAuthentication` secrets. Debug with
`kubectl describe scaledobject`, `kubectl get hpa`, and operator logs; a `Ready: False` condition
almost always means permissions or an unreachable metric source.

### 2.8 Batch on EKS internals

A Batch EKS compute environment is bound to your cluster and a namespace: you create the namespace
and RBAC (a `Role`/`RoleBinding` for the `aws-batch` identity mapped through an access entry), Batch
launches EC2 instances (its own launch templates and AMIs, or yours) that join the cluster with a
Batch-managed node label, and each job becomes a pod in that namespace with node affinity to Batch
nodes. Batch scales nodes by `maxvCpus` and the runnable queue; it does not use Karpenter/Auto Mode
pools or Fargate. Job definitions map to pod specs (`eksProperties`: containers, volumes, service
account for Pod Identity/IRSA, security context); array jobs become many pods; retries recreate
pods. Debug with `aws batch describe-jobs` (status reasons), `kubectl -n batch get pods`, node join
events; jobs stuck `RUNNABLE` usually mean instance types unavailable, quotas, or the CE's subnets
lacking IPs.

Fair-share scheduling: a scheduling policy with share identifiers and weights lets queues shared by
teams allocate compute proportionally over a decay window instead of FIFO. Spot: Batch retries jobs
interrupted by Spot (`SPOT_CAPACITY_OPTIMIZED` allocation strategy) when the retry strategy allows;
make jobs idempotent and checkpoint long ones. GPU jobs: `resourceRequirements` type `GPU` with
accelerated instance types/AMIs.

### 2.9 Data DR properties

| Service | Replication | Failover | RPO / RTO shape |
| --- | --- | --- | --- |
| RDS Multi-AZ | synchronous standby in another AZ | automatic, ~1–2 min, endpoint unchanged | zero data loss within Region |
| RDS cross-Region read replica | asynchronous | manual promotion | seconds–minutes lag |
| Aurora Global Database | storage-level replication, typically < 1 s lag | managed planned/unplanned failover (switchover/failover), minutes | RPO ~1 s, RTO minutes |
| ElastiCache Multi-AZ / Global Datastore | replicas; cross-Region secondary | automatic in-Region; promote secondary cross-Region | cache can be cold-rebuilt; decide whether to replicate at all |
| SQS | regional, no replication | none | in-flight messages are lost with the Region; producers must be able to republish, or dual-write |
| MSK | replication factor within Region; MSK Replicator across clusters/Regions | consumer offset translation on the replica | lag-dependent RPO |
| S3 | Cross-Region Replication (async), multi-Region access points | DNS-level | minutes lag |
| DynamoDB global tables | active-active multi-Region | none needed | last-writer-wins conflicts |

The container layer's DR plan is only as good as this table; the [data recovery runbook](../../playbooks/dr/data-recovery-runbook.md)
sequences the steps.

## 3. How it interacts with the rest of AWS

| Component | Talks to | Protocol/API | Prerequisite (IAM, network, DNS) | What breaks if missing |
| --- | --- | --- | --- | --- |
| Consumers | SQS `ChangeMessageVisibility` | HTTPS | permission included in the worker policy | long jobs redelivered mid-flight |
| Kafka clients | MSK group coordination | Kafka protocol | `kafka-cluster:AlterGroup`/`DescribeGroup` | rebalance failures, no commits |
| Producers/consumers | Glue Schema Registry | HTTPS | `glue:GetSchemaVersion`, `RegisterSchemaVersion` | serialisation failures |
| KEDA operator | SQS/CloudWatch/AMP | HTTPS via Pod Identity | association; NetworkPolicy egress | ScaledObject not ready |
| Batch | EKS API, EC2 | service-linked role; access entry for the Batch role; RBAC in the namespace | CE `INVALID` |
| RDS Proxy | Secrets Manager, Aurora | proxy role | secret per user | `PAM authentication failed` |
| MSK Replicator | source/target clusters | replicator role | IAM auth on both | topics not replicated |

## 4. Use it when / avoid it when

Use:

- Conditional updates/inbox tables for idempotency; DLQs with alarms; visibility heartbeats for long
  jobs.
- Cooperative-sticky assignment and static membership for Kafka consumers on Kubernetes.
- Schema registry with compatibility rules for any topic with more than one team.
- RDS Proxy and jittered start-up for large fleets; probabilistic early expiration for hot keys.
- Batch on EKS when jobs need cluster-local resources; Batch on Fargate otherwise.

Avoid:

- Counters incremented by redelivered events without an inbox (double counting).
- `auto.offset.reset=latest` on a new consumer group in production without thinking (skips history).
- Increasing partitions to "fix" lag on a slow consumer (breaks per-key order and does not speed the
  consumer).
- `KEYS *`, unbounded `SCAN` loops, or giant hash keys in Valkey.
- Relying on SQS surviving a Region failure.

Alternatives: Kinesis Data Streams with enhanced fan-out; Amazon MQ for AMQP semantics; EventBridge
Pipes to move records from SQS/MSK to targets without custom consumers.

## 5. Well-Architected view

| Pillar | Contribution | Cost | Practice |
| --- | --- | --- | --- |
| Operational Excellence | DLQ redrive runbooks; lag alarms; schema governance | discipline | redrive tasks, not manual re-sends |
| Security | IAM auth to data services; per-service credentials | setup | least privilege per topic/queue |
| Reliability | idempotency, heartbeats, static membership, Multi-AZ data | design time | chaos-test redelivery |
| Performance Efficiency | partition/consumer balance, pooling, early expiration | tuning | partition count from throughput targets |
| Cost Optimization | long polling, Serverless tiers, Spot for Batch | measurement | `NumberOfEmptyReceives`, idle consumers |
| Sustainability | scale-to-zero consumers via KEDA | none | activation thresholds |

## 6. Failure modes and troubleshooting

| Symptom | Likely cause | How to confirm (command/metric) | Fix |
| --- | --- | --- | --- |
| Duplicate side effects | non-idempotent consumer; visibility < processing | receive counts > 1 in logs | conditional writes; inbox; heartbeat |
| Kafka partition stuck, lag on one partition | poison record blocking; slow consumer for a hot key | group description lag per partition | skip/dead-letter topic; key design |
| Frequent rebalances | pods restarting; `max.poll.interval.ms` exceeded | consumer logs `Revoke`/`Assign` | cooperative-sticky; static membership; shorter batches |
| Database CPU spike at each deploy | connection storm | `DatabaseConnections` vs deployment events | lazy pools, jitter, Proxy |
| Periodic database load spikes aligned to TTL | synchronised cache expiry / stampede | cache miss rate spikes | jittered TTL, early expiration, single-flight |
| `Evictions` rising | cache too small or missing TTLs | `DatabaseMemoryUsagePercentage` | TTLs; bigger node/serverless |
| KEDA scaled to zero and never up | activation threshold or permission | `keda_scaler_errors_total` | fix; `activationQueueLength` |
| Batch EKS jobs `RUNNABLE` forever | CE cannot launch nodes; RBAC missing | `describe-compute-environments`, EKS events | fix CE/RBAC ([playbook](../../playbooks/incidents/pending-pods-and-capacity.md)) |
| Analytics double counts after a restart | upsert increments on redelivery | compare counts with source | inbox table keyed by event id |
| Queue age high, receives high, deletes low | failures loop | `NumberOfMessagesReceived` ≫ `Deleted` | fix bug; DLQ ([playbook](../../playbooks/incidents/queue-backlog-and-consumer-lag.md)) |

## 7. Signals: metrics, logs, traces

- Correctness: receive count distribution (SQS `ApproximateReceiveCount` in logs), DLQ depth,
  `orders_failed_total`, duplicate-detection counters (inbox hits).
- Kafka: lag per partition, rebalance count, commit failures, `records-consumed-rate`,
  `fetch-latency-avg`.
- Database: connection count around deployments, `Deadlocks`, lock waits, replication lag.
- Cache: hit rate, evictions, big keys (`redis-cli --bigkeys`), `EngineCPUUtilization`.
- KEDA: `keda_scaler_metrics_value`, `keda_scaler_errors_total`, HPA events.
- Batch: runnable age, failed job reasons, node join time (EKS CE).
- Traces: producer→consumer latency (queue time) from propagated context.

Full table: [`reference/metrics-catalog.md`](../../reference/metrics-catalog.md).

## 8. Testing and DR notes

Testing correctness: property-style tests that replay the same message twice and N times out of
order; crash tests that kill the consumer between effect and acknowledgement (in Compose: `docker
kill` the worker mid-batch, then observe redelivery); rebalance tests scaling the Kafka consumer from
1 to 3 and back under load; stampede tests expiring a hot key while running k6 against `catalog` and
watching database QPS; connection-storm tests deploying 3× replicas at once. DR drills: promote an
Aurora Global secondary and verify the application reconnects (endpoint change), rebuild the cache
cold and measure the miss storm, verify MSK Replicator offset translation, and exercise the SQS
republish path (producers re-send unfulfilled orders after failover)
([data recovery runbook](../../playbooks/dr/data-recovery-runbook.md)).

## 9. Hands-on

```bash
make up && make smoke
# 1. Redelivery is harmless: send the same SQS body twice and watch "already processed"
BODY=$(docker compose -f labs/local/compose.yaml logs --no-log-prefix orders | grep -m1 '"order created"' | jq -c '{type:"order.created",version:1,orderId:.order_id,productId:1,quantity:1,priceCents:1999,createdAt:(now|todate)}')
for i in 1 2; do aws --endpoint-url http://localhost:9324 --region us-east-1 sqs send-message --queue-url http://localhost:9324/000000000000/orders-created --message-body "$BODY" >/dev/null; done
docker compose -f labs/local/compose.yaml logs --no-log-prefix fulfillment-worker | grep -E 'already processed|order fulfilled' | tail -2

# 2. Crash between effect and ack: kill the worker while it processes, then watch redelivery
docker compose -f labs/local/compose.yaml kill fulfillment-worker && docker compose -f labs/local/compose.yaml up -d fulfillment-worker
curl -s http://localhost:9325/ | grep -oE 'orders-created[^<]*' | head -3

# 3. Kafka rebalance: scale the consumer group and describe assignments
docker compose -f labs/local/compose.yaml up -d --scale analytics-consumer=2 --no-recreate analytics-consumer 2>/dev/null || true
docker compose -f labs/local/compose.yaml exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group analytics
# Observe: 3 partitions split across members; lag per partition.

# 4. Stampede: expire the hot key and hit catalog concurrently
docker compose -f labs/local/compose.yaml exec -T valkey valkey-cli del product:1
seq 1 50 | xargs -P 50 -I{} curl -s -o /dev/null -w '%{http_code} ' localhost:8081/products/1; echo
docker compose -f labs/local/compose.yaml exec -T postgres psql -U app -d shopfront -tAc "select calls from pg_stat_statements limit 1" 2>/dev/null || echo "(enable pg_stat_statements to count queries)"
```

## 10. Check yourself

1. The analytics consumer upserts `daily_stats` with `orders_count + 1`. A rebalance redelivers 200
   records. What happens and how do you fix it?

<details><summary>Answer</summary>
Each redelivered record increments the counters again, so the day's counts are inflated by up to 200
orders and their revenue. Fix with an inbox: insert the event id into a `processed_events` table in
the same transaction as the upsert (`ON CONFLICT DO NOTHING`) and skip the upsert when the insert
affected zero rows; or recompute aggregates from `orders` instead of incrementing.
</details>

2. Why does increasing partitions not fix a lagging consumer group, and what can it break?

<details><summary>Answer</summary>
Lag comes from consumer throughput; more partitions only help if you also add consumers (members ≤
partitions) and the per-record work parallelises. Repartitioning changes the key→partition mapping,
so events for the same key may be in two partitions during the transition and per-key ordering is
lost; partitions also cannot be reduced later.
</details>

3. What is the precise failure a visibility timeout shorter than processing time causes, and why is
   it still "safe" with an idempotent consumer?

<details><summary>Answer</summary>
The message becomes visible again while the first consumer is still working, so a second consumer
receives and processes it concurrently; both may complete and one delete fails harmlessly. With an
idempotent effect (conditional update) the outcome is correct, but work is duplicated and the
receive count climbs toward the DLQ threshold; heartbeat with `ChangeMessageVisibility` or raise the
timeout.
</details>

4. Which two mechanisms shape a connection storm during a 200% rollout, and which metric proves it?

<details><summary>Answer</summary>
Client-side: lazy/small pools with jittered start-up and a capped `maximumPercent`; server-side: RDS
Proxy multiplexing many client connections onto a bounded database pool. `DatabaseConnections` (and
database `CPUUtilization`) plotted against deployment events shows the spike before and the flat
line after.
</details>

5. What does "SQS is regional" mean for the DR plan of `orders`?

<details><summary>Answer</summary>
Messages in the queue exist only in that Region; a Region failure loses unprocessed messages and
their in-flight state. The plan must either accept and recover from that (re-derive fulfilment work
from the `orders` table: every `CREATED` order older than N minutes is republished in the DR Region),
dual-write to queues in both Regions, or use a replicated stream (MSK Replicator) as the source of
truth instead of the queue.
</details>

## 11. Sources

- Amazon SQS: at-least-once delivery, visibility timeout, dead-letter queues, FIFO high throughput — https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html and https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/high-throughput-fifo.html
- Kafka consumer group protocol, cooperative rebalancing, static membership — https://kafka.apache.org/documentation/#consumerconfigs and https://cwiki.apache.org/confluence/display/KAFKA/KIP-429%3A+Kafka+Consumer+Incremental+Rebalance+Protocol
- Kafka transactions and exactly-once semantics — https://kafka.apache.org/documentation/#semantics
- Amazon MSK consumer lag metrics; MSK Replicator — https://docs.aws.amazon.com/msk/latest/developerguide/consumer-lag.html and https://docs.aws.amazon.com/msk/latest/developerguide/what-is-msk-replicator.html
- Strimzi documentation — https://strimzi.io/documentation/
- AWS Glue Schema Registry compatibility modes — https://docs.aws.amazon.com/glue/latest/dg/schema-registry.html#schema-registry-compatibility
- Amazon RDS Proxy: pinning and connection pooling — https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-managing.html#rds-proxy-pinning
- ElastiCache: eviction policies and best practices — https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/BestPractices.html
- Optimal probabilistic cache stampede prevention (Vattani, Chierichetti, Lowenstein) — https://cseweb.ucsd.edu/~avattani/papers/cache_stampede.pdf
- KEDA concepts: scaling deployments, activation, `TriggerAuthentication` — https://keda.sh/docs/latest/concepts/scaling-deployments/
- AWS Batch on EKS: how it works, RBAC, compute environments — https://docs.aws.amazon.com/batch/latest/userguide/eks.html
- AWS Batch fair-share scheduling — https://docs.aws.amazon.com/batch/latest/userguide/fair-share-scheduling.html
- Aurora Global Database failover; RDS Multi-AZ — https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-global-database-disaster-recovery.html and https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html
- ElastiCache Global Datastore — https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Redis-Global-Datastore.html
