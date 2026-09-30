# CrashLoopBackOff, "Essential container in task exited", exit codes 1 / 137 / 139 / 143

**Applies to:** both · **Severity guide:** SEV1 when all replicas of a customer-facing service loop; SEV3 for a single background replica · **Time to first fix:** 5–30 min

## Symptoms

- EKS: `kubectl get pods` shows `CrashLoopBackOff` with a rising `RESTARTS` count; back-off doubles from 10 s to 5 min.
- ECS: task `STOPPED`, `stopCode: EssentialContainerExited`, `stoppedReason: Essential container in task exited`; the service keeps launching replacements and the deployment circuit breaker trips.
- The process starts and exits within seconds (configuration, dependency) or after minutes (memory, health check).

## Triage in five minutes

```bash
# 1. Exit code and last state of the crashed container. The number is the diagnosis half the time.
kubectl -n shopfront get pod <pod> -o jsonpath='{range .status.containerStatuses[*]}{.name}{" exit="}{.lastState.terminated.exitCode}{" reason="}{.lastState.terminated.reason}{" signal="}{.lastState.terminated.signal}{"\n"}{end}'
aws ecs describe-tasks --cluster shopfront-dev --tasks <task-arn> \
  --query 'tasks[0].containers[*].{name:name,exit:exitCode,reason:reason,health:healthStatus}'
#   0   -> the process finished on purpose (a job in a Deployment, CMD that returns)
#   1   -> application error: read the log (config, missing env, dependency unreachable at start)
#   2/126/127 -> shell: bad command, permission, "not found" (ENTRYPOINT/CMD typo, missing shell in distroless)
#   137 -> SIGKILL: OOMKilled (check reason) or kubelet/ECS killed it after the grace period
#   139 -> SIGSEGV: native crash (glibc vs musl, wrong architecture image, corrupted binary)
#   143 -> SIGTERM handled and exited: something asked it to stop (probe failure, scale-in, spot) - look at events, not the app

# 2. Logs of the PREVIOUS instance (the current one may not have logged yet)
kubectl -n shopfront logs <pod> -c orders --previous --tail=100
aws logs tail /shopfront/dev/orders --since 15m --format short | tail -100

# 3. Events tell you whether probes killed it
kubectl -n shopfront describe pod <pod> | sed -n '/Events:/,$p'
#   "Liveness probe failed" before the restart -> branch P (probe), not an app crash
#   "Back-off restarting failed container"      -> plain crash, keep reading the log

# 4. Was the start-up budget too short? Time from container start to the first log line vs startupProbe/health check start period
kubectl -n shopfront get pod <pod> -o jsonpath='{.status.containerStatuses[0].state}'

# 5. Reproduce locally with the same image and environment
docker run --rm -e PORT=8080 -e DATABASE_URL=postgres://... 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders:sha-1a2b3c4
```

## Causes and fixes

