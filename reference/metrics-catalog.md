# Metrics catalog

Every metric named in the hub, grouped by component: where it comes from, what a bad value means,
and a starting alarm threshold where one is defensible. Thresholds are starting points for a
service like shopfront; tune them against your SLOs ([07 · L300](../hub/07-observability/L300-metrics-that-matter-and-alerting.md)
explains how, and why ratios beat counts). Sources: **CW** = CloudWatch namespace, **CI** = Container
Insights (`ECS/ContainerInsights`, `ContainerInsights`), **Prom** = Prometheus exposition (scraped by
the CloudWatch agent/ADOT/AMP), **CT** = CloudTrail, **Logs** = log group.

## Golden signals per service (the ones to alarm on first)

| Signal | Metric | Source | Starting threshold |
| --- | --- | --- | --- |
| Availability | `HTTPCode_Target_5XX_Count` / `RequestCount` per target group | CW `AWS/ApplicationELB` | > 1% (prod) / 5% (dev) for 3 of 5 min → page (`05-observability.yaml Orders5xxRatioAlarm`) |
| Latency | `TargetResponseTime` p99 | CW `AWS/ApplicationELB` | > 1 s for 3 of 5 min |
| Saturation | `CPUUtilization`, `MemoryUtilization` per service | CW `AWS/ECS` / CI | CPU > 85% 5 min; memory > 90% 3 min |
| Errors (app) | `http_requests_total{status=~"5.."}` rate | Prom (the shopfront apps) | same ratio as above, for in-cluster traffic |
| Backlog | `ApproximateAgeOfOldestMessage` | CW `AWS/SQS` | > 300 s 3 min |
| Capacity | `RunningTaskCount` < `DesiredTaskCount`; `pod_status_pending` | CI | gap > 0 for 5 min |

## Load balancers (ALB `AWS/ApplicationELB`, NLB `AWS/NetworkELB`)

| Metric | Dimensions | Meaning when bad | Threshold |
| --- | --- | --- | --- |
| `RequestCount` | LoadBalancer, TargetGroup | denominator for every ratio; a drop to zero is an outage or a DNS change | anomaly detection |
| `HTTPCode_ELB_5XX_Count` (`_502_`, `_503_`, `_504_`) | LoadBalancer | the ALB generated the error: target closed/reset (502), no healthy targets (503), target timeout (504) | > 10/min 3 of 5 |
| `HTTPCode_Target_5XX_Count` / `_4XX_Count` | LoadBalancer, TargetGroup | the application answered 5xx/4xx | ratio as above; 4xx anomaly only |
| `TargetResponseTime` | TargetGroup | time from request leaving the ALB to response headers; p50 vs p99 gap shows tail latency | p99 > SLO |
| `HealthyHostCount` / `UnHealthyHostCount` | TargetGroup, LoadBalancer | targets failing `/readyz`; flapping means probes vs GC/throttling | unhealthy ≥ 1 for 2 of 3 min |
| `RequestCountPerTarget` | TargetGroup | load per task/pod; the ECS scaling metric (`ALBRequestCountPerTarget`) | scale at 500/min per target (lab) |
| `TargetConnectionErrorCount` | LoadBalancer | ALB could not connect to targets: security group, port, target dead | > 0 sustained |
| `RejectedConnectionCount` | LoadBalancer | ALB out of capacity (surge) | > 0 |
| `ActiveConnectionCount`, `NewConnectionCount` | LoadBalancer | connection churn; keep-alive mismatches show as high new/active ratio | trend |
| `ProcessedBytes` | LoadBalancer | data-transfer cost driver | trend |
| `ELBAuthError`, `ELBAuthFailure` | LoadBalancer | OIDC authentication at the ALB failing | > 0 |
| NLB `UnHealthyHostCount`, `TCP_Target_Reset_Count`, `PortAllocationErrorCount` | LoadBalancer | target resets; SNAT port exhaustion behind the NLB | resets anomaly; port errors > 0 |
| Access log fields `elb_status_code`, `target_status_code`, `target_processing_time`, `request_processing_time`, `response_processing_time`, `error_reason` | Logs (S3) | forensics per request; `target_status_code=-` means the target was never reached | n/a |

