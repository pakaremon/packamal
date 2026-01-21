# GKE Infrastructure Setup

## Cluster Requirements
- **GKE Standard** (not Autopilot) to allow privileged pods and hostPath mounts.
- **VPC-native** cluster with IP aliasing.
- **Network Policy** enabled.
- **Workload Identity** enabled.

## Recommended Node Pools
1. **system-pool** (small nodes)
   - Runs kube-system and infrastructure pods.

2. **app-pool** (general workloads)
   - Runs backend, frontend, celery, postgres, redis.

3. **heavy-analysis** (large nodes)
   - Dedicated to privileged analysis jobs.
   - Taint: `heavy-analysis=true:NoSchedule`.
   - Label example: `nodepool=heavy-analysis`.

## REfesh config
```sh
gcloud container clusters get-credentials packamal-gke --project k8s-packamal --zone us-central1-a
```
## Example gcloud Commands
```SH
 
export PROJECT_ID="k8s-packamal"
export ZONE="us-central1-a"
export CLUSTER="packamal-gke"

# Bước 1: Tạo Cluster với cấu hình mặc định siêu nhỏ (Chỉ để giữ Control Plane)
gcloud container clusters create $CLUSTER \
    --project $PROJECT_ID \
    --zone $ZONE \
    --num-nodes 1 \
    --machine-type "e2-medium" \
    --spot \
    --enable-ip-alias \
    --workload-pool=$PROJECT_ID.svc.id.goog \
    --enable-shielded-nodes

# Bước 2: Tạo App Pool (Dành cho Backend, DB, Redis)
# Dùng 16GB RAM để chạy mượt các dịch vụ quản trị
gcloud container node-pools create app-pool \
    --cluster $CLUSTER \
    --zone $ZONE \
    --machine-type "e2-standard-4" \
    --num-nodes 1 \
    --spot \
    --image-type "COS_CONTAINERD" \
    --node-labels "role=app-node"

# Bước 3: Tạo Heavy Analysis Pool (Dành riêng cho Malware)
# Có Taint để cách ly tuyệt đối

gcloud container node-pools create analysis-pool \
    --cluster $CLUSTER \
    --zone $ZONE \
    --machine-type "e2-standard-4" \
    --image-type "COS_CONTAINERD" \
    --num-nodes 0 \
    --enable-autoscaling \
    --min-nodes 0 \
    --max-nodes 1 \
    --spot \
    --sandbox type=gvisor \
    --node-taints "dedicated=analysis:NoSchedule" \
    --node-labels "role=analysis-worker"

# NOTE (quan trọng):
# - Node pool chạy `--sandbox type=gvisor` sẽ có thêm taint:
#     sandbox.gke.io/runtime=gvisor:NoSchedule
# - Vì vậy Pod/Job Go heavy worker phải có:
#   - nodeSelector: role=analysis-worker
#   - tolerations:
#       - dedicated=analysis:NoSchedule
#       - sandbox.gke.io/runtime=gvisor:NoSchedule
# Nếu thiếu toleration gvisor thì Job sẽ Pending và autoscaler cũng không scale-up từ 0 node.

## Reasoning
- **Dedicated node pool** isolates privileged analysis pods from core services.
- **Network Policy** enables micro-segmentation with Kubernetes NetworkPolicies.
- **Workload Identity** reduces credential exposure and simplifies IAM.
