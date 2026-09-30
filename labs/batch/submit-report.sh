#!/usr/bin/env bash
# Submits the shopfront daily report to AWS Batch and follows it to completion.
#
#   labs/batch/submit-report.sh                       # yesterday (UTC), queue/definition from the 06-batch stack
#   labs/batch/submit-report.sh 2026-09-15            # a specific day
#   JOB_QUEUE=... JOB_DEFINITION=... labs/batch/submit-report.sh
#
# Read-only apart from the SubmitJob call; nothing is created or deleted. Uses the stack outputs of
# shopfront-<env>-06-batch when JOB_QUEUE / JOB_DEFINITION are not set.
set -euo pipefail

REPORT_DATE="${1:-}"
ENV="${ENV:-dev}"
PROJECT="${PROJECT:-shopfront}"
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

stack_output() {
  aws cloudformation describe-stacks --stack-name "${PROJECT}-${ENV}-06-batch" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

JOB_QUEUE="${JOB_QUEUE:-$(stack_output JobQueueArn)}"
JOB_DEFINITION="${JOB_DEFINITION:-$(stack_output JobDefinitionArn)}"
JOB_NAME="manual-report-${REPORT_DATE:-yesterday}-$(date -u +%Y%m%dT%H%M%SZ)"

overrides='{}'
if [[ -n "$REPORT_DATE" ]]; then
  [[ "$REPORT_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "REPORT_DATE must be YYYY-MM-DD" >&2; exit 2; }
  overrides="$(printf '{"environment":[{"name":"REPORT_DATE","value":"%s"}]}' "$REPORT_DATE")"
fi

echo "queue      : ${JOB_QUEUE}"
echo "definition : ${JOB_DEFINITION}"
echo "job name   : ${JOB_NAME}"

JOB_ID="$(aws batch submit-job --job-name "$JOB_NAME" --job-queue "$JOB_QUEUE" --job-definition "$JOB_DEFINITION" \
  --container-overrides "$overrides" --tags "Trigger=manual" --query jobId --output text)"
echo "job id     : ${JOB_ID}"

# SUBMITTED -> PENDING -> RUNNABLE -> STARTING -> RUNNING -> SUCCEEDED | FAILED
# RUNNABLE for minutes means the compute environment cannot place the job (hub/09 L200 §2.6).
status=""
while true; do
  status="$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].status' --output text)"
  printf '%s %s\n' "$(date -u +%H:%M:%S)" "$status"
  case "$status" in
    SUCCEEDED|FAILED) break ;;
  esac
  sleep 10
done

aws batch describe-jobs --jobs "$JOB_ID" \
  --query 'jobs[0].{status:status,reason:statusReason,exitCode:container.exitCode,logStream:container.logStreamName,attempts:length(attempts)}' \
  --output table
LOG_STREAM="$(aws batch describe-jobs --jobs "$JOB_ID" --query 'jobs[0].container.logStreamName' --output text)"
if [[ -n "$LOG_STREAM" && "$LOG_STREAM" != "None" ]]; then
  echo "== last log lines"
  aws logs get-log-events --log-group-name "/${PROJECT}/${ENV}/report-job" --log-stream-name "$LOG_STREAM" \
    --limit 20 --query 'events[*].message' --output text
fi
[[ "$status" == "SUCCEEDED" ]]
