# Queue backlog and consumer lag: SQS age growing, Kafka lag, DLQ filling, KEDA not scaling, database connections exhausted

**Applies to:** both · **Severity guide:** SEV2 when orders stay `CREATED` beyond the fulfilment SLO; SEV1 when the DLQ receives customer orders · **Time to first fix:** 10–30 min

## Symptoms

- `ApproximateAgeOfOldestMessage` climbs (alarm `shopfront-dev-orders-queue-age`); `ApproximateNumberOfMessagesVisible` grows while `NumberOfMessagesDeleted` stays flat.
- `shopfront-dev-orders-dlq-not-empty` fires: messages exhausted `maxReceiveCount`.
- MSK: consumer group lag (`SumOffsetLag`, `EstimatedMaxTimeLag`) grows; `analytics-consumer` logs rebalances (`Attempt to heartbeat failed since group is rebalancing`).
- KEDA: `ScaledObject` `READY False` / `ACTIVE False`, HPA shows `<unknown>` for the external metric; replicas stay at the floor while the queue grows.
- Consumers log `FATAL: remaining connection slots are reserved` / `too many connections for role "app"` / RDS Proxy `DatabaseConnectionsBorrowLatency` up.

## Triage in five minutes

```bash
# 1. Queue picture: depth, in-flight, age, DLQ
Q=https://sqs.us-east-1.amazonaws.com/123456789012/shopfront-dev-orders-created
aws sqs get-queue-attributes --queue-url "$Q" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed VisibilityTimeout RedrivePolicy --output table
aws cloudwatch get-metric-statistics --namespace AWS/SQS --metric-name ApproximateAgeOfOldestMessage --dimensions Name=QueueName,Value=shopfront-dev-orders-created \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 300 --statistics Maximum --query 'Datapoints[*].[Timestamp,Maximum]' --output text | sort
#   NotVisible high and Visible low -> consumers are receiving but not finishing (slow or crashing mid-message)
#   Visible high, NotVisible ~0    -> nobody is receiving (consumers down, wrong queue URL, no permission)
#   DLQ growing                     -> poison messages or a consumer that always fails

# 2. Consumer picture: how many, healthy, what do they say?
aws ecs describe-services --cluster shopfront-dev --services fulfillment-worker --query 'services[0].{running:runningCount,desired:desiredCount,events:events[0:3].message}'
kubectl -n shopfront get deploy fulfillment-worker scaledobject fulfillment-worker hpa
kubectl -n shopfront describe scaledobject fulfillment-worker | sed -n '/Conditions:/,/Events:/p'
kubectl -n shopfront logs deploy/fulfillment-worker --since=10m | grep -iE 'error|exception|timeout|AccessDenied' | tail -20
aws logs tail /shopfront/dev/fulfillment-worker --since 10m --format short | grep -iE 'error|exception|timeout' | tail -20

# 3. Peek at a DLQ message (do not delete)
aws sqs receive-message --queue-url "${Q}-dlq" --max-number-of-messages 1 --visibility-timeout 5 --attribute-names All --message-attribute-names All --query 'Messages[0].{body:Body,attrs:Attributes}'

# 4. Kafka lag and rebalances
aws kafka get-bootstrap-brokers --cluster-arn <msk-arn> --query BootstrapBrokerStringSaslIam --output text
aws cloudwatch get-metric-statistics --namespace AWS/Kafka --metric-name SumOffsetLag --dimensions Name="Cluster Name",Value=shopfront-dev Name="Consumer Group",Value=analytics Name=Topic,Value=orders.created \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 300 --statistics Maximum --query 'Datapoints[*].Maximum'
kubectl -n shopfront logs deploy/analytics-consumer --since=15m | grep -ciE 'rebalanc'

# 5. Database side: connections and the proxy
aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name DatabaseConnections --dimensions Name=DBClusterIdentifier,Value=shopfront-dev \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 300 --statistics Maximum --query 'Datapoints[*].Maximum'
aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name DatabaseConnectionsCurrentlySessionPinned --dimensions Name=ProxyName,Value=shopfront-dev \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 300 --statistics Average --query 'Datapoints[*].Average'
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **Consumers down or at zero** | step 2: `runningCount 0`, pods CrashLooping, KEDA scaled to 0 and not waking | Fix the crash (crashloop runbook); check `minReplicaCount`; the ECS backlog policy needs Container Insights `RunningTaskCount` (metric math in `04-services.yaml`) |
| **Consumers up but not receiving: wrong queue URL / Region / permission** | Visible high, NotVisible ~0; logs `AccessDenied` on `sqs:ReceiveMessage` or `NonExistentQueue` | Fix `SQS_QUEUE_URL`/`AWS_REGION`; task/pod role needs `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility`, `GetQueueAttributes` (iam runbook) |
| **Slow processing: each message takes longer than before** | NotVisible high; per-message latency up in traces (`order.fulfill` span); DB latency | Find the slow dependency (DB query plan, Valkey, downstream); scale out (KEDA/ECS backlog target); raise `SQS_MAX_MESSAGES` batch only if per-message cost is small |
| **Visibility timeout shorter than processing time: duplicates and thrash** | Same message id processed by several consumers; `ApproximateReceiveCount` > 1 on healthy messages | `VisibilityTimeout` ≥ 6 × the p99 processing time (or extend it in-flight); idempotency key on the order id (hub/09 L300 §2.1) |
| **Poison messages: the same message fails every time and lands in the DLQ** | step 3: body malformed, unknown product id, schema drift | Fix the producer or add validation; redrive from the DLQ after the fix (`aws sqs start-message-move-task --source-arn <dlq-arn>`); keep `maxReceiveCount` 5–10 |
| **KEDA cannot read the metric** | `ScaledObject` condition `Ready False: error getting scaler metrics ... AccessDenied`; HPA `<unknown>` | KEDA operator identity needs `sqs:GetQueueAttributes` on the queue (Pod Identity association `keda/keda-operator`); `TriggerAuthentication` `podIdentity.provider: aws` |
| **KEDA `fallback` holding replicas after a metrics outage** | HPA external metric flat at `fallback.replicas` | Fix the metric source; fallback is doing its job |
| **KEDA scaled, pods Pending** | HPA desired > ready | Capacity runbook (IPs, nodes, quota) |
| **ECS backlog policy not scaling** | Alarm for the target-tracking policy `INSUFFICIENT_DATA`; `RunningTaskCount` metric missing (Container Insights off) | `containerInsights: enhanced` on the cluster (02-cluster.yaml); check the policy's alarms in CloudWatch (`TargetTracking-service/...`) |
| **Scale-in too eager: consumers killed with messages in flight** | Duplicates after scale-in; `SIGTERM` logs with `in-flight` count | `SHUTDOWN_TIMEOUT_SECONDS` and `stopTimeout`/`terminationGracePeriodSeconds` ≥ time to finish the batch; `ScaleInCooldown 300`; KEDA `cooldownPeriod` |
| **Kafka rebalance storm** | `rebalance` count high; consumers restarted by Spot reclaims or liveness probes; `max.poll.interval.ms` exceeded on slow batches | Consumers on on-demand capacity (`workload=stable` in the lab), longer `max.poll.interval.ms` or smaller `max.poll.records`, cooperative-sticky assignor, static group membership |
| **Kafka lag on one partition** | Per-partition lag skewed; hot key | Partition key design (order id, not customer id for a big customer); more partitions only with a plan for re-keying |
| **MSK Serverless throttling** | `ThrottledRequests`/`FetchThrottleTime` non-zero; partition throughput limits | Spread across partitions; Provisioned or Express brokers for sustained throughput (hub/09 L200 §2.5) |
| **Database connections exhausted by scale-out** | `remaining connection slots are reserved`; connections = (replicas × pool size) > `max_connections`; proxy pinning high | Pool size per replica small (worker pool `max_size 4`); RDS Proxy in front (03-data.yaml) and no pinning (`SET` statements, unnamed prepared statements); cap `maxReplicaCount` at what the DB tolerates |
| **RDS Proxy pinning defeats multiplexing** | `DatabaseConnectionsCurrentlySessionPinned` ≈ `DatabaseConnections` | Avoid session state: no `SET search_path`, no advisory locks, use protocol-level prepared statements; alarm `rds-proxy-pinned-sessions` |
| **Producer outage disguised as consumer lag** | Age grows but Visible is flat and `NumberOfMessagesSent` is 0: no new messages, one stuck old one | Look at the stuck message (step 3 with the main queue): a poison message that keeps being retried |

## Verify the fix

```bash
watch -n 30 "aws sqs get-queue-attributes --queue-url $Q --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes --output text"   # both trending to 0
aws cloudwatch describe-alarms --alarm-names shopfront-dev-orders-queue-age shopfront-dev-orders-dlq-not-empty --query 'MetricAlarms[*].[AlarmName,StateValue]'
curl -fsS "http://<alb>/orders?status=CREATED" | head -c 300     # shrinking; orders flip to FULFILLED within seconds
```

## Prevent it

- Alarm on age, not depth; DLQ ≥ 1 alarm; consumer error rate; RDS connections at 80% of `max_connections`.
- Scaling on backlog per consumer (KEDA `queueLength`, ECS metric math) with a max that the database can serve.
- Idempotent consumers, visibility timeout ≥ 6 × p99, DLQ with redrive, schema validation at the boundary.
- Load test the async path with the report of hub/11 L300 §2.5: how long does a 10 000-message burst take to drain, and what did the database do meanwhile.

## Related

- Mechanism: [09 L200 SQS, MSK, KEDA, RDS Proxy](../../hub/09-data-messaging-and-batch/L200-integration-patterns.md), [09 L300 at-least-once, poison messages, connection storms, KEDA internals](../../hub/09-data-messaging-and-batch/L300-messaging-and-data-deep-dive.md), [09 L400 backpressure and load shedding](../../hub/09-data-messaging-and-batch/L400-event-driven-architecture-at-scale.md)
- Neighbours: [iam-accessdenied-from-containers.md](iam-accessdenied-from-containers.md), [pending-pods-and-capacity.md](pending-pods-and-capacity.md), [crashloop-and-exit-codes.md](crashloop-and-exit-codes.md)
- DR: [data-recovery-runbook.md](../dr/data-recovery-runbook.md)
- Reference: [metrics catalog](../../reference/metrics-catalog.md)