## ECS (`AWS/ECS`, `ECS/ContainerInsights`, service events)

| Metric | Source | Meaning when bad | Threshold |
| --- | --- | --- | --- |
| `CPUUtilization`, `MemoryUtilization` (ClusterName, ServiceName) | CW `AWS/ECS` | percentage of the task reservation (CPU) / hard limit (memory) | CPU > 85% 5 min; mem > 90% 3 min |
| `CpuUtilized`, `CpuReserved`, `MemoryUtilized`, `MemoryReserved` | CI | absolute units; utilized/reserved is the right-sizing ratio | utilized < 30% of reserved for a week → shrink |
| `RunningTaskCount`, `DesiredTaskCount`, `PendingTaskCount` | CI | pending > 0 for minutes = placement or start failures | desired − running > 0 for 5 min |
| `DeploymentCount`, `TaskSetCount` | CI | deployments > 1 for long = stuck rollout | > 1 for 20 min |
| `ServiceCount`, `TaskCount`, `ContainerInstanceCount` | CI | cluster-level inventory | n/a |
| `EphemeralStorageUtilized`/`Reserved` | CI | Fargate task disk filling | > 80% |
| `NetworkRxBytes`, `NetworkTxBytes`, `StorageReadBytes`, `StorageWriteBytes` | CI | saturation of the ENI / EBS for EC2 | trend |
| `CapacityProviderReservation` (CapacityProviderName) | CW `AWS/ECS/ManagedScaling` | > 100 means the ASG is undersized for placed tasks; the managed-scaling target | target 80–100 |
| Service Connect: `TargetResponseTime`, `HTTPCode_Target_5XX_Count`, `RequestCount`, `ActiveConnectionCount`, `NewConnectionCount`, `ProcessedBytes`, `TargetConnectionErrorCount` (DiscoveryName, ServiceName, TargetDiscoveryName) | CW `AWS/ECS` (Service Connect) | the same golden signals for east-west calls (orders → catalog) | as ALB |
| Service events: `SERVICE_TASK_START_IMPAIRED`, `SERVICE_TASK_PLACEMENT_FAILURE`, `SERVICE_STEADY_STATE`, `SERVICE_DEPLOYMENT_FAILED` | EventBridge → Logs (`/shopfront/<env>/ecs-events`) | tasks cannot start / be placed / deployment rolled back | any `IMPAIRED`, `FAILURE`, `FAILED` → alert |
| Task state changes: `stopCode`, `stoppedReason`, `exitCode` | EventBridge → Logs | see the stopped-reasons runbook | count of `TaskFailedToStart` > 3 in 5 min |
| ECS Exec: `ExecuteCommand` | CT | who opened a shell in which task | every event → audit log |

## Fargate

| Metric | Source | Meaning when bad | Threshold |
| --- | --- | --- | --- |
| Task-level `CpuUtilized`/`MemoryUtilized`/`EphemeralStorageUtilized` | CI | same as ECS; there is no host to look at | as ECS |
| `ResourceInitializationError` count | ECS events log | secrets/logs/ENI provisioning failures | > 0 |
| Fargate On-Demand vCPU usage vs quota | Service Quotas usage metric (`AWS/Usage` `ResourceCount`, Service=Fargate) | approaching the vCPU quota | > 80% of quota |

