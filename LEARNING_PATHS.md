# Learning paths

Four ordered paths, one per level. Each path sweeps a level across the twelve domains in an order
where every document builds on the previous ones, adds the labs that exercise it, and ends with
checkpoint questions you should be able to answer without looking. Reading times are the estimates
at the top of each document; labs add hands-on time on top. The levels themselves are defined in
[`docs/STYLE_GUIDE.md`](docs/STYLE_GUIDE.md) §2.

How to use a path: read in order, run the lab when the path says so, answer the checkpoints, then
move to the next level of the domains you work with most instead of finishing every domain at the
next level. Depth per domain matters more than breadth per level once you are past 200.

## Path 100 — Foundations

**For:** you have run `docker run`, you have an AWS account, and you are new to running containers
in production. **Time:** ~7.5 h of reading plus ~2 h of labs.

| Step | Read | Min | Then |
| --- | --- | --- | --- |
| 1 | [Containers explained](hub/01-container-fundamentals/L100-containers-explained.md) | 40 | build one image: `docker build -t shopfront/catalog:dev labs/apps/catalog` and inspect its layers |
| 2 | [ECR basics](hub/02-ecr/L100-ecr-basics.md) | 35 | |
| 3 | [ECS basics](hub/03-ecs/L100-ecs-basics.md) | 45 | read [`labs/ecs/taskdefs/orders.json`](labs/ecs/taskdefs/orders.json) with the field table in [`labs/ecs/taskdefs/README.md`](labs/ecs/taskdefs/README.md) |
| 4 | [Kubernetes and EKS basics](hub/04-eks/L100-kubernetes-and-eks-basics.md) | 45 | read [`labs/eks/manifests/base/deployment-orders.yaml`](labs/eks/manifests/base/deployment-orders.yaml) next to the task definition and map the fields |
| 5 | [VPC for containers](hub/05-networking/L100-vpc-for-containers.md) | 45 | |
| 6 | [Security basics for containers](hub/06-identity-and-security/L100-security-basics-for-containers.md) | 40 | |
| 7 | [Stateful dependencies](hub/09-data-messaging-and-batch/L100-stateful-dependencies.md) | 35 | **lab:** `make up && make smoke` ([`labs/README.md`](labs/README.md)); open Jaeger at `http://localhost:16686` and follow one order through orders → catalog → SQS → worker |
| 8 | [Observability basics](hub/07-observability/L100-observability-basics.md) | 30 | `curl localhost:8080/metrics`, `docker compose -f labs/local/compose.yaml logs orders` |
| 9 | [CI/CD basics](hub/08-delivery-cicd-gitops/L100-cicd-basics.md) | 30 | read [`labs/pipelines/github-actions/ci.yml`](labs/pipelines/github-actions/ci.yml) top to bottom |
| 10 | [Resilience basics](hub/10-resilience-and-dr/L100-resilience-basics.md) | 30 | `docker compose -f labs/local/compose.yaml kill catalog` while running `make smoke`; watch orders return 503 and recover |
| 11 | [Testing basics](hub/11-testing-workloads/L100-testing-basics.md) | 30 | run one unit test suite: `docker run --rm -v $PWD/labs/apps/report-job:/src -w /src python:3.12-slim-bookworm sh -c 'pip install -q -r requirements.txt pytest && pytest -q'` |
| 12 | [Pillars for containers](hub/12-well-architected/L100-pillars-for-containers.md) | 30 | |

**Checkpoint.** Explain, in your own words: the difference between an image and a container; what a
task definition and a Deployment have in common; where a Fargate task's private IP comes from;
why a container should never hold long-lived AWS keys; what `/healthz` and `/readyz` mean and why
they differ; the four DR strategies by name; what "multi-AZ by default" costs you and buys you.

## Path 200 — Building

**For:** you ship services on ECS or EKS and want every field and flag that matters, wired
correctly the first time. **Time:** ~15 h of reading plus ~4 h of labs (an AWS account is needed
for the ECS/EKS labs; costs apply, see [`labs/README.md`](labs/README.md)).

