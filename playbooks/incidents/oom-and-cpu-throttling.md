# OOMKilled (exit 137), memory limits vs runtimes, and CPU throttling

**Applies to:** both · **Severity guide:** SEV2 when restarts are frequent enough to drop requests; SEV3 for throttling-induced latency · **Time to first fix:** 10–30 min

## Symptoms

- Container restarts with exit code 137 and reason `OOMKilled` (EKS) or `OutOfMemoryError: Container killed due to memory usage` (ECS).
- Memory graph climbs to the limit and drops vertically at each restart (leak or oversized heap), or spikes on specific requests (large payloads, batch jobs).
- p99 latency rises while CPU utilisation looks "fine" at 50–70 percent: classic CFS throttling; `container_cpu_cfs_throttled_periods_total` grows.
- JVM/Node/Go process is killed even though its own metrics show heap well under the limit (page cache, off-heap, threads, or a sidecar counted in the task limit).

## Triage in five minutes

```bash
# 1. Is it memory (OOM) or CPU (throttling)? They look alike from the outside.
kubectl -n shopfront get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'   # OOMKilled -> memory
aws ecs describe-tasks --cluster shopfront-dev --tasks <task-arn> --query 'tasks[0].containers[*].[name,exitCode,reason]'

# 2. Requests, limits and actual usage (working set includes page cache the kernel could reclaim)
kubectl -n shopfront get pod <pod> -o jsonpath='{range .spec.containers[*]}{.name}{": "}{.resources}{"\n"}{end}'
kubectl -n shopfront top pod <pod> --containers
aws cloudwatch get-metric-statistics --namespace ECS/ContainerInsights --metric-name MemoryUtilized \
  --dimensions Name=ClusterName,Value=shopfront-dev Name=ServiceName,Value=orders \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 60 --statistics Maximum

# 3. Throttling counters (EKS with cAdvisor/Prometheus, or from inside the container)
kubectl -n shopfront exec <pod> -c orders -- cat /sys/fs/cgroup/cpu.stat          # nr_throttled / nr_periods, throttled_usec
kubectl -n shopfront exec <pod> -c orders -- cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak
kubectl -n shopfront exec <pod> -c orders -- cat /sys/fs/cgroup/memory.events     # oom_kill counter
#   nr_throttled/nr_periods above 10-20% -> CPU limit is the problem
#   memory.current close to memory.max with rising oom_kill -> memory

# 4. What the runtime thinks its budget is
kubectl -n shopfront exec <pod> -c orders -- node -e 'console.log(process.memoryUsage(), require("v8").getHeapStatistics().heap_size_limit/1048576)'
kubectl -n shopfront exec <pod> -c catalog -- env | grep -E 'GOMEMLIMIT|GOMAXPROCS'
#   Java: -XX:+PrintFlagsFinal | grep -E 'MaxHeapSize|MaxRAMPercentage'

# 5. Node pressure or noisy neighbour? (EKS)
kubectl describe node <node> | sed -n '/Conditions:/,/Addresses:/p;/Allocated resources:/,/Events:/p'
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **Heap configured above the container limit** (JVM default 25% of RAM is fine; `-Xmx` set by hand is not; Node default old-space ~2 GB+) | `heap_size_limit` > memory limit; JVM `MaxHeapSize` > limit | Node: `--max-old-space-size` at ~75% of the limit (`NODE_OPTIONS` in the manifests); JVM: `-XX:MaxRAMPercentage=70` and let it read the cgroup; Go: `GOMEMLIMIT` at ~80% (hub/01 L400 §2.6) |
| **Non-heap memory not budgeted** (JVM metaspace, threads, direct buffers; Node native modules; Python C extensions) | Heap under limit, RSS at limit | Raise the limit 30–50% above the heap you configured; cap thread pools; for Python watch `ujson`/`numpy` allocations |
| **Page cache counted in the working set** (writes to `/tmp` `emptyDir` in memory, log files) | `memory.stat` `file` large; usage drops when files are deleted | `emptyDir` with `medium: ""` (disk) and `sizeLimit`; do not log to files; rotate |
| **Sidecar shares the task limit (ECS)** | Task `memory` = app + collector; the app's `memoryReservation` is soft | Give the app a hard `memory` per container or size the task for both; `04-services.yaml` reserves 256 MiB for the collector |
| **Genuine leak** | Sawtooth that resets only on restart; heap dump shows growth in one type | Fix the code; meanwhile a scheduled restart (`kubectl rollout restart` by CronJob) is a legitimate stopgap, an OOM loop is not |
| **Batch-shaped traffic** (one request allocates GBs) | Spikes tied to specific endpoints or SQS messages | Stream instead of buffering; move the work to the report-job / Batch tier with its own limit |
| **Requests far below usage: pod scheduled on a full node** (EKS) | `Allocated resources` near 100%; node-level OOM kills the BestEffort/Burstable pods first | Set requests equal to real p95 usage (VPA in `Off` mode gives the numbers); Guaranteed QoS for critical pods |
| **CPU limit throttles bursts** | `nr_throttled` high while average CPU is moderate; latency spikes every 100 ms period | Remove the CPU limit (keep requests) or raise it well above the request; the lab manifests set no CPU limit on purpose; on ECS task `cpu` is a hard budget: size it for peak, not average |
| **GOMAXPROCS / thread pools sized for the node, not the container** | Go sees 64 CPUs on a big node; Java `availableProcessors` wrong on old JVMs | `GOMAXPROCS` = ceil(limit) or `automaxprocs`; JVM 17+ reads cgroup v2 correctly; Node is single-threaded but libuv pool defaults to 4 |
| **Fargate memory pairs** (ECS) | Task `cpu`/`memory` combination forces more memory than needed or the container `memory` exceeds the task's | Pick a valid pair (0.5 vCPU: 1–4 GB, 1 vCPU: 2–8 GB ...); container hard limits must fit inside the task |
| **Kernel memory / conntrack on the node** | `dmesg` on node shows `nf_conntrack: table full` or kernel OOM | Node-level tuning; see dns-failures for conntrack |

## Verify the fix

```bash
# No new OOM kills over an hour, and throttling under 5%:
kubectl -n shopfront exec <pod> -c orders -- sh -c 'cat /sys/fs/cgroup/memory.events; cat /sys/fs/cgroup/cpu.stat'
kubectl -n shopfront get pods -l app.kubernetes.io/name=orders -o custom-columns=NAME:.metadata.name,RESTARTS:.status.containerStatuses[0].restartCount
aws cloudwatch get-metric-statistics --namespace AWS/ECS --metric-name MemoryUtilization \
  --dimensions Name=ClusterName,Value=shopfront-dev Name=ServiceName,Value=orders \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 300 --statistics Maximum
