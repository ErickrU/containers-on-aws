# 11 · Testing workloads

Testing a containerised workload means more than unit tests: the image must be built correctly, the
manifests and templates must be valid, the service must behave against real dependencies, the
deployment must survive rollouts and node loss, the platform must scale under load, and the whole
system must recover from faults you inject on purpose. This domain owns the test pyramid for
containers, the tools that validate images and infrastructure code offline (`kubeconform`,
`cfn-lint`, `hadolint`, `trivy`, `checkov`), integration testing with Docker Compose and
Testcontainers, ephemeral environments, load testing (k6, Locust, Artillery, Distributed Load Testing
on AWS), right-sizing, chaos with AWS FIS, and verification in production (canary analysis, synthetics,
DR tests, security scans). The repository's own `make check` and `make smoke` are the first two rungs.

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 Testing basics](L100-testing-basics.md) | The pyramid for container services; unit vs integration with Compose; container structure tests; health endpoint tests; smoke tests after deploy |
| 200 | [L200 Testing in pipelines and clusters](L200-testing-in-pipelines-and-clusters.md) | Testcontainers, Compose in CI, LocalStack/ElasticMQ, contract tests, ephemeral environments per PR, kind, manifest/template validation, load tools, test data |
| 300 | [L300 Performance and chaos testing](L300-performance-and-chaos-testing.md) | Load test design (open/closed models, SLO thresholds, soak/spike/capacity), right-sizing with VPA and Compute Optimizer, Graviton benchmarking, AWS FIS experiments, Litmus/Chaos Mesh, dependency failure injection, game days |
| 400 | [L400 Verification at scale](L400-verification-at-scale.md) | Testing in production (canaries, shadow traffic, synthetics), continuous verification with Argo Rollouts and ECS lifecycle hooks, DR tests, security testing (kube-bench, Inspector, Trivy Operator, pen tests), compliance as code, metrics-driven quality gates, anti-patterns |

## Components covered

- Test pyramid for containers: unit, component, integration, contract, end-to-end, smoke — L100 §2.1
- Docker Compose as the integration harness; `make smoke` — L100 §2.2–2.3, L200 §2.2
- Container structure tests (user, entrypoint, labels, no shell) and image tests — L100 §2.4
- Health endpoint tests and readiness semantics — L100 §2.5
- Testcontainers (Go, Node, Python) — L200 §2.1
- LocalStack and ElasticMQ for AWS API stand-ins — L200 §2.3
- Contract tests (Pact, schema registry compatibility) — L200 §2.4
- Ephemeral environments: namespace per PR on EKS, service per PR on ECS, preview URLs — L200 §2.5
- kind/minikube for Kubernetes logic — L200 §2.6
- Validation tooling: `kubeconform`, `kube-linter`, `cfn-lint`, `hadolint`, `trivy` (image, config,
  fs), `checkov`, `conftest`, `helm lint`/`helm template` — L200 §2.7
- Load tools: k6, Locust, Artillery, Distributed Load Testing on AWS — L200 §2.8, L300 §2.1
- Load test design: open vs closed models, SLO-based thresholds, warm-up, soak, spike, capacity
  tests that measure HPA/Karpenter/ECS scaling reaction — L300 §2.1–2.3
- Right-sizing: VPA recommendations, Compute Optimizer for Fargate/EC2, requests vs usage — L300 §2.4
- Graviton vs x86 benchmarking — L300 §2.5
- Chaos: AWS FIS (ECS, EKS, EC2, RDS, network), Litmus, Chaos Mesh, DNS and dependency failure
  injection, game days — L300 §2.6–2.8
- Production testing: canary analysis, shadow/mirrored traffic, synthetics — L400 §2.1–2.2
- Continuous verification: Argo Rollouts AnalysisTemplates, ECS lifecycle hooks with test suites —
  L400 §2.3
- DR tests, security tests (kube-bench, Inspector, Trivy Operator, ZAP, pen tests), compliance as
  code (Config, Security Hub, Kyverno reports) — L400 §2.4–2.6
- Metrics-driven quality gates and anti-patterns — L400 §2.7–2.8

## Related

- Labs: [`labs/local/smoke.sh`](../../labs/local/smoke.sh), unit tests in
  [`labs/apps/catalog/`](../../labs/apps/catalog/), [`labs/apps/orders/`](../../labs/apps/orders/),
  [`labs/apps/worker/`](../../labs/apps/worker/), [`labs/apps/report-job/`](../../labs/apps/report-job/);
  the repository's [`tools/check.sh`](../../tools/check.sh); pipelines in
  [`labs/pipelines/`](../../labs/pipelines/); the canary rollout in
  [`labs/eks/gitops/rollout-orders-canary.yaml`](../../labs/eks/gitops/rollout-orders-canary.yaml).
- Playbooks: [Game-day guide](../../playbooks/dr/game-day-guide.md),
  [ECS deployment stuck or rolled back](../../playbooks/incidents/ecs-deployment-stuck-or-rolled-back.md),
  [OOM and CPU throttling](../../playbooks/incidents/oom-and-cpu-throttling.md).
- Reference: [metrics catalog](../../reference/metrics-catalog.md), [CLI cheat sheet](../../reference/cli-cheatsheet.md).
- Neighbouring domains: [08 Delivery](../08-delivery-cicd-gitops/README.md) (where tests run),
  [10 Resilience and DR](../10-resilience-and-dr/README.md) (what chaos and DR tests prove),
  [07 Observability](../07-observability/README.md) (the metrics that judge a test),
  [06 Identity and security](../06-identity-and-security/README.md) (security tests),
  [01 Container fundamentals](../01-container-fundamentals/README.md) (right-sizing mechanics).
