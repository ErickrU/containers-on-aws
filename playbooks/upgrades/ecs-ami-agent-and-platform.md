# ECS: AMI rotation, agent updates, Fargate platform versions, Managed Instances patching

**Applies to:** ECS · **Severity guide:** planned change, SEV3; rotations touch every task once · **Time to first fix:** Fargate: none (AWS rotates); EC2 ASG: 30–90 min per fleet; Managed Instances: AWS-driven

What you own depends on the capacity type ([03 · L100](../../hub/03-ecs/L100-ecs-basics.md) §2,
[03 · L300](../../hub/03-ecs/L300-ecs-internals.md) §2.4–2.5):

| Capacity | Host OS and agent | Runtime | Your job |
| --- | --- | --- | --- |
| Fargate | AWS | Firecracker microVM, `platformVersion` (Linux `1.4.0` = `LATEST`) | Keep tasks tolerant of replacement; pin the platform version only while investigating |
| EC2 (ASG capacity provider) | You: ECS-optimized AMI (AL2023 or Bottlerocket; AL2 ECS AMIs reach end of standard support 2026-06-30), agent version, `ECS_*` config | Docker Engine (the ECS agent still drives Docker on EC2) | Rotate AMIs, update the agent, drain safely |
| ECS Managed Instances | AWS patches and rotates the EC2 instances in your account | containerd-based AWS-managed AMI | Set the capacity provider attributes; watch the rotation events |
| ECS Anywhere | You (on-prem OS + agent) | Docker | Same as EC2 without the ASG tooling |

## Preconditions

```bash
export CLUSTER=shopfront-dev
# Current fleet state
aws ecs describe-clusters --clusters $CLUSTER --include ATTACHMENTS SETTINGS --query 'clusters[0].{cps:capacityProviders,insights:settings}'
aws ecs list-container-instances --cluster $CLUSTER --query containerInstanceArns --output text | tr '\t' '\n' | xargs -I{} aws ecs describe-container-instances --cluster $CLUSTER --container-instances {} \
  --query 'containerInstances[0].{id:ec2InstanceId,agent:versionInfo.agentVersion,docker:versionInfo.dockerVersion,ami:attributes[?name==`ecs.ami-id`].value|[0],connected:agentConnected,running:runningTasksCount,status:status}'
# Latest recommended AMI and agent
aws ssm get-parameter --name /aws/service/ecs/optimized-ami/amazon-linux-2023/arm64/recommended --query 'Parameter.Value' --output text | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["image_id"], d["ecs_agent_version"], d["ecs_runtime_version"])'
# Services tolerate one task being replaced: MinimumHealthyPercent, HealthCheckGracePeriodSeconds, stopTimeout <= drain timeout
aws ecs describe-services --cluster $CLUSTER --services orders --query 'services[0].deploymentConfiguration'
# Fargate platform version in use and pinned?
aws ecs describe-services --cluster $CLUSTER --services orders catalog --query 'services[*].[serviceName,platformVersion,platformFamily]'
```

Managed instance draining must be on for the ASG capacity provider (`managedDraining: ENABLED`) so
scale-in and instance refresh drain tasks (SIGTERM → `stopTimeout`) instead of killing them.

## Steps: EC2 capacity provider (ASG) AMI rotation

1. Update the launch template with the new AMI id (from the SSM parameter above; never a hard-coded id) and any user-data changes (`ECS_CLUSTER`, `ECS_ENABLE_SPOT_INSTANCE_DRAINING=true`, `ECS_AWSVPC_BLOCK_IMDS=true`, `ECS_CONTAINER_STOP_TIMEOUT`, `ECS_IMAGE_CLEANUP_INTERVAL`, `ECS_ENGINE_TASK_CLEANUP_WAIT_DURATION`).

   ```bash
   aws ec2 create-launch-template-version --launch-template-name shopfront-dev-ecs --source-version '$Latest' \
     --launch-template-data '{"ImageId":"ami-0123456789abcdef0","MetadataOptions":{"HttpTokens":"required","HttpPutResponseHopLimit":1}}'
   aws ec2 modify-launch-template --launch-template-name shopfront-dev-ecs --default-version '$Latest'
   ```

2. Start an instance refresh; the capacity provider's managed draining moves tasks off each instance before termination.

   ```bash
   aws autoscaling start-instance-refresh --auto-scaling-group-name shopfront-dev-ecs \
     --preferences '{"MinHealthyPercentage":90,"InstanceWarmup":300,"SkipMatching":true,"AutoRollback":true,"CheckpointPercentages":[25,100],"CheckpointDelay":600}'
   aws autoscaling describe-instance-refreshes --auto-scaling-group-name shopfront-dev-ecs --query 'InstanceRefreshes[0].{status:Status,pct:PercentageComplete,reason:StatusReason}'
   ```