## EKS control plane (`ContainerInsights` control-plane metrics, `/aws/eks/<cluster>/cluster` logs, API server Prom endpoint)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `apiserver_request_duration_seconds` (verb, resource) p99 | slow API: overloaded control plane, big list calls, slow webhooks | p99 > 1 s for reads, > 5 s for LIST |
| `apiserver_request_total{code=~"5.."}` rate | API errors | > 0.1% |
| `apiserver_current_inflight_requests`, `apiserver_flowcontrol_rejected_requests_total` | priority and fairness rejecting requests (429) | rejected > 0 |
| `apiserver_storage_objects` (resource) | object count growth: leaked Jobs/Events/Secrets | trend; > 100k of one kind → investigate |
| `etcd_db_total_size_in_bytes` | etcd size; EKS quota 8 GiB | > 5 GiB warn, > 6.5 GiB page |
| `apiserver_admission_webhook_admission_duration_seconds` (name) | slow admission webhooks (Kyverno, Gatekeeper, LBC) | p99 > 1 s |
| `apiserver_requested_deprecated_apis` | clients using APIs removed in a future version | > 0 before an upgrade |
| `scheduler_pending_pods`, `scheduler_schedule_attempts_total{result="unschedulable"}` | pods that cannot be placed | unschedulable rate > 0 for 5 min |
| `workqueue_depth` (controller-manager) | controllers falling behind | trend |
| Authenticator log `access denied` | mapping problems | > 5/min from one principal |
| Audit log `responseStatus.code=403` rate | RBAC denials | trend; spikes = misconfiguration or probing |

## Nodes (Container Insights `ContainerInsights`, node-exporter/kubelet Prom)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `node_cpu_utilization`, `node_memory_utilization` (CI) | node saturation; memory near 100% → node OOM kills | CPU > 80% 15 min; mem > 85% |
| `node_filesystem_utilization` (CI) / `node_filesystem_avail_bytes` | disk pressure imminent (images, logs) | > 80% |
| `node_number_of_running_pods` vs `allocatable.pods` | max-pods exhaustion | > 90% |
| `kube_node_status_condition{condition="Ready",status!="true"}`; `MemoryPressure`, `DiskPressure`, `PIDPressure` | node conditions | any True for 5 min |
| `node_pressure_cpu_waiting_seconds_total`, `node_pressure_memory_stalled_seconds_total` (PSI) | stall time: contention before it becomes OOM/throttle | some avg10 > 20% |
| `node_nf_conntrack_entries` / `node_nf_conntrack_entries_limit` (`nf_conntrack_count`/`nf_conntrack_max`) | conntrack table filling: dropped packets, DNS timeouts | > 80% |
| `node_network_receive_drop_total`, `container_network_receive_errors_total` | packet drops on the ENI | > 0 sustained |
| `kubelet_pleg_relist_duration_seconds` p99 | container runtime slow → PLEG unhealthy → NotReady | p99 > 3 s |
| `kubelet_runtime_operations_errors_total` | containerd errors | rate > 0 |
| `kubelet_image_pull_duration_seconds` | pull time; image size or registry problems | p99 > 60 s |
| `kubelet_volume_stats_*` | PV filling | > 85% |
| `kube_node_spec_taint` | unexpected taints (`node.kubernetes.io/unreachable`, `disk-pressure`) | any unexpected |
| `nf_conntrack_max`, `net.core.somaxconn` (sysctl) | node tuning knobs, not metrics; check when drops or resets appear | n/a |

## Pods and containers (Container Insights, kube-state-metrics, cAdvisor)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `pod_cpu_utilization`, `pod_memory_utilization` (CI, % of request/limit); `pod_memory_utilization_over_pod_limit` | approaching the limit → OOM | mem over limit > 90% |
| `pod_memory_working_set` / `container_memory_working_set_bytes` | what the OOM killer counts (RSS + active page cache) | vs limit |
| `container_cpu_cfs_throttled_periods_total` / `container_cpu_cfs_periods_total` (also `container_cpu_cfs_throttled_seconds_total`) | CFS throttling ratio; latency without CPU saturation | > 20% of periods |
| `pod_number_of_container_restarts` (CI) / `kube_pod_container_status_restarts_total` | crash loops | rate > 3 in 15 min |
| `kube_pod_container_status_waiting_reason` (`CrashLoopBackOff`, `ImagePullBackOff`, `CreateContainerConfigError`) | why a container is not running | any for 5 min |
| `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`, `container_oom_events_total` | OOM kills | > 0 |
| `kube_pod_status_phase{phase="Pending"}` / `pod_status_pending` (CI) | unschedulable or waiting on volumes/images | pending > 5 min |
| `kube_deployment_status_replicas_unavailable`, `kube_deployment_status_replicas_available`, `kube_deployment_spec_replicas`, `kube_deployment_status_observed_generation` | rollout health; observed generation lagging spec = controller not reconciling | unavailable > 0 for 10 min |
| `kube_daemonset_status_number_ready` vs desired | system DaemonSets (CNI, kube-proxy) missing on nodes | ready < desired 5 min |
| `kube_horizontalpodautoscaler_status_current_replicas` vs `spec_max_replicas` | HPA pinned at max | current = max 15 min |
| `service_number_of_running_pods` (CI) | service capacity | < min replicas |
| `container_fs_usage_bytes` | writable layer / emptyDir growth | > 80% of `sizeLimit` |

