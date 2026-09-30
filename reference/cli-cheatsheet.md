# CLI cheatsheet

The commands the hub and the playbooks keep reaching for, grouped by tool. Region `us-east-1`,
account `123456789012`, cluster `shopfront-dev`, namespace `shopfront`. Read-only commands first in
every section; anything that changes state is marked **(writes)**.

## aws ecs

```bash
# Inventory
aws ecs list-clusters
aws ecs describe-clusters --clusters shopfront-dev --include SETTINGS CONFIGURATIONS ATTACHMENTS STATISTICS
aws ecs list-services --cluster shopfront-dev
aws ecs describe-services --cluster shopfront-dev --services orders --query 'services[0].{running:runningCount,desired:desiredCount,deployments:deployments,events:events[0:5].message}'
aws ecs list-tasks --cluster shopfront-dev --service-name orders --desired-status RUNNING
aws ecs list-tasks --cluster shopfront-dev --service-name orders --desired-status STOPPED     # last hour only
aws ecs describe-tasks --cluster shopfront-dev --tasks <task-arn> --query 'tasks[0].{status:lastStatus,stopCode:stopCode,reason:stoppedReason,containers:containers[*].{name:name,exit:exitCode,reason:reason},eni:attachments[0].details}'
aws ecs describe-task-definition --task-definition shopfront-dev-orders --query 'taskDefinition.{cpu:cpu,memory:memory,exec:executionRoleArn,task:taskRoleArn,containers:containerDefinitions[*].{name:name,image:image,secrets:secrets}}'
aws ecs list-task-definitions --family-prefix shopfront-dev-orders --sort DESC --max-items 5
aws ecs describe-capacity-providers
aws ecs list-container-instances --cluster shopfront-dev && aws ecs describe-container-instances --cluster shopfront-dev --container-instances <arn> --query 'containerInstances[0].{agent:versionInfo,connected:agentConnected,status:status,tasks:runningTasksCount}'
aws ecs list-account-settings --effective-settings                                            # awsvpcTrunking, containerInsights defaults...

# Change (writes)
aws ecs update-service --cluster shopfront-dev --service orders --desired-count 4
aws ecs update-service --cluster shopfront-dev --service orders --force-new-deployment          # same task definition, new tasks
aws ecs update-service --cluster shopfront-dev --service orders --task-definition shopfront-dev-orders:12   # manual rollback
aws ecs wait services-stable --cluster shopfront-dev --services orders
aws ecs register-task-definition --cli-input-json file://labs/ecs/taskdefs/orders.json
aws ecs run-task --cluster shopfront-dev --launch-type FARGATE --task-definition shopfront-dev-report-job --network-configuration "awsvpcConfiguration={subnets=[subnet-0a1b2c3d4e5f6a7b8],securityGroups=[sg-0123456789abcdef0],assignPublicIp=DISABLED}" --overrides '{"containerOverrides":[{"name":"report-job","environment":[{"name":"REPORT_DATE","value":"2026-09-28"}]}]}'
aws ecs stop-task --cluster shopfront-dev --task <task-arn> --reason "game day"
aws ecs execute-command --cluster shopfront-dev --task <task-arn> --container orders --interactive --command "/bin/sh"   # needs enableExecuteCommand + ssmmessages
aws ecs put-account-setting-default --name awsvpcTrunking --value enabled
```

## aws eks

