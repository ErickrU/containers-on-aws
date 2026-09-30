# DNS failures: NXDOMAIN, SERVFAIL, timeouts, slow first requests, CoreDNS restarts, Cloud Map TTLs

**Applies to:** both · **Severity guide:** SEV1 when service-to-service calls fail cluster-wide; SEV2 for intermittent timeouts · **Time to first fix:** 10–30 min

## Symptoms

- Applications log `getaddrinfo ENOTFOUND catalog`, `dial tcp: lookup catalog.shopfront.svc.cluster.local: i/o timeout`, `Temporary failure in name resolution`, `NXDOMAIN`, `SERVFAIL`.
- Latency histograms show a 5 s step (one UDP timeout) or 2.5 s (`timeout:2 attempts:...`) on a fraction of requests; the "slow first request" pattern.
- CoreDNS pods restarting or `OOMKilled`; `coredns_dns_request_duration_seconds` p99 climbs; `coredns_forward_responses_total{rcode="SERVFAIL"}` grows.
- ECS: `Service Connect` or Cloud Map names resolve to IPs of tasks that no longer exist (TTL) or not at all (`NXDOMAIN` for `catalog` outside the namespace).

## Triage in five minutes

```bash
# 1. Reproduce from inside a pod/task, against each resolver in the chain
kubectl -n shopfront run dnsdbg --rm -it --restart=Never --image=public.ecr.aws/docker/library/busybox:1.37 -- sh -c \
  'cat /etc/resolv.conf; nslookup catalog; nslookup catalog.shopfront.svc.cluster.local; nslookup sqs.us-east-1.amazonaws.com; nslookup example.com'
#   cluster name fails, external works  -> CoreDNS/kube-dns Service or NetworkPolicy
#   external fails, cluster works       -> CoreDNS upstream (Route 53 Resolver 169.254.169.253 / VPC +2) or egress policy
#   both intermittent                   -> conntrack/UDP or CoreDNS overload
aws ecs execute-command --cluster shopfront-dev --task <task-arn> --container orders --interactive --command "sh -c 'cat /etc/resolv.conf; getent hosts catalog; getent hosts catalog.shopfront.local'"

# 2. CoreDNS health and error rate
kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide
kubectl -n kube-system logs -l k8s-app=kube-dns --since=10m | grep -iE 'SERVFAIL|i/o timeout|refused|plugin/errors|loop' | tail -20
kubectl -n kube-system port-forward svc/kube-dns 9153:9153 & sleep 1; curl -s localhost:9153/metrics | grep -E 'coredns_dns_responses_total|coredns_forward_requests_total|coredns_panics_total|process_resident' | head -20

# 3. Does every node reach the CoreDNS pod IPs (UDP and TCP 53)? kube-proxy/NetworkPolicy/security groups
kubectl -n kube-system get endpointslices -l k8s-app=kube-dns -o jsonpath='{range .items[*].endpoints[*]}{.addresses[0]}{" ready="}{.conditions.ready}{"\n"}{end}'
kubectl -n shopfront get networkpolicy allow-dns -o yaml | sed -n '/spec:/,$p'

# 4. conntrack and UDP drops on a node (classic race with parallel A/AAAA queries)
kubectl debug node/<node> -it --image=public.ecr.aws/amazonlinux/amazonlinux:2023 -- chroot /host sh -c \
  'conntrack -S 2>/dev/null | head -3; cat /proc/sys/net/netfilter/nf_conntrack_count /proc/sys/net/netfilter/nf_conntrack_max; nstat -az | grep -iE "UdpInErrors|UdpRcvbufErrors|InsertFailed"'

# 5. Resolver throttling from the ENI (1024 packets/s per ENI to the VPC resolver) and Route 53 Resolver query logs
aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name ... 2>/dev/null   # no direct metric: use VPC Resolver query logging
aws route53resolver list-resolver-query-log-configs --query 'ResolverQueryLogConfigs[*].[Name,DestinationArn,Status]'

# 6. ECS/Cloud Map: what does the namespace hold right now?
aws servicediscovery discover-instances --namespace-name shopfront.local --service-name catalog --query 'Instances[*].[InstanceId,Attributes.AWS_INSTANCE_IPV4,HealthStatus]'
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **`ndots:5` turns every external name into 5 cluster lookups first** | `resolv.conf` `options ndots:5`; CoreDNS logs many `NXDOMAIN` for `sqs.us-east-1.amazonaws.com.shopfront.svc.cluster.local` | Use FQDNs with a trailing dot in config (`sqs.us-east-1.amazonaws.com.`), or `dnsConfig: {options: [{name: ndots, value: "2"}]}` on pods that mostly call external names; CoreDNS `autopath` reduces the round trips (hub/04 L300 §2.5) |
| **UDP conntrack race: parallel A and AAAA on the same socket, one reply dropped** | `InsertFailed` counter grows; 5 s stalls on ~0.1–1% of lookups | `single-request-reopen` in `dnsConfig.options` (glibc); NodeLocal DNSCache (TCP to CoreDNS, cache on node); disable IPv6 lookups in the app when unused |
| **CoreDNS overloaded** | CPU at limit, p99 latency high, `SERVFAIL` on upstream timeouts; 2 replicas for 500 nodes | Add-on autoscaling (`coredns-configuration-values.json`), NodeLocal DNSCache, `cache 30` with `prefetch`; raise the memory limit if OOMKilled |
| **Upstream (VPC resolver) throttled: 1024 pps per ENI** | High query volume from a few nodes; `SERVFAIL`/timeouts only for external names | NodeLocal DNSCache to spread load across nodes' ENIs; caching; move `forward` to Route 53 Resolver endpoints only if you need on-prem names |
| **NetworkPolicy blocks DNS** | Cluster names fail only in namespaces with default-deny; `allow-dns` missing or wrong pod selector for CoreDNS (`k8s-app: kube-dns`) | Add the egress rule to `kube-system` pods with `k8s-app: kube-dns` on UDP and TCP 53 (`labs/eks/manifests/base/networkpolicies.yaml`) |
| **Security group blocks 53 between node groups or to the CNI** | Cross-node lookups fail; same-node works | Cluster security group must allow all traffic between nodes (default); custom node SGs need UDP/TCP 53 |
| **CoreDNS on a node with a broken CNI** | Some queries fail: endpoints on a NotReady node still listed | Fix the node (see node-not-ready); `readinessProbe` and `lameduck` keep bad instances out |
| **Corefile `loop` detected** | CoreDNS `CrashLoopBackOff` with `Loop ... detected for zone "."` | Node `resolv.conf` points to `127.0.0.53` (systemd-resolved): set `--resolv-conf=/run/systemd/resolve/resolv.conf` in kubelet or `forward . 169.254.169.253` |
| **Private hosted zone not associated with the VPC / split-horizon** | Name resolves publicly but not from the VPC (or vice versa) | Associate the zone with the VPC; for VPC endpoints ensure private DNS is on |
| **Headless Service or StatefulSet name misuse** | `catalog` resolves to many A records (headless) and clients cache one | Use a ClusterIP Service for load-balanced access; headless only when you want per-pod addresses |
| **ECS Cloud Map TTL serves stale IPs** | `discover-instances` shows fewer IPs than DNS returns; clients cached 60 s records | Lower TTL (10 s) on the Cloud Map service, prefer Service Connect (proxy-based, no client caching problem), or client-side retries (hub/03 L300 §2.7) |
| **ECS Service Connect name unresolvable from a non-member service** | `NXDOMAIN` for `catalog` from a task outside the namespace/Service Connect | Add the client service to the same namespace with `ServiceConnectConfiguration.Enabled: true` (client-only mode, as `fulfillment-worker` in `04-services.yaml`) |
| **Service Connect alias resolves but connect refused** | Envoy agent container unhealthy; port name mismatch | `PortName` in `Services[]` must match the `portMappings[].name`; check the `service-connect` log group |
| **Application caches DNS forever (JVM `networkaddress.cache.ttl`, Node `dns.lookup` results held by a pool)** | Traffic still goes to old IPs after a rollout | JVM: `-Dsun.net.inetaddr.ttl=30`; use connection pools with max lifetime; prefer Service/ALB in front |

## Verify the fix

```bash
# 100 lookups, none slower than 100 ms:
kubectl -n shopfront run dnsbench --rm -it --restart=Never --image=public.ecr.aws/docker/library/busybox:1.37 -- sh -c \
  'for i in $(seq 1 100); do s=$(date +%s%N); nslookup catalog >/dev/null 2>&1 || echo FAIL; e=$(date +%s%N); echo $(( (e-s)/1000000 )); done | sort -n | tail -3'