3. Watch the cluster: new instances register with the new agent version, old ones go `DRAINING` then disappear; services stay at desired count.

   ```bash
   watch -n 20 "aws ecs list-container-instances --cluster $CLUSTER --status DRAINING --query 'length(containerInstanceArns)'; aws ecs describe-services --cluster $CLUSTER --services orders catalog fulfillment-worker --query 'services[*].[serviceName,runningCount,desiredCount]' --output text"
   ```

4. Pause at the 25% checkpoint (the `CheckpointDelay`), check error rates and stopped-task reasons (`ecs-task-stopped-reasons.md`), then let it continue.

Agent-only update on AL2023 without an AMI change (rarely needed; the AMI rotation is the normal path):
`aws ecs update-container-agent --cluster $CLUSTER --container-instance <arn>` (agent must be ≥ 1.0 and the instance must have `ecs-init`).

## Steps: Fargate platform version

Nothing to rotate: AWS retires old platform versions and moves `LATEST`. Keep `PlatformVersion: LATEST`
(the lab does). When a new platform version changes behaviour (ephemeral storage, kernel, IMDS),
AWS announces it; test by deploying the service with the explicit new version in staging:

```bash
aws ecs update-service --cluster shopfront-staging --service orders --platform-version 1.4.0 --force-new-deployment
```

Tasks are replaced on the next deployment or when AWS retires the platform revision underneath
(you see `ServiceSchedulerInitiated` stops with a platform-retirement reason and an AWS Health event
first). Services with `MinimumHealthyPercent 100` see no capacity dip.

## Steps: ECS Managed Instances

AWS owns the AMI and rotates instances (patching cadence and instance lifetime are managed). Your
levers are on the capacity provider: instance requirements (families, sizes, architectures, Spot),
`propagateTags`, and the drain settings. Observe rotations through the ECS events log group and EC2
Health events; keep `MinimumHealthyPercent`/PDB-equivalents (desired count ≥ 2) so a rotation never
reduces capacity below your floor.

```bash
aws ecs describe-capacity-providers --capacity-providers shopfront-dev-managed --query 'capacityProviders[0].{status:status,managedInstances:managedInstancesProvider}'
aws logs start-query --log-group-name /shopfront/dev/ecs-events --start-time "$(date -u -v-24H +%s)" --end-time "$(date -u +%s)" \
  --query-string 'fields @timestamp, detail.eventName, detail.reason | filter `detail-type` = "ECS Service Action" | sort @timestamp desc | limit 20'
```

## Verify

```bash
aws ecs list-container-instances --cluster $CLUSTER --query containerInstanceArns --output text | tr '\t' '\n' | xargs -I{} aws ecs describe-container-instances --cluster $CLUSTER --container-instances {} --query 'containerInstances[0].[versionInfo.agentVersion,attributes[?name==`ecs.ami-id`].value|[0],agentConnected]' --output text | sort | uniq -c   # one line
aws ecs describe-services --cluster $CLUSTER --services orders catalog fulfillment-worker --query 'services[*].[serviceName,runningCount,desiredCount,deployments[0].rolloutState]' --output table
aws cloudwatch describe-alarms --alarm-name-prefix shopfront-dev --state-value ALARM --query 'MetricAlarms[*].AlarmName'
```

## Rollback

- Instance refresh: `AutoRollback: true` reverts to the previous launch template version when the health checks fail; manually: `aws autoscaling rollback-instance-refresh` or start a new refresh with the previous version as default.
- Fargate: pin the previous `platformVersion` on the service and force a new deployment.
- Managed Instances: not applicable (AWS rotation); open a case if a rotation caused failures.

## Related

- [upgrade-breakage.md](../incidents/upgrade-breakage.md), [ecs-task-stopped-reasons.md](../incidents/ecs-task-stopped-reasons.md)
- Mechanism: [03 · L300 ECS agent, Fargate platform versions, Managed Instances internals](../../hub/03-ecs/L300-ecs-internals.md), [03 · L200 capacity providers and managed draining](../../hub/03-ecs/L200-task-definitions-services-and-scaling.md), [01 · L300 why ECS EC2 still uses Docker Engine](../../hub/01-container-fundamentals/L300-runtimes-and-the-kernel.md)
- Reference: [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md)