```bash
aws eks list-clusters
aws eks describe-cluster --name shopfront-dev --query 'cluster.{version:version,platform:platformVersion,endpoint:endpoint,status:status,vpc:resourcesVpcConfig,auth:accessConfig,logging:logging.clusterLogging[0].types,oidc:identity.oidc.issuer}'
aws eks describe-cluster-versions --query 'clusterVersions[*].[clusterVersion,status,endOfStandardSupportDate]' --output table
aws eks list-nodegroups --cluster-name shopfront-dev && aws eks describe-nodegroup --cluster-name shopfront-dev --nodegroup-name general-arm64 --query 'nodegroup.{status:status,version:version,release:releaseVersion,scaling:scalingConfig,health:health.issues,lt:launchTemplate}'
aws eks list-addons --cluster-name shopfront-dev && aws eks describe-addon --cluster-name shopfront-dev --addon-name vpc-cni --query 'addon.{version:addonVersion,status:status,config:configurationValues,issues:health.issues}'
aws eks describe-addon-versions --kubernetes-version 1.36 --addon-name coredns --query 'addons[0].addonVersions[0:3].[addonVersion,compatibilities[0].defaultVersion]'
aws eks describe-addon-configuration --addon-name vpc-cni --addon-version <v> --query configurationSchema --output text | python3 -m json.tool | head -60
aws eks list-access-entries --cluster-name shopfront-dev
aws eks describe-access-entry --cluster-name shopfront-dev --principal-arn arn:aws:iam::123456789012:role/Dev
aws eks list-associated-access-policies --cluster-name shopfront-dev --principal-arn arn:aws:iam::123456789012:role/Dev
aws eks list-pod-identity-associations --cluster-name shopfront-dev --namespace shopfront
aws eks describe-pod-identity-association --cluster-name shopfront-dev --association-id <id>
aws eks list-insights --cluster-name shopfront-dev --filter kubernetesVersions=1.36
aws eks list-updates --name shopfront-dev && aws eks describe-update --name shopfront-dev --update-id <id>
aws eks get-token --cluster-name shopfront-dev --query 'status.expirationTimestamp'

# writes
aws eks update-kubeconfig --name shopfront-dev --alias shopfront-dev [--role-arn <role>]
aws eks create-access-entry --cluster-name shopfront-dev --principal-arn arn:aws:iam::123456789012:role/Dev --type STANDARD
aws eks associate-access-policy --cluster-name shopfront-dev --principal-arn arn:aws:iam::123456789012:role/Dev --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy --access-scope type=namespace,namespaces=shopfront
aws eks create-pod-identity-association --cluster-name shopfront-dev --namespace shopfront --service-account orders --role-arn arn:aws:iam::123456789012:role/shopfront-dev-eks-orders
aws eks update-addon --cluster-name shopfront-dev --addon-name coredns --addon-version <v> --resolve-conflicts PRESERVE --configuration-values file://labs/eks/addons/coredns-configuration-values.json
aws eks update-cluster-version --name shopfront-dev --kubernetes-version 1.36
aws eks update-nodegroup-version --cluster-name shopfront-dev --nodegroup-name general-arm64
aws eks update-cluster-config --name shopfront-dev --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}'
```

## aws ecr

```bash
aws ecr get-login-password | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com
aws ecr describe-repositories --query 'repositories[*].[repositoryName,imageTagMutability,imageScanningConfiguration.scanOnPush,encryptionConfiguration.encryptionType]' --output table
aws ecr describe-images --repository-name shopfront/orders --query 'sort_by(imageDetails,&imagePushedAt)[-5:].[imageTags[0],imageDigest,imageSizeInBytes,imagePushedAt]' --output table
aws ecr describe-images --repository-name shopfront/orders --image-ids imageTag=sha-1a2b3c4 --query 'imageDetails[0].imageDigest'
aws ecr describe-image-scan-findings --repository-name shopfront/orders --image-id imageTag=sha-1a2b3c4 --query 'imageScanFindings.findingSeverityCounts'
aws ecr get-registry-scanning-configuration
aws ecr get-lifecycle-policy --repository-name shopfront/orders --query lifecyclePolicyText --output text | python3 -m json.tool
aws ecr get-repository-policy --repository-name shopfront/orders --query policyText --output text | python3 -m json.tool
aws ecr describe-registry                                                                       # replication configuration
aws ecr describe-pull-through-cache-rules
aws ecr batch-get-image --repository-name shopfront/orders --image-ids imageTag=sha-1a2b3c4 --query 'images[0].imageManifest' --output text | python3 -m json.tool | head -30   # manifest / index

# writes
aws ecr put-image-tag-mutability --repository-name shopfront/orders --image-tag-mutability IMMUTABLE
aws ecr put-registry-scanning-configuration --scan-type ENHANCED --rules '[{"scanFrequency":"CONTINUOUS_SCAN","repositoryFilters":[{"filter":"shopfront/*","filterType":"WILDCARD"}]}]'
aws ecr put-lifecycle-policy --repository-name shopfront/orders --lifecycle-policy-text file://lifecycle.json
aws ecr start-lifecycle-policy-preview --repository-name shopfront/orders && aws ecr get-lifecycle-policy-preview --repository-name shopfront/orders
aws ecr create-pull-through-cache-rule --ecr-repository-prefix docker-hub --upstream-registry-url registry-1.docker.io --credential-arn arn:aws:secretsmanager:us-east-1:123456789012:secret:ecr-pullthroughcache/docker-hub
aws ecr batch-delete-image --repository-name shopfront/orders --image-ids imageTag=old
```

## kubectl