| Step | Read | Min | Then |
| --- | --- | --- | --- |
| 1 | [Images, builds and registries](hub/01-container-fundamentals/L200-images-builds-and-registries.md) | 75 | compare the four Dockerfiles in `labs/apps/*/Dockerfile`: multi-stage, pinned bases, non-root, PID 1 |
| 2 | [ECR lifecycle, scanning, access and endpoints](hub/02-ecr/L200-lifecycle-scanning-access-and-endpoints.md) | 60 | read the repositories and replication rule in [`labs/ecs/cloudformation/02-cluster.yaml`](labs/ecs/cloudformation/02-cluster.yaml) |
| 3 | [Task definitions, services and scaling](hub/03-ecs/L200-task-definitions-services-and-scaling.md) | 75 | **lab:** `CONFIRM_DEPLOY=yes labs/ecs/cloudformation/deploy.sh` (layers 01–05), push images, `deploy.sh migrate`, `curl http://<alb>/products` |
| 4 | [Load balancing, ingress and discovery](hub/05-networking/L200-load-balancing-ingress-and-discovery.md) | 75 | inspect the target group health and the Service Connect namespace from the ECS lab |
| 5 | [IAM for containers](hub/06-identity-and-security/L200-iam-for-containers.md) | 90 | run `aws sts get-caller-identity` from inside a task with ECS Exec; compare with the task role in `02-cluster.yaml` |
| 6 | [Cluster components and add-ons](hub/04-eks/L200-cluster-components-and-add-ons.md) | 90 | **lab:** `eksctl create cluster -f labs/eks/cluster/eksctl-standard.yaml`, then [`labs/eks/addons/README.md`](labs/eks/addons/README.md) steps 1–6 and `kubectl apply -k labs/eks/manifests/overlays/dev` |
| 7 | [Integration patterns](hub/09-data-messaging-and-batch/L200-integration-patterns.md) | 90 | watch KEDA scale `fulfillment-worker` while you POST orders; run `labs/batch/submit-report.sh` |
| 8 | [Observability tooling on AWS](hub/07-observability/L200-tooling-on-aws.md) | 75 | open the dashboard from `05-observability.yaml`; find the same order in X-Ray / Application Signals |
| 9 | [Pipelines on AWS](hub/08-delivery-cicd-gitops/L200-pipelines-on-aws.md) | 75 | run `ci.yml` on a fork with OIDC; apply [`labs/eks/gitops/application.yaml`](labs/eks/gitops/application.yaml) and let Argo CD take over |
| 10 | [Designing for failure](hub/10-resilience-and-dr/L200-designing-for-failure.md) | 75 | `aws ecs stop-task` one orders task under load (or `kubectl delete pod`) and read the ALB 5xx metric afterwards |
| 11 | [Testing in pipelines and clusters](hub/11-testing-workloads/L200-testing-in-pipelines-and-clusters.md) | 60 | `make check`; read what each validator catches |
| 12 | [Pillar checklists for ECS and EKS](hub/12-well-architected/L200-pillar-checklists-ecs-and-eks.md) | 60 | tick the checklist against the lab as deployed; note the gaps |
| 13 | tear down | | `labs/ecs/cloudformation/destroy.sh`, `eksctl delete cluster -f ...` |

**Checkpoint.** Write from memory: the ECS task definition fields that make a task safe to run
(user, read-only root, capabilities, init, health check, stop timeout, secrets) and their
Kubernetes equivalents; the two IAM roles of an ECS task and what each may do; how a pod gets AWS
credentials with Pod Identity; the three ECR-related VPC endpoints and why S3 is one of them; the
ALB health check settings and how they relate to `deregistration_delay` and `stopTimeout`; the
difference between a rolling deployment with a circuit breaker and one with alarm rollback; what
KEDA needs to scale on an SQS queue.

## Path 300 — Operating

**For:** you get paged for this platform. **Time:** ~20 h of reading, plus the runbooks, plus one
game day. Read the runbook next to each document; the document is the mechanism, the runbook is the
muscle memory.