## CoreDNS (Prom `:9153`)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `coredns_dns_request_duration_seconds` (p99; `_bucket` for histograms) | DNS latency; the "slow first request" | p99 > 100 ms |
| `coredns_dns_requests_total` (type, zone) | query volume; AAAA share and `ndots` amplification | trend |
| `coredns_dns_responses_total{rcode}` | `SERVFAIL` = upstream failure, `NXDOMAIN` storms = `ndots` | SERVFAIL rate > 1% |
| `coredns_forward_requests_total`, `coredns_forward_responses_total{rcode}`, `coredns_forward_healthcheck_failures_total` | upstream (VPC resolver) health and throttling | failures > 0 |
| `coredns_cache_hits_total` / misses | cache effectiveness | hit ratio < 60% → raise TTL/prefetch |
| `coredns_panics_total` | crashes | > 0 |
| CoreDNS pod restarts, CPU vs limit | overload | restarts > 0; CPU > 80% |

## VPC CNI (`aws-node` Prom `:61678`)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `awscni_total_ip_addresses`, `awscni_assigned_ip_addresses` | IPs available vs used per node; exhaustion imminent | assigned/total > 90% |
| `awscni_eni_allocated`, `awscni_eni_max` | ENIs attached vs instance limit | allocated = max and IPs low |
| `awscni_ipamd_error_count`, `awscni_ec2api_error_count` | ipamd/EC2 API errors (IAM, throttling, subnet full) | rate > 0 |
| `awscni_add_ip_req_count`, `del_ip_req_count`, `awscni_ipamd_action_inprogress` | churn and stuck operations | in-progress stuck > 1 min |
| Network policy agent: `network_policy_enforcing_latency_seconds`, policy event logs | slow policy application; denied flows (`/aws/eks/<cluster>/network-policy`) | denies of legitimate flows |

## kube-proxy and node networking

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `kubeproxy_sync_proxy_rules_duration_seconds` | time to program iptables/nftables; thousands of Services make it slow | p99 > 5 s |
| `kubeproxy_sync_proxy_rules_last_timestamp_seconds` age | stale rules | > 60 s |
| conntrack metrics (nodes table) | table exhaustion | as nodes |

## Karpenter / Auto Mode (Prom `:8080` on the controller; Auto Mode exposes a subset through Container Insights)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `karpenter_pods_startup_duration_seconds` | pod pending → running time including node launch | p95 > 5 min |
| `karpenter_nodeclaims_created_total`, `karpenter_nodeclaims_terminated_total` (reason) | churn; too much consolidation | trend |
| `karpenter_nodepool_usage` / `karpenter_nodepool_limit` | limits about to block scaling | > 80% |
| `karpenter_voluntary_disruption_decisions_total` | consolidation/drift decisions; spikes after upgrades | trend |
| `karpenter_cluster_state_synced`, controller errors | Karpenter cannot see the cluster | synced = 0 |
| Interruption queue: `ApproximateNumberOfMessagesVisible` on the Karpenter SQS queue | interruptions not being processed | > 0 for 5 min |

## ECR

