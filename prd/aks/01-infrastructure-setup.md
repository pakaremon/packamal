# Infrastructure Setup for AKS

## Prerequisites

- Azure subscription with appropriate permissions
- Azure CLI installed and configured
- kubectl installed
- Helm 3.x installed (for ingress controller)
- Terraform (optional, for infrastructure as code)

## AKS Cluster Configuration

### Cluster Specifications

```bash
# Variables
RESOURCE_GROUP="packamal-rg"
LOCATION="eastus"  # or your preferred region
CLUSTER_NAME="packamal-aks"
NODE_COUNT=3
NODE_VM_SIZE="Standard_D4s_v3"  # 4 vCPU, 16GB RAM
MIN_NODES=3
MAX_NODES=10
```

### Create Resource Group

```bash
az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION
```

### Create AKS Cluster

```bash
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --node-count $NODE_COUNT \
  --node-vm-size $NODE_VM_SIZE \
  --enable-cluster-autoscaler \
  --min-count $MIN_NODES \
  --max-count $MAX_NODES \
  --enable-managed-identity \
  --network-plugin azure \
  --network-policy azure \
  --enable-addons monitoring \
  --enable-addons http_application_routing \
  --generate-ssh-keys \
  --kubernetes-version 1.28.0
```

### Alternative: Using Node Pools

For better cost optimization, use separate node pools:

```bash
# System node pool (for system pods)
az aks nodepool add \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  --name systempool \
  --node-count 2 \
  --node-vm-size Standard_D2s_v3 \
  --mode System

# User node pool (for application workloads)
az aks nodepool add \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  --name userpool \
  --node-count 3 \
  --node-vm-size Standard_D4s_v3 \
  --mode User \
  --enable-cluster-autoscaler \
  --min-count 3 \
  --max-count 10

# Spot node pool (for analysis jobs - optional)
az aks nodepool add \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  --name spotpool \
  --node-count 0 \
  --node-vm-size Standard_D4s_v3 \
  --mode User \
  --priority Spot \
  --eviction-policy Delete \
  --spot-max-price -1 \
  --enable-cluster-autoscaler \
  --min-count 0 \
  --max-count 5 \
  --node-taints kubernetes.io/spot=true:NoSchedule
```

### Get Credentials

```bash
az aks get-credentials \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --overwrite-existing
```

## Storage Configuration

### Storage Classes

AKS provides default storage classes. For production, create custom storage classes:

```yaml
# storage-classes.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: managed-premium
provisioner: disk.csi.azure.com
parameters:
  skuname: Premium_LRS
  kind: managed
  cachingMode: ReadWrite
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: managed-premium-ssd
provisioner: disk.csi.azure.com
parameters:
  skuname: PremiumSSD_LRS
  kind: managed
  cachingMode: ReadOnly
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
---
# For ReadWriteMany (static files, if needed)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: azurefile-csi
provisioner: file.csi.azure.com
parameters:
  skuname: Premium_LRS
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

Apply:
```bash
kubectl apply -f storage-classes.yaml
```

## Networking

### Network Policies

Enable network policies during cluster creation (already done with `--network-policy azure`).

Create network policy for namespace isolation:

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: packamal-network-policy
  namespace: packamal
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    - namespaceSelector:
        matchLabels:
          name: kube-system
  - from:
    - podSelector:
        matchLabels:
          app: backend
    - podSelector:
        matchLabels:
          app: celery-worker
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: database
    ports:
    - protocol: TCP
      port: 5432
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379
  - to:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - protocol: TCP
      port: 8000
  - to: []  # Allow DNS
    ports:
    - protocol: UDP
      port: 53
  - to: []  # Allow external HTTPS
    ports:
    - protocol: TCP
      port: 443
```

### Ingress Controller

Install NGINX Ingress Controller:

```bash
# Add Helm repo
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

# Install
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=LoadBalancer \
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz
```

Get external IP:
```bash
kubectl get service ingress-nginx-controller -n ingress-nginx
```

## Azure Container Registry (ACR) Integration

Attach ACR to AKS:

```bash
# Get ACR name (created in 02-container-registry.md)
ACR_NAME="packamalacr"

# Get AKS credentials
az aks get-credentials --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME

# Attach ACR
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --attach-acr $ACR_NAME
```

## Managed Identity

AKS uses managed identity by default. For additional permissions:

```bash
# Get cluster identity
CLUSTER_IDENTITY=$(az aks show \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --query identity.principalId -o tsv)

# Grant permissions (example: Key Vault access)
KEY_VAULT_NAME="packamal-kv"
az keyvault set-policy \
  --name $KEY_VAULT_NAME \
  --object-id $CLUSTER_IDENTITY \
  --secret-permissions get list
```

## Resource Quotas

Set namespace resource quotas:

```yaml
# resource-quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: packamal-quota
  namespace: packamal
spec:
  hard:
    requests.cpu: "20"
    requests.memory: 40Gi
    limits.cpu: "40"
    limits.memory: 80Gi
    persistentvolumeclaims: "10"
    pods: "50"
```

## Limit Ranges

```yaml
# limit-range.yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: packamal-limits
  namespace: packamal
spec:
  limits:
  - default:
      cpu: "1"
      memory: 2Gi
    defaultRequest:
      cpu: 250m
      memory: 512Mi
    type: Container
  - max:
      cpu: "4"
      memory: 8Gi
    min:
      cpu: 100m
      memory: 128Mi
    type: Container
```

## Verification

```bash
# Check nodes
kubectl get nodes -o wide

# Check storage classes
kubectl get storageclass

# Check network policies
kubectl get networkpolicies -n packamal

# Check ingress controller
kubectl get pods -n ingress-nginx

# Test ACR access
kubectl run test-pod --image=$ACR_NAME.azurecr.io/packamal-backend:latest --rm -it --restart=Never -- /bin/sh
```

## Cost Estimation

Approximate monthly costs (East US region):

- AKS Cluster (3 nodes, Standard_D4s_v3): ~$450/month
- Managed Premium Disks (18Gi total): ~$3/month
- Load Balancer: ~$25/month
- Ingress Controller: Included in cluster
- Azure Monitor: ~$50/month (first 5GB free)

**Total: ~$528/month** (excluding data transfer and backup costs)

For cost optimization, see `08-cost-optimization.md`.

## Next Steps

1. Set up Azure Container Registry (see `02-container-registry.md`)
2. Configure security and RBAC (see `03-security-rbac.md`)
3. Prepare Kubernetes manifests (see `04-kubernetes-manifests/`)

