# Things broke after an upgrade: removed APIs, add-on incompatibility, node group failures, PDBs blocking drains

**Applies to:** both · **Severity guide:** SEV2 by default (the platform is in a mixed state); SEV1 when workloads are down · **Time to first fix:** 15–60 min

## Symptoms

- After a control plane upgrade: `kubectl apply` fails with `no matches for kind "X" in version "Y"`, controllers log `the server could not find the requested resource`, Argo CD shows `Unknown` health for some objects.
- After an add-on upgrade: pods `Pending` (`cni plugin not initialized`), DNS timeouts (CoreDNS), Services unreachable (kube-proxy), Ingress not reconciled (load balancer controller), nodes not provisioned (Karpenter).
- Node group update stuck: `UpdateInProgress` for an hour; `health.issues` `PodEvictionFailure`; `kubectl get nodes` shows `SchedulingDisabled` nodes that never go away.
- ECS after an AMI/agent change: `AGENT` placement failures, tasks fail with `CannotStartContainerError`, `ECS_*` config regressions; after a Fargate platform version change: tasks using a removed feature fail to start.

## Triage in five minutes

```bash
# 1. Establish the versions in play: control plane, add-ons, nodes, kubelet skew
aws eks describe-cluster --name shopfront-dev --query 'cluster.{version:version,platform:platformVersion,status:status}'
aws eks list-addons --cluster-name shopfront-dev --query 'addons' --output text | tr '\t' '\n' | while read -r a; do printf '%-36s ' "$a"; aws eks describe-addon --cluster-name shopfront-dev --addon-name "$a" --query 'addon.[addonVersion,status,health.issues[0].message]' --output text; done
kubectl get nodes -o custom-columns=NAME:.metadata.name,KUBELET:.status.nodeInfo.kubeletVersion,RUNTIME:.status.nodeInfo.containerRuntimeVersion,OS:.status.nodeInfo.osImage,READY:.status.conditions[-1].type
aws eks describe-update --name shopfront-dev --update-id <id> --query 'update.{type:type,status:status,errors:errors}'   # from list-updates

# 2. Removed or deprecated APIs still referenced (Kubernetes 1.36: check the deprecation guide for your jump)
kubectl get --raw /metrics | grep -E '^apiserver_requested_deprecated_apis' | head
kubectl api-resources --verbs=list -o name | head -40
# Offline, against the manifests:  kubent / pluto detect-files -d labs/eks/manifests/

# 3. Add-on health right after the change
kubectl -n kube-system get pods -o wide | grep -vE 'Running|Completed'
kubectl -n kube-system logs ds/aws-node -c aws-node --since=15m | tail -20
kubectl -n kube-system logs deploy/coredns --since=15m | tail -20
kubectl -n kube-system logs deploy/aws-load-balancer-controller --since=15m | grep -iE 'error|failed' | tail -10

# 4. Node group update / drain blockers
aws eks describe-nodegroup --cluster-name shopfront-dev --nodegroup-name general-arm64 --query 'nodegroup.{status:status,version:version,release:releaseVersion,issues:health.issues}'
kubectl get pdb -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,MIN:.spec.minAvailable,MAXUNAVAIL:.spec.maxUnavailable,ALLOWED:.status.disruptionsAllowed
kubectl get events -A --field-selector reason=EvictionBlocked --sort-by=.lastTimestamp | tail   # Karpenter/kubectl drain blocked by PDB

# 5. ECS side
aws ecs list-container-instances --cluster shopfront-dev --query 'containerInstanceArns' --output text | tr '\t' '\n' | head -3 | xargs -I{} aws ecs describe-container-instances --cluster shopfront-dev --container-instances {} --query 'containerInstances[0].{agent:versionInfo.agentVersion,docker:versionInfo.dockerVersion,connected:agentConnected,status:status,ami:attributes[?name==`ecs.ami-id`].value|[0]}'
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].{platform:platformVersion,events:events[0:3].message}'
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **Removed API version in manifests, Helm releases or controllers** | step 2 `apiserver_requested_deprecated_apis` with `removed_release`; `no matches for kind` | Update manifests to the served version; `helm mapkubeapis` for release state; upgrade the controller that still uses the old API; next time run `pluto`/`kubent` before the upgrade (eks-version-upgrade runbook) |
| **Add-on version incompatible with the new control plane** | `describe-addon` `health.issues`: `InsufficientNumberOfReplicas`, `AddonSubscriptionNeeded`, `UnsupportedAddonModification`; pods CrashLoop with API errors | `aws eks describe-addon-versions --kubernetes-version 1.36 --addon-name vpc-cni` → `update-addon` to a compatible version; order: kube-proxy → VPC CNI → CoreDNS (addon-and-controller-upgrades runbook) |
| **Add-on `configurationValues` lost or conflicts** | `update-addon` with `--resolve-conflicts OVERWRITE` reset custom settings (prefix delegation off → pods Pending) or `PRESERVE` kept a now-invalid field | Re-apply `configurationValues` from git; use `--resolve-conflicts PRESERVE` when your config is the source of truth |
| **VPC CNI upgraded past what the kubelet/kernel supports, or downgraded** | ipamd logs version errors; nodes `NotReady` with CNI errors | Follow the CNI upgrade path (one minor at a time when documented); restart `aws-node` pods after config changes |
| **kube-proxy mode changed (iptables → nftables/ipvs) mid-fleet** | Service traffic fails on some nodes | Roll the mode with node replacement, not in place; keep all nodes on one mode |
| **CoreDNS Corefile overwritten by the add-on** | `cache`, `autopath`, custom forwards gone; latency up | Manage the Corefile through `configurationValues` (`coredns-configuration-values.json`), not by editing the ConfigMap |
| **Kubelet skew: nodes more than 3 minors behind the API server** | step 1: `v1.32` kubelets with a `1.36` control plane (EKS blocks the control plane upgrade at 3 minors, but old self-managed nodes can slip) | Upgrade node groups before the next control plane step; Auto Mode does it for you within 21 days |
| **Node group update stuck on PDB eviction** | `PodEvictionFailure`; PDB `disruptionsAllowed 0` (single replica with `minAvailable: 1`, or unhealthy pods with `unhealthyPodEvictionPolicy: IfHealthyBudget`) | Fix the PDB (`maxUnavailable: 1`, `AlwaysAllow`), scale the workload to 2, or `--force` the node group update (accepts disruption) |
| **Node group update stuck because new nodes cannot join** | `NodeCreationFailure`: new AMI needs a different bootstrap (AL2 → AL2023 `nodeadm` config), access entry, or a launch template `user data` for AL2 | Move to AL2023 with `nodeadm` `NodeConfig`; keep `disablePodIMDS`/hop limit settings; AL2 EKS AMIs ended support 2025-11-26 |
| **Launch template referenced an AMI that no longer exists for the new version** | `Ec2LaunchTemplateInvalidConfiguration` | Use the SSM parameter for the AMI (`/aws/service/eks/optimized-ami/1.36/amazon-linux-2023/arm64/standard/recommended/image_id`) rather than a hard-coded id |
| **Karpenter upgraded across a CRD change without converting NodePools** | Controller logs `no matches for kind NodePool in version` or webhook failures | Follow the Karpenter upgrade guide version by version; apply new CRDs first (`karpenter-crd` chart), then the controller |
| **Cilium/CNI chaining broke on kube-proxy replacement** | Services dead on upgraded nodes | Cilium version compatible with the Kubernetes minor; `cilium status` on each node; roll nodes |
| **Load balancer controller: new version needs new IAM actions** | Controller logs `AccessDenied` on `elasticloadbalancing:...` | Update the IAM policy from the release's `iam_policy.json` (`pod-identity-associations.sh` pulls the versioned file) |
| **ECS agent/AMI: agent disconnected, `AGENT` placement failures** | `agentConnected: false`; new AMI has a different Docker/containerd or `ECS_*` config lost in user data | Drain and replace instances with the previous AMI (ASG instance refresh rollback); fix user data; Managed Instances avoid this class entirely |
| **Fargate platform version removed/changed a behaviour** | Tasks fail after `PlatformVersion: LATEST` moved | Pin `PlatformVersion: 1.4.0` while you investigate; check the platform version release notes |
| **Application incompatible with the new runtime kernel/cgroup v2** | After AL2023 nodes: JVM/Node memory accounting differs, `cgroup v1` paths hard-coded | Upgrade runtimes (JDK 17+, Node 20+); remove `/sys/fs/cgroup/memory/...` reads |

Rollback options: control plane upgrades cannot be rolled back; add-ons can (`update-addon --addon-version <previous>`); node groups can (`update-nodegroup-version --release-version <previous>` or pin the launch template version); ECS AMIs through ASG instance refresh with the previous template version; Fargate through `PlatformVersion` pinning.

## Verify the fix

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,READY:.status.conditions[-1].status
kubectl -n kube-system get pods | grep -vE 'Running|Completed'          # empty
kubectl get --raw /metrics | grep -c '^apiserver_requested_deprecated_apis'   # 0 after clients moved
kubectl -n shopfront rollout status deploy/orders && curl -fsS "http://$(kubectl -n shopfront get ingress shopfront -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')/products" | head -c 200
```

