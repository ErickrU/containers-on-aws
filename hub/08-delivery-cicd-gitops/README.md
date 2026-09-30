# 08 · Delivery: CI/CD and GitOps

Delivery is everything between a commit and a running container: building and scanning the image,
pushing it to ECR, deciding which revision runs where, moving traffic to it safely, and undoing it
when the signals say so. On AWS that involves several tool families that overlap in confusing ways
(GitHub Actions, CodePipeline/CodeBuild/CodeDeploy, Jenkins, Argo CD, Argo Rollouts, Flux, the EKS
Capability for Argo CD) and two orchestrators with different deployment primitives (ECS deployment
strategies with circuit breakers, blue/green, canary and lifecycle hooks; Kubernetes rolling
updates with PDBs, readiness gates and progressive-delivery controllers). This domain owns the
pipeline, the deployment mechanics and the platform-engineering practices that let many teams
deliver without a central queue. Everything uses `shopfront` from
[`labs/CONTRACT.md`](../../labs/CONTRACT.md) and the pipelines in [`labs/pipelines/`](../../labs/pipelines/).

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 CI/CD basics](L100-cicd-basics.md) | The build → test → scan → push → deploy chain; tags vs digests; environments and promotion; CI vs CD vs GitOps; where Jenkins, GitHub Actions, CodePipeline and Argo CD each fit |
| 200 | [L200 Pipelines on AWS](L200-pipelines-on-aws.md) | GitHub Actions with OIDC to AWS (no stored keys), CodePipeline/CodeBuild/CodeDeploy, Jenkins on EKS and ECS, in-cluster builds, Helm and Kustomize, Argo CD basics and the EKS Capability, ECR lifecycle in pipelines |
| 300 | [L300 Progressive delivery and GitOps internals](L300-progressive-delivery-and-gitops-internals.md) | ECS deployment strategies in depth vs Kubernetes rolling updates; Argo Rollouts and Flagger; feature flags; database migrations; Argo CD and Jenkins internals; supply-chain steps in the pipeline; pipeline security |
| 400 | [L400 Platform engineering and delivery at scale](L400-platform-engineering-and-delivery-at-scale.md) | Golden paths, multi-cluster GitOps, policy in the pipeline, release trains, DR of the delivery system, SLSA, build performance and cost, DORA metrics, anti-patterns |

## Components covered

- Pipeline stages: build (BuildKit, multi-arch), test, scan (Trivy/Grype, Inspector), SBOM,
  sign (Notation/Signer, cosign), push (ECR by digest), deploy, verify — L100 §2, L200 §2.1, L300 §2.7
- GitHub Actions: OIDC federation to AWS, trust policy conditions, SHA-pinned actions, environments
  and protection rules, reusable workflows — L200 §2.2
- AWS CodePipeline, CodeBuild (`buildspec.yml`), CodeDeploy for ECS blue/green vs native ECS
  strategies, CodeConnections to GitHub — L200 §2.3
- Jenkins: controller on EKS or ECS, Kubernetes plugin pod templates, ECS Fargate agents plugin,
  JCasC, shared libraries, credentials, controller HA and backup — L200 §2.4, L300 §2.6
- In-cluster and hosted builds: BuildKit, kaniko, CodeBuild, GitHub-hosted and self-hosted runners
  (Actions Runner Controller on EKS) — L200 §2.5
- Packaging: Helm charts and values, Kustomize bases and overlays, image tag/digest bumps — L200 §2.6
- Argo CD: Application, AppProject, sync policies, health, sync waves and hooks, App of Apps,
  ApplicationSet generators, image updater, SSO/RBAC, notifications; the EKS Capability for Argo
  CD (managed, off-cluster) — L200 §2.7, L300 §2.5, L400 §2.2
- Flux (mention and comparison) — L200 §2.7
- ECS deployments: rolling (`minimumHealthyPercent`/`maximumPercent`), deployment circuit breaker,
  CloudWatch alarm rollback, native blue/green, canary/linear with bake time, lifecycle hooks,
  pause/continue, CodeDeploy legacy — L300 §2.1
- Kubernetes rolling updates: `maxSurge`/`maxUnavailable`, `minReadySeconds`, `progressDeadlineSeconds`,
  PDBs, readiness gates (`pod-readiness-gate-inject`) — L300 §2.2
- Argo Rollouts (canary and blue/green with ALB traffic routing, AnalysisTemplates against
  CloudWatch/Prometheus), Flagger — L300 §2.3
- Feature flags with AWS AppConfig; database migrations in pipelines (expand/contract) — L300 §2.4
- Secrets in GitOps: External Secrets Operator, Sealed Secrets, Secrets Store CSI — L300 §2.5
- Pipeline security: least-privilege deploy roles, OIDC, artifact immutability, environment
  protection, provenance — L300 §2.8
- Platform engineering: golden paths, templates, developer portals (Backstage), multi-cluster
  GitOps topologies (hub-and-spoke, per-cluster, EKS Capability), policy as code in pipelines,
  release trains, SLSA levels, build caches and Graviton builders, DORA metrics — L400

## Related

- Labs: [`labs/pipelines/github-actions/`](../../labs/pipelines/github-actions/) (`ci.yml`,
  `deploy-ecs.yml`, `deploy-eks.yml`), [`labs/pipelines/jenkins/`](../../labs/pipelines/jenkins/)
  (`Jenkinsfile`, `jcasc.yaml`, Helm values), [`labs/pipelines/codepipeline/`](../../labs/pipelines/codepipeline/)
  (`buildspec.yml`, `pipeline.yaml`), [`labs/eks/gitops/`](../../labs/eks/gitops/) (Argo CD
  project, applications, ApplicationSet, Argo Rollouts canary), [`labs/ecs/cloudformation/04-services.yaml`](../../labs/ecs/cloudformation/04-services.yaml)
  (deployment configuration).
- Playbooks: [ECS deployment stuck or rolled back](../../playbooks/incidents/ecs-deployment-stuck-or-rolled-back.md),
  [Upgrade breakage](../../playbooks/incidents/upgrade-breakage.md),
  [Image pull failures](../../playbooks/incidents/image-pull-failures.md),
  [IAM AccessDenied from containers](../../playbooks/incidents/iam-accessdenied-from-containers.md)
  (deploy roles), [Cluster rebuild runbook](../../playbooks/dr/cluster-rebuild-runbook.md).
- Reference: [decision guides](../../reference/decision-guides.md) (Jenkins vs Argo CD vs
  CodePipeline vs GitHub Actions), [CLI cheat sheet](../../reference/cli-cheatsheet.md) (`argocd`,
  `helm`, `kustomize`), [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md).
- Neighbouring domains: [01 Container fundamentals](../01-container-fundamentals/README.md) (image
  hardening and supply chain), [02 ECR](../02-ecr/README.md) (registry policies and replication),
  [03 ECS](../03-ecs/README.md) and [04 EKS](../04-eks/README.md) (the deployment targets),
  [06 Identity and security](../06-identity-and-security/README.md) (deploy roles, admission),
  [11 Testing workloads](../11-testing-workloads/README.md) (tests inside pipelines).
