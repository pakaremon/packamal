# Cost Optimization

## Overview

This document provides strategies and recommendations for optimizing costs in the Packamal AKS deployment.

## Cost Breakdown

### Estimated Monthly Costs (East US)

| Component | Configuration | Monthly Cost |
|------------|---------------|--------------|
| AKS Cluster (3 nodes) | Standard_D4s_v3 | ~$450 |
| Managed Premium Disks | 85Gi total | ~$15 |
| Load Balancer | Standard | ~$25 |
| Azure Monitor | Logs + Metrics | ~$50 |
| Container Registry | Premium, 50GB | ~$9 |
| **Total** | | **~$549/month** |

*Excluding data transfer, backup storage, and other services*

## Node Optimization

### Right-Sizing Nodes

```bash
# Analyze current resource usage
kubectl top nodes
kubectl top pods -n packamal --containers

# Use smaller nodes if resources are underutilized
# Standard_D2s_v3 (2 vCPU, 8GB) instead of D4s_v3
az aks nodepool update \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  --name userpool \
  --node-vm-size Standard_D2s_v3
```

### Cluster Autoscaler

Enable cluster autoscaler to scale nodes based on demand:

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --enable-cluster-autoscaler \
  --min-count 2 \
  --max-count 5
```

### Spot Instances for Analysis Jobs

Use spot node pool for ephemeral analysis jobs:

```bash
# Create spot node pool
az aks nodepool add \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  --name spotpool \
  --node-count 0 \
  --node-vm-size Standard_D4s_v3 \
  --priority Spot \
  --eviction-policy Delete \
  --spot-max-price -1 \
  --enable-cluster-autoscaler \
  --min-count 0 \
  --max-count 3 \
  --node-taints kubernetes.io/spot=true:NoSchedule

# Update analysis job to use spot nodes
# Add to job spec:
tolerations:
- key: kubernetes.io/spot
  operator: Equal
  value: "true"
  effect: NoSchedule
nodeSelector:
  kubernetes.io/os: linux
```

**Savings**: Up to 90% discount on compute costs for analysis jobs

## Storage Optimization

### Use Standard Storage for Non-Critical Data

```yaml
# Use Standard storage for Redis (less critical)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: redis-pvc
spec:
  storageClassName: managed-standard  # Instead of managed-premium
  resources:
    requests:
      storage: 5Gi
```

### Enable Disk Compression

For analysis results, consider compression:

```python
# Compress results before saving
import gzip
import json

with gzip.open('/results/analysis.json.gz', 'wt') as f:
    json.dump(results, f)
```

### Lifecycle Management

Move old data to cool/archive tiers:

```bash
# Configure lifecycle policy for blob storage
az storage blob service-properties update \
  --account-name packamalbackups \
  --enable-delete-retention true \
  --delete-retention-days 30
```

## Resource Requests and Limits

### Optimize Resource Requests

Review and adjust based on actual usage:

```yaml
# Before (over-provisioned)
resources:
  requests:
    cpu: 1000m
    memory: 2Gi
  limits:
    cpu: 4000m
    memory: 8Gi

# After (right-sized)
resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 2Gi
```

### Use Vertical Pod Autoscaler (VPA)

```bash
# Install VPA
git clone https://github.com/kubernetes/autoscaler.git
cd autoscaler/vertical-pod-autoscaler
./hack/vpa-up.sh

# Create VPA for backend
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: backend-vpa
  namespace: packamal
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  updatePolicy:
    updateMode: "Auto"
```

## Image Optimization

### Multi-Stage Builds

Reduce image sizes:

```dockerfile
# Backend Dockerfile optimization
FROM python:3.11-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .
ENV PATH=/root/.local/bin:$PATH
```

### Image Caching

Use ACR build cache:

```bash
az acr build \
  --registry $ACR_NAME \
  --image packamal-backend:latest \
  --cache-from packamal-backend:latest \
  ./backend
```

## Monitoring Costs

### Azure Cost Management

```bash
# Set budget alert
az consumption budget create \
  --budget-name packamal-monthly \
  --amount 600 \
  --time-grain Monthly \
  --start-date $(date +%Y-%m-01) \
  --end-date $(date -d "+1 year" +%Y-%m-01) \
  --resource-group $RESOURCE_GROUP
```

### Cost Analysis Queries

```kql
// Azure Cost Management query
Usage
| where ResourceGroup == "packamal-rg"
| summarize TotalCost = sum(Cost) by ResourceType
| order by TotalCost desc
```

## Reserved Instances

### Purchase Reserved Instances

For predictable workloads, purchase 1-year or 3-year reservations:

```bash
# Calculate savings
# Standard_D4s_v3: Pay-as-you-go ~$150/month
# 1-year reserved: ~$90/month (40% savings)
# 3-year reserved: ~$60/month (60% savings)
```

**Savings**: 40-60% on compute costs

## Network Optimization

### Use Internal Load Balancer

For internal services, use internal load balancer:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend
  annotations:
    service.beta.kubernetes.io/azure-load-balancer-internal: "true"
spec:
  type: LoadBalancer
```

**Savings**: ~$10/month per internal load balancer

### Data Transfer Optimization

- Use Azure CDN for static assets
- Enable compression
- Cache responses
- Use regional endpoints

## Database Optimization

### Use Azure Database for PostgreSQL

Managed service can be more cost-effective:

```bash
# Compare costs
# Self-managed: ~$150/month (VM + storage + backup)
# Managed: ~$100/month (includes HA, backups, maintenance)
```

### Connection Pooling

Reduce database connections:

```python
# Django database settings
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'CONN_MAX_AGE': 600,  # Reuse connections
        'OPTIONS': {
            'connect_timeout': 10,
        }
    }
}
```

## Cost Optimization Checklist

- [ ] Right-size nodes based on actual usage
- [ ] Enable cluster autoscaler
- [ ] Use spot instances for analysis jobs
- [ ] Optimize resource requests/limits
- [ ] Use standard storage for non-critical data
- [ ] Implement image optimization
- [ ] Purchase reserved instances for stable workloads
- [ ] Use internal load balancers where possible
- [ ] Monitor costs with budgets
- [ ] Review and optimize regularly

## Cost Monitoring Dashboard

Create Azure dashboard to track costs:

```json
{
  "lenses": [
    {
      "order": 0,
      "parts": [
        {
          "position": {
            "x": 0,
            "y": 0,
            "colSpan": 6,
            "rowSpan": 4
          },
          "metadata": {
            "inputs": [],
            "type": "Extension/Azure_Cost_Management_Part/PartType/CostAnalysisPart",
            "settings": {
              "scope": "/subscriptions/{subscription-id}/resourceGroups/packamal-rg"
            }
          }
        }
      ]
    }
  ]
}
```

## Regular Review

### Monthly Cost Review

1. Analyze cost trends
2. Identify cost drivers
3. Review resource utilization
4. Optimize underutilized resources
5. Update budgets and alerts

### Quarterly Optimization

1. Review reserved instance purchases
2. Evaluate new Azure services
3. Optimize storage tiers
4. Review network costs
5. Update cost optimization strategies

## Expected Savings

With optimizations:

| Optimization | Monthly Savings |
|--------------|----------------|
| Right-sized nodes | $100-150 |
| Spot instances (analysis jobs) | $50-100 |
| Reserved instances | $150-200 |
| Storage optimization | $10-20 |
| **Total** | **$310-470/month** |

**Optimized monthly cost: ~$80-240/month** (from ~$549/month)

## Next Steps

1. Analyze current resource usage
2. Implement right-sizing
3. Set up cost monitoring
4. Purchase reserved instances
5. Schedule regular cost reviews