| Step | Read | Min | Then |
| --- | --- | --- | --- |
| 1 | [Runtimes and the kernel](hub/01-container-fundamentals/L300-runtimes-and-the-kernel.md) | 120 | `docker run --memory=256m` a shopfront image and read `/sys/fs/cgroup/memory.max` from inside; runbook [oom-and-cpu-throttling](playbooks/incidents/oom-and-cpu-throttling.md), [crashloop-and-exit-codes](playbooks/incidents/crashloop-and-exit-codes.md) |
| 2 | [ECS internals](hub/03-ecs/L300-ecs-internals.md) | 90 | runbooks [ecs-task-stopped-reasons](playbooks/incidents/ecs-task-stopped-reasons.md), [ecs-deployment-stuck-or-rolled-back](playbooks/incidents/ecs-deployment-stuck-or-rolled-back.md); query `/shopfront/dev/ecs-events` |
| 3 | [EKS internals and operations](hub/04-eks/L300-eks-internals-and-operations.md) | 120 | runbooks [node-not-ready](playbooks/incidents/node-not-ready.md), [pending-pods-and-capacity](playbooks/incidents/pending-pods-and-capacity.md), [eks-auth-and-access](playbooks/incidents/eks-auth-and-access.md); `kubectl debug node/...` once |
| 4 | [Container networking internals](hub/05-networking/L300-container-networking-internals.md) | 120 | runbook [dns-failures](playbooks/incidents/dns-failures.md); table [ports, addresses and endpoints](reference/ports-addresses-and-endpoints.md); prove the IMDS hop limit from a pod |
| 5 | [Pull-through cache, replication and limits](hub/02-ecr/L300-pull-through-cache-replication-and-limits.md) | 90 | runbook [image-pull-failures](playbooks/incidents/image-pull-failures.md); table [quotas and limits](reference/quotas-and-limits.md) |
| 6 | [Hardening workloads and clusters](hub/06-identity-and-security/L300-hardening-workloads-and-clusters.md) | 100 | runbook [iam-accessdenied-from-containers](playbooks/incidents/iam-accessdenied-from-containers.md); quarantine a pod with the label in [`networkpolicies.yaml`](labs/eks/manifests/base/networkpolicies.yaml) |
| 7 | [Metrics that matter and alerting](hub/07-observability/L300-metrics-that-matter-and-alerting.md) | 100 | [metrics catalog](reference/metrics-catalog.md); read every alarm in [`05-observability.yaml`](labs/ecs/cloudformation/05-observability.yaml) and say why each threshold |
| 8 | [Messaging and data deep dive](hub/09-data-messaging-and-batch/L300-messaging-and-data-deep-dive.md) | 100 | runbook [queue-backlog-and-consumer-lag](playbooks/incidents/queue-backlog-and-consumer-lag.md); send a poison message locally and watch the DLQ |
| 9 | [Progressive delivery and GitOps internals](hub/08-delivery-cicd-gitops/L300-progressive-delivery-and-gitops-internals.md) | 100 | run the canary in [`rollout-orders-canary.yaml`](labs/eks/gitops/rollout-orders-canary.yaml) and abort it |
| 10 | [DR strategies for container platforms](hub/10-resilience-and-dr/L300-dr-strategies-for-container-platforms.md) | 90 | runbooks [data-recovery](playbooks/dr/data-recovery-runbook.md), [cluster-rebuild](playbooks/dr/cluster-rebuild-runbook.md); do a PITR restore in a sandbox |
| 11 | [Performance and chaos testing](hub/11-testing-workloads/L300-performance-and-chaos-testing.md) | 75 | **game day:** three scenarios from [game-day-guide](playbooks/dr/game-day-guide.md) with [`fis-stop-tasks.json`](labs/ecs/fis-stop-tasks.json) |
| 12 | [Running a review](hub/12-well-architected/L300-running-a-review.md) | 60 | review the lab as you left it after the game day |
| 13 | Upgrades | | [eks-version-upgrade](playbooks/upgrades/eks-version-upgrade.md), [addon-and-controller-upgrades](playbooks/upgrades/addon-and-controller-upgrades.md), [ecs-ami-agent-and-platform](playbooks/upgrades/ecs-ami-agent-and-platform.md); runbook [upgrade-breakage](playbooks/incidents/upgrade-breakage.md) |

