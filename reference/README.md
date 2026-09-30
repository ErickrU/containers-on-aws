# Reference

Lookup tables. Nothing here teaches; each file exists so that a hub document or a runbook can say
"see the table" instead of repeating numbers that would drift.

| File | What you look up there |
| --- | --- |
| [metrics-catalog.md](metrics-catalog.md) | Every metric named in the hub: component, source, what a bad value means, starting threshold |
| [ports-addresses-and-endpoints.md](ports-addresses-and-endpoints.md) | Link-local addresses (IMDS, ECS credentials, Pod Identity, Resolver, Time Sync), ports per component, VPC endpoints for private ECS/EKS, IP arithmetic |
| [service-interaction-map.md](service-interaction-map.md) | Who talks to whom (ECS/EKS/ECR/IAM/ELB/Cloud Map/CloudWatch/…), protocol, prerequisites, how it breaks; Mermaid diagrams |
| [decision-guides.md](decision-guides.md) | ECS vs EKS; Fargate vs EC2 vs Managed Instances vs Auto Mode; ALB vs NLB vs API Gateway vs Lattice; VPC CNI vs Cilium; IRSA vs Pod Identity; Service Connect vs Cloud Map vs mesh; X-Ray vs OTel; Jenkins vs Argo CD vs CodePipeline vs GitHub Actions; SQS vs Kafka; Batch vs Jobs; Karpenter vs Cluster Autoscaler vs Auto Mode; rolling vs blue/green vs canary; one cluster vs many |
| [quotas-and-limits.md](quotas-and-limits.md) | The quotas that bite (IPs, ENIs, Fargate vCPUs, ALB targets and rules, ECR pulls, etcd size, pods per node, SQS, MSK, RDS connections…) with the error you see |
| [lifecycle-and-deprecations.md](lifecycle-and-deprecations.md) | Dates from `docs/FACTS-2026-09.md`: EKS version calendar, AMI end of support, App Mesh and Copilot end of support, migration pointers |
| [cli-cheatsheet.md](cli-cheatsheet.md) | `aws ecs/eks/ecr`, `kubectl`, `eksctl`, `docker`, `ctr`, `nerdctl`, `crictl`, `helm`, `kustomize`, `argocd`, plus the one-liners the runbooks use |

Conventions: Region `us-east-1`, account `123456789012`, cluster `shopfront-dev`, namespace
`shopfront`, domain `shopfront.example.com`. Dates and defaults are as of September 2026; the
commands to re-verify them are at the bottom of each file where it matters.