## Prevent it

- The upgrade runbooks: pre-flight (`kubent`/`pluto`, add-on compatibility list, PDB review, Insights in the EKS console), one step at a time, a staging cluster first, a rollback window for nodes and add-ons.
- Add-on configuration in git (`configurationValues`), applied with `PRESERVE`.
- AMIs by SSM parameter; AL2023 or Bottlerocket; node group `updateConfig.maxUnavailablePercentage` that tolerates PDBs.
- EKS Upgrade Insights checked before every version step (`aws eks list-insights --cluster-name shopfront-dev`).

## Related

- Runbooks: [eks-version-upgrade.md](../upgrades/eks-version-upgrade.md), [addon-and-controller-upgrades.md](../upgrades/addon-and-controller-upgrades.md), [ecs-ami-agent-and-platform.md](../upgrades/ecs-ami-agent-and-platform.md)
- Mechanism: [04 L300 upgrade mechanics](../../hub/04-eks/L300-eks-internals-and-operations.md), [04 L400 upgrade cadences for a fleet](../../hub/04-eks/L400-eks-at-scale.md), [03 L300 agent and platform versions](../../hub/03-ecs/L300-ecs-internals.md)
- Neighbours: [node-not-ready.md](node-not-ready.md), [pending-pods-and-capacity.md](pending-pods-and-capacity.md), [dns-failures.md](dns-failures.md)
- Reference: [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md)