| Cause | Confirm | Fix |
| --- | --- | --- |
| **Missing or invalid configuration** (exit 1 within a second) | Log line `missing required environment variables: DATABASE_URL`; `kubectl get pod -o yaml` shows the env or `secretKeyRef` absent; ECS `secrets[]` pointing at a wrong ARN | Fix the ConfigMap/Secret or task definition; the shopfront services fail fast with the variable name on purpose (labs/CONTRACT.md §3) |
| **Secret not synced yet** (EKS with ESO) | `ExternalSecret` status `SecretSyncedError`; pod `CreateContainerConfigError` rather than crash | Fix the store/IAM (`kubectl describe externalsecret shopfront-db`); see iam-accessdenied |
| **Dependency unreachable at start** (exit 1 after ~30 s) | `database not reachable after 30s`; security group, DNS, RDS Proxy down | Fix the network path; the apps retry with backoff for 30 s then exit so the platform restarts them cleanly (hub/10 L200 §2.5) |
| **Wrong ENTRYPOINT/CMD or no shell** (exit 127/126) | `exec: "sh": executable file not found`; `command` in the manifest overrides an ENTRYPOINT image | Distroless images have no shell: use exec-form commands, no `sh -c`; check `command` vs `args` semantics (Kubernetes `command` replaces ENTRYPOINT) |
| **Wrong architecture** (exit 139 or `exec format error`) | amd64 image on Graviton/ARM64 Fargate | Multi-arch build or pin the platform; see image-pull-failures B3 |
| **Runs as root in the image but `runAsNonRoot: true`** | `CreateContainerConfigError: container has runAsNonRoot and image will run as root` | Set a numeric `USER` in the Dockerfile (uid 10001) or `runAsUser` |
| **Read-only root filesystem and the app writes** (exit 1, `EROFS`/`Read-only file system`) | Log shows a write to `/app`, `/var`, `$HOME` | Mount an `emptyDir` (EKS) or a volume (ECS) at the paths it writes (`/tmp`); set `HOME=/tmp` |
| **Port already in use / binding privileged port as non-root** | `EACCES: permission denied 0.0.0.0:80` | Listen above 1024 and let the Service/ALB map the port |
| **OOMKilled** (exit 137, reason `OOMKilled`) | `lastState.terminated.reason: OOMKilled`; ECS `OutOfMemoryError: Container killed due to memory usage` | See oom-and-cpu-throttling |
| **P. Liveness probe or ECS health check too aggressive** (exit 137/143 after start) | Events show probe failures; app was busy (GC, JIT warm-up, migrations); `interval`/`timeout` too tight | Add a `startupProbe` (EKS) or `startPeriod` (ECS); liveness should test only "the process is alive", not dependencies; readiness carries dependency state |
| **PID 1 does not forward signals** (exit 137 on every rollout) | Container takes exactly `terminationGracePeriodSeconds`/`stopTimeout` to die; `sh -c "node ..."` wrapper | Exec-form ENTRYPOINT so the app is PID 1, or `initProcessEnabled: true` / a tiny init (hub/01 L200 §2.6) |
| **Scale-in, Spot reclaim or node drain** (exit 143, no error in the app) | Events `Killing`, node `NotReady`, Karpenter `Disrupting`, ECS `SpotInterruption` | Not a crash: confirm capacity and PDBs; see pending-pods-and-capacity |
| **Deployment restarts because the Job-like process exits 0** | exit 0, `Completed` then restarted | Use a Job/CronJob (EKS) or a scheduled task / Batch (ECS) for run-to-completion work |

## Verify the fix

```bash
kubectl -n shopfront get pods -l app.kubernetes.io/name=orders -w          # RESTARTS stays flat for 10 minutes
kubectl -n shopfront get pod <pod> -o jsonpath='{.status.containerStatuses[0].restartCount}'
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].deployments[0].{rollout:rolloutState,running:runningCount,failed:failedTasks}'
curl -fsS http://<alb>/orders/readyz    # or the service's own /readyz through port-forward
```

## Prevent it

- Fail fast with a message that names the variable; never loop silently.
- `startupProbe` on every container that takes more than a few seconds; liveness independent of dependencies.
- Exec-form ENTRYPOINT, non-root numeric user, `/tmp` writable, tested locally with `docker run --read-only`.
- Unit test the configuration loader (`labs/apps/report-job/tests/test_report.py::test_load_config_*`).
- Alarm on `kube_pod_container_status_restarts_total` rate (Container Insights `pod_number_of_container_restarts`) and on ECS `EssentialContainerExited` counts from the events log group.

## Related

- Mechanism: [01 L200 PID 1 and signals](../../hub/01-container-fundamentals/L200-images-builds-and-registries.md), [01 L300 runtimes and the kernel](../../hub/01-container-fundamentals/L300-runtimes-and-the-kernel.md), [10 L200 probes and graceful shutdown](../../hub/10-resilience-and-dr/L200-designing-for-failure.md)
- Neighbours: [oom-and-cpu-throttling.md](oom-and-cpu-throttling.md), [ecs-task-stopped-reasons.md](ecs-task-stopped-reasons.md), [image-pull-failures.md](image-pull-failures.md)
