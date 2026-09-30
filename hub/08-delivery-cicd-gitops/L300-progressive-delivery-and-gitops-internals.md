# Delivery · L300 — Progressive delivery and GitOps internals

**Level:** 300 · **Time:** ~100 min · **Prerequisites:** [L200 Pipelines on AWS](L200-pipelines-on-aws.md),
[ECS L300](../03-ecs/L300-ecs-internals.md), [EKS L300](../04-eks/L300-eks-internals-and-operations.md)

**After this document you can:**

- Configure every ECS deployment strategy and predict its behaviour second by second, and do the
  same for a Kubernetes rolling update with PDBs and readiness gates.
- Run canary and blue/green with Argo Rollouts (ALB traffic routing, metric analysis) or Flagger.
- Ship database migrations and feature flags without breaking deployments.
- Explain how Argo CD and Jenkins work internally well enough to scale, secure and recover them.
- Put supply-chain and least-privilege controls into the pipeline where they cannot be skipped.

## 1. Mental model

```mermaid
sequenceDiagram
  autonumber
  participant G as git (digest bump)
  participant A as Argo CD application-controller
  participant K as API server
  participant R as Argo Rollouts controller
  participant ALB as ALB (weighted target groups)
  participant M as metrics (CloudWatch / Prometheus)
  G->>A: new commit (webhook or 3-min poll)
  A->>A: repo-server renders manifests; diff live vs desired
  A->>K: apply (server-side) Rollout object with new image digest
  K->>R: Rollout spec changed
  R->>K: create canary ReplicaSet (1 pod)
  R->>ALB: set weights: stable 95 / canary 5
  loop analysis
    R->>M: query error rate, p99 for canary
    M-->>R: values
  end
  alt analysis passes
    R->>ALB: 25 → 50 → 100; scale stable down
  else fails
    R->>ALB: weight canary 0; scale canary down (rollback)
  end
```

Progressive delivery replaces "deploy and hope" with "deploy a little, measure, continue or undo".
On ECS the machinery is inside the service scheduler (rolling parameters, circuit breaker, alarms,
native blue/green and canary with lifecycle hooks); on Kubernetes the Deployment controller does
rolling updates and a separate controller (Argo Rollouts, Flagger) does traffic-weighted canaries
with metric analysis. GitOps supplies the desired state; the controllers supply the steps; the
metrics supply the verdict. Understanding each controller's loop is what lets you set timeouts and
budgets that match reality.

## 2. Concepts

### 2.1 ECS deployment strategies in depth

| Strategy | Mechanism | Rollback trigger | Traffic control | Extra capacity |
| --- | --- | --- | --- | --- |
| Rolling (`ECS`) | scheduler starts new tasks up to `maximumPercent`, stops old ones keeping `minimumHealthyPercent` | circuit breaker (tasks failing to start/health), CloudWatch alarms | none (targets join as they become healthy) | up to `maximumPercent − 100` |
| Blue/green (`BLUE_GREEN`) | full green task set behind an alternate target group; test listener; production listener rule switched | lifecycle hook failure, alarms during `bakeTimeInMinutes`, manual `stop-service-deployment --stop-type ROLLBACK` | all-or-nothing at the listener rule | 100% |
| Canary / linear | green set receives a percentage of production traffic for a bake period, then the rest | same as blue/green plus alarm evaluation during canary | weighted forwarding on the production listener rule (as low as 0.1%) | 100% |
| CodeDeploy (`CODE_DEPLOY`) | external controller drives task sets and listener rules | CodeDeploy alarms/hooks | CodeDeploy configs (linear/canary) | 100% |
| `EXTERNAL` | you manage task sets and traffic | yours | yours | yours |

Rolling timeline with `desiredCount 4`, `100/200`, health check grace 60 s, deregistration 20 s:
t=0 register revision; scheduler starts 4 new tasks (PROVISIONING → PENDING → ACTIVATING);
~60–90 s new tasks healthy in the target group; scheduler stops 4 old tasks (draining 20 s, SIGTERM,
`stopTimeout` 30); ~2–3 minutes total. Circuit breaker threshold = max(10, min(200, desiredCount ×
0.5)) failed tasks (verify the exact formula); with `rollback: true` a failure redeploys the last
steady revision automatically and the deployment reports `ROLLBACK_SUCCESSFUL`.

