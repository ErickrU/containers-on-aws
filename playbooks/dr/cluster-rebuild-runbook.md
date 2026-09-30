# Rebuild an EKS cluster or the ECS environment from code

**Applies to:** both · **Severity guide:** SEV1 when the production cluster is lost or compromised; SEV3 when rehearsed in a sandbox · **Time to first fix:** ECS environment ~45 min (Aurora dominates); EKS ~40 min cluster + add-ons, then application sync

The premise of this repository: compute is disposable, state lives in managed services, everything
else is in git. This runbook proves it. If a step needs information that is not in git, that is a
finding for the game-day report.

## Preconditions

- [ ] Access to the target account and Region with a role that can create the stacks (`CAPABILITY_NAMED_IAM`); `aws sts get-caller-identity` shows it.
- [ ] Images present in the target Region's ECR (replication) or rebuildable from source by the pipeline; note the tag/digests to deploy.
- [ ] Data layer status decided: reuse the existing `03-data` stack (cluster loss only) or restore it (see data-recovery-runbook).
- [ ] Quotas in the target Region checked: Fargate vCPU, EC2 vCPU, EIPs/NAT, ALBs, VPCs.
- [ ] A clone of this repository at the commit that matches production (`git log -1`), `make check` green.

## Steps: ECS environment

```bash
cd labs/ecs/cloudformation
export AWS_REGION=us-east-1 ENV=prod      # or the recovery Region with parameters/prod-us-west-2.json
CONFIRM_DEPLOY=yes ONLY=01-network ./deploy.sh
CONFIRM_DEPLOY=yes ONLY=02-cluster ./deploy.sh          # cluster, namespace, ECR repos + replication, log groups, roles; enables enhanced scanning
# Data: skip if 03-data survived. Otherwise restore first (data-recovery-runbook) and then run 03 so exports exist, or
CONFIRM_DEPLOY=yes ONLY=03-data ./deploy.sh              # new Aurora/Valkey/SQS/S3 + DATABASE_URL secret composed by the script
CONFIRM_DEPLOY=yes IMAGE_TAG=sha-1a2b3c4 ONLY=04-services ./deploy.sh
CONFIRM_DEPLOY=yes ONLY=05-observability ./deploy.sh
CONFIRM_DEPLOY=yes IMAGE_TAG=sha-1a2b3c4 ONLY=04-services ./deploy.sh   # wires RollbackAlarmNames
CONFIRM_DEPLOY=yes IMAGE_TAG=sha-1a2b3c4 ONLY=06-batch ./deploy.sh
CONFIRM_DEPLOY=yes ./deploy.sh migrate                    # schema + seed (idempotent) only when the database is new
```

If images are missing in this Region: run `labs/pipelines/github-actions/ci.yml` against the commit
(`workflow_dispatch`) or `docker buildx build --push` from a trusted machine, then `deploy.sh`.

Timing to expect: 01 ~4 min (NAT), 02 ~3 min, 03 ~20–25 min (Aurora + proxy + Valkey), 04 ~6 min,
05 ~2 min, 06 ~3 min. Record the actuals.

## Steps: EKS cluster (standard)

