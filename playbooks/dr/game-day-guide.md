# Game-day guide: planning, scenarios, scoring, follow-ups

**Applies to:** both · **Severity guide:** none (planned); the game day itself is run as a declared SEV3 so tooling and communications are exercised · **Time to first fix:** 2–4 h per game day, quarterly

A game day is a rehearsal with a hypothesis, an injected fault, observers with stopwatches, and a
written result. It is how the numbers in the DR plan become measured rather than hoped. The theory
is in [10 · L400](../../hub/10-resilience-and-dr/L400-dr-plan-and-game-days.md) and the fault-injection
tooling in [11 · L300](../../hub/11-testing-workloads/L300-performance-and-chaos-testing.md).

## Preconditions

- [ ] Environment chosen: staging that mirrors prod (first runs), then prod with a small blast radius and an abort condition.
- [ ] Hypothesis written for every scenario: "when X fails, the system does Y within Z and customers see W".
- [ ] Abort condition and who may call it (any participant; the FIS stop condition on `shopfront-*-orders-unhealthy` does it automatically for FIS experiments).
- [ ] Observers assigned: one per dashboard (ALB, ECS/EKS, data), one scribe with the timeline.
- [ ] Stakeholders informed; status page set to "maintenance" only if customers could notice.
- [ ] Baseline captured 30 min before: error ratio, p99, queue age, running counts.

## Scenario catalogue

| # | Scenario | Injection | Hypothesis (fill in numbers) | Runbook exercised |
| --- | --- | --- | --- | --- |
| 1 | Half of the `orders` tasks die | FIS `aws:ecs:stop-task` 50% (`labs/ecs/fis-stop-tasks.json`) or `kubectl delete pod -l app.kubernetes.io/name=orders --field-selector ...` | ALB 5xx ratio stays < 0.1%; replacements Running in < 90 s; alarm does not fire | alb-5xx, ecs-task-stopped |
| 2 | An AZ goes dark | FIS `aws:network:disrupt-connectivity` on one AZ's subnets, or ARC zonal shift away from it | Traffic drains from the AZ in < 2 min; capacity in the other two absorbs it; no manual action | pending-pods (capacity per AZ) |
| 3 | Database writer fails over | `aws rds failover-db-cluster` | Writes fail for < 30 s; pools reconnect through the proxy; no restarts | data-recovery A |
| 4 | Valkey unavailable | Security group rule removed for 10 min | catalog p99 rises but stays under 500 ms; DB connections stay under 80%; no 5xx | data-recovery Valkey |
| 5 | Queue consumer stalls | Scale `fulfillment-worker` to 0 for 15 min, then back | Age alarm fires at 300 s; on restore, backlog drains at ≥ N msg/s; KEDA/ECS scales to the expected count; zero DLQ | queue-backlog |
| 6 | Poison message | Send a malformed message to the queue | DLQ alarm within 2 min; healthy messages unaffected; redrive after "fix" succeeds | queue-backlog |
| 7 | Bad deployment | Deploy an image that returns 500 on 20% of requests | ECS alarm rollback / Argo Rollouts analysis aborts within the bake time; customers see < 1% errors for < 5 min | ecs-deployment, 08 L300 |
| 8 | Node loss (EKS) | Terminate an instance without draining (`aws ec2 terminate-instances`) | Pods rescheduled in < 2 min; PDBs did not block; no single-replica service existed | node-not-ready |
| 9 | Karpenter/Auto Mode capacity crunch | NodePool `limits.cpu` lowered below need, then a scale-out | Pending pods alarm; runbook finds the limit in < 10 min | pending-pods |
| 10 | Identity revoked | Detach the worker's IAM policy for 10 min | Consumer logs `AccessDenied`, metrics show 0 receives, age alarm; restore works without restart | iam-accessdenied |
| 11 | DNS impairment | NetworkPolicy blocking DNS applied to one service for 5 min | Service fails fast with clear errors; others unaffected; runbook step 1 pinpoints it | dns-failures |
| 12 | Registry unavailable | ECR endpoint policy set to deny for 15 min, then trigger a scale-out | Running tasks unaffected; new tasks fail with `CannotPullContainerError`; alarm on service events; rollback of the policy fixes it | image-pull-failures |
| 13 | Regional failover (full) | Follow region-failover-runbook in staging | Tier-1 RTO and RPO met; failback works; every step was in the runbook | region-failover |
| 14 | Cluster rebuild from scratch | cluster-rebuild-runbook in a sandbox account | Rebuild time < target; zero steps required information outside git | cluster-rebuild |