```bash
kubectl auth whoami; kubectl auth can-i --list -n shopfront
kubectl get nodes -o wide -L topology.kubernetes.io/zone,karpenter.sh/nodepool,eks.amazonaws.com/nodegroup,kubernetes.io/arch
kubectl describe node <node> | sed -n '/Conditions:/,/Addresses:/p;/Allocated resources:/,/Events:/p'
kubectl top nodes; kubectl top pods -n shopfront --containers
kubectl -n shopfront get pods -o wide --sort-by=.status.startTime
kubectl -n shopfront get pods -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,REASON:.status.containerStatuses[0].lastState.terminated.reason,NODE:.spec.nodeName
kubectl -n shopfront describe pod <pod> | sed -n '/Events:/,$p'
kubectl -n shopfront logs deploy/orders --since=10m --all-containers --prefix
kubectl -n shopfront logs <pod> -c orders --previous
kubectl -n shopfront exec deploy/orders -- sh -c 'cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.current; cat /sys/fs/cgroup/cpu.stat'
kubectl -n shopfront get events --sort-by=.lastTimestamp | tail -30
kubectl get events -A --field-selector reason=FailedScheduling --sort-by=.lastTimestamp | tail
kubectl -n shopfront rollout status deploy/orders; kubectl -n shopfront rollout history deploy/orders
kubectl -n shopfront get deploy,svc,ingress,hpa,pdb,networkpolicy,scaledobject,externalsecret,cronjob,job
kubectl -n shopfront get ingress shopfront -o jsonpath='{.status.loadBalancer.ingress[0].hostname}{"\n"}'
kubectl -n shopfront get endpointslices -l kubernetes.io/service-name=catalog -o wide
kubectl -n kube-system get pods -o wide | grep -vE 'Running|Completed'
kubectl -n kube-system logs ds/aws-node -c aws-node --since=10m | tail
kubectl get --raw /metrics | grep '^apiserver_requested_deprecated_apis'
kubectl get --raw /readyz?verbose; kubectl get --raw /livez?verbose
kubectl api-resources --verbs=list -o name | xargs -n1 kubectl get -n shopfront --ignore-not-found --show-kind 2>/dev/null   # everything in a namespace
kubectl -n shopfront run dbg --rm -it --restart=Never --image=public.ecr.aws/amazonlinux/amazonlinux:2023 -- bash
kubectl debug -n shopfront <pod> -it --image=public.ecr.aws/amazonlinux/amazonlinux:2023 --target=orders --profile=general     # ephemeral container for distroless pods
kubectl debug node/<node> -it --image=public.ecr.aws/amazonlinux/amazonlinux:2023 -- chroot /host bash
kubectl -n shopfront port-forward svc/orders 8080:8080

# writes
kubectl apply -k labs/eks/manifests/overlays/dev; kubectl diff -k labs/eks/manifests/overlays/dev
kubectl apply --dry-run=server -f <file>                                                  # admission + validation without changes
kubectl -n shopfront rollout restart deploy/orders; kubectl -n shopfront rollout undo deploy/orders
kubectl -n shopfront scale deploy/fulfillment-worker --replicas=0
kubectl -n shopfront label pod <pod> shopfront.example.com/quarantine=true                 # isolate (networkpolicies.yaml)
kubectl cordon <node>; kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --grace-period=60 --timeout=10m; kubectl uncordon <node>
kubectl -n shopfront create job report-manual --from=cronjob/report-job
```

## eksctl

```bash
eksctl create cluster -f labs/eks/cluster/eksctl-standard.yaml [--dry-run]
eksctl get cluster --region us-east-1; eksctl get nodegroup --cluster shopfront-dev; eksctl get addon --cluster shopfront-dev
eksctl get podidentityassociation --cluster shopfront-dev; eksctl get accessentry --cluster shopfront-dev
eksctl utils describe-addon-versions --cluster shopfront-dev --name vpc-cni
eksctl utils update-cluster-logging --cluster shopfront-dev --enable-types all --approve
eksctl upgrade cluster -f labs/eks/cluster/eksctl-standard.yaml --approve              # control plane
eksctl update addon -f labs/eks/cluster/eksctl-standard.yaml
eksctl upgrade nodegroup --cluster shopfront-dev --name general-arm64 [--kubernetes-version 1.36]
eksctl create podidentityassociation --cluster shopfront-dev --namespace shopfront --service-account-name orders --role-arn <arn>
eksctl scale nodegroup --cluster shopfront-dev --name general-arm64 --nodes 4
eksctl delete cluster -f labs/eks/cluster/eksctl-standard.yaml [--disable-nodegroup-eviction]
```

## docker and BuildKit

