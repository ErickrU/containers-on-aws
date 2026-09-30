# Add-on and controller upgrades: VPC CNI, CoreDNS, kube-proxy, load balancer controller, Karpenter, Cilium, KEDA, ESO, Argo

**Applies to:** EKS · **Severity guide:** planned, SEV3; a broken CNI or kube-proxy is SEV1 within minutes, so upgrade one component at a time with a rollback ready · **Time to first fix:** 10–30 min per component

Two kinds of components: **managed add-ons** (`aws eks update-addon`, versions published per
Kubernetes version, configuration through `configurationValues`) and **Helm-installed controllers**
(you own versions, values and CRDs). Order within a Kubernetes version: kube-proxy → VPC CNI →
CoreDNS → the rest; controllers after the managed add-ons. Compatibility is per Kubernetes minor:
check each project's matrix before touching anything ([04 · L200](../../hub/04-eks/L200-cluster-components-and-add-ons.md) §2.6).

## Preconditions

```bash
export CLUSTER=shopfront-dev K8S=$(aws eks describe-cluster --name $CLUSTER --query cluster.version --output text)
aws eks describe-addon-versions --kubernetes-version $K8S --query 'addons[*].{name:addonName,latest:addonVersions[0].addonVersion,default:addonVersions[?compatibilities[0].defaultVersion==`true`].addonVersion|[0]}' --output table
helm list -A -o json | python3 -c 'import json,sys; [print(f"{r[\"namespace\"]:20s}{r[\"name\"]:32s}{r[\"chart\"]:45s}{r[\"app_version\"]}") for r in json.load(sys.stdin)]'
# Staging first; a game-day observer for prod; PDBs allow disruption (kube-system components have their own)
kubectl get pdb -n kube-system
```

## Steps: managed add-ons

Always `--resolve-conflicts PRESERVE` when your `configurationValues` are the source of truth (they
are, in `eksctl-standard.yaml`); `OVERWRITE` resets fields you changed outside the add-on.

### VPC CNI (`vpc-cni`)

Upgrade one minor version at a time when the release notes say so; the DaemonSet rolls node by node
(pods on a node keep networking during the restart; new pods wait a few seconds).

```bash
aws eks describe-addon --cluster-name $CLUSTER --addon-name vpc-cni --query 'addon.{version:addonVersion,config:configurationValues}'
aws eks update-addon --cluster-name $CLUSTER --addon-name vpc-cni --addon-version v1.20.x-eksbuild.y --resolve-conflicts PRESERVE
aws eks wait addon-active --cluster-name $CLUSTER --addon-name vpc-cni
kubectl -n kube-system rollout status ds/aws-node
kubectl -n kube-system get ds aws-node -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
kubectl -n kube-system logs ds/aws-node -c aws-node --since=5m | grep -iE 'error|fail' | tail
# Prefix delegation and network policy still on?
kubectl -n kube-system get ds aws-node -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}' | grep -E 'PREFIX|NETWORK_POLICY'
```

### kube-proxy

Must match the control plane minor (n or n-1 is tolerated, not more). Mode changes (iptables → nftables)
are done by node replacement, not in place.

```bash
aws eks update-addon --cluster-name $CLUSTER --addon-name kube-proxy --addon-version v1.36.x-eksbuild.y --resolve-conflicts PRESERVE
kubectl -n kube-system rollout status ds/kube-proxy
kubectl -n shopfront run svc-test --rm -it --restart=Never --image=public.ecr.aws/docker/library/busybox:1.37 -- wget -qO- http://catalog:8081/healthz
```

### CoreDNS

```bash
aws eks update-addon --cluster-name $CLUSTER --addon-name coredns --addon-version v1.13.x-eksbuild.y --resolve-conflicts PRESERVE \
  --configuration-values file://labs/eks/addons/coredns-configuration-values.json
kubectl -n kube-system rollout status deploy/coredns
kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}' | head -20      # your Corefile survived?
# DNS check from a pod (see dns-failures.md verify section)
```

### Pod Identity agent, EBS CSI, metrics-server, CloudWatch Observability

Same command shape; the Pod Identity agent DaemonSet restart is invisible to pods (credentials are
cached by the SDKs and re-fetched on expiry); EBS CSI upgrades do not touch mounted volumes.

## Steps: Helm-installed controllers

General pattern: read the release notes for CRD changes and IAM changes, `helm diff` if you have the
plugin, upgrade with the pinned values file, watch the controller's log for one reconcile cycle.

### AWS Load Balancer Controller

```bash
helm repo update eks
# IAM first: new versions may need new actions; compare with the versioned policy document
curl -fsSL https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v3.5.0/docs/install/iam_policy.json -o /tmp/lbc.json
aws iam put-role-policy --role-name shopfront-dev-eks-aws-load-balancer-controller --policy-name AWSLoadBalancerControllerIAMPolicy --policy-document file:///tmp/lbc.json
# CRDs (IngressClassParams, TargetGroupBinding) ship in the chart's crds/; upgrade them explicitly across major versions
kubectl apply -k "github.com/aws/eks-charts/stable/aws-load-balancer-controller/crds?ref=master" # term-ok (upstream branch name)
helm upgrade aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f labs/eks/addons/aws-load-balancer-controller-values.yaml --set clusterName=$CLUSTER
kubectl -n kube-system rollout status deploy/aws-load-balancer-controller
kubectl -n kube-system logs deploy/aws-load-balancer-controller --since=5m | grep -iE 'error|failed' | tail
kubectl -n shopfront describe ingress shopfront | sed -n '/Events:/,$p'      # "Successfully reconciled"
```

