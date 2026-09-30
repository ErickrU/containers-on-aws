# Delivery pipelines for shopfront

Three implementations of the same pipeline, so you can compare the tools on identical work
(hub/08). All of them: run the unit tests, build the four images for `linux/amd64` and
`linux/arm64` with BuildKit, attach SBOM and provenance attestations, push to ECR by tag, scan the
pushed digest and fail on fixable CRITICAL/HIGH findings, then deploy by re-running the
`04-services` CloudFormation stack (ECS) or by bumping image digests in git for Argo CD (EKS).

| Directory | Tool | Runs where | Identity to AWS | Deploy step |
| --- | --- | --- | --- | --- |
| `github-actions/` | GitHub Actions | GitHub-hosted runners | OIDC federation to an IAM role (no keys); `sub` bound to the repo, branch or environment | `deploy-ecs.yml`: CloudFormation; `deploy-eks.yml`: digest bump PR for Argo CD |
| `jenkins/` | Jenkins on EKS | Ephemeral agent pods (Kubernetes plugin) | Pod Identity on the agent ServiceAccount | Jenkinsfile stage → CloudFormation |
| `codepipeline/` | CodePipeline + CodeBuild | AWS managed | Service roles | CloudFormation deploy action |

## Files

- `github-actions/ci.yml` — lint, tests, multi-arch build with registry cache in ECR, SBOM +
  provenance, Trivy → code scanning, keyless cosign signature and SBOM attestation, digests as
  artifacts. Every action pinned to a commit SHA.
- `github-actions/deploy-ecs.yml` — environment-gated deploy: verifies the images exist, refuses
  active CRITICAL findings from ECR enhanced scanning, deploys `04-services` with the rollback
  alarms, waits for `services-stable`, smoke-tests through the ALB.
- `github-actions/deploy-eks.yml` — resolves tag → digest for the four images, `kustomize edit set image`
  in the chosen overlay, validates the render with kubeconform, opens a pull request.
- `jenkins/Jenkinsfile` — declarative pipeline with one pod template (tools, go, node, python,
  rootless BuildKit, trivy). `jenkins/jcasc.yaml` — controller configuration as code (OIDC login,
  role strategy, Kubernetes cloud, GitHub App credential from Secrets Manager, seed job).
  `jenkins/jenkins-values.yaml` — Helm values (pinned plugins, encrypted gp3 persistence, internal
  ALB, ephemeral agents in their own namespace).
- `codepipeline/pipeline.yaml` — CloudFormation for the pipeline (V2, queued execution, path
  filters), the CodeBuild project (ARM64, privileged for BuildKit), the deploy role and failure
  alerting. `codepipeline/buildspec.yml` — the build.

## Try them without an AWS account

```bash
.venv/bin/cfn-lint labs/pipelines/codepipeline/pipeline.yaml
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.12 -color labs/pipelines/github-actions/*.yml
```

The Jenkinsfile can be linted against a running controller with
`curl -X POST -F "jenkinsfile=<labs/pipelines/jenkins/Jenkinsfile" https://jenkins.shopfront.example.com/pipeline-model-converter/validate`.

## What to compare (hub/08 L400 §2.6 has the decision record)

Time from push to running task; where credentials live; what happens when the runner dies mid-build;
how a rollback is expressed; how many components you operate. GitHub Actions has the least to run
and the widest ecosystem, Jenkins the most control and the most to maintain, CodePipeline the
tightest IAM integration and the least portability.