Run 3–5 scenarios per game day; rotate through the catalogue over the year; repeat any that failed.

## Steps (per scenario)

1. **Announce** in the incident channel: scenario number, hypothesis, start time, abort condition.
2. **Inject** the fault with the exact command from the catalogue; the scribe records the timestamp.
3. **Observe** silently for the first two minutes: does anything page? does anyone notice without being told? (Detection time.)
4. **Respond** using only the runbooks; observers note every step that was not in a runbook, every command that failed, every dashboard that was missing a panel.
5. **Stop** the injection at the planned time or on abort; record recovery time (metrics back to baseline).
6. **Score** immediately (table below) while memories are fresh.

```bash
# Useful during any scenario: the clocks
date -u +%FT%TZ                                                                # timestamps for the scribe
aws cloudwatch describe-alarm-history --alarm-name shopfront-dev-orders-unhealthy --history-item-type StateUpdate --max-items 5 --query 'AlarmHistoryItems[*].[Timestamp,HistorySummary]'
aws fis list-experiments --query 'experiments[0:3].[id,state.status,creationTime]'
aws fis stop-experiment --id <experiment-id>                                   # manual abort
```

## Scoring

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Detection | nobody noticed until told | a dashboard showed it, no page | the right alarm paged the right person |
| Diagnosis | guessed | runbook found it with detours | runbook triage pointed straight at the cause |
| Recovery | manual heroics | runbook with gaps | automatic, or runbook followed verbatim |
| Customer impact | above hypothesis | at hypothesis | below hypothesis |
| Timeline | none | partial | complete with timestamps |

A scenario "passes" at 8/10 or above **and** with the hypothesis's numbers met. Anything else
produces follow-ups.

## Follow-ups

Every gap becomes a ticket with an owner and a date, tagged `game-day`:

- Missing alarm or wrong threshold → change in `05-observability.yaml` / Prometheus rules.
- Missing runbook step → edit the runbook in the same pull request as the fix.
- Slow detection → SLO burn-rate alert (hub/07 L300 §2.7).
- Hidden dependency → dependency map in the DR plan §4.
- Undocumented manual step → automate or document; re-test next game day.

Publish a one-page report: scenarios, scores, measured times vs hypotheses, follow-ups. Update the DR
plan's "last rehearsal" fields.

## Verify

The game day succeeded when the report exists, the DR plan has new measured numbers, and the
follow-ups are tracked. A game day with no findings usually means the scenarios were too easy.

## Related

- Plan: [dr-plan-template.md](dr-plan-template.md) · [region-failover-runbook.md](region-failover-runbook.md) · [cluster-rebuild-runbook.md](cluster-rebuild-runbook.md) · [data-recovery-runbook.md](data-recovery-runbook.md)
- Mechanism: [10 · L200 FIS basics and zonal shift](../../hub/10-resilience-and-dr/L200-designing-for-failure.md), [11 · L300 chaos engineering with FIS and what to record](../../hub/11-testing-workloads/L300-performance-and-chaos-testing.md), [11 · L400 continuous verification](../../hub/11-testing-workloads/L400-verification-at-scale.md)
- Lab: [`labs/ecs/fis-stop-tasks.json`](../../labs/ecs/fis-stop-tasks.json)