Blue/green with hooks: `PRE_SCALE_UP` → green tasks start → `POST_SCALE_UP` → test listener routes
to green → `TEST_TRAFFIC_SHIFT`/`POST_TEST_TRAFFIC_SHIFT` (run synthetic tests against the test
listener from a Lambda hook; return `FAILED` to abort) → production shift (`PRODUCTION_TRAFFIC_SHIFT`,
`POST_PRODUCTION_TRAFFIC_SHIFT`) → bake with alarms → blue tasks stopped (`RECONCILE_SERVICE`).
Canary adds a weighted step before the full shift; pause/continue lets an operator hold at any stage.
`describe-service-deployments` and `describe-service-revisions` expose the state machine; the
console shows it in real time (2026-09). Configuration examples: [ECS L200 §2.8](../03-ecs/L200-task-definitions-services-and-scaling.md).

Alarm design for rollbacks: target 5xx rate (`HTTPCode_Target_5XX_Count / RequestCount` via metric
math), p99 latency, and an application-level error metric; 1-minute periods, 3 datapoints, `TREAT
MISSING DATA` as `notBreaching` for low-traffic services (or the alarm never resolves). Alarms must
cover the *new* revision: with blue/green use the green target group's metrics.

### 2.2 Kubernetes rolling updates

```yaml
spec:
  replicas: 6
  minReadySeconds: 10                  # a pod must be Ready for 10 s before it counts (catches crash-after-start)
  progressDeadlineSeconds: 600         # rollout marked failed (not rolled back) after 10 min without progress
  strategy: { type: RollingUpdate, rollingUpdate: { maxSurge: 25%, maxUnavailable: 0 } }
```

The Deployment controller creates a new ReplicaSet and scales it up while scaling the old one down,
never exceeding `replicas + maxSurge` nor dropping below `replicas − maxUnavailable` *Ready* pods.
Readiness is the gate: with the ALB readiness gate injected by the load balancer controller, Ready
also means "healthy in the target group", which closes the window where a pod receives traffic before
the ALB checked it ([05 L200 §2.3](../05-networking/L200-load-balancing-ingress-and-discovery.md)).
PDBs apply to evictions (drains, Karpenter), not to Deployment rollouts; rollouts respect
`maxUnavailable` instead. `progressDeadlineSeconds` sets a condition; automatic rollback needs Argo
Rollouts, Flagger or the GitOps layer (Argo CD does not roll back on unhealthy by itself; it reports
`Degraded`). `kubectl rollout undo` is the manual path; in GitOps, revert the commit instead.

Timeline for one pod replacement: new pod scheduled → containers start → `startupProbe` →
`readinessProbe` passes → ALB target registered and healthy (readiness gate) → pod Ready →
controller terminates an old pod → endpoints remove it (async) → `preStop` sleep 5 s → SIGTERM →
app drains → exit → ALB deregistration delay elapses. The `preStop` sleep exists because endpoint
removal and ALB deregistration are asynchronous; without it the pod stops accepting before some
clients learn it is gone.

### 2.3 Argo Rollouts and Flagger

