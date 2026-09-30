# Node NotReady: kubelet and PLEG, disk pressure, ENI attach failures, IMDS and hop-limit surprises

**Applies to:** EKS (standard clusters; on Auto Mode AWS replaces unhealthy nodes, you only confirm and open a case if it repeats) · **Severity guide:** SEV3 for one node with PDB-protected workloads; SEV2 when several nodes in one AZ flap · **Time to first fix:** 10–30 min

## Symptoms

- `kubectl get nodes` shows `NotReady` or `NotReady,SchedulingDisabled`; pods on it become `Terminating`/`Unknown` after the 5-minute eviction timeout.
- `kubectl describe node` conditions: `MemoryPressure`, `DiskPressure`, `PIDPressure` `True`, or `Ready False` with `PLEG is not healthy`, `container runtime is down`, `KubeletNotReady ... network plugin returns error: cni plugin not initialized`.
- New nodes register but never become Ready (VPC CNI pod not running, node cannot reach the API endpoint, wrong cluster CA/endpoint in user data).
- Pods on the node fail IMDS calls (`169.254.169.254` timeouts) after a launch template change: expected when the hop limit is 1 and the pod is not `hostNetwork`.

## Triage in five minutes

```bash
# 1. Which condition, since when, and is it one node or a zone?
kubectl get nodes -o wide -L topology.kubernetes.io/zone,karpenter.sh/nodepool,eks.amazonaws.com/nodegroup
kubectl describe node <node> | sed -n '/Conditions:/,/Addresses:/p'
kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node> --sort-by=.lastTimestamp | tail -20

# 2. Are the node's system pods healthy? (aws-node = VPC CNI, kube-proxy, csi drivers)
kubectl -n kube-system get pods -o wide --field-selector spec.nodeName=<node>
kubectl -n kube-system logs ds/aws-node -c aws-node --since=15m | grep -iE 'error|fail|ENI|IP' | tail -20

# 3. On the node itself (Session Manager on AL2023/Bottlerocket admin container, or kubectl debug)
aws ssm start-session --target <instance-id>
#   or: kubectl debug node/<node> -it --image=public.ecr.aws/amazonlinux/amazonlinux:2023 -- chroot /host bash
systemctl status kubelet containerd
journalctl -u kubelet --since -15m | grep -iE 'PLEG|NotReady|eviction|failed|timeout' | tail -30
df -h /var/lib/containerd /var/lib/kubelet; du -sh /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs 2>/dev/null
crictl ps -a | head; crictl images | wc -l
ps -eo pid,ppid,stat,comm | awk '$3 ~ /^D/' | head            # processes stuck in uninterruptible IO
cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io   # PSI: "some avg10" > 20 means the node is starving

# 4. Network path from the node: API endpoint, IMDS, ENI state
curl -sk -m 5 "$(aws eks describe-cluster --name shopfront-dev --query cluster.endpoint --output text)/healthz"; echo
TOKEN=$(curl -s -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 60" http://169.254.169.254/latest/api/token) && curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id
aws ec2 describe-network-interfaces --filters Name=attachment.instance-id,Values=<instance-id> --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,Attachment.Status]'
aws ec2 describe-instances --instance-ids <instance-id> --query 'Reservations[0].Instances[0].MetadataOptions'

# 5. EC2 status checks and scheduled events
aws ec2 describe-instance-status --instance-ids <instance-id> --include-all-instances --query 'InstanceStatuses[0].{sys:SystemStatus.Status,inst:InstanceStatus.Status,events:Events}'
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **Disk pressure: images or logs fill the root volume** | `DiskPressure True`; `df` on `/var/lib/containerd` > 85%; eviction events | Immediate: `crictl rmi --prune`, truncate rogue logs; durable: larger `volumeSize` (80 GiB in the lab), `imageGCHighThresholdPercent`, ship logs off-node, limit `emptyDir` sizes |
| **Memory pressure / node OOM** | `MemoryPressure True`; `dmesg` `Out of memory: Killed process`; PSI memory high | Requests that reflect usage (pods without requests are killed first), `kubeReserved`/`systemReserved` set (`EC2NodeClass.kubelet` in the lab), fewer pods per node |
| **PID pressure** | `PIDPressure True`; a pod forked thousands of processes | `podPidsLimit` in kubelet config; fix the app |
| **PLEG unhealthy: container runtime slow or hung** | `PLEG is not healthy: pleg was last seen active Xm ago`; `crictl ps` hangs; many containers or D-state processes | Restart containerd then kubelet; if it recurs: too many containers per node, slow EBS (check `VolumeQueueLength`), or a stuck NFS/EFS mount |
| **VPC CNI not initialised on a new node** | `cni plugin not initialized`; `aws-node` pod `CrashLoopBackOff` or missing; ipamd logs IAM errors | The CNI's Pod Identity association or node role must allow `ec2:AssignPrivateIpAddresses`, `ec2:AttachNetworkInterface` etc.; `aws-node` needs to reach the EC2 API (endpoint or NAT) |
| **ENI attach failures** | ipamd `Failed to attach ENI`, `AttachmentLimitExceeded`, `InsufficientFreeAddressesInSubnet`; `describe-network-interfaces` shows `available` ENIs piling up | Larger instance type (ENI limit), subnet IPs (see pending-pods), leaked ENIs from crashed nodes: delete `available` ones tagged `node.k8s.amazonaws.com/instance_id` of terminated instances |
| **Node cannot reach the API endpoint** | step 4 `healthz` times out; private endpoint only and node subnet lacks a route or the cluster security group rule | Allow 443 from node security groups to the cluster security group; private endpoint requires DNS resolution from the VPC (enable DNS hostnames/support) |
| **IMDS hop limit 1 breaks pods that used IMDS** (after enabling `disablePodIMDS`/`httpPutResponseHopLimit: 1`) | Pods log `169.254.169.254` timeouts; nodes themselves fine | Expected and desired: pods must use IRSA/Pod Identity. Find offenders with VPC Flow Logs to 169.254.169.254 or the SDK error strings; the node itself is unaffected (hub/05 L300 §2.2) |
| **IMDSv2 required but a legacy agent uses IMDSv1** | Node bootstrap or an agent fails with 401 from IMDS | Update the agent; do not lower `httpTokens` |
| **Clock skew** (`x509: certificate has expired or is not yet valid` in kubelet) | `chronyc tracking` off by minutes | Ensure `169.254.169.123` (Amazon Time Sync) is reachable; security groups do not block link-local |
| **EC2 system status check failed / scheduled retirement** | step 5 shows `impaired` or a `system-reboot`/`instance-retirement` event | Cordon, drain, terminate; ASG/Karpenter replaces it. Karpenter with the interruption queue does this on its own |
| **Bottlerocket update reboot in progress** | Brupop or update operator activity; node returns in minutes | Wait; check `apiclient get updates` from the admin container |
| **kubelet certificate rotation failed** | `Unable to rotate certificate`; node role or access entry removed | Restore the access entry (`EC2_LINUX`) for the node role; re-run bootstrap or replace the node |
| **Spot interruption / capacity rebalance** | EC2 event; Karpenter `Interruption` events; node terminates in 2 min | Not a failure: PDBs and spread absorb it; if not, move the workload to on-demand NodePool |

For any single node that is not obviously recoverable: cordon, drain, terminate, let the group replace it. Nodes are cattle; debugging one for an hour is rarely worth it after you have captured the logs.

```bash
kubectl cordon <node> && kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --grace-period=60 --timeout=10m
aws ec2 terminate-instances --instance-ids <instance-id>      # ASG/Karpenter replaces it
```

## Verify the fix

```bash
kubectl get nodes -o wide | grep -v ' Ready '                  # empty
kubectl -n kube-system get pods -o wide --field-selector spec.nodeName=<node>   # aws-node, kube-proxy Running
kubectl get pods -A -o wide --field-selector spec.nodeName=<node> | grep -vE 'Running|Completed'
```

## Prevent it

- Nodes are replaceable: root volume 80 GiB+, `kubeReserved`/`systemReserved`, eviction thresholds, PDBs on every workload, NodePool `expireAfter` so nothing runs for months.
- Node Problem Detector or Container Insights node conditions alarms (`node_status_condition_ready`, `node_filesystem_utilization`, `node_number_of_running_pods`).
- Bottlerocket for a smaller, read-only host OS; AL2023 otherwise (AL2 is out of support since 2025-11-26).
- Keep the CNI, kube-proxy and kubelet versions within the supported skew (see upgrade runbooks).

## Related

- Mechanism: [04 L300 VPC CNI, kubelet, containerd on nodes](../../hub/04-eks/L300-eks-internals-and-operations.md), [05 L300 link-local addresses and IMDSv2](../../hub/05-networking/L300-container-networking-internals.md), [01 L300 containerd and cgroups](../../hub/01-container-fundamentals/L300-runtimes-and-the-kernel.md)
- Neighbours: [pending-pods-and-capacity.md](pending-pods-and-capacity.md), [image-pull-failures.md](image-pull-failures.md), [upgrade-breakage.md](upgrade-breakage.md)
- Runbooks: [eks-version-upgrade.md](../upgrades/eks-version-upgrade.md)
