# Containers on AWS — a 100→400 knowledge hub

Everything that sits between "I can run a container on my laptop" and "I design container
platforms for a company": the container itself (images, containerd, runc, the kernel), Amazon ECR,
Amazon ECS (Fargate, EC2, Managed Instances, Express Mode, Service Connect, Cloud Map), Amazon EKS
(control plane, kubelet, kube-proxy, CoreDNS, VPC CNI, Cilium, Auto Mode, managed node groups,
Fargate, Karpenter, IRSA and Pod Identity, the AWS Load Balancer Controller), VPC networking for
containers (ELB, ingress, link-local addresses, IMDSv2, PrivateLink), identity and security,
observability (CloudWatch, Container Insights, OpenTelemetry, X-Ray, Prometheus/Grafana), delivery
(GitHub Actions, Jenkins, CodePipeline, Argo CD, progressive delivery), the stateful neighbours
(RDS, ElastiCache Valkey, SQS, MSK/Kafka, AWS Batch), resilience and disaster recovery, testing
workloads, and the Well-Architected Framework applied to all of it.

Every topic is written at four depths. Every level answers the same questions: why it exists, how
it works, how it interacts with everything else, when to use it and when not to, how it fails, what
to measure, how to test it, what disaster recovery means for it, and which Well-Architected pillar
it touches. One runnable system (`shopfront`) runs through every lab.

## The level ladder