| Metric | Source | Meaning when bad | Threshold |
| --- | --- | --- |
| `GetAuthorizationToken`, `BatchGetImage`, `GetDownloadUrlForLayer` errors (`errorCode`) | CT | throttling or denied pulls | any `ThrottlingException` / `AccessDenied` from workload roles |
| `ReplicateImage` events, replication status per image | CT / `describe-images` | replication lag or failure | image missing in the DR Region 15 min after push |
| Image scan findings by severity (Inspector) | ECR API / Security Hub | new CRITICAL in a deployed image | > 0 CRITICAL active |
| Repository size / image count vs lifecycle | ECR API | storage cost | trend |
| Pull-through cache: `BatchImportUpstreamImage` errors | CT | upstream (Docker Hub) failures or credentials | > 0 |

## SQS (`AWS/SQS`)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `ApproximateAgeOfOldestMessage` | consumers not keeping up or a poison message | > 300 s 3 min (`OrdersQueueAgeAlarm`) |
| `ApproximateNumberOfMessagesVisible` | backlog depth; the KEDA/ECS scaling signal | scale at 100 per consumer |
| `ApproximateNumberOfMessagesNotVisible` | in flight; high with low visible = slow processing | > consumers × batch × 2 |
| `NumberOfMessagesSent` / `NumberOfMessagesReceived` / `NumberOfMessagesDeleted` | flow; deleted << received = failures/redelivery | deleted/received < 0.9 |
| `NumberOfEmptyReceives` | polling cost with no work; long polling reduces it | trend (cost) |
| DLQ `ApproximateNumberOfMessagesVisible` | poison messages | ≥ 1 (`OrdersDlqDepthAlarm`) |

## RDS / Aurora / RDS Proxy (`AWS/RDS`)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `DatabaseConnections` (cluster) | connection storm from scale-out | > 80% of `max_connections` |
| `ServerlessDatabaseCapacity`, `ACUUtilization` | Serverless v2 near max ACU | ACU util > 90% 15 min (`AuroraCapacityAlarm`) |
| `CPUUtilization`, `FreeableMemory`, `BufferCacheHitRatio` | saturation; low cache hit → IO-bound | CPU > 80%; hit ratio < 95% |
| `CommitLatency`, `ReadLatency`, `WriteLatency`, `Deadlocks` | storage/lock problems | commit p99 > 20 ms; deadlocks > 0 |
| `ReplicaLag` (reader), `AuroraGlobalDBReplicationLag`, `AuroraGlobalDBRPOLag` | replication behind; the DR RPO | global lag > RPO |
| `EngineUptime` drop | failover/restart happened | drop |
| RDS Proxy: `ClientConnections`, `DatabaseConnections`, `DatabaseConnectionsCurrentlySessionPinned`, `DatabaseConnectionsBorrowLatency`, `ClientConnectionsSetupFailedAuth`, `QueryDatabaseResponseLatency` | pinning defeats pooling; borrow latency = pool exhausted; auth failures = secret rotation mismatch | pinned/total > 20% (`ProxyPinnedSessionsAlarm`); borrow p99 > 50 ms; auth failures > 0 |

## ElastiCache Serverless / Valkey (`AWS/ElastiCache`)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `CacheHitRate` (`CacheHits`/`CacheMisses`) | cold cache or bad keys; stampede risk | < 80% steady state |
| `ElastiCacheProcessingUnits`, `BytesUsedForCache` | serverless capacity and cost | trend; near the configured max |
| `CurrConnections`, `NewConnections` | connection churn (no pooling) | new/curr high |
| `Evictions`, `DatabaseMemoryUsagePercentage` | memory pressure evicting live data | evictions > 0 sustained |
| `EngineCPUUtilization` (node-based), `ThrottledCmds` (serverless) | hot keys / big commands | throttled > 0 |
| `SuccessfulReadRequestLatency`, `SuccessfulWriteRequestLatency` p99 | slow cache | p99 > 5 ms |

## MSK / Kafka (`AWS/Kafka`)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `SumOffsetLag`, `MaxOffsetLag`, `EstimatedMaxTimeLag` (Consumer Group, Topic) | consumers behind | time lag > 300 s |
| `UnderReplicatedPartitions`, `OfflinePartitionsCount` (provisioned) | broker/AZ problems | > 0 |
| `BytesInPerSec`, `BytesOutPerSec`, `MessagesInPerSec` | throughput vs broker/partition limits | near limits |
| `FetchThrottleTime`, `ProduceThrottleTime`, `ThrottledRequests` (serverless quotas) | clients throttled | > 0 |
| `ActiveControllerCount`, `ZooKeeperSessionState` (legacy) / KRaft controller metrics | cluster control health | controller != 1 |
| Consumer app: `kafka_messages_consumed_total`, rebalance count in logs | rebalance storms | rebalances > 3/h |