kubectl -n kube-system port-forward svc/kube-dns 9153:9153 & sleep 1; curl -s localhost:9153/metrics | grep 'coredns_dns_request_duration_seconds_bucket{server="dns://:53",zone=".",le="0.1"}'
```

## Prevent it

- CoreDNS add-on autoscaling, `cache 30` + `prefetch`, `lameduck 5s`, PDB, spread across zones (`coredns-configuration-values.json`).
- NodeLocal DNSCache on clusters above ~100 nodes or with DNS-heavy workloads; `ndots` tuned per workload.
- Trailing dots for AWS endpoints in configuration; SDKs with connection reuse so DNS is not on the hot path.
- Alarms: `coredns_dns_request_duration_seconds` p99 > 100 ms, `coredns_forward_responses_total{rcode="SERVFAIL"}` rate, CoreDNS restarts, `pod_status_pending` for CoreDNS itself.

## Related

- Mechanism: [04 L200 CoreDNS and kube-proxy](../../hub/04-eks/L200-cluster-components-and-add-ons.md), [04 L300 CoreDNS internals and failure modes](../../hub/04-eks/L300-eks-internals-and-operations.md), [05 L300 kube-proxy modes and conntrack](../../hub/05-networking/L300-container-networking-internals.md), [03 L300 Service Connect and Cloud Map](../../hub/03-ecs/L300-ecs-internals.md)
- Neighbours: [alb-5xx-and-unhealthy-targets.md](alb-5xx-and-unhealthy-targets.md), [node-not-ready.md](node-not-ready.md)
- Reference: [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md), [metrics catalog](../../reference/metrics-catalog.md)
