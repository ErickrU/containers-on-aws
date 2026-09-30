# Image pull failures: ImagePullBackOff, CannotPullContainerError, ECR 403, pulls that hang

**Applies to:** both · **Severity guide:** SEV2 when a deployment cannot roll out, SEV1 when tasks are being replaced and none can start · **Time to first fix:** 5–15 min once the cause is known

## Symptoms

- EKS: pod status `ErrImagePull` then `ImagePullBackOff`; `kubectl describe pod` shows `Failed to pull image ... : rpc error: code = Unknown desc = failed to pull and unpack image ... 403 Forbidden` or `... dial tcp ... i/o timeout` or `not found`.
- ECS: task `STOPPED`, `stopCode: TaskFailedToStart`, `stoppedReason: CannotPullContainerError: ...` (`pull access denied`, `no basic auth credentials`, `manifest unknown`, `context deadline exceeded`, `ResourceInitializationError: unable to pull secrets or registry auth`).
- Deployments stuck at old revision; ECS circuit breaker trips after repeated launch failures.
- Pull works from your laptop but not from the cluster: almost always network path or identity, not the image.

## Triage in five minutes

```bash
# 1. Read the exact message. The words decide the branch below.
kubectl -n shopfront describe pod <pod> | sed -n '/Events:/,$p'
aws ecs describe-tasks --cluster shopfront-dev --tasks <task-arn> \
  --query 'tasks[0].{stopCode:stopCode,reason:stoppedReason,containers:containers[*].{name:name,reason:reason}}'
#    "403 Forbidden" / "pull access denied" / "no basic auth"  -> identity (branch A)
#    "manifest unknown" / "not found" / "MANIFEST_UNKNOWN"     -> the reference (branch B)
#    "i/o timeout" / "context deadline exceeded" / "no such host" -> network path (branch C)
#    "toomanyrequests" / "429" / "ThrottlingException"          -> rate limits (branch D)
#    "ResourceInitializationError ... secrets"                  -> execution role or endpoints (branch A/C)

# 2. Does the reference exist, exactly as written?
aws ecr describe-images --repository-name shopfront/orders --image-ids imageTag=sha-1a2b3c4   # or imageDigest=sha256:...
#    ImageNotFoundException -> branch B

# 3. Which identity pulls? (EKS: node role or kubelet credential provider; ECS: EXECUTION role, not task role)
aws ecs describe-task-definition --task-definition shopfront-dev-orders --query 'taskDefinition.executionRoleArn'
aws eks describe-nodegroup --cluster-name shopfront-dev --nodegroup-name general-arm64 --query 'nodegroup.nodeRole'
aws iam simulate-principal-policy --policy-source-arn <role-arn> \
  --action-names ecr:GetAuthorizationToken ecr:BatchGetImage ecr:GetDownloadUrlForLayer ecr:BatchCheckLayerAvailability \
  --resource-arns arn:aws:ecr:us-east-1:123456789012:repository/shopfront/orders --query 'EvaluationResults[*].[EvalActionName,EvalDecision]'
#    any "implicitDeny"/"explicitDeny" -> branch A

# 4. Can the subnet reach ECR? (private subnets need NAT or the three endpoints: ecr.api, ecr.dkr, S3 gateway)
aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=<vpc-id> --query 'VpcEndpoints[*].[ServiceName,State]'
aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=<subnet-id> --query 'RouteTables[*].Routes[*].[DestinationCidrBlock,NatGatewayId,GatewayId]'
#    no NAT route and missing endpoints -> branch C

# 5. Look at the puller's own log (EKS nodes)
kubectl debug node/<node> -it --image=public.ecr.aws/amazonlinux/amazonlinux:2023 -- chroot /host journalctl -u containerd -u kubelet --since -10m | grep -i -E 'pull|ecr|auth' | tail -20
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **A1. Execution role lacks ECR permissions (ECS)** | step 3 shows deny on `ecr:BatchGetImage`/`GetDownloadUrlForLayer`; message `pull access denied` | Attach `AmazonECSTaskExecutionRolePolicy` or the scoped statements in `labs/ecs/cloudformation/02-cluster.yaml`; `ecr:GetAuthorizationToken` must be on `Resource: "*"` |
| **A2. Node role lacks ECR permissions (EKS)** | step 3 on the node role; Karpenter/Auto Mode nodes use their own role | Attach `AmazonEC2ContainerRegistryPullOnly` (or `ReadOnly`) to the node role / `EC2NodeClass.spec.role` / Auto Mode node role |
| **A3. Cross-account repository without a repository policy** | image in account B, puller in account A; 403 despite correct IAM | Add a repository policy in B allowing A's role (or `aws:PrincipalOrgID`) for `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`, `ecr:BatchCheckLayerAvailability`; Fargate also needs `ecr:GetAuthorizationToken` in A |
| **A4. Repository policy or endpoint policy denies** | `aws ecr get-repository-policy`; `ecr.dkr` endpoint policy with a `Deny` or restricted principals | Widen the policy to the puller's role; endpoint policies apply to every pull through that endpoint |
| **A5. Private registry (Docker Hub, GHCR) credentials missing or expired** | `no basic auth credentials`; ECS `repositoryCredentials` or K8s `imagePullSecrets` absent | ECS: `repositoryCredentials.credentialsParameter` (Secrets Manager) on the container; EKS: `imagePullSecrets` on the ServiceAccount; better: ECR pull-through cache so the cluster pulls from ECR only (hub/02 L300 §2.1) |
| **A6. Tag immutability blocked the push, deploy references a tag that never landed** | `ImageTagAlreadyExistsException` in CI logs | Deploy by digest; keep immutability on |
| **B1. Wrong tag, digest or registry hostname** | `describe-images` says not found; typo in region or account in the URI | Fix the reference; prefer `@sha256:` digests emitted by CI (`steps.build.outputs.digest`) |
| **B2. Lifecycle policy deleted the image that services still reference** | CloudTrail `BatchDeleteImage` by `ecr.amazonaws.com`; tag gone | Restore by re-pushing from source or another registry; change the lifecycle rule to keep tagged prefixes `sha-` for N images and exclude `latest`; protect with replication (hub/02 L200 §2.1, L400 §2.5) |
| **B3. Multi-arch mismatch** | `no match for platform in manifest`; ARM64 Fargate/Graviton node, amd64-only image | Build `linux/amd64,linux/arm64` (labs/pipelines) or pin `runtimePlatform`/`nodeSelector` to the architecture you built |
| **C1. Private subnet without NAT or endpoints** | step 4; `i/o timeout` to `*.dkr.ecr.*.amazonaws.com` or to S3 (layers) | Add `com.amazonaws.<region>.ecr.api`, `.ecr.dkr` interface endpoints (private DNS on) and the **S3 gateway** endpoint (layers are served from S3); or a NAT route. Fargate also needs `logs` and `secretsmanager` endpoints (hub/05 L200 §2.6) |
| **C2. Endpoint security group blocks 443 from the node/task subnets** | `dial tcp <10.x endpoint ip>:443: i/o timeout` | Allow TCP 443 from the VPC CIDR (or the node/task security groups) on the endpoint security group |
| **C3. DNS: private hosted zone or resolver rule hijacks `amazonaws.com`** | `no such host` or resolution to a public IP that the private subnet cannot reach | Fix the resolver rule; endpoints with private DNS enabled must resolve to endpoint ENIs |
| **C4. Egress firewall / proxy denies ECR or S3 hostnames** | Network Firewall/proxy logs show blocks | Allow `*.dkr.ecr.<region>.amazonaws.com`, `api.ecr.<region>.amazonaws.com`, `prod-<region>-starport-layer-bucket.s3.<region>.amazonaws.com`, `*.s3.<region>.amazonaws.com` |
| **D1. ECR pull throttling** | `ThrottlingException: Rate exceeded` on `GetAuthorizationToken`/`BatchGetImage`; big scale-out at once | Stagger rollouts (`maxSurge`), pre-pull with a DaemonSet, raise ECR quotas, keep the token cached (kubelet credential provider does; ECS agent does) (hub/02 L300 §2.3) |
| **D2. Docker Hub rate limit** | `toomanyrequests: You have reached your pull rate limit` | Pull-through cache with Docker Hub credentials in Secrets Manager; never pull public upstreams directly from a fleet |
| **E1. Image too large for the start budget** | Fargate `context deadline exceeded` after minutes; EKS pull takes longer than the startup probe budget | Slim the image (distroless, multi-stage, hub/01 L200), enable SOCI lazy loading (Fargate), raise `startupProbe.failureThreshold` |
| **E2. Node disk pressure evicts images mid-pull** | `no space left on device`; `kubectl describe node` shows `DiskPressure` | Larger root volume in the launch template / `EC2NodeClass.blockDeviceMappings`; `imageGCHighThresholdPercent`; see node-not-ready |

## Verify the fix

```bash
kubectl -n shopfront rollout status deploy/orders --timeout=5m && kubectl -n shopfront get pods -l app.kubernetes.io/name=orders
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].{running:runningCount,desired:desiredCount,events:events[0].message}'
# From a node or a debug pod, prove the pull path end to end:
kubectl -n shopfront run pulltest --rm -it --restart=Never --image=123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders:sha-1a2b3c4 --command -- node --version
```

## Prevent it

- Deploy by digest; tags are pointers that can move or vanish.
- Pull-through cache for every public upstream, replication for every Region you deploy to (hub/02 L300, L400).
- The three ECR endpoints plus S3 gateway in every private VPC that runs containers; test with a scheduled canary pull.
- Lifecycle policies that keep the last N `sha-` images and never touch images referenced by a running service (`aws ecr describe-images` in a pre-deletion check, or simply generous counts).
- Alarm on ECS `SERVICE_TASK_START_IMPAIRED` service events and on the `CannotPullContainerError` string in the ECS events log group (`labs/ecs/cloudformation/05-observability.yaml`).

## Related

- Mechanism: [02 · ECR L200](../../hub/02-ecr/L200-lifecycle-scanning-access-and-endpoints.md), [L300 pull-through cache and limits](../../hub/02-ecr/L300-pull-through-cache-replication-and-limits.md), [01 L300 image pull mechanics](../../hub/01-container-fundamentals/L300-runtimes-and-the-kernel.md)
- Neighbours: [ecs-task-stopped-reasons.md](ecs-task-stopped-reasons.md), [iam-accessdenied-from-containers.md](iam-accessdenied-from-containers.md), [node-not-ready.md](node-not-ready.md)
- Reference: [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md), [quotas and limits](../../reference/quotas-and-limits.md)
