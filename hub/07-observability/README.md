# 07 · Observability

Observability is how you know what a container platform is doing without logging into it: logs,
metrics, traces and events collected from the control planes (ECS, EKS), the data planes (nodes,
tasks, pods), the network (load balancers, DNS, CNI) and the applications, turned into dashboards,
alarms and answers. AWS offers several overlapping tool families — CloudWatch (Logs, Metrics,
Container Insights with enhanced observability, Application Signals, Transaction Search,
Synthetics), the AWS Distro for OpenTelemetry, X-Ray, Amazon Managed Service for Prometheus and
Amazon Managed Grafana, OpenSearch — plus the open-source agents (Fluent Bit/FireLens, the CloudWatch
agent, the OpenTelemetry collector, kube-state-metrics, node exporter). This domain owns the tool
choices, the collection architecture, the catalogue of metrics that matter for every component in
this repository, and alerting design. It uses the `shopfront` telemetry contract from
[`labs/CONTRACT.md`](../../labs/CONTRACT.md) §6: `/metrics` on every service, JSON logs with
`trace_id`, OTLP traces propagated through HTTP, SQS attributes and Kafka headers.

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 Observability basics](L100-observability-basics.md) | Logs, metrics, traces and events; CloudWatch's building blocks; `awslogs`; what Container Insights shows; the first five things to look at when a container is unhealthy |
| 200 | [L200 Tooling on AWS](L200-tooling-on-aws.md) | Container Insights (enhanced), CloudWatch agent vs Fluent Bit/FireLens vs ADOT, OpenTelemetry, X-Ray and its OTel direction, Application Signals and Transaction Search, AMP and AMG, kube-state-metrics/metrics-server, OpenSearch, log routing and retention, control-plane logs, alarms and a starter dashboard |
| 300 | [L300 Metrics that matter and alerting](L300-metrics-that-matter-and-alerting.md) | The per-component metrics catalogue with meaning and starting thresholds; RED/USE/golden signals; SLOs and burn-rate alerts; anomaly detection; alarm hygiene |
| 400 | [L400 Observability at scale](L400-observability-at-scale.md) | OpenTelemetry pipeline design, context propagation across queues, cardinality and cost control, central observability across accounts, synthetics, profiling, audit analytics, eBPF, observability for DR and on-call design |

## Components covered

- Signals and their AWS homes: CloudWatch Logs (groups, streams, Logs Insights, metric filters,
  subscription filters), CloudWatch Metrics (namespaces, dimensions, statistics, EMF), X-Ray traces,
  EventBridge events — L100 §2, L200 §2.1
- Container Insights and Container Insights with enhanced observability for EKS and ECS (metrics,
  performance log events, cost) — L100 §2.4, L200 §2.2, L300 §2
- Agents: CloudWatch agent (`amazon-cloudwatch-observability` add-on), Fluent Bit (`aws-for-fluent-bit`)
  as DaemonSet and as FireLens sidecar, AWS Distro for OpenTelemetry collector (sidecar, DaemonSet,
  gateway), Fargate logging on EKS (`aws-observability` namespace) — L200 §2.3
- OpenTelemetry: SDKs, auto-instrumentation, OTLP, collector receivers/processors/exporters, resource
  attributes, sampling — L200 §2.4, L400 §2.1
- AWS X-Ray (service map, traces, the X-Ray SDK/daemon migration to OpenTelemetry) — L200 §2.5
- CloudWatch Application Signals (auto-instrumentation, service map, SLOs) and Transaction Search
  (100% span ingestion as logs) — L200 §2.6
- Amazon Managed Service for Prometheus (remote write, alert manager, rules) and Amazon Managed
  Grafana (data sources, SSO) — L200 §2.7
- Kubernetes metrics sources: metrics-server, kube-state-metrics, node exporter, cAdvisor via kubelet,
  control-plane `/metrics`, CoreDNS and VPC CNI exporters — L200 §2.8, L300 §2.1–2.5
- ECS metrics: `AWS/ECS`, `ECS/ContainerInsights`, Service Connect metrics, `AWS/ECS/ManagedScaling`,
  task metadata stats — L300 §2.6
- Load balancer, NAT, Resolver, ECR (CloudTrail), SQS, RDS/Aurora, ElastiCache Valkey, MSK, AWS Batch
  metrics — L300 §2.7–2.12
- Golden signals, RED, USE; SLOs, error budgets, multi-window burn-rate alerts; anomaly detection;
  composite alarms; alarm hygiene — L300 §2.13–2.16
- OpenSearch for logs, log routing patterns and retention/cost controls — L200 §2.9
- EKS control-plane logs, ECS service events and task state change events — L200 §2.10
- Pipeline design (agent vs gateway collectors, tail sampling, batching), cardinality control, EMF,
  cross-account observability, Synthetics canaries, profiling, audit analytics, Hubble, DR and
  on-call design, DORA/SRE metrics — L400

## Related

- Labs: [`labs/local/otel-collector.yaml`](../../labs/local/otel-collector.yaml) and Jaeger at
  `http://localhost:16686` after `make up`; `/metrics` on ports 8080–8083;
  [`labs/eks/addons/adot-collector.yaml`](../../labs/eks/addons/adot-collector.yaml);
  [`labs/ecs/cloudformation/05-observability.yaml`](../../labs/ecs/cloudformation/05-observability.yaml)
  (Container Insights, log groups, alarms, dashboard); the ADOT sidecar in
  [`labs/ecs/taskdefs/orders.json`](../../labs/ecs/taskdefs/orders.json).
- Playbooks: every incident playbook starts from a signal in this domain —
  [OOM and CPU throttling](../../playbooks/incidents/oom-and-cpu-throttling.md),
  [DNS failures](../../playbooks/incidents/dns-failures.md),
  [ALB 5xx and unhealthy targets](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md),
  [Queue backlog and consumer lag](../../playbooks/incidents/queue-backlog-and-consumer-lag.md),
  [Node not ready](../../playbooks/incidents/node-not-ready.md).
- Reference: [metrics catalog](../../reference/metrics-catalog.md) (the full table this domain
  explains), [decision guides](../../reference/decision-guides.md) (X-Ray SDK vs OpenTelemetry,
  CloudWatch vs Prometheus/Grafana), [CLI cheat sheet](../../reference/cli-cheatsheet.md).
- Neighbouring domains: [03 ECS](../03-ecs/README.md) and [04 EKS](../04-eks/README.md) for what the
  components are, [05 Networking](../05-networking/README.md) for load balancer and DNS metrics,
  [09 Data, messaging and batch](../09-data-messaging-and-batch/README.md) for the data-tier
  metrics, [10 Resilience and DR](../10-resilience-and-dr/README.md) for what alarms should trigger,
  [11 Testing workloads](../11-testing-workloads/README.md) for validating dashboards under load.
