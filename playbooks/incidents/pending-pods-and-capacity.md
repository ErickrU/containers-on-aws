# Pending pods and capacity: insufficient cpu/memory, IP exhaustion, taints, autoscaler not scaling, ECS RESOURCE:CPU

**Applies to:** both · **Severity guide:** SEV2 when a rollout or scale-out cannot complete; SEV1 when replacements after failures cannot start · **Time to first fix:** 5–20 min

## Symptoms

- EKS: pods stay `Pending`; `kubectl describe pod` ends with `0/12 nodes are available: 3 Insufficient cpu, 4 Too many pods, 5 node(s) had untolerated taint ...`, or `FailedCreatePodSandBox ... failed to assign an IP address to container`.
- Karpenter/Auto Mode logs `could not schedule pod` with a reason (`no instance type satisfied resources`, `all requested instance types were unavailable during launch`, `NodePool limits exceeded`), or nothing at all (the pod does not match any NodePool).
- ECS: service event `(service orders) was unable to place a task because no container instance met all of its requirements. The closest matching container-instance ... has insufficient CPU units available` (`RESOURCE:CPU`, `RESOURCE:MEMORY`, `RESOURCE:ENI`, `AGENT`, `ATTRIBUTE`); Fargate: `Capacity is unavailable at this time` / `SpotCapacityNotAvailable`.
- Managed node group `desiredSize` raised but no node joins (launch failure, subnet out of IPs, service quota).

## Triage in five minutes

```bash
# 1. Read the scheduler's own verdict (it lists every rejection reason with counts)
kubectl -n shopfront describe pod <pod> | sed -n '/Events:/,$p'
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].events[0:5].message'

# 2. Autoscaler view: is anything trying to add capacity?
kubectl -n kube-system logs deploy/karpenter --since=10m | grep -iE 'could not schedule|insufficient|limit|unavailable|created nodeclaim' | tail -20
kubectl get nodeclaims -o wide                                   # Karpenter and Auto Mode: launching / registered / initialized?
kubectl get nodepool -o custom-columns=NAME:.metadata.name,CPU:.status.resources.cpu,LIMIT:.spec.limits.cpu,READY:.status.conditions[-1].status
aws eks describe-nodegroup --cluster-name shopfront-dev --nodegroup-name general-arm64 --query 'nodegroup.{desired:scalingConfig.desiredSize,max:scalingConfig.maxSize,health:health.issues}'

# 3. Are the nodes full, or full of IPs?
kubectl describe nodes | grep -A8 'Allocated resources' | grep -E 'cpu|memory|pods'
kubectl get nodes -o custom-columns=NAME:.metadata.name,PODS:.status.allocatable.pods,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory
aws ec2 describe-subnets --subnet-ids <subnet-ids> --query 'Subnets[*].[SubnetId,AvailabilityZone,AvailableIpAddressCount]'
kubectl -n kube-system logs ds/aws-node -c aws-node --since=10m | grep -iE 'no available IP|InsufficientFreeAddressesInSubnet|ENI' | tail -5

# 4. Does the pod fit ANY node type at all? (requests vs the biggest allowed instance; taints vs tolerations)
kubectl -n shopfront get pod <pod> -o jsonpath='{.spec.containers[*].resources.requests}{"\n"}{.spec.nodeSelector}{"\n"}{.spec.tolerations}{"\n"}{.spec.affinity}{"\n"}{.spec.topologySpreadConstraints}'
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# 5. Quotas and AZ capacity (EC2 and Fargate)
aws service-quotas get-service-quota --service-code ec2 --quota-code L-DB2E81BA --query 'Quota.Value'     # Running On-Demand Standard vCPUs
aws service-quotas get-service-quota --service-code fargate --quota-code L-3032A538 --query 'Quota.Value' # Fargate On-Demand vCPUs
aws ec2 describe-instance-type-offerings --location-type availability-zone --filters Name=instance-type,Values=m7g.large --query 'InstanceTypeOfferings[*].Location'
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **Requests exceed what remains on every node** (`Insufficient cpu/memory`) | step 3: allocated near 100%; no autoscaler, or it is at max | Raise `maxSize`/`NodePool.limits`; right-size requests (VPA `Off` mode); Karpenter needs a NodePool whose requirements fit the pod |
| **`Too many pods`: max-pods reached, CPU still free** | `allocatable.pods` = 29 on m7g.large without prefix delegation; nodes show `pods` allocated 100% | Enable prefix delegation (`ENABLE_PREFIX_DELEGATION=true`, `max-pods` recomputed on new nodes) or pick larger/ more instances (hub/05 L300 §2.3) |
| **Subnet out of IPs** (`failed to assign an IP address`, `InsufficientFreeAddressesInSubnet`) | step 3 `AvailableIpAddressCount` near 0; ipamd logs | Prefix delegation, secondary CIDR (100.64.0.0/16) with custom networking, or IPv6; short-term: scale down noisy namespaces, free unused ENIs (`aws ec2 describe-network-interfaces --filters Name=status,Values=available`) |
| **ENI attach limit on the instance type** | ipamd `ENI attach limit`; `RESOURCE:ENI` on ECS EC2 with awsvpc | Larger instance family, ENI trunking on ECS (`awsvpcTrunking` account setting, hub/03 L300 §2.6), prefix delegation on EKS |
| **Taint without toleration / nodeSelector or affinity nothing matches** | Events `untolerated taint`, `didn't match Pod's node affinity/selector`; Karpenter: no NodePool with the label | Add the toleration and selector (the `analytics-consumer` needs `workload=stable`); or create the NodePool with that label (`auto-mode-nodepool-nodeclass.yaml`) |
| **Topology spread `DoNotSchedule` cannot be satisfied** | Events `didn't match pod topology spread constraints`; one AZ has no capacity | Use `ScheduleAnyway` for non-critical spread, or provide capacity in every zone (Karpenter picks zones; MNG subnets must cover them) |
| **PodDisruptionBudget blocks consolidation, so nodes look full but are idle** | Karpenter `disruption blocked` events; PDB with `minAvailable` = replicas | Fix the PDB (`maxUnavailable: 1`), see `labs/eks/manifests/base/pdb.yaml` |
| **NodePool limits or Karpenter budgets reached** | `NodePool limits exceeded`; disruption budget `nodes: "0"` schedule active | Raise `spec.limits`; check the `budgets` schedule (the lab blocks disruption 09:00–17:00 UTC weekdays) |
| **Instance type unavailable in the AZ / Spot capacity** (`InsufficientInstanceCapacity`, `SpotCapacityNotAvailable`) | Karpenter `all requested instance types were unavailable`; ECS Fargate Spot events | Diversify: more instance families/sizes, both architectures, on-demand fallback (`capacity-type In [spot, on-demand]`; ECS capacity provider strategy with a `FARGATE` base) |
| **EC2 or Fargate vCPU quota** | step 5; `VcpuLimitExceeded`; CloudTrail `RunInstances` `Client.VcpuLimitExceeded` | Request a quota increase (takes minutes to hours); until then scale other workloads down |
| **Managed node group launch failures** | `health.issues`: `Ec2LaunchTemplateInvalidConfiguration`, `AsgInstanceLaunchFailures`, `NodeCreationFailure` (node never joins: IAM role, cluster security group, endpoint access) | Fix the launch template/IAM; for `NodeCreationFailure` check the node role has `AmazonEKSWorkerNodePolicy`, the access entry of type `EC2_LINUX` exists, and nodes can reach the API endpoint |
| **New nodes join but stay `NotReady`** | `kubectl get nodes`; VPC CNI not ready | See node-not-ready |
| **ECS EC2: `AGENT` (agent disconnected) or `ATTRIBUTE` (placement constraint)** | Service events name the requirement | `AGENT`: agent/instance health, see upgrade runbook; `ATTRIBUTE`: the task needs `ecs.instance-type` or a custom attribute no instance has |
| **ECS Fargate: `Capacity is unavailable`** | Rare; AZ-level | Retry (ECS retries placement); spread subnets across 3 AZs; open a support case if it persists |
| **Resource quota in the namespace** | `exceeded quota` in events (`kubectl describe quota -n shopfront`) | Raise the quota or fix the offending requests |

