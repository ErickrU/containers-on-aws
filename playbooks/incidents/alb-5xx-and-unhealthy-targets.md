# ALB 502 / 503 / 504 and unhealthy targets

**Applies to:** both · **Severity guide:** SEV1 when the error ratio exceeds the SLO for more than a few minutes; SEV2 for one target group or one AZ · **Time to first fix:** 5–20 min

## Symptoms

- `HTTPCode_ELB_5XX_Count` rises (the load balancer generated the error) or `HTTPCode_Target_5XX_Count` rises (the application returned it); the ratio alarm `shopfront-dev-orders-5xx-ratio` fires.
- `UnHealthyHostCount` > 0; targets flip between healthy and unhealthy ("flapping") on every deployment or under load.
- Clients see 502 on a fraction of requests during rollouts; 503 when no target is healthy; 504 when a target does not answer within the idle timeout.

## Triage in five minutes

```bash
# 1. Who generated the 5xx: the ALB or the target? Split by code.
ALB=$(aws cloudformation list-exports --query "Exports[?Name=='shopfront-dev-AlbFullName'].Value" --output text)
TG=$(aws cloudformation list-exports --query "Exports[?Name=='shopfront-dev-OrdersTgFullName'].Value" --output text)
for m in HTTPCode_ELB_502_Count HTTPCode_ELB_503_Count HTTPCode_ELB_504_Count HTTPCode_Target_5XX_Count RequestCount; do
  printf '%-28s' "$m"; aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name "$m" \
    --dimensions Name=LoadBalancer,Value="$ALB" --start-time "$(date -u -v-30M +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" \
    --period 1800 --statistics Sum --query 'Datapoints[0].Sum' --output text; done
#   ELB_502 -> target closed the connection / reset / invalid response (branch A)
#   ELB_503 -> no healthy targets, or target group has none registered (branch B)
#   ELB_504 -> target did not respond within idle_timeout (60 s here) (branch C)
#   Target_5XX -> the app answered 5xx: go to the app logs, not the load balancer

# 2. Target health with reasons
aws elbv2 describe-target-health --target-group-arn "$(aws elbv2 describe-target-groups --names shopfront-dev-orders --query 'TargetGroups[0].TargetGroupArn' --output text)" \
  --query 'TargetHealthDescriptions[*].[Target.Id,Target.Port,TargetHealth.State,TargetHealth.Reason,TargetHealth.Description]' --output table
#   Target.FailedHealthChecks -> app /readyz failing or too slow; Target.Timeout -> security group or app hung
#   Target.ResponseCodeMismatch -> /readyz returns not-200 (dependency down: readiness reports it on purpose)
#   Target.NotRegistered / Target.DeregistrationInProgress -> rollout in progress; expected briefly

# 3. Is the app itself healthy from inside the VPC? (ECS Exec or a debug pod, bypassing the ALB)
aws ecs execute-command --cluster shopfront-dev --task <task-arn> --container orders --interactive --command "sh -c 'wget -qO- http://127.0.0.1:8080/readyz; echo; wget -qO- http://127.0.0.1:8080/healthz'"
kubectl -n shopfront exec deploy/orders -- sh -c 'wget -qO- http://127.0.0.1:8080/readyz'

# 4. Did a deployment or scaling event coincide?
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].{deployments:deployments[*].{status:status,rollout:rolloutState,running:runningCount},events:events[0:5].message}'
kubectl -n shopfront rollout history deploy/orders; kubectl -n shopfront get events --sort-by=.lastTimestamp | tail -20

# 5. Access logs for the exact requests (enable on the ALB if not on: attribute access_logs.s3.enabled)
#    elb_status_code=502 target_status_code=- -> connection to target failed; target_processing_time=-1 -> never reached
aws s3 ls s3://shopfront-alb-logs-dev-123456789012/AWSLogs/123456789012/elasticloadbalancing/us-east-1/ --recursive | tail -3
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **A1. Target stopped during a rollout before the ALB stopped sending to it** | 502 spikes align with deployments; `target_status_code=-`; deregistration delay shorter than in-flight requests, or the app exits on SIGTERM immediately | Sequence: readiness fails/deregister → wait `deregistration_delay` (20 s) → SIGTERM → app drains ≤ 20 s → exit, all inside `stopTimeout`/`terminationGracePeriodSeconds` (45 s). EKS: `preStop` sleep 5–10 s and the readiness gate (`elbv2.k8s.aws/pod-readiness-gate-inject`). ECS: `stopTimeout: 30` and `deregistration_delay 20` as in `04-services.yaml` (hub/10 L200 §2.4) |
| **A2. Keep-alive mismatch: app idle timeout shorter than the ALB's** | 502 with `target_status_code=-` scattered, no deployment; app closes idle connections at 5 s while ALB idle timeout is 60 s | App keep-alive timeout > ALB `idle_timeout.timeout_seconds` (Node: `server.keepAliveTimeout = 65000`); or lower the ALB idle timeout |
| **A3. Target returned an invalid response** (headers too large, malformed) | `ELB_502` with `target_status_code` present in access logs, `error_reason` | Fix the app; ALB limits: 64 KB header |
| **A4. Target reset the connection under load** (accept queue full, `SOMAXCONN`) | 502 only at high RPS; `nstat TcpExtListenOverflows` on the node | Increase backlog (`net.core.somaxconn`, Node `server.listen(port, {backlog})`), scale out earlier (lower target-tracking value) |
| **B1. No healthy targets: readiness failing everywhere** | 503, all targets `unhealthy` with `FailedHealthChecks`/`ResponseCodeMismatch`; `/readyz` returns 503 because the DB or Valkey is down | This is readiness doing its job; fix the dependency (data-recovery runbook) or, if the dependency is optional, make readiness not depend on it |
| **B2. Security group blocks ALB → target port** | `Target.Timeout` on every target; ALB SG allowed but target SG lacks the ingress rule from the ALB SG on 8080/8081 | Target SG: allow the ALB security group on the container port (`01-network.yaml` `ServicesSecurityGroup`); EKS: the controller manages SG rules for `target-type: ip` when `manage-backend-security-group-rules` is on |
| **B3. Health check path/port/matcher wrong** | `ResponseCodeMismatch` while the app works; health check on `/` returns 404 | Health check `/readyz`, matcher `200`, port `traffic-port`; `alb.ingress.kubernetes.io/healthcheck-path` on the Ingress |
| **B4. Empty target group after a failed deployment or wrong container port** | `describe-target-health` returns none; ECS `LoadBalancers[].ContainerPort` mismatch; EKS Service `targetPort` mismatch | Fix the port mapping; ECS rolls back with the circuit breaker if configured |
| **B5. One AZ unhealthy with cross-zone off** | 503 only from one ALB node IP; targets in that AZ down | Cross-zone on (default for ALB), or capacity in every AZ; ARC zonal shift for the impaired AZ (hub/10 L200 §2.7) |
| **C1. Slow requests exceed idle timeout** | 504 with `target_processing_time=-1`; p99 > 60 s on some endpoint | Fix the slow path (usually a database query or a downstream timeout longer than the ALB's); raise `idle_timeout` only as a stopgap |
| **C2. Downstream (catalog) hangs and orders has no timeout** | orders p99 = catalog timeout; `CATALOG_URL` call has 2 s timeout in the lab | Timeouts shorter than the caller's on every hop; circuit breaker; hub/10 L200 §2.6 |
| **Targets flap: health check too aggressive vs GC/JIT pauses or CPU throttling** | Healthy → unhealthy → healthy every few minutes; CPU throttled | Interval 15 s, timeout 5 s, unhealthy threshold 3 (as configured); fix throttling (see oom-and-cpu-throttling) |
| **ALB scaling lag on a traffic spike** | 5xx and `RejectedConnectionCount`/`ELB_503` right at the spike; ALB capacity units climbing | Pre-warm through a support case for planned events; ramp traffic; ALB scales in minutes |
| **WAF blocking legitimate traffic** | 403, not 5xx, but reported as errors by users | WAF sampled requests; adjust rules |
| **Ingress annotation drift (EKS)** | Controller logs `failed to reconcile`; listener rules missing | `kubectl -n kube-system logs deploy/aws-load-balancer-controller`; fix the annotation; IAM of the controller |

## Verify the fix

```bash
aws elbv2 describe-target-health --target-group-arn <tg-arn> --query 'TargetHealthDescriptions[*].TargetHealth.State' --output text   # all healthy
aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name HTTPCode_ELB_5XX_Count --dimensions Name=LoadBalancer,Value="$ALB" \
  --start-time "$(date -u -v-10M +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 60 --statistics Sum --query 'Datapoints[*].Sum'   # zeros
