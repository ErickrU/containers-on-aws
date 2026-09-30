#!/usr/bin/env bash
# Creates the IAM roles and EKS Pod Identity associations for the shopfront workloads and the
# platform controllers when the cluster was NOT created with eksctl-standard.yaml (which already
# declares them), for example on a cluster you built with Terraform, CDK or the console.
#
#   CONFIRM_DEPLOY=yes labs/eks/addons/pod-identity-associations.sh shopfront-dev
#
# Idempotent: existing roles get their trust and inline policies updated; existing associations are
# left alone. The Pod Identity agent add-on must be installed (built in on Auto Mode).
# hub/06 L200 §2.3 explains the trust policy (pods.eks.amazonaws.com with sts:AssumeRole + sts:TagSession)
# and why session tags make ABAC possible.
set -euo pipefail

CLUSTER="${1:?usage: $0 <cluster-name>}"
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

if [[ "${CONFIRM_DEPLOY:-}" != "yes" ]]; then
  echo "refusing to create IAM roles: set CONFIRM_DEPLOY=yes" >&2
  exit 2
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
PARTITION="$(aws sts get-caller-identity --query Arn --output text | cut -d: -f2)"
echo "account ${ACCOUNT}, region ${REGION}, cluster ${CLUSTER}"

TRUST_POLICY="$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowEksAuthToAssumeRoleForPodIdentity",
    "Effect": "Allow",
    "Principal": { "Service": "pods.eks.amazonaws.com" },
    "Action": ["sts:AssumeRole", "sts:TagSession"],
    "Condition": { "StringEquals": { "aws:SourceAccount": "${ACCOUNT}" } }
  }]
}
JSON
)"

ensure_role() { # ensure_role <role-name> <policy-json>
  local role="$1" policy="$2"
  if aws iam get-role --role-name "$role" >/dev/null 2>&1; then
    echo "  role ${role}: updating trust and policy"
    aws iam update-assume-role-policy --role-name "$role" --policy-document "$TRUST_POLICY"
  else
    echo "  role ${role}: creating"
    aws iam create-role --role-name "$role" --assume-role-policy-document "$TRUST_POLICY" \
      --description "EKS Pod Identity role for ${CLUSTER}" \
      --tags "Key=Project,Value=shopfront" "Key=Cluster,Value=${CLUSTER}" --query Role.Arn --output text
  fi
  aws iam put-role-policy --role-name "$role" --policy-name least-privilege --policy-document "$policy"
}

ensure_association() { # ensure_association <namespace> <service-account> <role-name>
  local ns="$1" sa="$2" role="$3"
  local existing
  existing="$(aws eks list-pod-identity-associations --cluster-name "$CLUSTER" --namespace "$ns" --service-account "$sa" \
    --query 'associations[0].associationId' --output text)"
  if [[ -n "$existing" && "$existing" != "None" ]]; then
    echo "  association ${ns}/${sa}: exists (${existing})"
    return
  fi
  echo "  association ${ns}/${sa} -> ${role}"
  aws eks create-pod-identity-association --cluster-name "$CLUSTER" --namespace "$ns" --service-account "$sa" \
    --role-arn "arn:${PARTITION}:iam::${ACCOUNT}:role/${role}" \
    --tags "Project=shopfront" --query 'association.associationId' --output text
}

QUEUE_ARN="arn:${PARTITION}:sqs:${REGION}:${ACCOUNT}:shopfront-dev-orders-created"
REPORTS_BUCKET="shopfront-reports-dev-${ACCOUNT}"

echo "== workloads (namespace shopfront)"
ensure_role "${CLUSTER}-orders" "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["sqs:SendMessage","sqs:GetQueueAttributes"],"Resource":"${QUEUE_ARN}"},
  {"Effect":"Allow","Action":["kafka-cluster:Connect","kafka-cluster:WriteData","kafka-cluster:DescribeTopic"],"Resource":"*"}
]}
JSON
)"
ensure_association shopfront orders "${CLUSTER}-orders"

