#!/usr/bin/env bash
# Deploys the shopfront ECS environment layer by layer with CloudFormation.
#
#   CONFIRM_DEPLOY=yes ./deploy.sh                 # all layers, environment "dev"
#   CONFIRM_DEPLOY=yes ONLY=03-data ./deploy.sh    # one layer
#   CONFIRM_DEPLOY=yes ENV=staging ./deploy.sh     # reads parameters/staging.json
#   CONFIRM_DEPLOY=yes ./deploy.sh migrate         # apply schema.sql + seed.sql through a one-off task
#   CONFIRM_DEPLOY=yes IMAGE_TAG=sha-abc1234 ONLY=04-services ./deploy.sh   # roll a new image
#
# Nothing runs without CONFIRM_DEPLOY=yes. The script prints the target account and Region first.
# Order matters: 01 network -> 02 cluster -> 03 data -> 04 services -> 05 observability -> 04 again
# (to wire the rollback alarms) -> 06 batch. Every stack is named <project>-<env>-<layer>.
#
# Costs money while it runs (NAT, ALB, Aurora Serverless v2, ElastiCache Serverless, RDS Proxy,
# Fargate). Tear it down with destroy.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${ENV:-dev}"
PARAMS_FILE="${HERE}/parameters/${ENV}.json"
ACTION="${1:-deploy}"

if [[ "${CONFIRM_DEPLOY:-}" != "yes" ]]; then
  echo "refusing to deploy: set CONFIRM_DEPLOY=yes after reading the cost note at the top of this script" >&2
  exit 2
fi
for tool in aws python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing tool: $tool" >&2; exit 2; }
done
[[ -f "$PARAMS_FILE" ]] || { echo "no parameter file for ENV=${ENV}: ${PARAMS_FILE}" >&2; exit 2; }

# ---- read the parameter file --------------------------------------------------------------------
json_get() { # json_get <key>  -> top-level string value
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$PARAMS_FILE" "$1"
}
stack_overrides() { # stack_overrides <layer> -> "Key=Value" words, one per line
  python3 - "$PARAMS_FILE" "$1" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
for key, value in data["stacks"].get(sys.argv[2], {}).items():
    if value != "":  # empty means "keep the template default"
        print(f"{key}={value}")
PY
}

PROJECT="$(json_get project)"
REGION="${AWS_REGION:-$(json_get region)}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
CALLER="$(aws sts get-caller-identity --query Arn --output text)"

echo "target account : ${ACCOUNT}"
echo "caller         : ${CALLER}"
echo "region         : ${REGION}"
echo "project/env    : ${PROJECT}/${ENV}"
echo "action         : ${ACTION}${ONLY:+ (only ${ONLY})}"
echo

stack_name() { echo "${PROJECT}-${ENV}-$1"; }