**Checkpoint.** Given only the symptom, name the runbook and its first command for: `ImagePullBackOff`
with `403`; exit code 137 without `OOMKilled`; pods `Pending` with `Too many pods`; `SERVFAIL` on
external names only; 502s that align with deployments; `stoppedReason: ResourceInitializationError`;
`Unauthorized` from `kubectl` after a role change; queue age rising with `NotVisible` high. Then
explain the mechanism behind each in two sentences.

## Path 400 — Designing

**For:** you design the platform other teams build on. **Time:** ~16 h of reading plus the two
writing exercises. Every document ends in trade-offs; the exercises make you commit to some.

| Step | Read | Min | Then |
| --- | --- | --- | --- |
| 1 | [Trade-offs and anti-patterns](hub/12-well-architected/L400-trade-offs-and-anti-patterns.md) | 60 | read first: it frames every later choice; [decision guides](reference/decision-guides.md) |
| 2 | [Hardening, supply chain and performance](hub/01-container-fundamentals/L400-hardening-supply-chain-and-performance.md) | 100 | trace how `ci.yml` produces SBOM, provenance and a signature; decide what admission should verify |
| 3 | [Supply chain and multi-account registries](hub/02-ecr/L400-supply-chain-and-multi-account-registries.md) | 90 | draw the registry topology for three accounts and two Regions |
| 4 | [ECS at scale](hub/03-ecs/L400-ecs-at-scale.md) | 90 | |
| 5 | [EKS at scale](hub/04-eks/L400-eks-at-scale.md) | 90 | decide: one cluster or many, Auto Mode or Karpenter, for a stated organisation |
| 6 | [Network architecture at scale](hub/05-networking/L400-network-architecture-at-scale.md) | 75 | IP plan for 20 clusters; egress control design |
| 7 | [Security architecture and incident response](hub/06-identity-and-security/L400-security-architecture-and-incident-response.md) | 90 | threat model the shopfront platform; map controls to the pillars |
| 8 | [Observability at scale](hub/07-observability/L400-observability-at-scale.md) | 75 | design the collector topology and sampling for 200 services |
| 9 | [Platform engineering and delivery at scale](hub/08-delivery-cicd-gitops/L400-platform-engineering-and-delivery-at-scale.md) | 75 | write the golden path for a new service in one page |
| 10 | [Event-driven architecture at scale](hub/09-data-messaging-and-batch/L400-event-driven-architecture-at-scale.md) | 75 | outbox pattern for shopfront orders: sketch the tables and the relay |
| 11 | [The DR plan and game days](hub/10-resilience-and-dr/L400-dr-plan-and-game-days.md) | 75 | **exercise 1:** fill [dr-plan-template](playbooks/dr/dr-plan-template.md) for shopfront with real RTO/RPO numbers and the gaps you accept |
| 12 | [Verification at scale](hub/11-testing-workloads/L400-verification-at-scale.md) | 60 | **exercise 2:** define the quality gates from commit to production and where each metric comes from |
| 13 | Dates and limits | | [lifecycle and deprecations](reference/lifecycle-and-deprecations.md), [quotas and limits](reference/quotas-and-limits.md): which of these constrain your design in the next 12 months? |

**Checkpoint.** Defend, with numbers, a choice of Fargate vs Managed Instances vs Auto Mode for a
stated fleet; state the RTO and RPO your design supports per tier and what breaks them; name the
first three quotas you would raise in a new Region; describe how a compromised image would be
detected and how far it could get; list what is not in git in your platform and what you would do
about each item.

## After the paths

- Keep [`docs/FACTS-2026-09.md`](docs/FACTS-2026-09.md) honest: dates and versions move; the
  commands in [lifecycle and deprecations](reference/lifecycle-and-deprecations.md) re-verify them.
- Contribute: [CONTRIBUTING.md](CONTRIBUTING.md) explains the document template and `make check`.
- Vocabulary: [GLOSSARY.md](GLOSSARY.md).