```

## Prevent it

- Every runtime told its budget explicitly (`NODE_OPTIONS`, `GOMEMLIMIT`, `MaxRAMPercentage`); tested with `docker run --memory=512m` locally.
- Requests from measured p95, limits from the runtime budget plus headroom; VPA recommendations reviewed monthly (hub/11 L300 §2.3).
- Load tests that include the largest payloads (hub/11 L300).
- Alarms: `MemoryUtilization` > 90% for 3 min (`05-observability.yaml` `OrdersMemoryAlarm`), Container Insights `pod_memory_utilization_over_pod_limit`, restart rate.

## Related

- Mechanism: [01 L300 cgroups, CFS quota, OOM killer](../../hub/01-container-fundamentals/L300-runtimes-and-the-kernel.md), [01 L400 container-aware runtimes and the CPU-limit debate](../../hub/01-container-fundamentals/L400-hardening-supply-chain-and-performance.md), [04 L200 requests, limits, QoS](../../hub/04-eks/L200-cluster-components-and-add-ons.md)
- Neighbours: [crashloop-and-exit-codes.md](crashloop-and-exit-codes.md), [pending-pods-and-capacity.md](pending-pods-and-capacity.md), [node-not-ready.md](node-not-ready.md)
- Reference: [metrics catalog](../../reference/metrics-catalog.md)
