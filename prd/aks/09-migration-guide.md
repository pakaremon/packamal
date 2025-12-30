# Migration Guide: Minikube to AKS

## Overview

This guide provides a step-by-step process for migrating the Packamal application from local Minikube to Azure Kubernetes Service (AKS).

## Prerequisites

- [ ] Azure subscription with appropriate permissions
- [ ] Azure CLI installed and configured (`az login`)
- [ ] kubectl installed
- [ ] Docker installed (for building images)
- [ ] Access to existing Minikube cluster
- [ ] Application code and configuration files

## Pre-Migration Checklist

### 1. Document Current State

```bash
# Export current Minikube configuration
kubectl get all -n packamal -o yaml > minikube-state.yaml
kubectl get configmap -n packamal -o yaml > minikube-configmaps.yaml
kubectl get secrets -n packamal -o yaml > minikube-secrets.yaml
kubectl get pvc -n packamal -o yaml > minikube-pvcs.yaml
```

### 2. Backup Data

```bash
# Backup PostgreSQL
kubectl exec -n packamal deployment/database -- pg_dump -U packamal_db packamal > postgres-backup.sql

# Backup Redis (if needed)
kubectl exec -n packamal deployment/redis -- redis-cli SAVE
kubectl cp packamal/redis-pod:/data/dump.rdb ./redis-backup.rdb
```

### 3. Review Dependencies

- [ ] Database schema and migrations
- [ ] Environment variables
- [ ] Secrets and credentials
- [ ] External service dependencies
- [ ] DNS and networking requirements

## Migration Steps

### Phase 1: Infrastructure Setup

#### Step 1.1: Create Resource Group

```bash
RESOURCE_GROUP="packamal-rg"
LOCATION="eastus"

az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION
```

#### Step 1.2: Create AKS Cluster

```bash
CLUSTER_NAME="packamal-aks"

az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --node-count 3 \
  --node-vm-size Standard_D4s_v3 \
  --enable-cluster-autoscaler \
  --min-count 3 \
  --max-count 10 \
  --enable-managed-identity \
  --network-plugin azure \
  --network-policy azure \
  --enable-addons monitoring \
  --generate-ssh-keys

# Get credentials
az aks get-credentials \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --overwrite-existing
```

#### Step 1.3: Create Azure Container Registry

```bash
ACR_NAME="packamalacr"

az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Premium \
  --location $LOCATION

# Attach ACR to AKS
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --attach-acr $ACR_NAME
```

#### Step 1.4: Set Up Storage Classes

```bash
kubectl apply -f prd/aks/04-kubernetes-manifests/storage-classes.yaml
```

### Phase 2: Image Migration

#### Step 2.1: Build and Push Images

```bash
ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"
PROJECT_DIR="/home/azureuser/packamal"

# Login to ACR
az acr login --name $ACR_NAME

# Build and push backend
cd $PROJECT_DIR/backend
az acr build \
  --registry $ACR_NAME \
  --image packamal-backend:latest \
  --image packamal-backend:$(git rev-parse --short HEAD) \
  .

# Build and push frontend
cd $PROJECT_DIR/frontend
az acr build \
  --registry $ACR_NAME \
  --image packamal-frontend:latest \
  --image packamal-frontend:$(git rev-parse --short HEAD) \
  .

# Build and push Go worker
cd $PROJECT_DIR/worker
az acr build \
  --registry $ACR_NAME \
  --file cmd/analyze/Dockerfile \
  --image packamal-go-worker-analysis:latest \
  --image packamal-go-worker-analysis:$(git rev-parse --short HEAD) \
  .
```

#### Step 2.2: Verify Images

```bash
az acr repository list --name $ACR_NAME --output table
az acr repository show-tags --name $ACR_NAME --repository packamal-backend --output table
```

### Phase 3: Configuration Migration

#### Step 3.1: Update ConfigMaps

```bash
# Export from Minikube
kubectl get configmap packamal-config -n packamal -o yaml > minikube-config.yaml

# Update for AKS (see prd/aks/04-kubernetes-manifests/01-config.yaml)
# Key changes:
# - Update ALLOWED_HOSTS with AKS domain
# - Update CSRF_TRUSTED_ORIGINS
# - Update ANALYSIS_IMAGE to ACR path
```

#### Step 3.2: Migrate Secrets

**Option A: Manual (for testing)**

