# Regional failover and failback runbook for shopfront

**Applies to:** both (ECS steps shown; EKS differences called out) · **Severity guide:** SEV1 · **Time to first fix:** target RTO 30 min for tier 1 (measure it)

Warm-standby assumptions: the recovery Region (`us-west-2`) already has the network, cluster, data and
services stacks deployed from the same templates with `parameters/prod-us-west-2.json`, Aurora Global
Database secondary, ECR replication, replicated secrets, and services running at reduced capacity.
If that is not true, run [cluster-rebuild-runbook.md](cluster-rebuild-runbook.md) first (pilot light) and
accept the longer RTO. Nothing below runs on its own; two people execute it, one reads, one types.

## Preconditions

- [ ] Decision criteria in the DR plan §5 met; DR lead and second approver named in the incident channel with a timestamp.
- [ ] Recovery Region health: canary green, `aws health describe-events --region us-west-2` clear.
- [ ] Replication lag under RPO: `aws rds describe-global-clusters --global-cluster-identifier shopfront-prod-global --query 'GlobalClusters[0].GlobalClusterMembers'` and the `AuroraGlobalDBReplicationLag` metric.
- [ ] Credentials for both Regions in the operator's shell; `export AWS_REGION=us-west-2` set explicitly in every command below (mistakes here are the classic DR self-inflicted wound).
- [ ] Communications sent: "investigating / failover in progress".

## Steps

### 1. Freeze writes in the primary (if it is reachable)

Prevents split-brain data: the primary keeps serving reads while the secondary is promoted.

```bash
export AWS_REGION=us-east-1
aws ecs update-service --cluster shopfront-prod --service orders --desired-count 0        # writers off; catalog (reads) stays
aws ecs update-service --cluster shopfront-prod --service fulfillment-worker --desired-count 0
# EKS: kubectl --context prod-us-east-1 -n shopfront scale deploy/orders deploy/fulfillment-worker --replicas=0
# and pause Argo CD auto-sync so it does not scale them back: argocd app set shopfront-prod-us-east-1 --sync-policy none
```

If the primary Region is unreachable, skip: the promotion below detaches the secondary anyway.

### 2. Promote the database in the recovery Region

Managed failover (`switchover`) keeps replication and has zero data loss but needs both Regions healthy;
`failover` with `--allow-data-loss` detaches the secondary when the primary is impaired.

```bash
export AWS_REGION=us-west-2
# Both Regions healthy (planned or rehearsal):
aws rds switchover-global-cluster --global-cluster-identifier shopfront-prod-global \
  --target-db-cluster-identifier arn:aws:rds:us-west-2:123456789012:cluster:shopfront-prod
# Primary impaired (unplanned):
aws rds failover-global-cluster --global-cluster-identifier shopfront-prod-global \
  --target-db-cluster-identifier arn:aws:rds:us-west-2:123456789012:cluster:shopfront-prod --allow-data-loss
aws rds wait db-cluster-available --db-cluster-identifier shopfront-prod
aws rds describe-db-clusters --db-cluster-identifier shopfront-prod --query 'DBClusters[0].{status:Status,writer:DBClusterMembers[?IsClusterWriter].DBInstanceIdentifier,global:GlobalWriteForwardingStatus}'
```

Record the promotion time and, for `--allow-data-loss`, the lag at that moment (this is the actual RPO loss).

### 3. Point the services at the promoted database

The `DATABASE_URL` secret in `us-west-2` already targets the local RDS Proxy (deploy.sh composed it per
Region), so tasks need no change. Confirm the proxy now targets a writer:

```bash
aws rds describe-db-proxy-targets --db-proxy-name shopfront-prod --query 'Targets[*].{endpoint:Endpoint,role:Role,state:TargetHealth.State,reason:TargetHealth.Reason}'
# role READ_WRITE and state AVAILABLE. If UNAVAILABLE: the proxy still sees the old reader role; wait ~1 min or recreate the target group registration.
```

### 4. Scale the recovery Region to production capacity

```bash
aws ecs update-service --cluster shopfront-prod --service orders --desired-count 6
aws ecs update-service --cluster shopfront-prod --service catalog --desired-count 6
aws ecs update-service --cluster shopfront-prod --service fulfillment-worker --desired-count 2
aws ecs wait services-stable --cluster shopfront-prod --services orders catalog fulfillment-worker
# EKS: argocd app set shopfront-prod-us-west-2 --sync-policy automated ; kubectl scale ... ; HPAs and KEDA take over from there
# Auto scaling minimums: aws application-autoscaling register-scalable-target ... --min-capacity 6 (or let the policies catch up)
```

Watch for capacity failures: quotas in the recovery Region are the number one DR surprise
(`pending-pods-and-capacity.md`).