Argo Rollouts replaces `Deployment` with a `Rollout` CRD and adds traffic routing and analysis:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata: { name: orders, namespace: shopfront }
spec:
  replicas: 6
  selector: { matchLabels: { app.kubernetes.io/name: orders } }
  template: { ... same pod template as the Deployment ... }
  strategy:
    canary:
      canaryService: orders-canary
      stableService: orders
      trafficRouting:
        alb:
          ingress: orders
          servicePort: 8080
          rootService: orders-root         # the Ingress points at this; Rollouts rewrites weights via annotations
      steps:
        - setWeight: 5
        - pause: { duration: 10m }
        - analysis: { templates: [{ templateName: orders-success-rate }], args: [{ name: tg, value: "targetgroup/k8s-shopfront-orderscanary-…" }] }
        - setWeight: 25
        - pause: { duration: 10m }
        - setWeight: 50
        - pause: { duration: 10m }
      analysis:                                # background analysis during the whole rollout
        templates: [{ templateName: orders-p99 }]
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata: { name: orders-success-rate, namespace: shopfront }
spec:
  args: [{ name: tg }]
  metrics:
    - name: success-rate
      interval: 1m
      count: 10
      successCondition: result[0] >= 0.99
      failureLimit: 2
      provider:
        cloudWatch:
          interval: 5m
          metricDataQueries:
            - id: ok
              metricStat: { metric: { namespace: AWS/ApplicationELB, metricName: HTTPCode_Target_2XX_Count, dimensions: [{ name: TargetGroup, value: "{{args.tg}}" }, { name: LoadBalancer, value: "app/shopfront-dev/50dc6c495c0c9188" }] }, period: 300, stat: Sum }
            - id: total
              metricStat: { metric: { namespace: AWS/ApplicationELB, metricName: RequestCount, dimensions: [{ name: TargetGroup, value: "{{args.tg}}" }, { name: LoadBalancer, value: "app/shopfront-dev/50dc6c495c0c9188" }] }, period: 300, stat: Sum }
            - id: rate
              expression: "ok / total"