```bash
# Export from Minikube (decode base64)
kubectl get secret packamal-secrets -n packamal -o jsonpath='{.data}' | \
  jq -r 'to_entries[] | "\(.key)=\(.value | @base64d)"'

# Create in AKS
kubectl create secret generic packamal-secrets \
  --from-literal=POSTGRES_PASSWORD='your-password' \
  --from-literal=SECRET_KEY='your-secret-key' \
  --from-literal=INTERNAL_API_TOKEN='your-token' \
  --namespace packamal
```

**Option B: Azure Key Vault (recommended for production)**

```bash
# Create Key Vault
az keyvault create \
  --name packamal-kv \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# Store secrets
az keyvault secret set --vault-name packamal-kv --name postgres-password --value "your-password"
az keyvault secret set --vault-name packamal-kv --name django-secret-key --value "your-secret-key"
az keyvault secret set --vault-name packamal-kv --name internal-api-token --value "your-token"

# Configure SecretProviderClass (see 03-security-rbac.md)
kubectl apply -f prd/aks/04-kubernetes-manifests/secret-provider-class.yaml
```

### Phase 4: Application Deployment

#### Step 4.1: Create Namespace

```bash
kubectl apply -f prd/aks/04-kubernetes-manifests/00-namespace.yaml
```

#### Step 4.2: Deploy RBAC

```bash
kubectl apply -f prd/aks/04-kubernetes-manifests/11-rbac.yaml
```

#### Step 4.3: Deploy Config and Secrets

```bash
# Update ACR name in config
sed -i "s/packamalacr.azurecr.io/$ACR_LOGIN_SERVER/g" \
  prd/aks/04-kubernetes-manifests/01-config.yaml

kubectl apply -f prd/aks/04-kubernetes-manifests/01-config.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/01-secrets.yaml
```

#### Step 4.4: Create Persistent Volumes

```bash
kubectl apply -f prd/aks/04-kubernetes-manifests/02-pvc.yaml

# Wait for PVCs to be bound
kubectl wait --for=condition=Bound pvc -n packamal --all --timeout=5m
```

#### Step 4.5: Deploy Databases

```bash
kubectl apply -f prd/aks/04-kubernetes-manifests/03-postgres.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/04-redis.yaml

# Wait for databases to be ready
kubectl wait --for=condition=ready pod -n packamal -l app=database --timeout=5m
kubectl wait --for=condition=ready pod -n packamal -l app=redis --timeout=5m
```

#### Step 4.6: Restore Database

```bash
# Copy backup to AKS pod
kubectl cp postgres-backup.sql packamal/$(kubectl get pod -n packamal -l app=database -o jsonpath='{.items[0].metadata.name}'):/tmp/backup.sql

# Restore
kubectl exec -n packamal deployment/database -- psql -U packamal_db -d packamal -f /tmp/backup.sql
```

#### Step 4.7: Deploy Application Components

```bash
# Update image references in manifests
find prd/aks/04-kubernetes-manifests -name "*.yaml" -exec \
  sed -i "s|packamalacr.azurecr.io|$ACR_LOGIN_SERVER|g" {} \;

# Deploy in order
kubectl apply -f prd/aks/04-kubernetes-manifests/13-image-preloader.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/05-backend.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/06-worker.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/08-worker-2.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/09-celery-beat.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/10-flower.yaml
kubectl apply -f prd/aks/04-kubernetes-manifests/07-frontend.yaml
```

#### Step 4.8: Deploy Autoscaling

```bash
kubectl apply -f prd/aks/04-kubernetes-manifests/12-backend-hpa.yaml
```

#### Step 4.9: Deploy Ingress

```bash
# Install NGINX Ingress Controller (if not already installed)
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=LoadBalancer

# Update ingress hostname
sed -i "s/packamal.example.com/your-domain.com/g" \
  prd/aks/04-kubernetes-manifests/14-ingress.yaml

kubectl apply -f prd/aks/04-kubernetes-manifests/14-ingress.yaml
```

### Phase 5: Verification

#### Step 5.1: Check Pod Status

```bash
kubectl get pods -n packamal
kubectl get services -n packamal
kubectl get ingress -n packamal
```

#### Step 5.2: Verify Application