```bash
export AWS_REGION=us-east-1
# 1. Cluster, node group, managed add-ons, Pod Identity associations (roles are recreated by eksctl)
eksctl create cluster -f labs/eks/cluster/eksctl-standard.yaml          # ~20 min
aws eks update-kubeconfig --name shopfront-dev --alias shopfront-dev

# 2. Controllers, in order (labs/eks/addons/README.md)
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f labs/eks/addons/aws-load-balancer-controller-values.yaml
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter --version 1.14.1 -n kube-system -f labs/eks/addons/karpenter-values.yaml
kubectl apply -f labs/eks/cluster/karpenter-nodepool.yaml
helm upgrade --install external-secrets external-secrets/external-secrets --version 2.11.0 -n external-secrets --create-namespace -f labs/eks/addons/external-secrets-values.yaml
kubectl apply -f labs/eks/addons/external-secrets-clustersecretstore.yaml
helm upgrade --install keda kedacore/keda --version 2.21.0 -n keda --create-namespace -f labs/eks/addons/keda-values.yaml
kubectl apply -f labs/eks/addons/adot-collector.yaml
helm upgrade --install argo-rollouts argo/argo-rollouts --version 2.43.2 -n argo-rollouts --create-namespace -f labs/eks/addons/argo-rollouts-values.yaml

# 3. Application: GitOps (preferred) or direct
helm upgrade --install argocd argo/argo-cd --version 10.9.4 -n argocd --create-namespace       # or the EKS Capability for Argo CD
kubectl apply -f labs/eks/gitops/project.yaml -f labs/eks/gitops/applicationset.yaml
#   direct alternative: kubectl apply -k labs/eks/manifests/overlays/prod

# 4. Anything that was NOT in git (the findings list): access entries for humans, Velero restore of
#    PVC-backed state, secrets that were created by hand, WAF associations, Route 53 records.
velero restore create --from-backup <latest> --include-namespaces <stateful-ns>    # only if you run Velero
```

EKS Auto Mode: replace step 1 with `eksctl create cluster -f labs/eks/cluster/eksctl-auto-mode.yaml`
and `kubectl apply -f labs/eks/cluster/auto-mode-nodepool-nodeclass.yaml`; skip the load balancer
controller and Karpenter in step 2.

Compromised-cluster variant: build the **new** cluster with a new name (`shopfront-prod-b`), cut
traffic over through the Ingress group/DNS, then delete the old one. Never reuse a cluster whose
control-plane credentials may have leaked; rotate the Pod Identity roles' trust if the cluster ARN
was in conditions (it is: `aws:SourceArn`).

## Verify

```bash
# ECS
aws ecs describe-services --cluster shopfront-prod --services orders catalog fulfillment-worker --query 'services[*].[serviceName,runningCount,desiredCount,deployments[0].rolloutState]' --output table
alb=$(aws cloudformation describe-stacks --stack-name shopfront-prod-04-services --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerDnsName'].OutputValue" --output text)
curl -fsS "http://$alb/products" | head -c 200
# EKS
kubectl get nodes; kubectl -n shopfront get pods,ingress,externalsecret,scaledobject
argocd app list -p shopfront
curl -fsS "http://$(kubectl -n shopfront get ingress shopfront -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')/products" | head -c 200
# Both: an order round-trips to FULFILLED; alarms exist; a no-op pipeline deploy succeeds.
```

## Rollback

There is nothing to roll back to; if the rebuild fails at a layer, fix and re-run that layer
(`ONLY=<layer>`; eksctl and Helm are idempotent). Delete half-built stacks with `destroy.sh` only in
a rehearsal.

## Prevent it (make the next rebuild boring)

- Everything in git, including access entries, WAF, Route 53 and alarm subscriptions; a quarterly rebuild in a sandbox account with a stopwatch (game-day-guide).
- Images replicated to the recovery Region; pipelines able to target it.
- Quotas in the recovery Region equal to primary; a checklist item, not a discovery.
- Velero only for state that cannot live in a managed service; audit that list quarterly.

## Related

- Plan: [dr-plan-template.md](dr-plan-template.md) · Failover: [region-failover-runbook.md](region-failover-runbook.md) · Data: [data-recovery-runbook.md](data-recovery-runbook.md)
- Mechanism: [03 · L400 DR posture for ECS](../../hub/03-ecs/L400-ecs-at-scale.md), [04 · L400 EKS DR: Velero, rebuild from git](../../hub/04-eks/L400-eks-at-scale.md), [08 · L400 DR of the delivery system](../../hub/08-delivery-cicd-gitops/L400-platform-engineering-and-delivery-at-scale.md)