## AWS Batch

| Metric | Source | Meaning when bad | Threshold |
| --- | --- | --- | --- |
| Job state counts: `RUNNABLE` age | Batch API / EventBridge `Batch Job State Change` | jobs stuck runnable = compute environment cannot place | runnable > 10 min |
| `FAILED` jobs with `statusReason` | EventBridge → SNS (`06-batch.yaml BatchJobFailedRule`) | app or infra failure | any |
| `DesiredvCpus`, `MaxvCpus` usage (compute environment) | Batch API | at the ceiling | desired = max |
| Job runtime vs `attemptDurationSeconds` | job metadata | approaching timeout | > 80% |

## Delivery and platform controllers

| Metric | Source | Meaning when bad | Threshold |
| --- | --- | --- | --- |
| `argocd_app_info{sync_status,health_status}` | Argo CD Prom | apps `OutOfSync`/`Degraded` | degraded > 10 min |
| `argocd_app_reconcile` duration, `argocd_app_sync_total{phase="Failed"}` | Argo CD Prom | slow/failed syncs | failed > 0 |
| Argo Rollouts `rollout_phase`, analysis run results | Prom | aborted rollouts | aborted → notify |
| `keda_scaler_errors_total`, `keda_scaler_metrics_value`, `keda_scaled_object_errors_total` | KEDA Prom | scaler cannot read SQS; value used for the HPA | errors > 0 |
| `kyverno_policy_results_total{rule_result="fail"}` / Gatekeeper violations | Prom | admission denials | unexpected fails |
| Jenkins queue length, executor saturation, agent launch failures | Jenkins Prom plugin | builds waiting on capacity | queue > 5 for 10 min |
| DORA: deployment frequency, lead time, change failure rate, time to restore | pipeline events (EventBridge/CodePipeline, GitHub) | delivery health | trend per quarter |

## Observability pipeline itself

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `otelcol_receiver_accepted_spans`, `otelcol_receiver_refused_spans` | collector refusing data (memory_limiter) | refused > 0 |
| `otelcol_processor_dropped_spans`, `otelcol_exporter_send_failed_spans`, `otelcol_exporter_queue_size` | data loss on the way to X-Ray/AMP | dropped/failed > 0; queue near capacity |
| `fluentbit_output_proc_records_total`, `fluentbit_output_errors_total`, `fluentbit_output_retries_failed_total` | log shipping failing | errors/failed retries > 0 |
| CloudWatch `IncomingLogEvents`/`IncomingBytes` per log group | log volume and cost | anomaly |
| X-Ray / Application Signals: `Fault`, `Error`, `Latency` per service/operation; SLO attainment and burn rate | service map health | burn rate > 14.4 (1 h) / 6 (6 h) |

## Application (shopfront `/metrics`, labs/CONTRACT.md §6)

| Metric | Meaning when bad | Threshold |
| --- | --- | --- |
| `http_requests_total{method,route,status}` | per-route traffic and errors | 5xx ratio > 1% |
| `http_request_duration_seconds` histogram | per-route latency | p99 > route budget |
| `orders_created_total`, `orders_fulfilled_total`, `orders_failed_total` | business flow; created − fulfilled growing = backlog | failed rate > 1% |
| `catalog_cache_hits_total`, `catalog_cache_misses_total` | cache effectiveness | hit ratio < 80% |
| `sqs_messages_received_total`, `kafka_messages_consumed_total` | consumer throughput | 0 while queue depth > 0 |
| `processing_duration_seconds` (worker) | per-message time vs visibility timeout | p99 > timeout/6 |
| Process metrics (`process_resident_memory_bytes`, event-loop lag for Node, GC pause for JVM) | runtime health | Node event-loop lag > 100 ms |
