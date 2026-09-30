# Data recovery runbook: Aurora PostgreSQL, Valkey, SQS, MSK, S3 and secrets

**Applies to:** both · **Severity guide:** SEV1 for data loss or corruption in `orders`; SEV2 for cache/queue/stream loss (recoverable by design) · **Time to first fix:** Aurora PITR 15–30 min plus verification; others minutes

The compute tiers are stateless. Every recovery below ends with re-pointing them at the recovered
store and verifying through the API, never by editing data by hand under pressure.

## Preconditions

- [ ] Know **what** is wrong: deleted rows, bad migration, corrupted writes since time T, cluster unavailable, or Region loss (then use the failover runbook).
- [ ] Know **when** it started (T): from the deployment timeline (`/shopfront/<env>/ecs-events`, Argo CD history), CloudTrail, or the application logs.
- [ ] Data owner available to approve a point-in-time choice (everything after T is lost or must be reconciled).
- [ ] Writers stopped if corruption is ongoing (`orders` and `fulfillment-worker` to 0) so the restore target is stable.

## Aurora PostgreSQL

### A. Cluster unavailable (instance failure, AZ event)

Aurora fails over inside the cluster (writer → reader promotion, ~30 s) on its own when a reader exists
(`DbReader` in prod). Nothing to restore.

```bash
aws rds describe-db-clusters --db-cluster-identifier shopfront-prod --query 'DBClusters[0].{status:Status,members:DBClusterMembers[*].[DBInstanceIdentifier,IsClusterWriter]}'
aws rds describe-events --source-identifier shopfront-prod --source-type db-cluster --duration 60 --query 'Events[*].[Date,Message]' --output text
aws rds failover-db-cluster --db-cluster-identifier shopfront-prod          # force it when the writer is unhealthy but not failed over
```

Applications reconnect through the RDS Proxy (connection pinned to the old writer are dropped and
retried by the pools; hub/09 L200 §2.1). Verify with `curl /readyz` on the services.

### B. Logical damage: bad migration, deleted or corrupted rows since T

Point-in-time restore creates a **new** cluster; you then move the application to it (or copy rows back).

```bash
# 1. Restore to T-1 minute as a new cluster in the same subnet group / security group
aws rds restore-db-cluster-to-point-in-time --db-cluster-identifier shopfront-prod-pitr \
  --source-db-cluster-identifier shopfront-prod --restore-to-time 2026-09-29T10:14:00Z \
  --db-subnet-group-name <subnet-group> --vpc-security-group-ids <data-sg> \
  --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=4 --enable-iam-database-authentication
aws rds create-db-instance --db-instance-identifier shopfront-prod-pitr-1 --db-cluster-identifier shopfront-prod-pitr --db-instance-class db.serverless --engine aurora-postgresql
aws rds wait db-instance-available --db-instance-identifier shopfront-prod-pitr-1      # ~10-20 min

# 2. Verify on the restored cluster BEFORE moving anything (one-off task with psql; the secret is the same admin password)
#    - row counts around T:  select status, count(*) from orders where created_at between T-1h and T group by 1;
#    - the damaged rows exist and look right
# 3a. Move the application: register the new cluster with the proxy target group and keep DATABASE_URL unchanged
aws rds deregister-db-proxy-targets --db-proxy-name shopfront-prod --db-cluster-identifiers shopfront-prod
aws rds register-db-proxy-targets --db-proxy-name shopfront-prod --db-cluster-identifiers shopfront-prod-pitr
#    (the proxy secret must match the restored cluster's credentials: PITR keeps the same admin user/password)
# 3b. Or surgical repair: copy rows from the restored cluster into the live one (dblink / \copy through the one-off task) when only a subset was damaged and writes since T must be kept.
```

Afterwards: rename clusters so IaC matches (`modify-db-cluster --new-db-cluster-identifier`) or update
`03-data.yaml` to import the restored cluster; delete the damaged cluster only after a final snapshot.

### C. Snapshot restore (cluster deleted, or `DeletionPolicy: Snapshot` fired)

```bash
aws rds describe-db-cluster-snapshots --db-cluster-identifier shopfront-prod --query 'DBClusterSnapshots[*].[DBClusterSnapshotIdentifier,SnapshotCreateTime,Status]' --output table
aws rds restore-db-cluster-from-snapshot --db-cluster-identifier shopfront-prod --snapshot-identifier <id> --engine aurora-postgresql \
  --db-subnet-group-name <subnet-group> --vpc-security-group-ids <data-sg> --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=4
aws rds create-db-instance --db-instance-identifier shopfront-prod-1 --db-cluster-identifier shopfront-prod --db-instance-class db.serverless --engine aurora-postgresql
```

The managed admin secret is not restored with the snapshot: set `ManageMasterUserPassword` again
through the stack or `modify-db-cluster --manage-master-user-password`, then re-run `deploy.sh`'s <!-- term-ok -->
`compose_database_url` (redeploy `03-data`, which recomposes `DATABASE_URL`).

### D. Backups exist? Prove it monthly

```bash
aws rds describe-db-clusters --db-cluster-identifier shopfront-prod --query 'DBClusters[0].{retention:BackupRetentionPeriod,earliest:EarliestRestorableTime,latest:LatestRestorableTime}'
aws backup list-recovery-points-by-resource --resource-arn arn:aws:rds:us-east-1:123456789012:cluster:shopfront-prod --query 'RecoveryPoints[0:3].[CreationDate,Status]'
```

## Valkey (ElastiCache Serverless)

It is a cache. Recovery = let it refill.