Existing ALBs are not recreated by a controller upgrade unless the spec changes; the `group.name`
annotation keeps one ALB across Ingresses.

### Karpenter

Follow the upgrade guide **version by version** (CRD schema changes exist between minors). CRDs come
from the `karpenter-crd` chart; the controller is pinned to the node group so it never drains itself.

```bash
helm upgrade --install karpenter-crd oci://public.ecr.aws/karpenter/karpenter-crd --version 1.14.1 -n kube-system
helm upgrade karpenter oci://public.ecr.aws/karpenter/karpenter --version 1.14.1 -n kube-system -f labs/eks/addons/karpenter-values.yaml
kubectl -n kube-system rollout status deploy/karpenter
kubectl get nodepools,ec2nodeclasses -o wide           # Ready True
kubectl -n kube-system logs deploy/karpenter --since=5m | grep -iE 'error|drift|disrupt' | tail
```

A Karpenter upgrade may mark nodes as drifted (new AMI alias resolution, new defaults): disruption
budgets (`budgets` in the NodePool) bound how fast they roll; check them before the upgrade.

### Cilium

Pre-flight `cilium-pre-flight-check` per the Cilium upgrade guide, then `helm upgrade` with the same
values; agents restart node by node and keep the eBPF state (connections survive). Verify with
`cilium status --wait` and `cilium connectivity test`.

### KEDA, External Secrets, Argo Rollouts, Argo CD

```bash
helm upgrade keda kedacore/keda --version 2.21.0 -n keda -f labs/eks/addons/keda-values.yaml && kubectl -n keda rollout status deploy/keda-operator
kubectl -n shopfront get scaledobject fulfillment-worker -o jsonpath='{.status.conditions[*].status}{"\n"}'     # True True ...
helm upgrade external-secrets external-secrets/external-secrets --version 2.11.0 -n external-secrets -f labs/eks/addons/external-secrets-values.yaml
kubectl -n shopfront get externalsecret shopfront-db -o jsonpath='{.status.conditions[0].reason}{"\n"}'          # SecretSynced
helm upgrade argo-rollouts argo/argo-rollouts --version 2.43.2 -n argo-rollouts -f labs/eks/addons/argo-rollouts-values.yaml
helm upgrade argocd argo/argo-cd --version 10.9.4 -n argocd                                                       # or the EKS Capability handles it
argocd app list -p shopfront                                                                                     # Synced/Healthy
```

CRD-bearing charts (KEDA, ESO, Argo) do not upgrade CRDs through `helm upgrade` unless the chart
does it explicitly; apply the release's CRDs when the notes ask for it (`kubectl apply --server-side -f <crds>`).

## Verify

```bash
kubectl -n kube-system get pods -o wide | grep -vE 'Running|Completed'          # nothing
for d in aws-load-balancer-controller karpenter coredns; do kubectl -n kube-system rollout status deploy/$d --timeout=2m; done
kubectl -n shopfront get pods,ingress,externalsecret,scaledobject                 # all healthy, ADDRESS on the ingress
# New pod gets an IP, DNS and identity within seconds:
kubectl -n shopfront run smoke --rm -it --restart=Never --image=public.ecr.aws/aws-cli/aws-cli:2.37.6 --overrides='{"spec":{"serviceAccountName":"orders"}}' -- sts get-caller-identity
```

## Rollback

- Managed add-ons: `update-addon --addon-version <previous> --resolve-conflicts PRESERVE`.
- Helm: `helm history <release> -n <ns>` then `helm rollback <release> <revision> -n <ns>`; CRDs are not rolled back by Helm (keep the newer CRD unless the release notes say it is unsafe).
- VPC CNI regression: rolling back the DaemonSet image is safe; pods keep their IPs.
- Karpenter regression: roll back the controller; do not roll back CRDs after NodePools were converted.

## Related

- [eks-version-upgrade.md](eks-version-upgrade.md), [upgrade-breakage.md](../incidents/upgrade-breakage.md), [dns-failures.md](../incidents/dns-failures.md), [pending-pods-and-capacity.md](../incidents/pending-pods-and-capacity.md)
- Mechanism: [04 · L200 managed vs self-managed add-ons](../../hub/04-eks/L200-cluster-components-and-add-ons.md), [04 · L300 VPC CNI, kube-proxy, CoreDNS internals](../../hub/04-eks/L300-eks-internals-and-operations.md), [12 · L400 managed vs self-managed add-ons trade-off](../../hub/12-well-architected/L400-trade-offs-and-anti-patterns.md)
- Versions in use: [`labs/eks/addons/README.md`](../../labs/eks/addons/README.md)
