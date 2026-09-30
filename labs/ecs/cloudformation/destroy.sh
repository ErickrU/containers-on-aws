#!/usr/bin/env bash
# Deletes the shopfront ECS stacks created by deploy.sh, in reverse order.
#
#   CONFIRM_DESTROY=yes ./destroy.sh              # everything for ENV=dev
#   CONFIRM_DESTROY=yes ONLY=06-batch ./destroy.sh
#
# What this does NOT delete, on purpose (you may want them, and they are cheap or free):
#   - the ECR images (empty the repositories first or the 02-cluster deletion fails; see below)
#   - the Aurora final snapshot taken by DeletionPolicy: Snapshot on the DB cluster
#   - the S3 reports bucket if it still has objects (CloudFormation refuses; empty it yourself)
#   - CloudWatch log groups that other stacks did not create
# It only deletes stacks whose names match <project>-<env>-<layer>, so it cannot touch anything
# you did not create with these templates.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${ENV:-dev}"
PARAMS_FILE="${HERE}/parameters/${ENV}.json"

if [[ "${CONFIRM_DESTROY:-}" != "yes" ]]; then
  echo "refusing to destroy: set CONFIRM_DESTROY=yes" >&2
  exit 2
fi
[[ -f "$PARAMS_FILE" ]] || { echo "no parameter file for ENV=${ENV}: ${PARAMS_FILE}" >&2; exit 2; }

json_get() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$PARAMS_FILE" "$1"
}
PROJECT="$(json_get project)"
REGION="${AWS_REGION:-$(json_get region)}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

echo "target account : ${ACCOUNT}"
echo "region         : ${REGION}"
echo "project/env    : ${PROJECT}/${ENV}"
echo

stack_exists() {
  aws cloudformation describe-stacks --stack-name "$1" >/dev/null 2>&1
}

empty_repositories() {
  local repo
  for repo in catalog orders worker report-job; do
    local name="${PROJECT}/${repo}"
    aws ecr describe-repositories --repository-names "$name" >/dev/null 2>&1 || continue
    local ids
    ids="$(aws ecr list-images --repository-name "$name" --query 'imageIds[*]' --output json)"
    if [[ "$ids" != "[]" ]]; then
      echo "    emptying ${name}"
      aws ecr batch-delete-image --repository-name "$name" --image-ids "$ids" --query 'failures' --output text
    fi
  done
}

empty_reports_bucket() {
  local bucket="${PROJECT}-reports-${ENV}-${ACCOUNT}"
  if aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    echo "    emptying s3://${bucket} (versioned: deleting all versions and markers)"
    python3 - "$bucket" <<'PY'
import json, subprocess, sys
bucket = sys.argv[1]
while True:
    out = subprocess.run(["aws", "s3api", "list-object-versions", "--bucket", bucket, "--max-items", "500",
                          "--output", "json"], check=True, capture_output=True, text=True).stdout
    data = json.loads(out) if out.strip() else {}
    objects = [{"Key": v["Key"], "VersionId": v["VersionId"]}
               for v in data.get("Versions", []) + data.get("DeleteMarkers", [])]
    if not objects:
        break
    payload = json.dumps({"Objects": objects, "Quiet": True})
    subprocess.run(["aws", "s3api", "delete-objects", "--bucket", bucket, "--delete", payload],
                   check=True, capture_output=True, text=True)
PY
  fi
}

delete_layer() {
  local name="${PROJECT}-${ENV}-$1"
  if ! stack_exists "$name"; then
    echo "==> ${name}: not found, skipping"
    return
  fi
  echo "==> deleting ${name}"
  aws cloudformation delete-stack --stack-name "$name"
  aws cloudformation wait stack-delete-complete --stack-name "$name"
}

LAYERS=(06-batch 05-observability 04-services 03-data 02-cluster 01-network)
if [[ -n "${ONLY:-}" ]]; then
  LAYERS=("$ONLY")
fi

for layer in "${LAYERS[@]}"; do
  case "$layer" in
    03-data) empty_reports_bucket ;;
    02-cluster) empty_repositories ;;
  esac
  delete_layer "$layer"
done

echo
echo "done. Remaining on purpose: Aurora final snapshot (aws rds describe-db-cluster-snapshots), and any"
echo "log groups or secrets you created outside these templates."
