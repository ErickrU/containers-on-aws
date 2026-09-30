# shopfront on Amazon EKS

The same four services as the ECS lab, expressed as Kubernetes objects, on either an EKS standard
cluster (you run the data plane: managed node group + Karpenter) or an EKS Auto Mode cluster (AWS
runs it). Nothing here deploys on its own; every step is a command you run.

```text
cluster/      eksctl ClusterConfigs (standard, Auto Mode), Karpenter NodePool/EC2NodeClass, Auto Mode NodePool/NodeClass
manifests/    kustomize base (namespace, service accounts, config, deployments, services, ingress, HPA, PDB,
              network policies, KEDA ScaledObject, CronJob, migration Job) and overlays dev/prod
addons/       Helm values and manifests for the controllers, plus the Pod Identity script
gitops/       Argo CD AppProject, Application, ApplicationSet; Argo Rollouts canary
```

## Run it

```bash
# 0. images in ECR (once): labs/pipelines/github-actions/ci.yml, or make build-images + docker push
# 1. cluster (pick one)
eksctl create cluster -f cluster/eksctl-standard.yaml      # ~20 min, then addons/README.md steps 1-6
eksctl create cluster -f cluster/eksctl-auto-mode.yaml     # ~12 min, then addons/README.md steps 3-6

# 2. data layer: reuse the ECS lab's 03-data stack (RDS Proxy, Valkey, SQS, S3) or point the
#    ConfigMap and ExternalSecret at your own; the pods need the VPC route to reach them.

# 3. application
kubectl apply -k manifests/overlays/dev
kubectl -n shopfront get pods,ingress,hpa,pdb,networkpolicy,scaledobject,externalsecret
kubectl -n shopfront get ingress shopfront -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
curl -s http://<alb-hostname>/products | head -c 300

# 4. GitOps (optional)
kubectl apply -f gitops/project.yaml -f gitops/application.yaml

# 5. tear down (the ALB is deleted with the Ingress; delete the namespace first, then the cluster)
kubectl delete -k manifests/overlays/dev
eksctl delete cluster -f cluster/eksctl-standard.yaml
```

## Cost while running

Control plane (per hour), three m7g.large nodes or Auto Mode compute, one NAT gateway, one ALB, and
the data layer from the ECS lab. Delete the cluster when you stop; a forgotten cluster is the most
common lab bill.

## Where each decision is explained

| Artifact | Hub document |
| --- | --- |
| `cluster/eksctl-standard.yaml` add-ons, node group, IMDS settings | [04 L200](../../hub/04-eks/L200-cluster-components-and-add-ons.md) |
| `cluster/eksctl-auto-mode.yaml`, `auto-mode-nodepool-nodeclass.yaml` | [04 L200 §2.7](../../hub/04-eks/L200-cluster-components-and-add-ons.md), [04 L300 §2.6](../../hub/04-eks/L300-eks-internals-and-operations.md) |
| `cluster/karpenter-nodepool.yaml` | [04 L400 §2.3](../../hub/04-eks/L400-eks-at-scale.md) |
| `manifests/base/ingress.yaml`, load balancer controller values | [05 L200 §2.3](../../hub/05-networking/L200-load-balancing-ingress-and-discovery.md) |
| `manifests/base/networkpolicies.yaml` | [05 L300 §2.6](../../hub/05-networking/L300-container-networking-internals.md), [06 L300](../../hub/06-identity-and-security/L300-hardening-workloads-and-clusters.md) |
| `serviceaccounts.yaml`, `addons/pod-identity-associations.sh` | [06 L200 §2.3](../../hub/06-identity-and-security/L200-iam-for-containers.md) |
| `securityContext`, PSA labels | [06 L300 §2.1](../../hub/06-identity-and-security/L300-hardening-workloads-and-clusters.md) |
| `addons/adot-collector.yaml` | [07 L200](../../hub/07-observability/L200-tooling-on-aws.md), [07 L400 §2.1](../../hub/07-observability/L400-observability-at-scale.md) |
| `gitops/*`, `rollout-orders-canary.yaml` | [08 L200 §2.6](../../hub/08-delivery-cicd-gitops/L200-pipelines-on-aws.md), [08 L300 §2.3](../../hub/08-delivery-cicd-gitops/L300-progressive-delivery-and-gitops-internals.md) |
| `scaledobject-fulfillment.yaml`, `cronjob-report.yaml` | [09 L200](../../hub/09-data-messaging-and-batch/L200-integration-patterns.md) |
| PDB, topology spread, probes, `terminationGracePeriodSeconds` | [10 L200](../../hub/10-resilience-and-dr/L200-designing-for-failure.md) |