```bash
docker build -t shopfront/orders:dev labs/apps/orders
docker buildx build --platform linux/amd64,linux/arm64 --sbom=true --provenance=mode=max -t 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders:sha-1a2b3c4 --push labs/apps/orders
docker buildx imagetools inspect 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders:sha-1a2b3c4         # index, platforms, attestations
docker image inspect shopfront/orders:dev --format '{{.Config.User}} {{.Config.Entrypoint}} {{.Config.ExposedPorts}} {{len .RootFS.Layers}} layers'
docker history --no-trunc shopfront/orders:dev | head
docker run --rm --read-only --tmpfs /tmp --memory=512m --cpus=0.5 --user 10001:10001 -e PORT=8080 shopfront/orders:dev   # prove the hardening locally
docker stats --no-stream; docker inspect <ctr> --format '{{.State.OOMKilled}} {{.State.ExitCode}} {{.HostConfig.Memory}}'
docker compose -f labs/local/compose.yaml up -d --build; docker compose -f labs/local/compose.yaml ps; docker compose -f labs/local/compose.yaml logs -f orders
docker compose -f labs/local/compose.yaml down -v
docker system df; docker builder prune --filter until=168h
```

## ctr, nerdctl, crictl (on a node)

```bash
# containerd's own CLI (namespaces: k8s.io on Kubernetes nodes, moby on Docker hosts)
sudo ctr -n k8s.io containers ls | head; sudo ctr -n k8s.io images ls | head; sudo ctr -n k8s.io tasks ls
sudo ctr -n k8s.io image pull --user AWS:$(aws ecr get-login-password) 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders:sha-1a2b3c4
sudo ctr -n k8s.io snapshots ls | head; sudo ctr plugins ls | grep -E 'snapshotter|cri'
# CRI view (what kubelet sees)
sudo crictl ps -a; sudo crictl pods; sudo crictl images
sudo crictl inspect <container-id> | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"]["state"], d["info"]["runtimeSpec"]["linux"]["resources"])'
sudo crictl logs --tail 50 <container-id>; sudo crictl stats
sudo crictl exec -it <container-id> sh
sudo crictl rmi --prune                                                                   # free disk from unused images
sudo crictl info | head -40                                                               # runtime config, registry mirrors
# Docker-compatible UX over containerd (Bottlerocket admin container / dev hosts)
nerdctl --namespace k8s.io ps; nerdctl --namespace k8s.io images
# ECS EC2 hosts still run Docker Engine:
docker ps --filter label=com.amazonaws.ecs.task-arn; curl -s localhost:51678/v1/tasks | python3 -m json.tool | head
sudo journalctl -u ecs -u containerd -u kubelet --since -15m
```

## helm and kustomize

```bash
helm repo add eks https://aws.github.io/eks-charts; helm repo update
helm search repo eks/aws-load-balancer-controller --versions | head -5
helm show values eks/aws-load-balancer-controller --version 3.5.0 | less
helm template aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f labs/eks/addons/aws-load-balancer-controller-values.yaml | kubeconform -strict -ignore-missing-schemas -summary
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f labs/eks/addons/aws-load-balancer-controller-values.yaml --set clusterName=shopfront-dev --atomic --timeout 5m
helm list -A; helm history karpenter -n kube-system; helm get values karpenter -n kube-system
helm rollback karpenter 3 -n kube-system
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter --version 1.14.1 -n kube-system -f labs/eks/addons/karpenter-values.yaml
kustomize build labs/eks/manifests/overlays/dev | kubeconform -strict -ignore-missing-schemas -summary -schema-location default -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
(cd labs/eks/manifests/overlays/dev && kustomize edit set image 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders@sha256:<digest>)
kubectl kustomize labs/eks/manifests/overlays/dev | grep -nE '^kind:|^  name:' | head -40
```

## argocd and Argo Rollouts

```bash
argocd login argocd.shopfront.example.com --sso; argocd context
argocd app list -p shopfront; argocd app get shopfront-dev-us-east-1; argocd app diff shopfront-dev-us-east-1
argocd app history shopfront-dev-us-east-1; argocd app rollback shopfront-dev-us-east-1 <id>
argocd app sync shopfront-dev-us-east-1 --prune; argocd app set shopfront-prod-us-east-1 --sync-policy none      # pause automation
argocd app resources shopfront-dev-us-east-1; argocd app logs shopfront-dev-us-east-1 --kind Deployment --name orders
argocd proj get shopfront; argocd proj windows list shopfront
argocd appset get shopfront; argocd cluster list; argocd repo list
kubectl argo rollouts get rollout orders -n shopfront --watch
kubectl argo rollouts set image orders orders=123456789012.dkr.ecr.us-east-1.amazonaws.com/shopfront/orders@sha256:<digest> -n shopfront
kubectl argo rollouts promote orders -n shopfront [--full]; kubectl argo rollouts abort orders -n shopfront; kubectl argo rollouts undo orders -n shopfront
kubectl argo rollouts list analysisruns -n shopfront; kubectl argo rollouts dashboard
```

