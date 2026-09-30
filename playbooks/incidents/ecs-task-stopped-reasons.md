# ECS task STOPPED: the stoppedReason and stopCode catalog

**Applies to:** ECS · **Severity guide:** SEV1 when a service cannot keep `runningCount` = `desiredCount`; SEV3 for a single scheduled task · **Time to first fix:** 5–20 min

## Symptoms

- `aws ecs describe-tasks` shows `lastStatus: STOPPED` with a `stopCode` and a `stoppedReason`; the console shows the same in the task detail.
- Service events repeat `(service orders) has started 2 tasks` followed by stops; `runningCount` below `desiredCount`; the deployment circuit breaker trips after enough failures.
- Stopped tasks disappear from `describe-tasks` about one hour after stopping; the EventBridge capture in `/shopfront/dev/ecs-events` (`05-observability.yaml`) keeps them.

## Triage in five minutes

```bash
# 1. The exact stopCode + stoppedReason + per-container exit codes and reasons
aws ecs list-tasks --cluster shopfront-dev --service-name orders --desired-status STOPPED --query 'taskArns[0:5]' --output text | tr '\t' '\n' | head -5
aws ecs describe-tasks --cluster shopfront-dev --tasks <task-arn> \
  --query 'tasks[0].{stopCode:stopCode,reason:stoppedReason,stoppedAt:stoppedAt,startedAt:startedAt,pullStarted:pullStartedAt,pullStopped:pullStoppedAt,containers:containers[*].{name:name,exit:exitCode,reason:reason,health:healthStatus},capacity:capacityProviderName,platform:platformVersion}'

# 2. History after the hour (EventBridge -> log group)
aws logs start-query --log-group-name /shopfront/dev/ecs-events --start-time "$(date -u -v-24H +%s)" --end-time "$(date -u +%s)" \
  --query-string 'fields @timestamp, detail.group, detail.stopCode, detail.stoppedReason | filter `detail-type` = "ECS Task State Change" | sort @timestamp desc | limit 50'

# 3. Service-level story
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].{events:events[0:8].[createdAt,message],deployments:deployments[*].{status:status,rollout:rolloutState,reason:rolloutStateReason,running:runningCount,pending:pendingCount,failed:failedTasks}}'

# 4. Application log of the stopped task (stream name = prefix/container/task-id)
aws logs tail /shopfront/dev/orders --since 1h --log-stream-names "ecs/orders/<task-id>" --format short | tail -50
```

## Causes and fixes

The `stopCode` groups the reasons; the `stoppedReason` text tells you which one.

