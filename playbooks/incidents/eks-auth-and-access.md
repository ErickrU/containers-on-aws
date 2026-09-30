# kubectl Unauthorized, "You must be logged in to the server", access entries and kubeconfig problems

**Applies to:** EKS · **Severity guide:** SEV3 for one engineer; SEV2 when CI/CD or the on-call role is locked out; SEV1 when the cluster creator is gone and nobody has access · **Time to first fix:** 5–15 min

## Symptoms

- `kubectl get pods` returns `error: You must be logged in to the server (Unauthorized)` or `the server has asked for the client to provide credentials`.
- `Error from server (Forbidden): pods is forbidden: User "arn:aws:sts::123456789012:assumed-role/Dev/alice" cannot list resource "pods" in API group "" in the namespace "shopfront"` (authenticated, not authorised).
- `dial tcp: lookup AAAA...gr7.us-east-1.eks.amazonaws.com: no such host` or `i/o timeout` (network, not auth).
- `aws eks get-token` fails (`ExpiredToken`, `could not get token: AccessDenied`) or uses the wrong profile.
- Argo CD / CI service account suddenly `Unauthorized` after a cluster change.

## Triage in five minutes

```bash
# 1. Who am I to AWS, and what does kubeconfig do with it?
aws sts get-caller-identity
kubectl config view --minify -o jsonpath='{.users[0].user.exec}'    # exec: aws eks get-token --cluster-name ... (--profile? --role-arn?)
aws eks get-token --cluster-name shopfront-dev --query 'status.token' --output text | cut -c1-20; echo ...

# 2. Can I reach the endpoint at all? (Unauthorized needs a connection first)
aws eks describe-cluster --name shopfront-dev --query 'cluster.{endpoint:endpoint,public:resourcesVpcConfig.endpointPublicAccess,private:resourcesVpcConfig.endpointPrivateAccess,cidrs:resourcesVpcConfig.publicAccessCidrs,mode:accessConfig.authenticationMode}'
curl -sk -m 5 "$(aws eks describe-cluster --name shopfront-dev --query cluster.endpoint --output text)/version" | head -3
#   connection refused / timeout -> endpoint access (public CIDR allowlist, private-only from outside the VPC), not auth
#   401 JSON -> the endpoint works; identity mapping is the problem

# 3. Is my principal mapped? (access entries, or the legacy aws-auth ConfigMap)
aws eks list-access-entries --cluster-name shopfront-dev
aws eks describe-access-entry --cluster-name shopfront-dev --principal-arn arn:aws:iam::123456789012:role/Dev --query 'accessEntry.{k8sGroups:kubernetesGroups,type:type,user:username}'
aws eks list-associated-access-policies --cluster-name shopfront-dev --principal-arn arn:aws:iam::123456789012:role/Dev --query 'associatedAccessPolicies[*].[policyArn,accessScope]'
kubectl -n kube-system get configmap aws-auth -o yaml 2>/dev/null | sed -n '/mapRoles/,/mapUsers/p'     # only if authenticationMode includes CONFIG_MAP

# 4. Authenticated but Forbidden: RBAC
kubectl auth whoami                       # Kubernetes 1.30+: the username and groups the authenticator produced
kubectl auth can-i list pods -n shopfront
kubectl auth can-i --list -n shopfront | head -20

# 5. Authenticator log on the control plane (enable "authenticator" logging)
aws logs filter-log-events --log-group-name /aws/eks/shopfront-dev/cluster --log-stream-name-prefix authenticator \
  --start-time "$(( $(date +%s) - 900 ))000" --filter-pattern '"access denied"' --query 'events[*].message' --output text | tail -5
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **Principal has no access entry** (`Unauthorized`) | step 3: not listed; authenticator log `access denied` with your ARN | `aws eks create-access-entry --cluster-name shopfront-dev --principal-arn <role-arn> --type STANDARD` then `associate-access-policy` with `AmazonEKSViewPolicy`/`EditPolicy`/`AdminPolicy`/`ClusterAdminPolicy` and an access scope (cluster or namespaces) |
| **Assumed-role ARN vs role ARN** | kubeconfig uses `--role-arn` or your session ARN includes a path/session; access entries take the **role ARN without session** and paths are stripped | Map `arn:aws:iam::123456789012:role/Dev` (no `/path/`, no session); for IAM Identity Center use the permission-set role `AWSReservedSSO_*` ARN (path removed) |
| **Wrong AWS profile / expired SSO** | `get-caller-identity` shows another account or `ExpiredToken` | `aws sso login --profile ...`; set `--profile` in the kubeconfig `exec.args` or `AWS_PROFILE`; `aws eks update-kubeconfig --name shopfront-dev --profile <p>` |
| **Cluster creator's admin permission missing** (`bootstrapClusterCreatorAdminPermissions: false`) and no other entry | Nobody has admin; `list-access-entries` shows only node entries | Any IAM principal with `eks:CreateAccessEntry` on the cluster can add an entry: access entries are IAM-authorised, so the lock-out is recoverable without the creator (unlike `aws-auth` days) |
| **Authentication mode is `CONFIG_MAP` only and you edited access entries** (or vice versa) | `authenticationMode` in step 2 | Switch to `API_AND_CONFIG_MAP` then `API` (one way); edit whichever the mode honours |
| **Legacy `aws-auth` broken** (YAML indentation, wrong `rolearn`, path in ARN) | authenticator log parse errors; everyone locked out | Fix through an identity that still works (the creator, or `eks:CreateAccessEntry` in `API_AND_CONFIG_MAP` mode); move to access entries |
| **Authenticated, Forbidden: RBAC** | `kubectl auth whoami` shows groups; `can-i` false | Bind a Role/ClusterRole to the group (`kubernetesGroups` on the entry) or associate an access policy with a namespace scope |
| **Access policy scope excludes the namespace** | `accessScope.namespaces` lists others | Associate with the right namespaces or cluster scope |
| **Private endpoint only, running from outside the VPC** | step 2 timeout; `publicAccess: false` | Use a bastion/VPN/Cloud9/CloudShell in-VPC, or enable public access with a CIDR allowlist |
| **Public access CIDR allowlist excludes you** | `publicAccessCidrs` does not include your IP | Add the CIDR (`update-cluster-config --resources-vpc-config publicAccessCidrs=...`) or use the private path |
| **Nodes `Unauthorized` after a node role change** | Node entry type `EC2_LINUX` missing for the new role; new nodes NotReady | Create an access entry `--type EC2_LINUX` for the node role |
| **Pod Identity or IRSA service account for tooling (Argo CD, CI) lost its mapping** | CI role ARN changed; entry stale | Update the entry; CI should use its own role with `AmazonEKSEditPolicy` scoped to its namespaces |
| **Token clock skew** | `get-token` works but API says `Unauthorized`; laptop clock wrong | Sync the clock; presigned STS URLs are time-bound (15 min) |
| **Cluster deleted/recreated: kubeconfig has the old CA/endpoint** | `x509: certificate signed by unknown authority`, `no such host` | `aws eks update-kubeconfig --name shopfront-dev` |

## Verify the fix

```bash
aws eks update-kubeconfig --name shopfront-dev --alias shopfront-dev
kubectl auth whoami && kubectl auth can-i list pods -n shopfront && kubectl -n shopfront get pods | head -3
aws eks describe-access-entry --cluster-name shopfront-dev --principal-arn <role-arn> --query 'accessEntry.accessEntryArn'
```

## Prevent it

- `authenticationMode: API`; access entries in IaC (`accessConfig.accessEntries` in `eksctl-standard.yaml`), at least two admin principals (a break-glass role plus the platform team role).
- Access policies with namespace scopes for developers; cluster admin for platform only; no `system:masters` group membership. <!-- term-ok -->
- Authenticator logs on; alarm on repeated `access denied` from unexpected principals.
- Kubeconfig generation scripted (`aws eks update-kubeconfig --role-arn` for the standard role) so nobody hand-edits `exec` blocks.

## Related

- Mechanism: [04 L200 authentication: access entries, access policies, RBAC](../../hub/04-eks/L200-cluster-components-and-add-ons.md), [04 L300 the authentication flow](../../hub/04-eks/L300-eks-internals-and-operations.md), [06 L200 human access](../../hub/06-identity-and-security/L200-iam-for-containers.md)
- Neighbours: [iam-accessdenied-from-containers.md](iam-accessdenied-from-containers.md) (workload identity), [node-not-ready.md](node-not-ready.md) (node role entries)
- Reference: [CLI cheatsheet](../../reference/cli-cheatsheet.md)
