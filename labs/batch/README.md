# shopfront report-job on AWS Batch

`report-job` reads yesterday's orders and writes `daily-<date>.json` and `.csv` to S3. It is the
lab's run-to-completion workload, so it is the natural place to compare the three ways of running a
job on AWS containers (hub/09 L200 §2.7):

| Runner | Artifact here | Pick it when |
| --- | --- | --- |
| AWS Batch on Fargate | `job-definition-fargate.json`, CloudFormation `labs/ecs/cloudformation/06-batch.yaml` | Queues, retries, priorities, array jobs, Spot with automatic retry; no cluster to own |
| AWS Batch on EKS | `job-definition-eks.json` | You already run EKS and want Batch scheduling semantics on your nodes |
| Kubernetes CronJob | `labs/eks/manifests/base/cronjob-report.yaml` | You want the job in the same GitOps flow as the services and do not need queues |
| ECS scheduled task | EventBridge Scheduler → `ecs:RunTask` (hub/03 L200 §2.10) | One-off or cron on ECS without Batch's queue model |

## Files

- `job-definition-fargate.json` — `aws batch register-job-definition --cli-input-json file://job-definition-fargate.json`.
  Same hardening as the ECS task definitions: ARM64, non-root, read-only root filesystem, `/tmp`
  volume, secrets from Secrets Manager, `evaluateOnExit` so an application error (exit 1) is not
  retried while Spot reclaims and pull errors are.
- `job-definition-eks.json` — the EKS variant. Batch launches the pod in the `aws-batch`-managed
  namespace of your cluster with `eksProperties`; there is no `secrets[]`, so the Kubernetes Secret
  `shopfront-db` is mounted and read through `DATABASE_URL_FILE`.
- `submit-report.sh` — submits a job, prints the state transitions and the last log lines, exits
  non-zero when the job FAILED. Takes an optional `YYYY-MM-DD`.

## Run it

```bash
CONFIRM_DEPLOY=yes ONLY=06-batch labs/ecs/cloudformation/deploy.sh   # compute environments, queue, definition, schedule (disabled)
labs/batch/submit-report.sh                                          # yesterday
labs/batch/submit-report.sh 2026-09-15
aws s3 ls s3://shopfront-reports-dev-123456789012/daily/
```

What to observe: `RUNNABLE` for more than two minutes means the compute environment cannot place
the job (quota, subnet without NAT, security group without egress); `FAILED` with
`CannotPullContainerError` means the execution role or the ECR VPC endpoints; exit code 1 with a
`missing required environment variables` log line means the secret or `REPORT_OUTPUT` is wrong.
Enable the schedule with `ScheduleState=ENABLED` in `parameters/dev.json` once a manual run succeeds.