```bash
# Get external IP
EXTERNAL_IP=$(kubectl get service ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Test frontend
curl http://$EXTERNAL_IP

# Test backend API
curl http://$EXTERNAL_IP/api/v1/health
```

#### Step 5.3: Test Analysis Job

```bash
# Create test analysis job
curl -X POST "http://$EXTERNAL_IP/api/v1/analyze/" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"purl": "pkg:npm/lodash@4.17.21"}'

# Check job status
kubectl get jobs -n packamal
kubectl get pods -n packamal -l app=analysis-job
```

### Phase 6: Post-Migration

#### Step 6.1: Configure Monitoring

```bash
# Enable Container Insights (if not already enabled)
az aks enable-addons \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --addons monitoring
```

#### Step 6.2: Set Up Backups

```bash
# Install Velero
velero install \
  --provider azure \
  --plugins velero/velero-plugin-for-microsoft-azure:v1.6.0 \
  --bucket velero \
  --secret-file ./credentials-velero \
  --backup-location-config resourceGroup=$RESOURCE_GROUP,storageAccount=packamalvelero

# Create backup schedule
velero schedule create packamal-daily \
  --schedule="0 2 * * *" \
  --include-namespaces packamal
```

#### Step 6.3: Configure Alerts

See `06-monitoring-logging.md` for alert configuration.

## Rollback Plan

If migration fails:

### Option 1: Keep Minikube Running

```bash
# Switch back to Minikube
kubectl config use-context minikube

# Verify Minikube cluster
kubectl get pods -n packamal
```

### Option 2: Restore from Backup

```bash
# Restore database
kubectl exec -n packamal deployment/database -- psql -U packamal_db -d packamal < postgres-backup.sql

# Restore PVCs from snapshots (if created)
# See 07-backup-disaster-recovery.md
```

## Common Issues and Solutions

### Issue 1: Image Pull Errors

**Symptom**: `ImagePullBackOff` errors

**Solution**:
```bash
# Verify ACR attachment
az aks show --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME --query addonProfiles

# Check image exists
az acr repository show-tags --name $ACR_NAME --repository packamal-backend

# Verify service account has permissions
kubectl get serviceaccount backend-serviceaccount -n packamal -o yaml
```

### Issue 2: PVC Not Binding

**Symptom**: PVC stuck in `Pending` state

**Solution**:
```bash
# Check storage class
kubectl get storageclass

# Check PVC events
kubectl describe pvc postgres-pvc -n packamal

# Verify node has available capacity
kubectl top nodes
```

### Issue 3: Analysis Jobs Failing

**Symptom**: Analysis jobs fail with Podman errors

**Solution**:
```bash
# Check pod logs
kubectl logs -n packamal <analysis-pod-name>

# Verify privileged mode
kubectl get job <job-name> -n packamal -o yaml | grep privileged

# Check image preloader
kubectl get pods -n packamal -l app=image-preloader
```

### Issue 4: Database Connection Issues

**Symptom**: Backend cannot connect to database

**Solution**:
```bash
# Check database pod
kubectl get pods -n packamal -l app=database

# Test connection from backend pod
kubectl exec -n packamal deployment/backend -- nc -zv database 5432

# Check service
kubectl get service database -n packamal
```

## Migration Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Infrastructure Setup | 1-2 hours | Azure subscription |
| Image Migration | 30-60 min | ACR created |
| Configuration Migration | 30 min | Secrets available |
| Application Deployment | 1-2 hours | All prerequisites |
| Verification | 30 min | Deployment complete |
| Post-Migration | 1-2 hours | Application running |

**Total Estimated Time: 4-7 hours**

## Success Criteria

- [ ] All pods running and healthy
- [ ] Database accessible and data restored
- [ ] Frontend accessible via ingress
- [ ] Backend API responding
- [ ] Analysis jobs executing successfully
- [ ] Monitoring and logging operational
- [ ] Backups configured
- [ ] Performance meets requirements

## Next Steps

1. Complete migration following this guide
2. Perform load testing
3. Monitor for 24-48 hours
4. Optimize based on metrics (see `08-cost-optimization.md`)
5. Decommission Minikube cluster (after verification)

## Support

For issues during migration:
1. Check logs: `kubectl logs -n packamal <pod-name>`
2. Review events: `kubectl get events -n packamal --sort-by='.lastTimestamp'`
3. Consult documentation in `prd/aks/` directory
4. Review Azure Monitor logs

