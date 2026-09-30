# AccessDenied and missing credentials inside containers: task role vs execution role, IRSA, Pod Identity, IMDS

**Applies to:** both · **Severity guide:** SEV2 when a service cannot reach its queue/bucket/database secret; SEV1 when it blocks every request · **Time to first fix:** 5–20 min

## Symptoms

- SDK errors: `AccessDeniedException`, `AccessDenied: User: arn:aws:sts::123456789012:assumed-role/<role>/<session> is not authorized to perform: sqs:SendMessage on resource: ...`.
- Credential chain errors: `Unable to locate credentials`, `NoCredentialProviders: no valid providers in chain`, `CredentialsProviderError: Could not load credentials from any providers`, `Error retrieving credentials from container metadata`.
- Web identity errors: `WebIdentityErr: failed to retrieve credentials ... InvalidIdentityToken` / `Not authorized to perform sts:AssumeRoleWithWebIdentity`.
- Pod Identity: `Error: Unable to retrieve credentials from the EKS Pod Identity agent` / HTTP 4xx from `169.254.170.23`.
- The call works from your laptop with admin rights and fails from the container: the container has a different, smaller identity. That is the design working.

## Triage in five minutes

```bash
# 1. Which identity does the code actually have? Ask STS from inside the container.
kubectl -n shopfront exec deploy/orders -- env | grep -E 'AWS_(ROLE_ARN|WEB_IDENTITY_TOKEN_FILE|CONTAINER_CREDENTIALS_FULL_URI|CONTAINER_AUTHORIZATION_TOKEN_FILE|REGION)'
kubectl -n shopfront run awscli --rm -it --restart=Never --image=public.ecr.aws/aws-cli/aws-cli:2.37.6 \
  --overrides='{"spec":{"serviceAccountName":"orders","automountServiceAccountToken":false}}' -- sts get-caller-identity
aws ecs execute-command --cluster shopfront-dev --task <task-arn> --container orders --interactive \
  --command "sh -c 'env | grep AWS_CONTAINER; wget -qO- \"http://169.254.170.2\$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI\" | head -c 200'"
#   assumed-role/shopfront-dev-orders-task     -> right role, wrong permissions (branch P)
#   assumed-role/eksctl-...-NodeInstanceRole   -> the pod fell through to the NODE role: identity not injected (branch I)
#   no credentials at all                      -> no association/annotation, or IMDS blocked and nothing else configured (branch I)

# 2. Does the role allow the action on the resource? Simulate, do not guess.
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::123456789012:role/shopfront-dev-orders-task \
  --action-names sqs:SendMessage --resource-arns arn:aws:sqs:us-east-1:123456789012:shopfront-dev-orders-created \
  --query 'EvaluationResults[*].[EvalActionName,EvalDecision,MatchedStatements[*].SourcePolicyId]'
#   implicitDeny -> add the statement; explicitDeny -> an SCP, permissions boundary or resource policy denies

# 3. Resource policies and encryption (the second half of most denials)
aws sqs get-queue-attributes --queue-url <url> --attribute-names Policy KmsMasterKeyId
aws secretsmanager describe-secret --secret-id shopfront/dev/database-url --query '{kms:KmsKeyId,policy:ResourcePolicy}'
aws kms get-key-policy --key-id <key-id> --policy-name default --query Policy --output text | head -40

# 4. EKS identity plumbing
aws eks list-pod-identity-associations --cluster-name shopfront-dev --namespace shopfront --query 'associations[*].[serviceAccount,associationArn]'
aws eks describe-pod-identity-association --cluster-name shopfront-dev --association-id <id> --query 'association.{sa:serviceAccount,role:roleArn}'
kubectl -n kube-system get ds eks-pod-identity-agent -o wide 2>/dev/null || echo "pod identity agent add-on missing"
kubectl -n shopfront get sa orders -o jsonpath='{.metadata.annotations}'                      # IRSA annotation, if using IRSA
aws iam get-role --role-name shopfront-dev-eks-orders --query 'Role.AssumeRolePolicyDocument'   # trust: pods.eks.amazonaws.com (Pod Identity) or the OIDC provider (IRSA)

# 5. CloudTrail: the denied call with the exact principal and error
aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=SendMessage --max-results 5 \
  --query 'Events[*].[EventTime,Username,CloudTrailEvent]' --output text | grep -o '"errorMessage":"[^"]*"' | head
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **P1. Task/pod role lacks the action or resource** | step 2 `implicitDeny`; ARN typo (queue name, bucket prefix) | Add the statement, scoped to the resource (the lab roles are in `02-cluster.yaml` and `eksctl-standard.yaml`) |
| **P2. Permission used the wrong role: execution vs task (ECS)** | The app is denied on Secrets Manager (that is the execution role's job at start) or the agent is denied on ECR (execution role) while you edited the task role | Execution role: ECR pull, logs, `secrets[]`, `environmentFiles`. Task role: everything your code calls. Never merge them (hub/06 L200 §2.1) |
| **P3. Explicit deny from SCP / permissions boundary / resource policy** | `explicitDeny` in the simulation; message mentions `with an explicit deny in a service control policy` | Fix at the source; resource policies (queue, bucket, secret) must allow the role or the account principal |
| **P4. KMS: the data is encrypted with a CMK the role cannot use** | Access to the queue/secret/bucket allowed, but `KMS.AccessDeniedException` or `kms:Decrypt` denied; `kms:ViaService` condition | Grant `kms:Decrypt`/`GenerateDataKey` on the key to the role (key policy or grant) with `kms:ViaService` for the service |
| **P5. Session tags / ABAC condition not met** | Pod Identity sessions carry tags (`eks-cluster-arn`, `kubernetes-namespace`, ...); a policy conditions on `aws:PrincipalTag` that IRSA sessions do not have | Align the policy with the identity mechanism; `aws sts get-caller-identity` shows the ARN, CloudTrail shows the tags |
| **I1. Pod Identity association missing or on the wrong SA/namespace** | step 4 lists no association for `shopfront/orders`; caller is the node role | `aws eks create-pod-identity-association` (or `addons/pod-identity-associations.sh`); pods created before the association need a restart to get the env injected |
| **I2. Pod Identity agent not installed / not on the node** | No `eks-pod-identity-agent` DaemonSet; pods have `AWS_CONTAINER_CREDENTIALS_FULL_URI` but `169.254.170.23` refuses | Install the `eks-pod-identity-agent` add-on; on Fargate profiles Pod Identity is not supported: use IRSA |
| **I3. Pod Identity trust policy wrong** | `describe-pod-identity-association` fine but STS denies `AssumeRoleForPodIdentity` | Trust must allow `pods.eks.amazonaws.com` for `sts:AssumeRole` **and** `sts:TagSession` |
| **I4. IRSA: trust `sub` or `aud` mismatch** | `Not authorized to perform sts:AssumeRoleWithWebIdentity`; trust condition `system:serviceaccount:shopfront:orders` vs the actual namespace/SA; `aud` must be `sts.amazonaws.com` | Fix the condition; OIDC provider must exist for this cluster's issuer (`aws eks describe-cluster --query cluster.identity.oidc.issuer`) |
| **I5. IRSA: token expired or projected volume missing** | `InvalidIdentityToken`; `AWS_WEB_IDENTITY_TOKEN_FILE` not set: the pod was created before the annotation, or the SA annotation has a typo | Restart the pods; check `eks.amazonaws.com/role-arn` spelling; the mutating webhook only acts at pod creation |
| **I6. Old SDK ignores the container credential provider** | Very old SDK versions predate `AWS_CONTAINER_CREDENTIALS_FULL_URI` + authorization token file (Pod Identity) | Upgrade the SDK to a version that supports EKS Pod Identity (2023-11+ releases of all SDKs) |
| **I7. Application configured a static profile or key that overrides the chain** | `AWS_PROFILE`, `AWS_ACCESS_KEY_ID` in the env, `~/.aws/credentials` baked into the image | Remove them; the chain must reach the container provider |
| **I8. Node role used by accident, then blocked by hop limit 1** | Pods without an identity mechanism time out on `169.254.169.254` | Correct behaviour: give the pod its own identity (I1/I4) rather than reopening IMDS |
| **I9. ECS: `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` present but 169.254.170.2 unreachable** | `awsvpc` task with a proxy/`HTTP_PROXY` set and no `NO_PROXY` for `169.254.170.2`; custom `iptables` in the container | `NO_PROXY=169.254.170.2,169.254.169.254`; do not touch link-local routes in the container |
| **I10. ECS EC2: `ECS_AWSVPC_BLOCK_IMDS=true` and a legacy library reads IMDS** | Task role exists but the library ignores the container provider | Upgrade the library; the block is right |
| **Cross-account: `sts:AssumeRole` into the other account denied** | Two-hop pattern; trust in account B missing the task/pod role | Add the role ARN (not the account root) to B's trust policy; `ExternalId` if required |
| **Region mismatch** | `AWS_REGION` unset or wrong: calls go to the wrong Region where the queue does not exist (`AWS.SimpleQueueService.NonExistentQueue`) | Set `AWS_REGION` (the lab config does); use full queue URLs |

## Verify the fix

```bash
kubectl -n shopfront rollout restart deploy/orders && kubectl -n shopfront rollout status deploy/orders
kubectl -n shopfront run awscli --rm -it --restart=Never --image=public.ecr.aws/aws-cli/aws-cli:2.37.6 \
  --overrides='{"spec":{"serviceAccountName":"orders"}}' -- sqs get-queue-attributes --queue-url <url> --attribute-names QueueArn
