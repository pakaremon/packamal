# Azure Container Registry (ACR) Setup

## Overview

Azure Container Registry (ACR) will host all container images for the Packamal application. This replaces the local image loading used in Minikube.

## Create ACR

```bash
# Variables
RESOURCE_GROUP="packamal-rg"
ACR_NAME="packamalacr"  # Must be globally unique, lowercase alphanumeric only
LOCATION="eastus"
SKU="Premium"  # Options: Basic, Standard, Premium

# Create ACR
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku $SKU \
  --location $LOCATION \
  --admin-enabled false  # Use managed identity instead
```

### ACR SKU Comparison

- **Basic**: Development/testing, 10GB storage, 1 webhook
- **Standard**: Production, 100GB storage, 5 webhooks, geo-replication
- **Premium**: Enterprise, 500GB storage, 10 webhooks, geo-replication, content trust

For production, use **Premium** for:
- Geo-replication (disaster recovery)
- Content trust (image signing)
- Higher throughput

## Configure ACR Access

### Option 1: Attach ACR to AKS (Recommended)

```bash
# Get AKS cluster name
CLUSTER_NAME="packamal-aks"

# Attach ACR to AKS (grants AKS pull permissions)
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --attach-acr $ACR_NAME
```

### Option 2: Service Principal (Alternative)

```bash
# Get service principal ID
AKS_SP_ID=$(az aks show \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --query servicePrincipalProfile.clientId -o tsv)

# Grant ACR pull permissions
az acr show --name $ACR_NAME --query id -o tsv | \
  az role assignment create \
    --assignee $AKS_SP_ID \
    --role AcrPull \
    --scope /subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.ContainerRegistry/registries/{acr-name}
```

## Build and Push Images

### Login to ACR

```bash
az acr login --name $ACR_NAME
```

### Build Images

```bash
# Set variables
PROJECT_DIR="/home/azureuser/packamal"
ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"

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

### Alternative: Docker Build and Push

```bash
# Tag images
docker build -t $ACR_LOGIN_SERVER/packamal-backend:latest $PROJECT_DIR/backend
docker build -t $ACR_LOGIN_SERVER/packamal-frontend:latest $PROJECT_DIR/frontend
docker build -t $ACR_LOGIN_SERVER/packamal-go-worker-analysis:latest \
  -f $PROJECT_DIR/worker/cmd/analyze/Dockerfile $PROJECT_DIR/worker

# Push images
docker push $ACR_LOGIN_SERVER/packamal-backend:latest
docker push $ACR_LOGIN_SERVER/packamal-frontend:latest
docker push $ACR_LOGIN_SERVER/packamal-go-worker-analysis:latest
```

## Image Tagging Strategy

### Recommended Tags

1. **latest**: Current production version
2. **Git commit SHA**: Immutable version (e.g., `abc1234`)
3. **Semantic version**: For releases (e.g., `v1.2.3`)
4. **Branch name**: For development (e.g., `dev`, `staging`)

### Example Workflow

```bash
# Build with multiple tags
COMMIT_SHA=$(git rev-parse --short HEAD)
VERSION="v1.0.0"

az acr build \
  --registry $ACR_NAME \
  --image packamal-backend:latest \
  --image packamal-backend:$COMMIT_SHA \
  --image packamal-backend:$VERSION \
  $PROJECT_DIR/backend
```

## Image Retention Policies

Configure retention to manage storage costs:

```bash
# Set retention policy (keep last 10 versions, delete older than 30 days)
az acr task create \
  --registry $ACR_NAME \
  --name retention-policy \
  --schedule "0 2 * * *" \
  --context /dev/null \
  --file /dev/null \
  --cmd "acr purge --filter 'packamal-.*:.*' --ago 30d --keep 10 --untagged"
```

Or use ACR retention policies (Premium SKU):

```bash
az acr config retention update \
  --registry $ACR_NAME \
  --status Enabled \
  --days 30 \
  --type UntaggedManifests
```

## Content Trust (Image Signing)

Enable content trust for production images:

```bash
# Enable content trust
export DOCKER_CONTENT_TRUST=1
export DOCKER_CONTENT_TRUST_SERVER=https://$ACR_NAME.azurecr.io:443

# Build and push signed image
az acr build --registry $ACR_NAME --image packamal-backend:signed .
```

## Geo-Replication (Premium SKU)

Replicate images to multiple regions for disaster recovery:

```bash
# Add replication
az acr replication create \
  --registry $ACR_NAME \
  --location westus2 \
  --region-endpoint-enabled true
```

## Webhooks

Set up webhooks for CI/CD integration:

```bash
# Create webhook for image push events
az acr webhook create \
  --registry $ACR_NAME \
  --name packamal-webhook \
  --uri https://your-cicd-endpoint.com/webhook \
  --actions push \
  --scope packamal-backend:*
```

## Image Scanning (Premium SKU)

Enable vulnerability scanning:

```bash
# Enable security scanning
az acr config security-scan update \
  --registry $ACR_NAME \
  --enabled true
```

## Update Kubernetes Manifests

Update image references in manifests:

```yaml
# Before (Minikube)
image: packamal-backend:local
imagePullPolicy: IfNotPresent

# After (AKS)
image: packamalacr.azurecr.io/packamal-backend:latest
imagePullPolicy: Always  # Or use specific tag
```

## Image Preloading Strategy

For the large Go worker image (10GB), use a DaemonSet to preload on all nodes:

```yaml
# See 04-kubernetes-manifests/13-image-preloader.yaml
# This ensures the image is cached on nodes before analysis jobs run
```

## Verification

```bash
# List repositories
az acr repository list --name $ACR_NAME --output table

# List tags
az acr repository show-tags --name $ACR_NAME --repository packamal-backend --output table

# Test pull from AKS
kubectl run test-pull \
  --image=$ACR_LOGIN_SERVER/packamal-backend:latest \
  --rm -it --restart=Never \
  --overrides='{"spec":{"imagePullSecrets":[{"name":"acr-secret"}]}}' \
  -- /bin/sh
```

## Cost Estimation

ACR Premium pricing (approximate):
- **Storage**: $0.167/GB/month (first 10GB free)
- **Operations**: $0.05 per 10,000 operations
- **Data Transfer**: Standard Azure egress rates

For 50GB storage and 1M operations/month: ~$8.50/month

## Best Practices

1. **Use specific tags** in production (not `latest`)
2. **Enable retention policies** to manage storage
3. **Use geo-replication** for multi-region deployments
4. **Scan images** for vulnerabilities
5. **Sign images** with content trust
6. **Monitor usage** via Azure Monitor
7. **Use ACR Tasks** for automated builds

## Next Steps

1. Build and push all images to ACR
2. Update Kubernetes manifests with ACR image references
3. Configure CI/CD pipeline (see `05-cicd-pipeline.md`)