stack_output() { # stack_output <layer> <OutputKey>
  aws cloudformation describe-stacks --stack-name "$(stack_name "$1")" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

export_value() { # export_value <ExportName suffix>
  aws cloudformation list-exports \
    --query "Exports[?Name=='${PROJECT}-${ENV}-$1'].Value" --output text
}

deploy_layer() { # deploy_layer <layer> [extra Key=Value ...]
  local layer="$1"; shift
  local -a overrides=()
  while IFS= read -r line; do [[ -n "$line" ]] && overrides+=("$line"); done < <(stack_overrides "$layer")
  overrides+=("ProjectName=${PROJECT}" "Environment=${ENV}" "$@")
  echo "==> ${layer}: aws cloudformation deploy --stack-name $(stack_name "$layer")"
  aws cloudformation deploy \
    --stack-name "$(stack_name "$layer")" \
    --template-file "${HERE}/${layer}.yaml" \
    --parameter-overrides "${overrides[@]}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset \
    --tags "Project=${PROJECT}" "Environment=${ENV}" "ManagedBy=containers-on-aws/labs"
}

# ---- post-03: compose DATABASE_URL from the managed admin secret and the proxy endpoint --------
compose_database_url() {
  local admin_secret proxy_endpoint url_secret
  admin_secret="$(stack_output 03-data DbAdminSecretArn)"
  proxy_endpoint="$(stack_output 03-data DbProxyEndpoint)"
  url_secret="$(stack_output 03-data DatabaseUrlSecretArn)"
  echo "==> composing DATABASE_URL secret (${url_secret##*:}) from ${admin_secret##*:} and ${proxy_endpoint}"
  # The password never touches the terminal or a temp file: it flows JSON -> python -> put-secret-value.
  aws secretsmanager get-secret-value --secret-id "$admin_secret" --query SecretString --output text \
    | python3 -c '
import json, sys, urllib.parse
admin = json.load(sys.stdin)
host = sys.argv[1]
user = urllib.parse.quote(admin["username"], safe="")
password = urllib.parse.quote(admin["password"], safe="")
print(f"postgres://{user}:{password}@{host}:5432/shopfront?sslmode=require", end="")
' "$proxy_endpoint" \
    | aws secretsmanager put-secret-value --secret-id "$url_secret" --secret-string file:///dev/stdin \
        --query VersionId --output text
}

# ---- ECR enhanced scanning is a registry-level setting with no CloudFormation resource ----------
enable_enhanced_scanning() {
  echo "==> enabling ECR enhanced scanning (Inspector, continuous) for repositories ${PROJECT}/*"
  aws ecr put-registry-scanning-configuration --scan-type ENHANCED --rules "[
    {\"scanFrequency\": \"CONTINUOUS_SCAN\", \"repositoryFilters\": [{\"filter\": \"${PROJECT}/*\", \"filterType\": \"WILDCARD\"}]}
  ]" --query registryScanningConfiguration.scanType --output text
}

# ---- one-off task: schema.sql + seed.sql through psql ------------------------------------------
migrate() {
  local taskdef cluster subnets sg schema seed task_arn exit_code
  taskdef="$(stack_output 04-services MigrateTaskDefinitionArn)"
  cluster="$(export_value ClusterName)"
  subnets="$(export_value PrivateSubnetIds)"
  sg="$(export_value ServicesSecurityGroupId)"
  schema="$(cat "${HERE}/../../local/schema.sql")"
  seed="$(cat "${HERE}/../../local/seed.sql")"
  echo "==> running db-migrate task on ${cluster}"
  # Overrides are limited to 8 KiB; schema.sql + seed.sql are about 2.5 KiB.
  task_arn="$(aws ecs run-task \
    --cluster "$cluster" --launch-type FARGATE --platform-version LATEST --count 1 \
    --task-definition "$taskdef" \
    --network-configuration "awsvpcConfiguration={subnets=[${subnets}],securityGroups=[${sg}],assignPublicIp=DISABLED}" \
    --overrides "$(python3 - "$schema" "$seed" <<'PY'
import json, sys
schema, seed = sys.argv[1], sys.argv[2]
cmd = ["sh", "-c", 'printf "%s\\n%s\\n" "$SCHEMA_SQL" "$SEED_SQL" | psql "$DATABASE_URL" -v ON_ERROR_STOP=1']
print(json.dumps({"containerOverrides": [{
    "name": "psql",
    "command": cmd,
    "environment": [{"name": "SCHEMA_SQL", "value": schema}, {"name": "SEED_SQL", "value": seed}],
}]}))
PY
)" \
    --query 'tasks[0].taskArn' --output text)"
  echo "    task ${task_arn##*/} started; waiting for it to stop"
  aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task_arn"
  exit_code="$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
    --query 'tasks[0].containers[0].exitCode' --output text)"
  aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
    --query 'tasks[0].{stopCode:stopCode,stoppedReason:stoppedReason,exitCode:containers[0].exitCode}' --output table
  echo "    logs: aws logs tail /${PROJECT}/${ENV}/db-migrate --since 15m"
  [[ "$exit_code" == "0" ]] || { echo "migration failed (exit ${exit_code})" >&2; exit 1; }
}

# ---- main ---------------------------------------------------------------------------------------
case "$ACTION" in
  migrate)
    migrate
    exit 0
    ;;
  deploy) ;;
  *) echo "unknown action: ${ACTION} (deploy|migrate)" >&2; exit 2 ;;
esac

LAYERS=(01-network 02-cluster 03-data 04-services 05-observability 06-batch)
if [[ -n "${ONLY:-}" ]]; then
  LAYERS=("$ONLY")
fi

for layer in "${LAYERS[@]}"; do
  case "$layer" in
    04-services)
      extra=()
      [[ -n "${IMAGE_TAG:-}" ]] && extra+=("ImageTag=${IMAGE_TAG}")
      # Wire the rollback alarms when 05 already exists (second pass or later re-deploys).
      if alarms="$(stack_output 05-observability RollbackAlarmNames 2>/dev/null)" && [[ -n "$alarms" && "$alarms" != "None" ]]; then
        extra+=("RollbackAlarmNames=${alarms}")
      fi
      deploy_layer "$layer" ${extra[@]+"${extra[@]}"}
      ;;
    06-batch)
      extra=()
      [[ -n "${IMAGE_TAG:-}" ]] && extra+=("ImageTag=${IMAGE_TAG}")
      deploy_layer "$layer" ${extra[@]+"${extra[@]}"}
      ;;
    *)
      deploy_layer "$layer"
      ;;
  esac
  case "$layer" in
    02-cluster) enable_enhanced_scanning ;;
    03-data) compose_database_url ;;
  esac
done

# Full run: after 05 exists, re-deploy 04 once so deployments roll back on the alarms.
if [[ -z "${ONLY:-}" ]]; then
  alarms="$(stack_output 05-observability RollbackAlarmNames)"
  extra=("RollbackAlarmNames=${alarms}")
  [[ -n "${IMAGE_TAG:-}" ]] && extra+=("ImageTag=${IMAGE_TAG}")
  deploy_layer 04-services ${extra[@]+"${extra[@]}"}
fi

echo
echo "done. Next steps:"
echo "  1. push images: labs/pipelines/github-actions/ci.yml or 'make build-images' + docker push to $(export_value RegistryUri 2>/dev/null || echo '<registry>')"
echo "  2. CONFIRM_DEPLOY=yes ./deploy.sh migrate      # schema + seed through a one-off task"
echo "  3. curl http://$(stack_output 04-services LoadBalancerDnsName 2>/dev/null || echo '<alb>')/products"
echo "  4. dashboard: $(stack_output 05-observability DashboardUrl 2>/dev/null || echo '<see 05 outputs>')"