aws ecs execute-command --cluster shopfront-dev --task <task-arn> --container orders --interactive --command "node -e \"require('@aws-sdk/client-sts')\" && echo sdk-ok"
# Then the application path: POST /orders returns 201 and the queue depth increments.
```

## Prevent it

- One role per workload, named after it, with the resources spelled out; no wildcard resources except where the API forces it (`ecr:GetAuthorizationToken`).
- Pod Identity by default on EKS; IRSA only for Fargate profiles and charts that need it. Associations declared in the cluster config (`eksctl-standard.yaml`) next to the workloads.
- CI check: `iam simulate-principal-policy` for each role against the actions the service needs (hub/11 L200 §2.5).
- Alarm on CloudTrail `errorCode = AccessDenied` for the workload roles (metric filter on the CloudTrail log group).

## Related

- Mechanism: [06 L200 IAM for containers](../../hub/06-identity-and-security/L200-iam-for-containers.md), [04 L300 authentication flow, OIDC issuer, Pod Identity agent](../../hub/04-eks/L300-eks-internals-and-operations.md), [03 L300 task metadata and credentials endpoint](../../hub/03-ecs/L300-ecs-internals.md), [05 L300 link-local addresses](../../hub/05-networking/L300-container-networking-internals.md)
- Neighbours: [eks-auth-and-access.md](eks-auth-and-access.md) (human access, `kubectl`), [image-pull-failures.md](image-pull-failures.md) (execution/node role side)
- Reference: [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md)
