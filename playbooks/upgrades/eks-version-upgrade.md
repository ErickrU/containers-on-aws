# EKS Kubernetes version upgrade: control plane → add-ons → nodes

**Applies to:** EKS (standard clusters; Auto Mode still needs steps 1, 2 and 5, AWS does the node part) · **Severity guide:** planned change; treat as SEV3 with a rollback window for nodes and add-ons · **Time to first fix:** 2–4 h per cluster per minor version, most of it waiting

One minor version per run (1.35 → 1.36). The control plane upgrade itself cannot be rolled back, so
the pre-flight is where the safety lives. As of September 2026 the standard-support versions are
1.34–1.36 and extended support (with the extended-support hourly fee) covers 1.31–1.33; check
`docs/FACTS-2026-09.md` and the EKS version calendar before planning
([04 · L300 upgrade mechanics](../../hub/04-eks/L300-eks-internals-and-operations.md), [04 · L400 cadences for a fleet](../../hub/04-eks/L400-eks-at-scale.md)).

## Preconditions (pre-flight, the day before)

```bash
export CLUSTER=shopfront-dev TARGET=1.36
# 1. Current versions and skew: nodes must be within 3 minors of the target (kubelet n-3), add-ons compatible
aws eks describe-cluster --name $CLUSTER --query 'cluster.{version:version,platform:platformVersion,mode:accessConfig.authenticationMode}'
kubectl get nodes -o custom-columns=NAME:.metadata.name,KUBELET:.status.nodeInfo.kubeletVersion | sort -k2 | uniq -c -f1
for a in $(aws eks list-addons --cluster-name $CLUSTER --query addons --output text); do
  printf '%-34s current=%s  target-latest=%s\n' "$a" \
    "$(aws eks describe-addon --cluster-name $CLUSTER --addon-name $a --query addon.addonVersion --output text)" \
    "$(aws eks describe-addon-versions --kubernetes-version $TARGET --addon-name $a --query 'addons[0].addonVersions[0].addonVersion' --output text)"
done

# 2. EKS Upgrade Insights: deprecated API usage and known blockers, computed by AWS from audit logs
aws eks list-insights --cluster-name $CLUSTER --filter kubernetesVersions=$TARGET --query 'insights[*].[name,insightStatus.status,insightStatus.reason]' --output table
aws eks describe-insight --cluster-name $CLUSTER --id <id> --query 'insight.{recommendation:recommendation,resources:resources[*].[kubernetesResourceUri,insightStatus.status]}'

# 3. Deprecated APIs in git (what will be applied after the upgrade), and live usage
pluto detect-files -d labs/eks/manifests -o wide --target-versions k8s=v$TARGET.0     # or: kubent
kubectl get --raw /metrics | grep '^apiserver_requested_deprecated_apis' | grep 'removed_release="'$TARGET'"'

# 4. Workload readiness: PDBs allow evictions, replicas >= 2, spread constraints not DoNotSchedule with 1 zone free
kubectl get pdb -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed | awk '$3==0'
kubectl get deploy -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,REPLICAS:.spec.replicas | awk '$3<2'

# 5. Controllers' compatibility matrices for the target version: load balancer controller, Karpenter, KEDA, Argo, Cilium, ESO
#    (release notes; the lab pins are in labs/eks/addons/README.md). Note the versions you will move to in step 3.

# 6. Capacity for the node roll: +25% instances during updateConfig.maxUnavailablePercentage=25; IPs in subnets; quotas
aws ec2 describe-subnets --filters Name=tag:alpha.eksctl.io/cluster-name,Values=$CLUSTER --query 'Subnets[*].[AvailabilityZone,AvailableIpAddressCount]'

# 7. Free IPs for the control plane ENIs (at least 5 per subnet the cluster uses) and a recent Velero/etcd-independent backup if you keep state in-cluster
# 8. Staging cluster upgraded with the same steps first; game-day style observers for prod
```

Abort the plan if: any insight is `ERROR`, deprecated APIs are still served to clients, a controller has
no compatible release, or any PDB has `disruptionsAllowed 0` for a workload you cannot fix now.

## Steps

### 1. Control plane (20–40 min, API server stays available but new connections may blip)

```bash
aws eks update-cluster-version --name $CLUSTER --kubernetes-version $TARGET
aws eks describe-update --name $CLUSTER --update-id <update-id> --query 'update.{status:status,errors:errors}'
aws eks wait cluster-active --name $CLUSTER
kubectl version -o json | jq -r '.serverVersion.gitVersion'
```

During the rolling replacement of API server instances, controllers reconnect on their own; watch
`kube-system` for restarts, nothing else should change.