## aws (the rest, one-liners used by the runbooks)

```bash
aws sts get-caller-identity
aws iam simulate-principal-policy --policy-source-arn <role-arn> --action-names sqs:SendMessage --resource-arns <queue-arn> --query 'EvaluationResults[*].[EvalActionName,EvalDecision]'
aws logs tail /shopfront/dev/orders --since 15m --follow --format short
aws logs start-query --log-group-name /shopfront/dev/ecs-events --start-time "$(date -u -v-24H +%s)" --end-time "$(date -u +%s)" --query-string 'fields @timestamp, detail.stopCode, detail.stoppedReason | filter `detail-type` = "ECS Task State Change" | sort @timestamp desc | limit 50'
aws logs get-query-results --query-id <id>
aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name TargetResponseTime --dimensions Name=LoadBalancer,Value=<alb-full-name> --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 60 --extended-statistics p99
aws cloudwatch describe-alarms --alarm-name-prefix shopfront-dev --state-value ALARM --query 'MetricAlarms[*].[AlarmName,StateReason]'
aws cloudwatch set-alarm-state --alarm-name shopfront-dev-orders-5xx-ratio --state-value ALARM --state-reason "game day"   # test a rollback wiring
aws elbv2 describe-target-health --target-group-arn <tg-arn>
aws ec2 describe-network-interfaces --filters Name=status,Values=available --query 'NetworkInterfaces[*].[NetworkInterfaceId,Description]'   # leaked ENIs
aws ec2 describe-subnets --subnet-ids <ids> --query 'Subnets[*].[SubnetId,AvailabilityZone,AvailableIpAddressCount]'
aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=<vpc> --query 'VpcEndpoints[*].[ServiceName,State,PrivateDnsEnabled]'
aws ec2 get-network-insights-access-scope-analysis-findings 2>/dev/null; aws ec2 create-network-insights-path --source <eni> --destination <eni> --protocol tcp --destination-port 5432   # Reachability Analyzer
aws sqs get-queue-attributes --queue-url <url> --attribute-names All
aws sqs start-message-move-task --source-arn <dlq-arn> --destination-arn <queue-arn>
aws rds describe-db-clusters --db-cluster-identifier shopfront-dev --query 'DBClusters[0].{status:Status,writer:DBClusterMembers[?IsClusterWriter].DBInstanceIdentifier,acu:ServerlessV2ScalingConfiguration}'
aws rds describe-db-proxy-targets --db-proxy-name shopfront-dev
aws secretsmanager describe-secret --secret-id shopfront/dev/database-url --query '{rotation:RotationEnabled,replication:ReplicationStatus,versions:VersionIdsToStages}'
aws servicediscovery discover-instances --namespace-name shopfront.local --service-name catalog
aws batch describe-jobs --jobs <id> --query 'jobs[0].{status:status,reason:statusReason,exit:container.exitCode,log:container.logStreamName}'
aws service-quotas get-service-quota --service-code fargate --quota-code L-3032A538
aws cloudformation describe-stack-events --stack-name shopfront-dev-04-services --max-items 20 --query 'StackEvents[?ResourceStatus!=`UPDATE_COMPLETE`].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]' --output table
aws cloudformation list-exports --query "Exports[?starts_with(Name,'shopfront-dev-')].[Name,Value]" --output table
aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=StopTask --max-results 10 --query 'Events[*].[EventTime,Username]'
aws health describe-events --filter services=ECS,EKS,EC2 eventStatusCodes=open
aws fis start-experiment --experiment-template-id <id> --tags Name=orders-stop-half; aws fis stop-experiment --id <id>
aws arc-zonal-shift start-zonal-shift --resource-identifier <alb-arn> --away-from use1-az1 --expires-in 2h --comment "AZ impairment"
```

## Validation tools used by `make check`

```bash
.venv/bin/cfn-lint labs/ecs/cloudformation/*.yaml labs/pipelines/codepipeline/*.yaml
kubeconform -strict -ignore-missing-schemas -summary -schema-location default -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' labs/eks/manifests/base/*.yaml
shellcheck labs/**/*.sh tools/*.sh
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.12 -color labs/pipelines/github-actions/*.yml
docker run --rm -i hadolint/hadolint:v2.15.1 < labs/apps/orders/Dockerfile
docker run --rm -v "$PWD":/src aquasec/trivy:0.74.0 fs --scanners vuln,misconfig,secret /src/labs
.venv/bin/python tools/check_docs.py
```
