# 02 · Amazon ECR

Amazon Elastic Container Registry is where every image in this repository lives between `docker
push` and the moment a kubelet, an ECS agent, Fargate or Lambda pulls it. It looks like a plain
OCI registry, but almost everything that matters in production sits outside the registry protocol:
IAM tokens instead of passwords, repository and registry policies instead of accounts, lifecycle
and archive rules instead of manual clean-up, Inspector scanning, pull-through caches for
third-party images, cross-Region and cross-account replication, VPC endpoints for private pulls,
API quotas that decide whether a 1,000-node scale-out succeeds, and signatures that decide whether
a cluster is allowed to run what it pulled. ECR is its own domain because the registry is both a
hard runtime dependency (no pull, no scale-out, no recovery) and the natural control point of the
software supply chain. Terms are defined once in the [glossary](../../GLOSSARY.md).

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 · ECR basics](L100-ecr-basics.md) | Registry, repository, image, tag and digest; the URI; the 12-hour token and the credential helper; push and pull; a first lifecycle policy; what a registry costs |
| 200 | [L200 · Lifecycle, scanning, access and endpoints](L200-lifecycle-scanning-access-and-endpoints.md) | Lifecycle rules and their evaluation order, the archive storage class, tag immutability, basic vs enhanced scanning, identity vs repository vs registry policies, cross-account pulls from ECS, EKS and Lambda, KMS, VPC endpoints and endpoint policies |
| 300 | [L300 · Pull-through cache, replication and limits](L300-pull-through-cache-replication-and-limits.md) | The API calls behind a pull; pull-through cache rules end to end; replication rules and what they do not copy; quotas and throttling math; pull performance (layer parallelism, SOCI, timeouts); CloudTrail forensics |
| 400 | [L400 · Supply chain and multi-account registries](L400-supply-chain-and-multi-account-registries.md) | Central vs per-account topologies with numbers, org-wide replication, signing and verification at scale, policy as code, DR of the registry, three incident stories, cost at scale, migrating images with `crane` and `skopeo` |

## Components covered

- Private registry, repositories, namespaces, image manifests, indexes, tags, digests, URIs — L100
- ECR Public and the public gallery; unauthenticated vs authenticated pull rates — L100, L300
- Authentication: `GetAuthorizationToken`, the 12-hour token, `docker login --username AWS`, the
  `amazon-ecr-credential-helper`; how ECS, EKS and Lambda authenticate without a login — L100, L200
- Lifecycle policies: `rulePriority`, `tagStatus`, `tagPrefixList`, `tagPatternList`,
  `countType` (`imageCountMoreThan`, `sinceImagePushed`, `sinceImagePulled`,
  `sinceImageTransitioned`), `expire` vs `transition`, evaluation rules, preview — L100 (first
  policy), L200 (in depth)
- Archive storage class and restore — L200, L400
- Tag immutability and exclusion filters — L200
- Basic scanning (AWS native) vs enhanced scanning (Amazon Inspector); scan on push, continuous
  scanning, findings to EventBridge and Security Hub — L200
- Identity policies, repository policies, registry permissions, VPC endpoint policies, SCPs; the
  IAM action map; cross-account pulls from ECS, EKS and Lambda — L200, L400
- Encryption at rest: SSE-S3, SSE-KMS, grants, key policies, DSSE-KMS — L200
- VPC interface endpoints `ecr.api` and `ecr.dkr`, the S3 gateway endpoint, private DNS,
  dual-stack and FIPS endpoints — L200, L300
- Pull-through cache rules: upstream registries, Secrets Manager credentials, repository prefixes,
  first pull vs cached vs sync, referrer sync, repository creation templates, required IAM
  (`ecr:BatchImportUpstreamImage`, `ecr:CreateRepository`), ECR-to-ECR caching — L300
- Replication rules: cross-Region, cross-account, filters, destination registry policy
  (`ecr:ReplicateImage`), what is not replicated, timing, status API — L300, L400
- Service quotas and throttling; `AWS/Usage` metrics; pull performance, containerd and kubelet
  parallelism, Fargate pull behaviour, SOCI lazy loading, image pull timeouts — L300
- CloudTrail auditing: `BatchGetImage`, `PolicyExecutionEvent`, `ReplicateImage`,
  `BatchImportUpstreamImage`; EventBridge event types — L300
- Image signing: Notation with AWS Signer, ECR managed signing, cosign; verification at admission
  and in pipelines; OCI 1.1 referrers — L400 (mechanics of signing itself in
  [01 · L400](../01-container-fundamentals/L400-hardening-supply-chain-and-performance.md))
- Central vs per-account registries, hub-and-spoke replication, policy as code, registry DR,
  incident stories, cost model, `crane`/`skopeo` migrations, blob mounting — L400

## Related

- Labs: the `shopfront` images are built from `labs/apps/*/Dockerfile` and pushed to
  `123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/<service>` by
  [`labs/pipelines/github-actions/ci.yml`](../../labs/pipelines/github-actions/ci.yml) (multi-arch
  build, scan, SBOM, sign, push through OIDC). The ECS execution role and cluster live in
  [`labs/ecs/cloudformation/02-cluster.yaml`](../../labs/ecs/cloudformation/02-cluster.yaml); the
  VPC endpoints in [`labs/ecs/cloudformation/01-network.yaml`](../../labs/ecs/cloudformation/01-network.yaml).
  The service contract, including the tag policy (`sha-<gitsha>`, deploy by digest, `latest` is
  never deployed), is [`labs/CONTRACT.md`](../../labs/CONTRACT.md).
- Playbooks: [image pull failures](../../playbooks/incidents/image-pull-failures.md),
  [IAM AccessDenied from containers](../../playbooks/incidents/iam-accessdenied-from-containers.md),
  [ECS task stopped reasons](../../playbooks/incidents/ecs-task-stopped-reasons.md),
  [region failover runbook](../../playbooks/dr/region-failover-runbook.md),
  [cluster rebuild runbook](../../playbooks/dr/cluster-rebuild-runbook.md).
- Reference: [quotas and limits](../../reference/quotas-and-limits.md),
  [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md),
  [metrics catalog](../../reference/metrics-catalog.md),
  [decision guides](../../reference/decision-guides.md),
  [CLI cheat sheet](../../reference/cli-cheatsheet.md),
  [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md).
- Neighbouring domains: image internals and supply chain in
  [01 · Container fundamentals](../01-container-fundamentals/README.md); execution roles and
  Fargate pull behaviour in [03 · ECS](../03-ecs/README.md); node roles, kubelet credential
  provider and Auto Mode in [04 · EKS](../04-eks/README.md); PrivateLink and IP planning in
  [05 · Networking](../05-networking/README.md); IRSA, Pod Identity and admission control in
  [06 · Identity and security](../06-identity-and-security/README.md); pipelines that push here in
  [08 · Delivery](../08-delivery-cicd-gitops/README.md).
- Time-sensitive facts (upstream list, feature dates, end-of-support dates) are pinned in
  [`docs/FACTS-2026-09.md`](../../docs/FACTS-2026-09.md).