ensure_role "${CLUSTER}-catalog" '{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"*","Resource":"*"}]}'
ensure_association shopfront catalog "${CLUSTER}-catalog"

ensure_role "${CLUSTER}-fulfillment-worker" "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["sqs:ReceiveMessage","sqs:DeleteMessage","sqs:ChangeMessageVisibility","sqs:GetQueueAttributes"],"Resource":"${QUEUE_ARN}"}
]}
JSON
)"
ensure_association shopfront fulfillment-worker "${CLUSTER}-fulfillment-worker"

ensure_role "${CLUSTER}-analytics-consumer" '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["kafka-cluster:Connect","kafka-cluster:ReadData","kafka-cluster:DescribeTopic","kafka-cluster:DescribeGroup","kafka-cluster:AlterGroup"],"Resource":"*"}]}'
ensure_association shopfront analytics-consumer "${CLUSTER}-analytics-consumer"

ensure_role "${CLUSTER}-report-job" "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:PutObject","s3:AbortMultipartUpload"],"Resource":"arn:${PARTITION}:s3:::${REPORTS_BUCKET}/daily/*"}
]}
JSON
)"
ensure_association shopfront report-job "${CLUSTER}-report-job"

echo "== platform controllers"
ensure_role "${CLUSTER}-external-secrets" "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["secretsmanager:GetSecretValue","secretsmanager:DescribeSecret"],"Resource":"arn:${PARTITION}:secretsmanager:${REGION}:${ACCOUNT}:secret:shopfront/*"}
]}
JSON
)"
ensure_association external-secrets external-secrets "${CLUSTER}-external-secrets"

ensure_role "${CLUSTER}-keda-operator" "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["sqs:GetQueueAttributes"],"Resource":"${QUEUE_ARN}"}
]}
JSON
)"
ensure_association keda keda-operator "${CLUSTER}-keda-operator"

ensure_role "${CLUSTER}-adot-collector" '{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["xray:PutTraceSegments","xray:PutTelemetryRecords","xray:GetSamplingRules","xray:GetSamplingTargets"],"Resource":"*"},
  {"Effect":"Allow","Action":["cloudwatch:PutMetricData"],"Resource":"*","Condition":{"StringEquals":{"cloudwatch:namespace":"shopfront/otel"}}},
  {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents","logs:DescribeLogStreams","logs:DescribeLogGroups","logs:PutRetentionPolicy"],"Resource":"*"}
]}'
ensure_association observability adot-collector "${CLUSTER}-adot-collector"

# The load balancer controller policy is long; download the official document and attach it as a
# managed policy instead of inlining it.
LBC_POLICY_NAME="${CLUSTER}-aws-load-balancer-controller"
if ! aws iam get-role --role-name "$LBC_POLICY_NAME" >/dev/null 2>&1; then
  echo "  role ${LBC_POLICY_NAME}: creating from the upstream iam_policy.json (v3.5.0)"
  curl -fsSL -o /tmp/lbc-iam-policy.json \
    https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v3.5.0/docs/install/iam_policy.json
  aws iam create-role --role-name "$LBC_POLICY_NAME" --assume-role-policy-document "$TRUST_POLICY" \
    --description "EKS Pod Identity role for the AWS Load Balancer Controller on ${CLUSTER}" --query Role.Arn --output text
  aws iam put-role-policy --role-name "$LBC_POLICY_NAME" --policy-name AWSLoadBalancerControllerIAMPolicy \
    --policy-document file:///tmp/lbc-iam-policy.json
  rm -f /tmp/lbc-iam-policy.json
else
  echo "  role ${LBC_POLICY_NAME}: exists"
fi
ensure_association kube-system aws-load-balancer-controller "$LBC_POLICY_NAME"

echo
echo "done. Verify from a pod:"
echo "  kubectl -n shopfront run awscli --rm -it --image=public.ecr.aws/aws-cli/aws-cli:2.37.6 --overrides='{\"spec\":{\"serviceAccountName\":\"orders\"}}' -- sts get-caller-identity"
echo "  (expect an assumed-role ARN for ${CLUSTER}-orders; the credentials come from 169.254.170.23)"