| stopCode | stoppedReason (prefix) | Meaning | Fix |
| --- | --- | --- | --- |
| `TaskFailedToStart` | `CannotPullContainerError: ...` | Image pull failed: auth, not found, network, throttling, arch mismatch | [image-pull-failures.md](image-pull-failures.md) |
| `TaskFailedToStart` | `ResourceInitializationError: unable to pull secrets or registry auth: ...` | Execution role cannot read Secrets Manager/SSM, or Fargate has no path to those endpoints (`secretsmanager`, `ssm`, `kms`, `logs`) | Execution role permissions on the secret ARN (+ `kms:Decrypt` for CMK); VPC endpoints or NAT (hub/05 L200 §2.6) |
| `TaskFailedToStart` | `ResourceInitializationError: failed to validate logger args ...` / `unable to create log stream` | `awslogs` group missing (`awslogs-create-group` not set) or execution role lacks `logs:*` | Create the log group in IaC (02-cluster.yaml does), or add `awslogs-create-group: "true"` plus `logs:CreateLogGroup` |
| `TaskFailedToStart` | `ResourceInitializationError: failed to invoke EFS utils ...` | EFS mount target/security group/access point | Allow NFS 2049 from the task SG to the mount target SG; access point posix user matches |
| `TaskFailedToStart` | `ResourceInitializationError: failed to download env files` | S3 `environmentFiles` unreachable | Execution role `s3:GetObject` on the file and `s3:GetBucketLocation`; S3 gateway endpoint |
| `TaskFailedToStart` | `ResourceInitializationError: unable to attach ENI` / `Timeout waiting for network interface provisioning` | Subnet out of IPs, ENI limit, or EC2 API throttling | [pending-pods-and-capacity.md](pending-pods-and-capacity.md) IP section; spread across more subnets |
| `TaskFailedToStart` | `InternalError` / `ContainerRuntimeError` | Runtime failed to create the container (bad `user`, missing mount source, `linuxParameters` unsupported on Fargate) | Check unsupported fields on Fargate (`privileged`, `devices`, `tmpfs`, `sharedMemorySize`, host volumes); validate with `register-task-definition` `--cli-input-json` |
| `EssentialContainerExited` | `Essential container in task exited` | The essential container exited: read exit codes | [crashloop-and-exit-codes.md](crashloop-and-exit-codes.md); container `reason: OutOfMemoryError: Container killed due to memory usage` → [oom-and-cpu-throttling.md](oom-and-cpu-throttling.md) |
| `ServiceSchedulerInitiated` | `Task failed container health checks` | The container `healthCheck` failed `retries` times | Health check command must exist in the image (no `curl` in distroless); `startPeriod` long enough; check the app's `/healthz` |
| `ServiceSchedulerInitiated` | `Task failed ELB health checks in (target-group ...)` | ALB marked it unhealthy | [alb-5xx-and-unhealthy-targets.md](alb-5xx-and-unhealthy-targets.md); `healthCheckGracePeriodSeconds` covers slow starts |
| `ServiceSchedulerInitiated` | `Scaling activity initiated by (deployment ...)` / `by (application autoscaling ...)` | Normal scale-in or rollout replacement | Nothing to fix; correlate with alarms if surprising |
| `ServiceSchedulerInitiated` | `Deployment circuit breaker: ...` | Rollback stopped the new tasks | [ecs-deployment-stuck-or-rolled-back.md](ecs-deployment-stuck-or-rolled-back.md) |
| `SpotInterruption` | `Your Spot Task was interrupted` | Fargate Spot / EC2 Spot capacity reclaimed (2-minute warning, SIGTERM) | Expected: keep a `FARGATE` base in the capacity provider strategy; only interruption-tolerant services on Spot (the worker, not orders) |
| `TerminationNotice` | `Task was stopped due to instance termination` / `EC2 Scheduled event` | Container instance retiring or ASG scale-in without managed draining | Enable managed instance draining on the capacity provider; ECS_ENABLE_SPOT_INSTANCE_DRAINING; Managed Instances handle this |
| `UserInitiated` | `Task stopped by user` | Someone ran `stop-task` (CloudTrail has who) | Check CloudTrail `StopTask`; a game day or a deploy script (`deploy.sh migrate` stops nothing; FIS does) |
| `TaskFailedToStart` | `Timeout waiting for EphemeralStorage provisioning` / `Unable to provision ephemeral storage` | Fargate ephemeral storage request failed | Retry; reduce `ephemeralStorage.sizeInGiB` if oversized |
| `TaskFailedToStart` | `Unexpected EC2 error while attempting to Create Network Interface: ... VcpuLimitExceeded` | Fargate vCPU quota | Quota increase (`L-3032A538`) |
| `ServiceSchedulerInitiated` | `Task stopped by ECS due to AZ rebalancing` | `AvailabilityZoneRebalancing: ENABLED` moved it to balance AZs after a zone recovered | Expected; nothing to fix |

Exit code cheat sheet for the essential container: `0` finished on purpose (wrong workload type for a service), `1` application error (read the log), `137` OOM or SIGKILL after `stopTimeout`, `139` segfault/arch mismatch, `143` clean SIGTERM exit.

## Verify the fix

```bash
aws ecs describe-services --cluster shopfront-dev --services orders \
  --query 'services[0].{running:runningCount,desired:desiredCount,pending:pendingCount,rollout:deployments[0].rolloutState}'
aws ecs list-tasks --cluster shopfront-dev --service-name orders --desired-status STOPPED --query 'length(taskArns)'   # not growing over 15 min
```

## Prevent it

- Log groups, secrets, execution role and VPC endpoints in the same IaC as the services, deployed before them (`deploy.sh` order).
- Circuit breaker with rollback on every service, plus alarm-based rollback; `healthCheckGracePeriodSeconds` ≥ start-up time.
- Container health checks only with commands the image contains; `startPeriod` generous.
- Keep `/shopfront/<env>/ecs-events` so `stoppedReason` history survives the one-hour window; alarm on `SERVICE_TASK_START_IMPAIRED` and `SERVICE_TASK_PLACEMENT_FAILURE` service actions.

## Related

- Mechanism: [03 L300 task lifecycle, stopCode/stoppedReason, agent internals](../../hub/03-ecs/L300-ecs-internals.md), [03 L200 task definition fields](../../hub/03-ecs/L200-task-definitions-services-and-scaling.md), [06 L200 execution role vs task role](../../hub/06-identity-and-security/L200-iam-for-containers.md)
- Neighbours: every runbook linked in the table above
- Reference: [CLI cheatsheet](../../reference/cli-cheatsheet.md)
