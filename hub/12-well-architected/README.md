# 12 · Well-Architected for containers

The AWS Well-Architected Framework is a set of questions organised in six pillars — Operational
Excellence, Security, Reliability, Performance Efficiency, Cost Optimization, Sustainability — that a
team answers about a workload to find risks and trade-offs before they become incidents or bills. For
containers, three documents sharpen the questions: the **Container Build Lens** (how images are built,
scanned, signed and deployed), the **Amazon EKS Best Practices Guide** and the **Amazon ECS Best
Practices Guide**. Every other domain in this repository ends each document with a Well-Architected
table; this domain is where those tables come together: the pillars restated for container workloads,
per-pillar checklists for ECS and EKS with links to the mechanism behind each item, a worked review of
the `shopfront` system, and the hard trade-offs and anti-patterns that reviews keep finding.

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 Pillars for containers](L100-pillars-for-containers.md) | The six pillars restated for container workloads; what the Container Build Lens and the EKS/ECS best-practices guides add; how a review works and what it produces |
| 200 | [L200 Pillar checklists for ECS and EKS](L200-pillar-checklists-ecs-and-eks.md) | Per-pillar checklists for ECS and for EKS, each item linking to the hub document that explains the mechanism and to the command that proves it |
| 300 | [L300 Running a review](L300-running-a-review.md) | A Well-Architected review of shopfront end to end: questions, evidence collected, risk rating, improvement plan, how to run it with the AWS Well-Architected Tool |
| 400 | [L400 Trade-offs and anti-patterns](L400-trade-offs-and-anti-patterns.md) | Decision records for the recurring hard choices (Fargate vs EC2 vs Managed Instances vs Auto Mode; one cluster vs many; mesh or not; multi-Region or not; managed vs self-managed add-ons; cost vs resilience) and the anti-pattern catalogue with the failure each causes |

## Components covered

- The six pillars and their design principles applied to containers — L100 §2.1
- Container Build Lens: design principles, build/deploy/operate practices — L100 §2.2, L200 (build
  items), L400 §2.7
- Amazon EKS Best Practices Guide and Amazon ECS Best Practices Guide: structure and how to use them —
  L100 §2.3
- AWS Well-Architected Tool: workloads, lenses, milestones, risk reports; custom lenses — L100 §2.4,
  L300 §2.1
- Checklists per pillar for ECS (task definitions, roles, networking, deployments, scaling, logging,
  cost) and for EKS (cluster configuration, add-ons, nodes, identities, policies, workloads, scaling,
  observability, cost) — L200
- Review method: scoping, questions, evidence, high/medium risks, improvement plan, milestones — L300
- Decision records: compute model, cluster topology, service mesh, multi-Region, add-on ownership,
  observability stack, CI/CD stack, data services — L400 §2.1–2.6
- Anti-pattern catalogue with failure modes and replacements — L400 §2.8

## Related

- The Well-Architected tables in every hub document (section 5) — this domain aggregates them.
- Labs: the review in L300 uses [`labs/`](../../labs/) as the workload under review
  ([`labs/ecs/cloudformation/`](../../labs/ecs/cloudformation/), [`labs/eks/`](../../labs/eks/),
  [`labs/pipelines/`](../../labs/pipelines/)).
- Playbooks: [DR plan template](../../playbooks/dr/dr-plan-template.md) (Reliability evidence),
  [Game-day guide](../../playbooks/dr/game-day-guide.md).
- Reference: [decision guides](../../reference/decision-guides.md) (the short form of L400),
  [metrics catalog](../../reference/metrics-catalog.md) (Operational Excellence evidence),
  [lifecycle and deprecations](../../reference/lifecycle-and-deprecations.md).
- Neighbouring domains: all of them; start with [03 ECS](../03-ecs/README.md) or
  [04 EKS](../04-eks/README.md) for the platform under review.
