# ECS deployment stuck IN_PROGRESS, circuit breaker tripped, or rolled back

**Applies to:** ECS · **Severity guide:** SEV2 (the old revision usually keeps serving); SEV1 if `MinimumHealthyPercent` let capacity drop · **Time to first fix:** 10–30 min

## Symptoms

- `describe-services` shows a `PRIMARY` deployment with `rolloutState: IN_PROGRESS` for far longer than usual, `pendingCount` > 0 or `failedTasks` climbing.
- `rolloutState: FAILED` with `rolloutStateReason: ECS deployment circuit breaker: tasks failed to start.` or `... task failed to reach a steady state.` or `... CloudWatch alarm(s) in ALARM state`; a new deployment appears with reason `rollback`.
- Blue/green: traffic shift paused at a lifecycle hook, or `ServiceRevision` stuck; canary or linear shift not progressing.
- CloudFormation stack `UPDATE_IN_PROGRESS` for an hour then `UPDATE_ROLLBACK_IN_PROGRESS` on `AWS::ECS::Service`.

## Triage in five minutes

```bash
# 1. Deployment state and the reason text
aws ecs describe-services --cluster shopfront-dev --services orders \
  --query 'services[0].deployments[*].{status:status,rollout:rolloutState,reason:rolloutStateReason,taskdef:taskDefinition,desired:desiredCount,running:runningCount,pending:pendingCount,failed:failedTasks,created:createdAt}' --output table
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].events[0:10].[createdAt,message]' --output table

# 2. Why do the NEW tasks stop? (the new task definition revision)
aws ecs list-tasks --cluster shopfront-dev --service-name orders --desired-status STOPPED --query 'taskArns[0:3]' --output text | tr '\t' '\n' \
  | xargs -I{} aws ecs describe-tasks --cluster shopfront-dev --tasks {} --query 'tasks[0].{taskdef:taskDefinitionArn,stopCode:stopCode,reason:stoppedReason,exit:containers[*].exitCode}'

# 3. Alarms wired to the deployment, and their state during the rollout
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].deploymentConfiguration'
aws cloudwatch describe-alarms --alarm-names shopfront-dev-orders-5xx-ratio shopfront-dev-orders-p99-latency shopfront-dev-orders-unhealthy-targets \
  --query 'MetricAlarms[*].[AlarmName,StateValue,StateReason]' --output table

# 4. Capacity: is the surge blocked? (MaximumPercent 200 needs room for 2x tasks: IPs, vCPU quota, Spot)
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].events[?contains(message, `unable to place`)].message' | head -3

# 5. Service Connect / load balancer wiring of the new revision
aws ecs describe-task-definition --task-definition <new-revision> --query 'taskDefinition.containerDefinitions[*].{name:name,ports:portMappings}'
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].{lb:loadBalancers,sc:serviceConnectConfiguration.services[*].{port:portName,alias:clientAliases}}'
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **New tasks fail to start** (circuit breaker `tasks failed to start`) | step 2: `CannotPullContainerError`, `ResourceInitializationError`, `EssentialContainerExited` | Fix per [ecs-task-stopped-reasons.md](ecs-task-stopped-reasons.md); the breaker threshold is max(10, 0.5 × desired) failures |
| **New tasks start but never become healthy** (`task failed to reach a steady state`) | Container health check or ALB health check failing on the new revision only | Compare env/secrets between revisions (`describe-task-definition` diff); a new required variable, a renamed secret, a port change without updating `LoadBalancers[].ContainerPort` |
| **Alarm rollback fired** | step 3: one of the `RollbackAlarmNames` was in `ALARM` during the deployment; note ECS ignores alarms already in ALARM when the deployment starts | Look at the alarm's metric for the window: genuine regression (5xx, latency) → fix the code; noisy alarm → tune `DatapointsToAlarm`/threshold in `05-observability.yaml` |
| **Bake time makes it look stuck** | Everything healthy, `IN_PROGRESS` for several minutes after tasks are running | Expected with alarm-based rollback: ECS waits the bake time (default < 5 min, configurable) before `COMPLETED` |
| **No room for the surge** | `unable to place a task`: subnet IPs, `RESOURCE:CPU`, Fargate vCPU quota, Spot unavailable | [pending-pods-and-capacity.md](pending-pods-and-capacity.md); lower `MaximumPercent` to 150 or raise capacity |
| **`MinimumHealthyPercent` too high with a small `DesiredCount`** | 1 task, min 100%, max 100%: nothing can move | Set `MaximumPercent: 200` (Fargate has room) or `MinimumHealthyPercent: 50` for workers as in `04-services.yaml` |
| **Health check grace too short** | New tasks are killed by the scheduler for failing ELB health checks during start-up | Raise `HealthCheckGracePeriodSeconds` (60 s in the lab) above the slowest cold start |
| **Service Connect misconfiguration** | Proxy container fails: `PortName` not in the task's `portMappings`, namespace mismatch, alias port collision; `service-connect` log group shows Envoy errors | `PortName` = `portMappings[].name`; one namespace per cluster; alias DNS names unique per namespace |
| **Blue/green lifecycle hook Lambda failed or timed out** | Deployment paused at `POST_TEST_TRAFFIC_SHIFT`/`PRE_PRODUCTION_TRAFFIC_SHIFT`; hook Lambda errors in its log group | Fix the hook (it must call back with `SUCCEEDED`/`FAILED`); set `bakeTimeInMinutes` and hook timeouts; a failed hook rolls back by design (hub/03 L200 §2.9) |
| **Blue/green target group / listener rule wiring** | Test listener rule missing; second target group absent | Blue/green needs two target groups and (optionally) a test listener; ECS native blue/green manages the switch, CodeDeploy needs the `AppSpec` |
| **CloudFormation waiting on ECS stabilisation** | Stack `UPDATE_IN_PROGRESS` on `AWS::ECS::Service` for up to 1 h then rolls back | The service never reached steady state: same root cause; CFN rollback also rolls the service back. Use `aws ecs describe-services` while the stack waits |
| **Task definition registered but the service points to the old one** | `describe-services` `taskDefinition` unchanged after deploy | The deploy did not update the service (`--force-new-deployment` needed for image tag reuse; `04-services.yaml` changes the family revision when `ImageTag` changes) |
| **Desired count changed by auto scaling mid-deployment** | Target tracking scaled in while the deployment surged | Normal; if it prolongs rollouts, add scale-in cooldown (`ScaleInCooldown: 180`) |

Manual rollback, when the automatic one did not happen:

```bash
aws ecs update-service --cluster shopfront-dev --service orders --task-definition shopfront-dev-orders:<previous-revision> --force-new-deployment
aws ecs wait services-stable --cluster shopfront-dev --services orders
```

## Verify the fix

```bash
aws ecs describe-services --cluster shopfront-dev --services orders \
  --query 'services[0].deployments[?status==`PRIMARY`].{rollout:rolloutState,reason:rolloutStateReason,running:runningCount,desired:desiredCount}'