### 2. Managed add-ons, in this order

kube-proxy first (it must match the API server minor), then VPC CNI, then CoreDNS, then the rest.
Use the version from the pre-flight table and `PRESERVE` so `configurationValues` in git remain the truth.

```bash
for a in kube-proxy vpc-cni coredns eks-pod-identity-agent aws-ebs-csi-driver metrics-server amazon-cloudwatch-observability; do
  v=$(aws eks describe-addon-versions --kubernetes-version $TARGET --addon-name $a --query 'addons[0].addonVersions[0].addonVersion' --output text)
  echo "== $a -> $v"
  aws eks update-addon --cluster-name $CLUSTER --addon-name $a --addon-version "$v" --resolve-conflicts PRESERVE
  aws eks wait addon-active --cluster-name $CLUSTER --addon-name $a
done
kubectl -n kube-system rollout status ds/aws-node ds/kube-proxy deploy/coredns
```

Re-apply CoreDNS configuration if the add-on replaced it (`coredns-configuration-values.json`).

### 3. Self-installed controllers

Upgrade the load balancer controller, Karpenter, KEDA, ESO, Argo Rollouts/Argo CD, Cilium to the
versions noted in the pre-flight, one at a time, checking each reconciles ([addon-and-controller-upgrades.md](addon-and-controller-upgrades.md)).

### 4. Nodes

Managed node groups: EKS launches nodes with the new AMI, cordons and drains the old ones respecting
PDBs, `maxUnavailablePercentage` at a time.

```bash
aws eks update-nodegroup-version --cluster-name $CLUSTER --nodegroup-name general-arm64    # picks the latest AMI for the cluster version
#   custom launch template: bump the template version to one whose AMI id comes from
#   aws ssm get-parameter --name /aws/service/eks/optimized-ami/$TARGET/amazon-linux-2023/arm64/standard/recommended/image_id --query Parameter.Value --output text
aws eks describe-nodegroup --cluster-name $CLUSTER --nodegroup-name general-arm64 --query 'nodegroup.{status:status,version:version,release:releaseVersion,issues:health.issues}'
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,STATUS:.status.conditions[-1].type -w
```

Karpenter nodes: `amiSelectorTerms` `al2023@latest` picks the AMI for the **cluster** version; drift
detection replaces nodes gradually within the disruption budgets. Pin an alias (`al2023@v20260915`)
in production and bump it deliberately. Auto Mode replaces nodes on its own within its 21-day
lifetime and drift rules; nothing to do.

Stuck on `PodEvictionFailure`: fix the PDB, or `--force` the node group update to accept disruption.

### 5. Clients and tooling

`kubectl` within one minor of the server; `eksctl`, Helm charts and CI images that embed `kubectl`;
`aws eks update-kubeconfig` if the CA changed (it does not on upgrades).

## Verify

```bash
kubectl version -o json | jq -r '.serverVersion.gitVersion'
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,READY:.status.conditions[-1].status | sort -k2 | uniq -c -f1   # one version
kubectl -n kube-system get pods | grep -vE 'Running|Completed'
kubectl get --raw /metrics | grep -c '^apiserver_requested_deprecated_apis'    # 0
kubectl -n shopfront rollout status deploy/orders deploy/catalog deploy/fulfillment-worker
curl -fsS "http://$(kubectl -n shopfront get ingress shopfront -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')/products" | head -c 200
aws eks list-insights --cluster-name $CLUSTER --query 'insights[?insightStatus.status!=`PASSING`].name'
```

Leave the old node group / launch template version available for 24 h (the rollback window), then
delete it.

## Rollback

- Control plane: not possible; forward-fix only (this is why the pre-flight is long).
- Add-ons: `aws eks update-addon --addon-version <previous> --resolve-conflicts PRESERVE`.
- Managed node group: `update-nodegroup-version --release-version <previous>` or point the launch template back; nodes roll again.
- Controllers: `helm rollback <release> <revision>`.
- Workloads that broke on removed APIs: fix the manifests (there is no serving of removed APIs).

## Related

- [upgrade-breakage.md](../incidents/upgrade-breakage.md) when something did break; [addon-and-controller-upgrades.md](addon-and-controller-upgrades.md); [node-not-ready.md](../incidents/node-not-ready.md)
- Mechanism: [04 · L300 upgrade mechanics, API deprecations](../../hub/04-eks/L300-eks-internals-and-operations.md), [04 · L400 fleet upgrade cadences](../../hub/04-eks/L400-eks-at-scale.md), [04 · L100 versions and support policy](../../hub/04-eks/L100-kubernetes-and-eks-basics.md)
- Reference: [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md)
