# 06 · Identity and security

Every container on AWS runs with at least three identities around it: the identity of the
platform that started it (an instance or node role, a Fargate agent), the identity your code uses
to call AWS (a task role, an IRSA role or a Pod Identity association) and the identities of the
humans and pipelines that deploy and debug it (IAM Identity Center roles, access entries, ECS
Exec). Security in this domain is mostly about keeping those identities apart, giving each one
the least it needs, keeping secrets out of images and task definitions, making the container
itself hard to escape (Pod Security Standards, read-only root filesystems, seccomp, signed images)
and being able to prove what happened afterwards (CloudTrail, EKS audit logs, GuardDuty). It is
its own domain because the mechanisms differ per platform — Fargate, ECS on EC2, EKS standard and
EKS Auto Mode split responsibility differently — and because the same mistake (a pod falling back
to the node role through IMDS) shows up in every other domain. The running example is the
`shopfront` system from [`labs/CONTRACT.md`](../../labs/CONTRACT.md); terms are defined in the
[glossary](../../GLOSSARY.md).

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 Security basics for containers](L100-security-basics-for-containers.md) | The shared-responsibility split for Fargate, ECS on EC2, EKS standard and EKS Auto Mode; every identity in play and what each may do; where secrets must never live; image scanning; TLS; the ten-line checklist |
| 200 | [L200 IAM for containers](L200-iam-for-containers.md) | ECS task role vs execution role with real trust policies; IRSA and EKS Pod Identity end to end with sequence diagrams and a decision table; why pods must not use the node role and how to block IMDS per platform; access entries, access policies and RBAC; human access through IAM Identity Center and ECS Exec; secrets delivery (`secrets[]`, Secrets Store CSI, External Secrets Operator); EKS envelope encryption; IMDSv2 |
| 300 | [L300 Hardening workloads and clusters](L300-hardening-workloads-and-clusters.md) | Pod Security Standards and Admission; every `securityContext` field and what it blocks; seccomp, AppArmor and SELinux on EKS nodes; network policy as a security control; ValidatingAdmissionPolicy, MutatingAdmissionPolicy, Kyverno and Gatekeeper; image signature verification with Notation/AWS Signer and cosign; GuardDuty Runtime Monitoring, Inspector, Security Hub, EKS audit logs and CloudTrail; the Fargate isolation model; private endpoints and egress control; secrets rotation |
| 400 | [L400 Security architecture and incident response](L400-security-architecture-and-incident-response.md) | A threat model for a container platform with a threat → control → evidence table; multi-tenancy tiers; Zero Trust and mTLS options (Service Connect TLS, Cilium, Istio, VPC Lattice auth policies); PCI DSS, HIPAA and SOC 2 mapped to controls; incident response for containers including credential revocation; security metrics; the Well-Architected security pillar checklist |

## Components covered

- Shared responsibility per platform: Fargate (ECS and EKS), ECS on EC2, EKS standard with managed
  node groups, EKS Auto Mode — L100 §2.1
- Identities: EC2 instance and EKS node roles, ECS task role, ECS task execution role, ECS
  infrastructure and service-linked roles, EKS cluster role, Fargate pod execution role, pod roles
  (IRSA, Pod Identity), human and CI/CD roles — L100 §2.2, L200 §2.1–2.4
- IRSA: cluster OIDC issuer, IAM OIDC provider, thumbprint, trust policy `sub`/`aud` conditions,
  `eks.amazonaws.com/role-arn`, pod-identity-webhook mutation, projected token audience and
  rotation, `sts:AssumeRoleWithWebIdentity` — L200 §2.3
- EKS Pod Identity: `eks-pod-identity-agent` add-on on `169.254.170.23` / `fd00:ec2::23`,
  associations, trust principal `pods.eks.amazonaws.com` with `sts:AssumeRole` and
  `sts:TagSession`, `AWS_CONTAINER_CREDENTIALS_FULL_URI`, `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE`,
  session tags for ABAC, target roles for cross-account, where IRSA is still required — L200 §2.4
- SDK credential provider chain and its traps — L200 §2.6
- IMDSv2 (PUT token, TTL, hop limit) and blocking IMDS from tasks and pods per platform — L200
  §2.2, L300 §2.6
- EKS access entries, access policies, authentication modes, Kubernetes RBAC, `aws eks get-token`,
  IAM Identity Center permission sets — L200 §2.7