# Rollout test: deploy a no-op change while running a steady 50 rps and confirm zero non-2xx
docker run --rm -i grafana/k6:2.3.0 run - <<'JS'
import http from 'k6/http'; import { check } from 'k6';
export const options = { vus: 10, duration: '3m', thresholds: { http_req_failed: ['rate<0.001'] } };
export default function () { check(http.get(`http://${__ENV.ALB}/products`), { ok: r => r.status === 200 }); }
JS
```

## Prevent it

- The shutdown timeline as configuration, not folklore: deregistration 20 s < `stopTimeout`/`terminationGracePeriodSeconds`; readiness gates on EKS; `preStop` sleep.
- Readiness reflects dependencies, liveness does not; health check settings identical in ECS target groups and Kubernetes Ingress annotations.
- Alarms on the **ratio** (`Orders5xxRatioAlarm`), on `UnHealthyHostCount`, and rollback alarms wired into the ECS deployment (`RollbackAlarmNames`).
- ALB access logs on, so the next incident has `target_status_code` and `error_reason` waiting.

## Related

- Mechanism: [05 L200 load balancing, health checks, deregistration](../../hub/05-networking/L200-load-balancing-ingress-and-discovery.md), [10 L200 graceful shutdown timeline](../../hub/10-resilience-and-dr/L200-designing-for-failure.md), [03 L300 ALB deregistration vs SIGTERM](../../hub/03-ecs/L300-ecs-internals.md), [08 L300 readiness gates and rollouts](../../hub/08-delivery-cicd-gitops/L300-progressive-delivery-and-gitops-internals.md)
- Neighbours: [ecs-deployment-stuck-or-rolled-back.md](ecs-deployment-stuck-or-rolled-back.md), [oom-and-cpu-throttling.md](oom-and-cpu-throttling.md), [dns-failures.md](dns-failures.md)
- Reference: [metrics catalog](../../reference/metrics-catalog.md)
