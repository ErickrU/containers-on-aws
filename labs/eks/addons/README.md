# Add-ons for the shopfront EKS lab

Managed add-ons (VPC CNI, CoreDNS, kube-proxy, Pod Identity agent, EBS CSI, metrics-server,
CloudWatch Observability) are declared in `../cluster/eksctl-standard.yaml` and installed by eksctl.
This directory holds the values for the components you install with Helm or `kubectl`, in the order
below. Chart versions are pinned to what was current in September 2026; check the upstream release
page before bumping.

| Order | Component | Version | Values / manifest | Why the lab needs it |
| --- | --- | --- | --- | --- |
| 1 | AWS Load Balancer Controller | chart 3.5.0 | `aws-load-balancer-controller-values.yaml` | Ingress → ALB, readiness gates (standard clusters only; built in on Auto Mode) |
| 2 | Karpenter | 1.14.1 | `karpenter-values.yaml`, `../cluster/karpenter-nodepool.yaml` | Just-in-time nodes, consolidation (standard clusters only) |
| 3 | External Secrets Operator | chart 2.11.0 | `external-secrets-values.yaml`, `external-secrets-clustersecretstore.yaml` | `DATABASE_URL` from Secrets Manager into a Kubernetes Secret |
| 4 | KEDA | chart 2.21.0 | `keda-values.yaml` | Scale `fulfillment-worker` on SQS backlog |
| 5 | ADOT collector | image v0.50.0 | `adot-collector.yaml` | OTLP gateway: tail sampling → X-Ray, metrics → CloudWatch EMF |
| 6 | Argo Rollouts | chart 2.43.2 (v1.10.0) | `argo-rollouts-values.yaml`, `../gitops/rollout-orders-canary.yaml` | Canary with ALB weights and CloudWatch analysis |
| opt | Cilium | 1.20.2 | `cilium-values.yaml` | ENI-mode CNI with kube-proxy replacement and Hubble, on a fresh standard cluster |
| opt | CoreDNS configuration | add-on | `coredns-configuration-values.json` | Autoscaling and Corefile tuning through `aws eks update-addon` |

IAM for every controller comes from EKS Pod Identity. eksctl creates the associations for a cluster
built from `eksctl-standard.yaml`; for any other cluster run
`CONFIRM_DEPLOY=yes ./pod-identity-associations.sh <cluster>` first.

```bash
# 1. load balancer controller
helm repo add eks https://aws.github.io/eks-charts
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 \
  -n kube-system -f aws-load-balancer-controller-values.yaml --set clusterName=shopfront-dev

# 2. karpenter (controller pinned to the managed node group, NodePools after it is Ready)
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter --version 1.14.1 \
  -n kube-system -f karpenter-values.yaml
kubectl -n kube-system rollout status deploy/karpenter
kubectl apply -f ../cluster/karpenter-nodepool.yaml

# 3. external secrets
helm repo add external-secrets https://charts.external-secrets.io
helm upgrade --install external-secrets external-secrets/external-secrets --version 2.11.0 \
  -n external-secrets --create-namespace -f external-secrets-values.yaml
kubectl apply -f external-secrets-clustersecretstore.yaml

# 4. keda
helm repo add kedacore https://kedacore.github.io/charts
helm upgrade --install keda kedacore/keda --version 2.21.0 -n keda --create-namespace -f keda-values.yaml

# 5. collector
kubectl apply -f adot-collector.yaml

# 6. argo rollouts
helm repo add argo https://argoproj.github.io/argo-helm
helm upgrade --install argo-rollouts argo/argo-rollouts --version 2.43.2 \
  -n argo-rollouts --create-namespace -f argo-rollouts-values.yaml

# then the application
kubectl apply -k ../manifests/overlays/dev
kubectl -n shopfront get pods,ingress,scaledobject,externalsecret
```

What to observe after each step is described in the hands-on sections of hub/04 L200, hub/05 L200,
hub/06 L200, hub/07 L200 and hub/09 L200.