| Level | You are | You get | Start |
| --- | --- | --- | --- |
| **100 Foundations** | new to the component | precise vocabulary, the problem it solves, first commands | [Path 100](LEARNING_PATHS.md#path-100--foundations) |
| **200 Building** | shipping services with it | every field and flag that matters, wiring to neighbours, the first ten mistakes | [Path 200](LEARNING_PATHS.md#path-200--building) |
| **300 Operating** | on call for it | internals (processes, packets, API calls, timing, limits), forensics, tuning | [Path 300](LEARNING_PATHS.md#path-300--operating) |
| **400 Designing** | building a platform for many teams | architecture at scale, cost and trade-offs with numbers, DR, failure stories | [Path 400](LEARNING_PATHS.md#path-400--designing) |

Levels live **inside each domain** (`hub/<domain>/L100…L400`), so you can go deep on one topic or
sweep one level across all topics with [LEARNING_PATHS.md](LEARNING_PATHS.md).

## The domain map

| # | Domain | What lives here |
| --- | --- | --- |
| 01 | [Container fundamentals](hub/01-container-fundamentals/) | images, OCI, Docker, containerd, runc, namespaces/cgroups, Firecracker, Bottlerocket, hardening, supply chain, performance |
| 02 | [Amazon ECR](hub/02-ecr/) | repositories, auth, lifecycle, scanning, pull-through cache, replication rules, endpoints, quotas, signing |
| 03 | [Amazon ECS](hub/03-ecs/) | task definitions, services, Fargate/EC2/Managed Instances/Express Mode, Service Connect, Cloud Map, deployments, agent internals, scale |
| 04 | [Amazon EKS](hub/04-eks/) | control plane, kubelet, kube-proxy, CoreDNS, VPC CNI, add-ons, node groups, Fargate, Auto Mode, Karpenter, LB controller, Cilium, Capabilities, Hybrid Nodes |
| 05 | [Networking](hub/05-networking/) | VPC design, ALB/NLB, ingress, Gateway API, discovery, link-local addresses, IMDSv2, IP math, network policies, PrivateLink, Lattice, mesh |
| 06 | [Identity and security](hub/06-identity-and-security/) | task/execution roles, IRSA vs Pod Identity, access entries, secrets, PSS, admission, signing, GuardDuty, incident response |
| 07 | [Observability](hub/07-observability/) | CloudWatch, Container Insights, Fluent Bit/FireLens, ADOT/OpenTelemetry, X-Ray, Application Signals, AMP/AMG, the metrics that matter, SLOs |
| 08 | [Delivery: CI/CD and GitOps](hub/08-delivery-cicd-gitops/) | GitHub Actions + OIDC, CodePipeline, Jenkins on EKS/ECS, Argo CD, Argo Rollouts, ECS blue/green and canary, platform engineering |
| 09 | [Data, messaging and batch](hub/09-data-messaging-and-batch/) | RDS/Aurora, ElastiCache Valkey, SQS/SNS/EventBridge, MSK/Kafka, AWS Batch, KEDA, event-driven patterns |
| 10 | [Resilience and DR](hub/10-resilience-and-dr/) | multi-AZ, graceful shutdown, autoscaling layers, FIS, zonal shift, DR strategies, Velero, Route 53/ARC, the DR plan, game days |
| 11 | [Testing workloads](hub/11-testing-workloads/) | test pyramid, Testcontainers, ephemeral environments, k6/Locust, chaos with FIS, right-sizing, verification in production |
| 12 | [Well-Architected](hub/12-well-architected/) | six pillars for containers, Container Build Lens, ECS/EKS checklists, running a review, trade-offs and anti-patterns |

Beyond the hub:

- [`labs/`](labs/) — the `shopfront` system: five services (Go, Node.js, Python), PostgreSQL,
  Valkey, SQS, Kafka, S3, OpenTelemetry; runs locally with Compose; deploys to ECS
  (CloudFormation), EKS (eksctl + Kustomize + Helm + Argo CD) and AWS Batch; CI with GitHub
  Actions, Jenkins and CodePipeline. See [`labs/CONTRACT.md`](labs/CONTRACT.md).
- [`playbooks/`](playbooks/) — incident runbooks by symptom, DR plan and runbooks, upgrade runbooks.
- [`reference/`](reference/) — metrics catalog, ports and link-local addresses, service interaction
  map, decision guides, quotas, deprecation dates, CLI cheat sheet.
- [`GLOSSARY.md`](GLOSSARY.md) — one-line definitions.

## Quick start

Read: [LEARNING_PATHS.md](LEARNING_PATHS.md) → pick your level → follow the order.

Run the labs locally (Docker or Colima, Node 20+, Python 3.12, no AWS account needed):

```bash
make up          # PostgreSQL, Valkey, Kafka, ElasticMQ (SQS), OTel collector, Jaeger, five services
make smoke       # creates an order, watches it get fulfilled, checks cache/metrics/trace
open http://localhost:16686   # traces
make down
```

Deploying to AWS is always an explicit, separate step with a confirmation gate and a cost
warning; nothing in this repository deploys on its own. Check `aws sts get-caller-identity`
first and treat an unknown account as production.

## How to read a leveled document

Every `L100…L400` document has the same eleven sections, so you always know where to look:

1. Mental model · 2. Concepts · 3. How it interacts with the rest of AWS · 4. Use it when / avoid
it when · 5. Well-Architected view · 6. Failure modes and troubleshooting · 7. Signals: metrics,
logs, traces · 8. Testing and DR notes · 9. Hands-on · 10. Check yourself · 11. Sources.

Facts that change with time (versions, dates, feature availability) are pinned in
[`docs/FACTS-2026-09.md`](docs/FACTS-2026-09.md) and verified against primary documentation as of
September 2026. When you read this later, check that sheet first.

## Boundaries

- This is a study and reference hub with runnable teaching code, not a production platform.
- The labs favour visibility over completeness: single Region, small instance sizes, permissive
  local defaults. Production guidance is in the L300/L400 documents, not in the lab defaults.
- No real account identifiers, credentials or customer data appear anywhere. The only account ID
  is `123456789012`.

## Validation

```bash
make check       # heading structure, links, inclusive language, YAML/JSON, cfn-lint, kubeconform, shellcheck
```

## License

MIT — see [LICENSE](LICENSE).