### 5. Move traffic

```bash
# Route 53 failover records: the health check on the primary ALB should already have flipped; force it if needed.
aws route53 list-health-checks --query 'HealthChecks[*].[Id,HealthCheckConfig.FullyQualifiedDomainName]'
aws route53 update-health-check --health-check-id <primary-hc-id> --disabled     # forces "unhealthy" -> failover to secondary
aws route53 test-dns-answer --hosted-zone-id <zone-id> --record-name shopfront.example.com --record-type A --query 'RecordData'
# With ARC routing controls (recommended for prod): aws route53-recovery-cluster update-routing-control-states ... us-east-1 Off, us-west-2 On
# CloudFront in front: switch the origin (or origin group) instead of DNS.
```

DNS TTL (60 s in the lab zone) bounds how long clients keep hitting the old Region; clients with
long-lived connections need the old ALB to go away (step 1 scaled the writers down; also consider
`aws elbv2 modify-listener` to return 503 in the primary).

### 6. Re-queue in-flight work

SQS is Regional. Orders that were `CREATED` in the primary but not fulfilled are re-queued from the
database in the recovery Region (the worker is idempotent: `status` transitions are guarded).

```bash
aws ecs run-task --cluster shopfront-prod --launch-type FARGATE --task-definition shopfront-prod-db-migrate \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"psql","command":["sh","-c","psql \"$DATABASE_URL\" -Atc \"select id from orders where status = '\''CREATED'\'' and created_at > now() - interval '\''2 hours'\''\""]}]}'
# Feed the ids to a small script that calls sqs send-message on the recovery queue: labs/apps/orders publishes {"orderId": "..."} (labs/CONTRACT.md §5).
```

Kafka (tier 3) is not replicated in the lab: `analytics-consumer` starts from the new cluster; `daily_stats` is recomputed by `report-job`.

### 7. Verify (tier 1 RTO clock stops here)

```bash
curl -fsS https://shopfront.example.com/products | head -c 200; echo
id=$(curl -fsS -X POST https://shopfront.example.com/orders -H 'content-type: application/json' -d '{"productId":1,"quantity":1}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
sleep 10; curl -fsS "https://shopfront.example.com/orders/$id" | grep -o '"status":"[A-Z]*"'     # FULFILLED
aws cloudwatch describe-alarms --region us-west-2 --state-value ALARM --alarm-name-prefix shopfront-prod --query 'MetricAlarms[*].AlarmName'
```

Announce "failed over, monitoring"; hand the data owner the RPO loss figure from step 2.

### 8. Stabilise

- Re-enable auto-sync / autoscaling minimums for steady state in the recovery Region.
- Enable the report-job schedule in the recovery Region (`ScheduleState=ENABLED` in 06-batch there).
- Confirm alarms route to the on-call (SNS subscriptions exist per Region).
- If the primary Region is still up, keep it read-only; do not let anyone "quickly" scale orders back up there.

## Failback (planned, days later)

1. Rebuild replication the other way: add the old primary Region as a **secondary** of the promoted global cluster (`aws rds create-db-cluster --global-cluster-identifier ... --region us-east-1`), or restore it from a snapshot of the new primary; wait for lag ≈ 0.
2. Deploy the current image tags to the old Region (`deploy.sh` with `ENV=prod` there) and confirm its canary.
3. Repeat steps 1–7 in the opposite direction, using `switchover-global-cluster` (zero data loss).
4. Reconcile: orders created during the outage in both Regions (should be none if step 1 held), reports for the outage day, analytics recount.
5. Post-incident review with the measured detection/decision/execution/verification times; update the plan's RTO/RPO table with actuals.

## Rollback (during the failover)

If the recovery Region cannot take traffic (capacity, quota, bad deploy): keep DNS on the primary
(re-enable the health check), scale the primary writers back up only if the database was **not**
promoted with `--allow-data-loss`; if it was, the primary is now stale and must become the secondary:
there is no way back without the data owner's decision.

## Related

- Plan: [dr-plan-template.md](dr-plan-template.md) · Rebuild: [cluster-rebuild-runbook.md](cluster-rebuild-runbook.md) · Data: [data-recovery-runbook.md](data-recovery-runbook.md) · Rehearsal: [game-day-guide.md](game-day-guide.md)
- Mechanism: [10 · L300 DR strategies, Route 53 and ARC](../../hub/10-resilience-and-dr/L300-dr-strategies-for-container-platforms.md), [10 · L400 multi-Region reference architectures and pitfalls](../../hub/10-resilience-and-dr/L400-dr-plan-and-game-days.md), [09 · L300 Aurora Global Database, SQS Regional scope](../../hub/09-data-messaging-and-batch/L300-messaging-and-data-deep-dive.md)