```

Mechanics: the controller manages two ReplicaSets and two Services; with the ALB provider it writes
the `alb.ingress.kubernetes.io/actions.<rootService>` annotation with weighted forward to the two
target groups, and the load balancer controller applies the weights. Analysis runs queries
(CloudWatch, Prometheus/AMP, Datadog, web hooks, Kubernetes Jobs) and aborts the rollout on failure
(scales the canary down, restores weights), which is the automatic rollback Kubernetes lacks.
Blue/green (`strategy.blueGreen` with `activeService`/`previewService`, `autoPromotionEnabled: false`)
switches the Service selector. Flagger does the same with a `Canary` CRD wrapping an existing
Deployment and supports more meshes/ingresses; both need metrics that separate canary from stable
(per target group, or labels in Prometheus). Canary math (minimum requests to detect a regression)
is in [ECS L400 §2.4](../03-ecs/L400-ecs-at-scale.md) and applies unchanged.

### 2.4 Feature flags and database migrations

**Feature flags** separate deploy from release: code ships dark, AWS AppConfig (or an in-house
flag service) turns it on per segment with its own rollout strategy (`AppConfig.Linear50PercentEvery30Seconds`),
bake time and CloudWatch alarm rollback. The application reads flags through the AppConfig agent
sidecar or the SDK with caching; flag evaluation is milliseconds and does not require a deployment
to undo.

**Migrations** must be backward compatible with the revision still running during a rollout
(expand/contract): add nullable columns and new tables first (expand), deploy code that writes both
shapes, backfill, then deploy code that reads the new shape, then drop the old (contract) in a later
release. Run migrations as a step before the rollout: ECS `run-task` with the same image and a
`migrate` command gated in the pipeline; Kubernetes `Job` as an Argo CD `PreSync` hook
(`argocd.argoproj.io/hook: PreSync`, `hook-delete-policy: HookSucceeded`). Never run migrations in
the application's start-up path of every replica (lock contention, partial failures). The shopfront
`db-migrate` one-shot in Compose models the pattern.

### 2.5 Argo CD internals

| Component | Role | Scaling and operations |
| --- | --- | --- |
| `argocd-repo-server` | clones repos, renders Kustomize/Helm, caches | CPU-bound; scale replicas; cache in Redis; `--parallelism-limit` |
| `argocd-application-controller` | reconciles Applications: refresh (3 min default or webhook), diff, sync | shard by cluster (`--sharding-method`), one shard per StatefulSet replica; watch load grows with cluster size |
| `argocd-server` | API/UI/CLI, SSO (OIDC/Dex), RBAC (`argocd-rbac-cm`) | stateless; scale for users |
| `argocd-redis` | cache of manifests and cluster state | ephemeral; losing it only costs recomputation |
| `argocd-applicationset-controller` | renders ApplicationSets from generators | one instance |
| `argocd-notifications-controller` | Slack/PagerDuty on sync/health events | templates + triggers |
| Argo CD Image Updater | writes new image digests/tags back to git | alternative to CI committing |

Sync mechanics: `apply` (server-side apply recommended) in waves (`argocd.argoproj.io/sync-wave`),
hooks (`PreSync`, `Sync`, `PostSync`, `SyncFail`), health assessment per resource kind (custom health
checks in Lua for CRDs), pruning of removed resources, self-heal reverting live drift. State that is
not in git: cluster and repository credentials (Secrets in the `argocd` namespace), SSO configuration
(`argocd-cm`, `argocd-rbac-cm`), notifications config — all reproducible from a bootstrap
Application except the credentials, which come from a secrets manager. The EKS Capability runs these
components as a managed service; you keep the `Application`/`AppProject` objects and an
`argocd-cm` for tuning.

Secrets in GitOps: External Secrets Operator (`ExternalSecret` → Kubernetes Secret from Secrets
Manager/SSM, refresh interval), Secrets Store CSI driver (mounted files, no Secret object unless
synced), Sealed Secrets (encrypted values in git decryptable only by the cluster's controller;
rotation and key management are yours). Prefer ESO or CSI so git holds references, not ciphertext.

### 2.6 Jenkins internals

The controller keeps job definitions (from `Jenkinsfile` in git, discovered by Multibranch
Pipeline/Organization folders), build history and credentials in `JENKINS_HOME`; executors on the
controller should be zero so every build runs on an agent. Agents connect inbound (JNLP/WebSocket) or
are launched by the cloud plugin; the Kubernetes plugin creates one pod per build from a pod
template (`containers`, `serviceAccount`, `nodeSelector`, `yamlMergeStrategy`), and the `container()`
step switches the executing container. Shared libraries (`@Library`) centralise the pipeline steps
(build/scan/sign/push/deploy) so each `Jenkinsfile` is a few lines. Credentials binding injects
secrets as environment variables masked in logs; better, agents get AWS access through Pod Identity
and Jenkins holds nothing. Controller recovery: `JENKINS_HOME` snapshots (EFS/EBS) plus JCasC and
`plugins.txt`; a controller can be rebuilt from image + JCasC in minutes, losing only build history.
Upgrade cadence: LTS controller every quarter, plugins pinned and updated together, tested on a
staging controller.

### 2.7 Supply chain in the pipeline

Where each control lives so it cannot be skipped:

| Control | Enforced by | Bypass risk |
| --- | --- | --- |
| SHA-pinned actions/plugins/base images | code review + Dependabot/Renovate | a maintainer can unpin; branch protection with required reviews |
| Scan gate | pipeline step with `--exit-code 1` | `continue-on-error`; protect the workflow file with CODEOWNERS |
| SBOM + provenance | `buildx --sbom --provenance` or attestation actions | none if admission requires provenance |
| Signature | `notation sign`/`cosign sign` with the pipeline's identity | none if admission requires it (EKS) / verify step before `register-task-definition` (ECS) |
| Deploy by digest | pipeline resolves digest; admission rejects tags | manual deploys outside the pipeline: remove human `UpdateService`/`kubectl` write access |
| Environment separation | roles bound to `environment:prod`; required reviewers | same identity for dev and prod |
| Immutable artifacts | ECR tag immutability | mutable tags |

### 2.8 Pipeline security

- One deploy role per environment and per target type; ECS roles get `iam:PassRole` scoped to the
  exact task/execution roles; GitOps CI roles get no cluster access at all.
- `sub` conditions on the OIDC trust policy; no `repo:*`; reject pull-request tokens for any role
  that can write.
- Ephemeral runners/agents; no Docker daemon exposure; no long-lived credentials in pipeline secrets.
- Workflow and Jenkinsfile changes reviewed by CODEOWNERS; branch protection; signed commits where
  the organisation requires them.
- Logs redacted; build artifacts stored immutably; audit CloudTrail for `AssumeRoleWithWebIdentity`
  from unexpected `sub` values.

## 3. How it interacts with the rest of AWS

| Component | Talks to | Protocol/API | Prerequisite (IAM, network, DNS) | What breaks if missing |
| --- | --- | --- | --- | --- |
| ECS blue/green | ELB listener rules, target groups | ECS infrastructure role modifies rules | `roleArn` in `advancedConfiguration` with `elasticloadbalancing:ModifyRule`… | deployment fails before shifting traffic |
| ECS lifecycle hooks | Lambda | invoke with deployment context | hook role `lambda:InvokeFunction`; Lambda returns `hookStatus` | hook `FAILED` → rollback, or timeout |
| Alarm rollback | CloudWatch | `DescribeAlarms` by service-linked role | alarm names exist, cover the new target group | no rollback on errors |
| Argo Rollouts | ALB via load balancer controller | Ingress annotations | controller version supports weighted actions; readiness gates | weights not applied; canary receives no traffic |
| Analysis provider | CloudWatch / AMP | `GetMetricData` / remote read | Rollouts controller role via Pod Identity | analysis `Error` → rollout aborted |
| AppConfig | application | agent sidecar/SDK polling | role with `appconfig:StartConfigurationSession`, `GetLatestConfiguration` | flags stale/unavailable (fail to defaults) |
| Argo CD | git, clusters | HTTPS | repo credentials; cluster access entries | `Unknown` apps |
| Migrations job | RDS | DB credentials via Secrets/IAM auth | SG from job to DB | rollout blocked on `PreSync` |

## 4. Use it when / avoid it when

Use:

- Rolling with circuit breaker + alarms as the default on ECS; blue/green or canary with hooks for
  tier-1 services.
- `maxUnavailable: 0` + readiness gates + `preStop` on every Kubernetes HTTP service; Argo Rollouts
  canary with CloudWatch/AMP analysis for tier-1.
- Feature flags for behaviour changes; expand/contract for schema changes.
- Argo CD sharding and repo-server scaling once Applications exceed a few hundred.

Avoid:

- Canary bake times chosen by feel (derive from traffic and effect size).
- Migrations at application start-up.
- Argo CD `selfHeal` with humans still running `kubectl apply` in production (they will fight).
- Sealed Secrets when a managed secrets store is available.

Alternatives: AWS AppConfig-driven dark launches instead of canary infrastructure for behaviour
changes; ECS Express Mode for services that accept AWS-managed rolling defaults.

## 5. Well-Architected view

| Pillar | Contribution | Cost | Practice |
| --- | --- | --- | --- |
| Operational Excellence | deterministic rollouts, automated rollback, GitOps audit trail | controller operations | strategy per service tier; runbooks per failure state |
| Security | signatures/provenance gates, scoped roles, no human write path | policy work | admission requires signature + digest; CODEOWNERS on pipelines |
| Reliability | bake time, analysis, PDBs, readiness gates, expand/contract | slower releases | alarm coverage of new revisions; migration hooks |
| Performance Efficiency | canary sized to traffic; surge capacity planned | extra capacity during rollouts | `maxSurge` and `maximumPercent` sized |
| Cost Optimization | blue/green doubles capacity briefly | short duration | keep bake times honest |
| Sustainability | fewer failed deployments and rebuilds | none | promotion by digest |

## 6. Failure modes and troubleshooting

| Symptom | Likely cause | How to confirm (command/metric) | Fix |
| --- | --- | --- | --- |
| ECS deployment `IN_PROGRESS` for 30+ minutes | tasks never healthy; capacity; `maximumPercent` 100 on a full cluster | service events; `describe-service-deployments` | ([playbook](../../playbooks/incidents/ecs-deployment-stuck-or-rolled-back.md)) |
| Blue/green fails at `TEST_TRAFFIC_SHIFT` | hook Lambda error/timeout; test listener SG | hook Lambda logs; deployment `statusReason` | fix hook; allow test listener |
| Canary receives no traffic (Rollouts) | ALB weights not written; controller version | Ingress annotations; load balancer controller logs | upgrade controller; check `rootService` |
| Analysis `Error` instead of `Failed` | metrics query permission or empty data | `kubectl describe analysisrun` | Pod Identity for Rollouts; `TREAT MISSING` semantics |
| Rollout stuck `Progressing`, `ProgressDeadlineExceeded` | new pods never Ready (probe/image/policy) | `kubectl describe pod`, events | fix cause; rollout does not auto-revert |
| 502s during Kubernetes rollout | no readiness gate; no `preStop`; app closes early | ALB 502 aligned with rollout | readiness gate + `preStop` + drain ([playbook](../../playbooks/incidents/alb-5xx-and-unhealthy-targets.md)) |
| Argo CD app `Degraded` after sync | health check for a CRD unknown; Job failed | app resource tree | custom health check; fix hook |
| Argo CD slow to sync at scale | single controller shard; repo-server CPU | controller metrics `argocd_app_reconcile` | shard controller; scale repo-server |
| Migration hook blocks every deploy | long migration in `PreSync` | hook Job logs | run heavy backfills out of band; keep hooks short |
| Jenkins agent cannot push after controller move | credentials in `JENKINS_HOME` lost; Pod Identity association missing | agent logs | Pod Identity; JCasC for credentials references |

## 7. Signals: metrics, logs, traces

- ECS: `DeploymentCount`, deployment duration (from `describe-service-deployments` timestamps),
  rollback count by reason (circuit breaker vs alarm vs hook), task start failures during rollouts.
- Kubernetes: rollout duration (`kube_deployment_status_observed_generation` vs generation),
  `kube_deployment_status_condition{condition="Progressing",status="false"}`,
  `kube_pod_container_status_waiting_reason` during rollouts.
- Argo Rollouts: `rollout_info` phase, `analysis_run_metric_phase` failures, `rollout_reconcile`
  errors.
- Argo CD: `argocd_app_info{sync_status,health_status}`, `argocd_app_sync_total{phase="Failed"}`,
  `argocd_app_reconcile` histogram, repo-server CPU.
- Jenkins: queue time, build duration, agent launch failures.
- Release metrics: lead time, deployment frequency, change failure rate, time to restore (DORA).

Full table: [`reference/metrics-catalog.md`](../../reference/metrics-catalog.md).

## 8. Testing and DR notes

Testing: rehearse every strategy against a staging copy with load running: deploy a revision that
fails `/readyz` (circuit breaker/analysis must roll back), one that returns 5xx for 2% of requests
(alarm/analysis must catch it within the bake), one that is slow (latency alarm); test lifecycle
hooks by returning `FAILED`; drain a node during a rollout to confirm PDB + `maxUnavailable: 0`
interplay; run the migration hook against a snapshot of production data for timing. Keep these as a
pipeline stage in staging ([11 L400](../11-testing-workloads/L400-verification-at-scale.md)).

DR: deployment configuration is in IaC (ECS) or git (Kubernetes). Argo CD in the DR Region needs
cluster/repo credentials recreated (or the EKS Capability enabled); Rollouts/analysis providers need
their roles; alarms referenced by ECS deployments must exist per Region with Region-specific ARNs;
AppConfig environments are regional. Add them to the [cluster rebuild runbook](../../playbooks/dr/cluster-rebuild-runbook.md).

## 9. Hands-on

```bash
# ECS: deployment configuration and alarms in the services stack
grep -nE 'DeploymentConfiguration|CircuitBreaker|Alarms|Strategy|BakeTime|LifecycleHooks' labs/ecs/cloudformation/04-services.yaml
# (billable) force a rollback: register a revision with a wrong CATALOG_URL so /readyz stays 200 but orders fail,
# and watch the 5xx alarm roll it back
aws ecs describe-service-deployments --cluster shopfront-dev --service orders --query 'serviceDeployments[:3].{status:status,reason:statusReason,started:startedAt}'