- ECS Exec: `ecs:ExecuteCommand`, SSM Session Manager, condition keys, KMS-encrypted sessions,
  logging to CloudWatch Logs and S3, its conflict with read-only root filesystems — L200 §2.8,
  L300 §2.9
- Secrets delivery: Secrets Manager, SSM Parameter Store, ECS `secrets[]` with `valueFrom`,
  Secrets Store CSI driver with ASCP, External Secrets Operator, rotation and reload behaviour —
  L200 §2.9, L300 §2.12
- EKS envelope encryption of Kubernetes API data with KMS — L200 §2.10
- Pod Security Standards (privileged, baseline, restricted) and Pod Security Admission labels;
  `securityContext` fields; seccomp `RuntimeDefault`; AppArmor field and annotations; SELinux on
  AL2023 and Bottlerocket; capabilities; read-only root filesystem with writable `emptyDir` —
  L300 §2.1–2.4
- ECS task definition equivalents: `user`, `readonlyRootFilesystem`, `privileged`,
  `linuxParameters.capabilities`, `dockerSecurityOptions`, `pidMode` — L300 §2.2
- Network policy (VPC CNI engine, Cilium) and security groups as security controls — L300 §2.5
- Admission: ValidatingAdmissionPolicy and MutatingAdmissionPolicy (CEL), Kyverno, Gatekeeper —
  L300 §2.7
- Image signing and verification: Notation with AWS Signer, ECR managed signing, Sigstore cosign
  with KMS, Kyverno `verifyImages`, Ratify — L300 §2.8
- Detection: GuardDuty EKS Protection and Runtime Monitoring (EKS add-on, ECS Fargate sidecar,
  EC2 agent), Amazon Inspector for ECR and EC2, Security Hub controls, EKS control plane audit
  logs, CloudTrail events for ECS and ECR — L300 §2.9
- Fargate isolation model (Firecracker microVM per task or pod) — L300 §2.10
- Private cluster endpoints, VPC endpoints, egress restriction — L300 §2.11
- Threat model, multi-tenancy tiers (namespace, node, cluster, account), Zero Trust and mTLS
  options, compliance mapping, incident response, security metrics, Well-Architected security
  pillar — L400

## Related

- Labs: [`labs/eks/manifests/base/`](../../labs/eks/manifests/base/) (service accounts, network
  policies, restricted `securityContext`), [`labs/eks/addons/`](../../labs/eks/addons/) (Pod
  Identity association script), [`labs/ecs/taskdefs/`](../../labs/ecs/taskdefs/) (`secrets[]`,
  `user`, `readonlyRootFilesystem`),
  [`labs/ecs/cloudformation/04-services.yaml`](../../labs/ecs/cloudformation/04-services.yaml)
  (task and execution roles), [`labs/pipelines/github-actions/ci.yml`](../../labs/pipelines/github-actions/ci.yml)
  (OIDC to AWS, scan, SBOM, sign).
- Playbooks: [IAM AccessDenied from containers](../../playbooks/incidents/iam-accessdenied-from-containers.md),
  [EKS auth and access](../../playbooks/incidents/eks-auth-and-access.md),
  [Image pull failures](../../playbooks/incidents/image-pull-failures.md),
  [Game-day guide](../../playbooks/dr/game-day-guide.md).
- Reference: [decision guides](../../reference/decision-guides.md) (IRSA vs Pod Identity, Service
  Connect vs Cloud Map vs mesh), [metrics catalog](../../reference/metrics-catalog.md),
  [ports, addresses and endpoints](../../reference/ports-addresses-and-endpoints.md),
  [CLI cheat sheet](../../reference/cli-cheatsheet.md).
- Neighbouring domains: [01 Container fundamentals](../01-container-fundamentals/README.md) for
  supply-chain hardening of the image itself, [02 ECR](../02-ecr/README.md) for repository
  policies and scanning, [03 ECS](../03-ecs/README.md) and [04 EKS](../04-eks/README.md) for the
  platforms these identities live on, [05 Networking](../05-networking/README.md) for link-local
  addresses, IMDSv2 mechanics and network policy engines, [08 Delivery](../08-delivery-cicd-gitops/README.md)
  for pipeline identity and supply-chain steps, [12 Well-Architected](../12-well-architected/README.md)
  for the full pillar checklists.