```bash
aws elasticache describe-serverless-caches --serverless-cache-name shopfront-prod --query 'ServerlessCaches[0].{status:Status,endpoint:Endpoint.Address}'
# Unavailable for long: catalog runs without cache when VALKEY_URL is unset (labs/CONTRACT.md); expect higher DB load.
# Serverless caches keep automatic snapshots when configured (SnapshotRetentionLimit); restore = create a new cache from the snapshot and update VALKEY_URL.
aws elasticache describe-serverless-cache-snapshots --serverless-cache-name shopfront-prod --query 'ServerlessCacheSnapshots[*].[ServerlessCacheSnapshotName,CreateTime]'
```

Watch for a **stampede** after a cold start: the catalog uses per-key TTL jitter (hub/09 L300 §2.4);
if p99 spikes, scale catalog up temporarily.

## SQS

Regional and durable; you do not restore a queue, you recover the **work**.

| Situation | Recovery |
| --- | --- |
| Queue deleted (60 s to recreate the same name is not allowed; a new one takes minutes) | Redeploy `03-data` (the name is fixed); orders in `CREATED` state older than the visibility timeout are re-queued from the database (`select id from orders where status = 'CREATED'` → `send-message`); consumers are idempotent |
| Messages in the DLQ after a fix | `aws sqs start-message-move-task --source-arn <dlq-arn> --destination-arn <queue-arn> --max-number-of-messages-per-second 50` then watch `dlq-not-empty` clear |
| Consumer processed messages wrongly | Data is in Aurora: repair there (section B), then re-queue affected order ids |
| Region loss | New queue in the recovery Region + re-queue from the database (region-failover runbook step 6) |

## MSK / Kafka

Tier 3 in the lab: the `orders.created` stream is derived data; `daily_stats` can be recomputed.

| Situation | Recovery |
| --- | --- |
| Consumer group offset wrong (reprocessing or skipping) | `kafka-consumer-groups.sh --bootstrap-server ... --group analytics --topic orders.created --reset-offsets --to-datetime 2026-09-29T00:00:00.000 --execute` (stop the consumer first); the consumer's `daily_stats` upsert is idempotent per day |
| Topic deleted / cluster lost | Recreate the topic (same partitions); producers resume (orders treats produce failures as non-fatal); rebuild `daily_stats` from `orders` with `report-job` or a SQL backfill |
| Retention too short for the outage | Accept the gap and backfill from `orders`; raise `retention.ms` for next time |
| Cross-Region | MSK Replicator when the stream becomes tier 1; otherwise rebuild as above |

## S3 reports

```bash
aws s3api list-object-versions --bucket shopfront-reports-prod-123456789012 --prefix daily/daily-2026-09-28 --query 'Versions[*].[Key,VersionId,IsLatest,LastModified]' --output table
aws s3api copy-object --bucket shopfront-reports-prod-123456789012 --key daily/daily-2026-09-28.json \
  --copy-source "shopfront-reports-prod-123456789012/daily/daily-2026-09-28.json?versionId=<good-version>"   # restore a previous version
labs/batch/submit-report.sh 2026-09-28                                                                        # or just regenerate it
```

## Secrets Manager

```bash
aws secretsmanager list-secret-version-ids --secret-id shopfront/prod/database-url --include-deprecated --query 'Versions[*].[VersionId,VersionStages,CreatedDate]'
aws secretsmanager update-secret-version-stage --secret-id shopfront/prod/database-url --version-stage AWSCURRENT --move-to-version-id <previous> --remove-from-version-id <current>
aws secretsmanager restore-secret --secret-id shopfront/prod/database-url        # within the recovery window after a delete
```

Tasks and pods read secrets at start: restart them (`update-service --force-new-deployment`,
`rollout restart`) after any secret change; ESO refreshes on its interval (1 h in the lab).

## Verify

```bash
# The API is the only acceptable verification of a data recovery:
curl -fsS https://shopfront.example.com/products/1 | head -c 200
id=$(curl -fsS -X POST https://shopfront.example.com/orders -H 'content-type: application/json' -d '{"productId":1,"quantity":1}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
sleep 10; curl -fsS "https://shopfront.example.com/orders/$id" | grep -o '"status":"[A-Z]*"'
# plus the data owner's reconciliation queries on the restored cluster, recorded in the incident timeline.
```

## Prevent it

- Backup retention 14 days in prod, PITR verified monthly by an automated restore + row-count check (hub/11 L400 §2.3).
- `DeletionProtection: true` in prod (`03-data.yaml` parameter), `DeletionPolicy: Snapshot`.
- Migrations expand/contract only (hub/08 L300 §2.5); every migration reversible or backed by a snapshot taken right before.
- Idempotent consumers and a DLQ, so queue recovery is a redrive, not a data hunt.
- Aurora Global Database and replicated secrets for tier 1 when the RPO says so.

## Related

- Plan: [dr-plan-template.md](dr-plan-template.md) · Failover: [region-failover-runbook.md](region-failover-runbook.md) · Rebuild: [cluster-rebuild-runbook.md](cluster-rebuild-runbook.md)
- Mechanism: [09 · L200 RDS Proxy, SQS redrive, MSK](../../hub/09-data-messaging-and-batch/L200-integration-patterns.md), [09 · L300 data DR options](../../hub/09-data-messaging-and-batch/L300-messaging-and-data-deep-dive.md), [10 · L300 what state exists and where](../../hub/10-resilience-and-dr/L300-dr-strategies-for-container-platforms.md)
- Incident: [queue-backlog-and-consumer-lag.md](../incidents/queue-backlog-and-consumer-lag.md)