# Kubernetes: rollout parameters and readiness gates
grep -nE 'maxSurge|maxUnavailable|minReadySeconds|preStop|terminationGracePeriodSeconds' labs/eks/manifests/base/deployment-orders.yaml
kubectl -n shopfront get ns shopfront -o jsonpath='{.metadata.labels}' ; echo   # pod-readiness-gate-inject

# Argo Rollouts canary example (labs/eks/gitops/rollout-orders-canary.yaml)
kubeconform -strict -ignore-missing-schemas labs/eks/gitops/rollout-orders-canary.yaml
kubectl argo rollouts get rollout orders -n shopfront --watch          # after installing Argo Rollouts + plugin
kubectl argo rollouts set image orders orders=123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders@sha256:<new-digest> -n shopfront
# Observe: weight 5 → pause → analysis → 25 → 50 → 100; abort with `kubectl argo rollouts abort orders`.

# Argo CD: sync waves and hooks in the manifests
grep -rn 'argocd.argoproj.io/' labs/eks/manifests/ labs/eks/gitops/ | head
```

## 10. Check yourself

1. Why does a PodDisruptionBudget not protect you during a Deployment rollout, and what does?

<details><summary>Answer</summary>
PDBs constrain voluntary evictions (drains, Karpenter consolidation, `kubectl drain`), not the
Deployment controller's replacement of pods, which is governed by `maxUnavailable`/`maxSurge` and
readiness. Set `maxUnavailable: 0`, use readiness gates so Ready means healthy at the ALB, and set
`minReadySeconds` so a pod that crashes seconds after start does not count as progress.
</details>

2. How does Argo Rollouts move 5% of traffic to a canary on an ALB, and what must be true for the
   analysis to compare canary with stable?

<details><summary>Answer</summary>
It creates a canary ReplicaSet and Service, then writes an `actions.<rootService>` annotation on the
Ingress that the load balancer controller turns into a weighted forward rule across two target
groups. Analysis needs metrics separable by target group (CloudWatch `TargetGroup` dimension) or by
pod labels (Prometheus), and enough requests during the bake to make the comparison statistically
meaningful.
</details>

3. What does the ECS deployment circuit breaker detect that alarm-based rollback does not, and vice
   versa?

<details><summary>Answer</summary>
The circuit breaker detects tasks that fail to reach a running, healthy state (image pull errors,
crashes, failed health checks) by counting failed task launches. Alarm rollback detects tasks that
run and pass health checks but degrade service (5xx, latency, business errors) by watching CloudWatch
alarms during the deployment and bake. You want both.
</details>

4. Describe expand/contract for renaming a column used by `orders`.

<details><summary>Answer</summary>
Expand: add the new column (nullable) and deploy code that writes both old and new columns and reads
the old; backfill existing rows in batches out of band. Switch: deploy code that reads the new column
(still writing both). Contract: after all old revisions are gone and data is verified, deploy code
that writes only the new column, then drop the old column in a later migration. Each step is
compatible with the revision running beside it during a rollout.
</details>

5. Which Argo CD state is not in git and how do you recover it in a new cluster?

<details><summary>Answer</summary>
Repository and cluster credentials (Secrets in the `argocd` namespace), SSO/RBAC ConfigMaps if not
bootstrapped from git, notification settings, and the Redis cache (disposable). Recover by
installing Argo CD (or enabling the EKS Capability), creating credentials from a secrets manager via
IaC, then applying the bootstrap Application (App of Apps/ApplicationSet) that recreates every
Application from git.
</details>

## 11. Sources

- Amazon ECS deployment types, blue/green, lifecycle hooks, circuit breaker — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-types.html and https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-blue-green.html
- Amazon ECS rollback with CloudWatch alarms — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-alarm-failure.html
- Kubernetes Deployments: rolling update strategy, progress deadline — https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- Kubernetes pod lifecycle and termination — https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
- Argo Rollouts: canary, ALB traffic routing, analysis (CloudWatch provider) — https://argo-rollouts.readthedocs.io/en/stable/ and https://argo-rollouts.readthedocs.io/en/stable/analysis/cloudwatch/
- Flagger — https://docs.flagger.app/
- AWS AppConfig feature flags and deployment strategies — https://docs.aws.amazon.com/appconfig/latest/userguide/what-is-appconfig.html
- Argo CD architecture, sync phases and waves, high availability — https://argo-cd.readthedocs.io/en/stable/operator-manual/architecture/ and https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/
- External Secrets Operator — https://external-secrets.io/latest/
- Jenkins Kubernetes plugin and shared libraries — https://plugins.jenkins.io/kubernetes/ and https://www.jenkins.io/doc/book/pipeline/shared-libraries/
- SLSA and Sigstore for CI — https://slsa.dev/ and https://docs.sigstore.dev/
- Expand/contract (parallel change) pattern — https://martinfowler.com/bliki/ParallelChange.html