# COMPLETED, running == desired, and the alarms OK:
aws cloudwatch describe-alarms --alarm-name-prefix shopfront-dev-orders --state-value ALARM --query 'MetricAlarms[*].AlarmName'
```

## Prevent it

- Circuit breaker + alarm rollback on every service; `RollbackAlarmNames` wired by `deploy.sh` after `05-observability` exists.
- `MaximumPercent 200`/`MinimumHealthyPercent 100` for HTTP services, `50/200` for workers; grace period ≥ cold start.
- Pre-deploy checks in the pipeline: images exist for the tag, no active CRITICAL findings (`deploy-ecs.yml`), task definition validated with `register-task-definition --cli-input-json` in a dry environment.
- Deployment events into the log group and SNS (`EcsDeploymentFailedRule`), so a rollback is announced, not discovered.

## Related

- Mechanism: [03 L200 deployment configuration](../../hub/03-ecs/L200-task-definitions-services-and-scaling.md), [08 L300 ECS deployment strategies in depth](../../hub/08-delivery-cicd-gitops/L300-progressive-delivery-and-gitops-internals.md), [03 L400 large-fleet deployment safety](../../hub/03-ecs/L400-ecs-at-scale.md)
- Neighbours: [ecs-task-stopped-reasons.md](ecs-task-stopped-reasons.md), [alb-5xx-and-unhealthy-targets.md](alb-5xx-and-unhealthy-targets.md), [pending-pods-and-capacity.md](pending-pods-and-capacity.md)