## Verify the fix

```bash
kubectl -n shopfront get pods -o wide | grep -v Running        # nothing Pending
kubectl get nodeclaims,nodes -o wide                            # new nodes Ready in < 3 min
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].{running:runningCount,desired:desiredCount,event:events[0].message}'
```

## Prevent it

- Prefix delegation (or IPv6) from day one; subnets sized for growth (`/20` per AZ for pods; hub/05 L400 §2.1).
- NodePools with wide instance requirements and Spot+on-demand; `limits` set but not tight; consolidation budgets that leave room for incidents.
- Alarms on `Pending` pod age (Container Insights `pod_status_pending`), Karpenter `karpenter_pods_startup_duration_seconds`, ECS `SERVICE_TASK_PLACEMENT_FAILURE` events, subnet free IPs (custom metric from `describe-subnets`).
- Quota reviews before launches; `service-quotas` alarms through Trusted Advisor or a scheduled Lambda.

## Related

- Mechanism: [04 L200 node groups, Karpenter, Auto Mode](../../hub/04-eks/L200-cluster-components-and-add-ons.md), [04 L300 VPC CNI internals](../../hub/04-eks/L300-eks-internals-and-operations.md), [05 L300 ENI/IP arithmetic](../../hub/05-networking/L300-container-networking-internals.md), [03 L300 placement engine and ENI trunking](../../hub/03-ecs/L300-ecs-internals.md)
- Neighbours: [node-not-ready.md](node-not-ready.md), [ecs-task-stopped-reasons.md](ecs-task-stopped-reasons.md), [ecs-deployment-stuck-or-rolled-back.md](ecs-deployment-stuck-or-rolled-back.md)
- Reference: [quotas and limits](../../reference/quotas-and-limits.md)
