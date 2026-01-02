# AKS Setup and Deployment Guide

This document provides step-by-step instructions for setting up and deploying the Packamal application on Azure Kubernetes Service (AKS).

## Connect to AKS Cluster

```bash
az aks get-credentials --resource-group packamal-rg --name packamal-aks
```

Expected output:
```
Merged "packamal-aks" as current context in /root/.kube/config
```

### Verify Cluster Connection

```bash
kubectl get nodes
```

Example output:
```
NAME                                STATUS   ROLES    AGE   VERSION
aks-agentpool-38156302-vmss000000   Ready    <none>   18h   v1.33.5
```

```bash
kubectl get services
```

Example output:
```
NAME         TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
kubernetes   ClusterIP   10.0.0.1     <none>        443/TCP   18h
```

## Create Azure Container Registry (ACR)

### Register Required Providers

Register the required Azure resource providers:

```bash
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.ContainerService
az provider register --namespace Microsoft.Compute
az provider register --namespace Microsoft.Network
```

Note: Registration may take a few minutes. You can monitor the status using:
```bash
az provider show -n Microsoft.ContainerRegistry
```

### Create ACR

```bash
az acr create --resource-group packamal-rg --name packamalacr --sku Basic
```

Example output (truncated):
```json
{
  "loginServer": "packamalacr.azurecr.io",
  "name": "packamalacr",
  "provisioningState": "Succeeded",
  "resourceGroup": "packamal-rg",
  "sku": {
    "name": "Basic",
    "tier": "Basic"
  }
}
```

### Log in to ACR

```bash
az acr login --name packamalacr
```

Expected output:
```
Login Succeeded
```

### Verify ACR

```bash
az acr list \
  --resource-group packamal-rg \
  --query "[].{acrLoginServer:loginServer}" \
  --output table
```

The registry for our setup is `packamalacr.azurecr.io`.

## Build and Push Images

```bash
# Build images
docker build -t packamal-backend:local /home/packamal/backend
docker build -t packamal-frontend:local /home/packamal/frontend
docker build -t packamal-go-worker-analysis:local -f /home/packamal/worker/cmd/analyze/Dockerfile /home/packamal/worker

# Tag images for ACR
docker tag packamal-backend:local packamalacr.azurecr.io/packamal-backend:latest
docker tag packamal-frontend:local packamalacr.azurecr.io/packamal-frontend:latest
docker tag packamal-go-worker-analysis:local packamalacr.azurecr.io/packamal-go-worker-analysis:latest

# Push images to ACR
docker push packamalacr.azurecr.io/packamal-backend:latest
docker push packamalacr.azurecr.io/packamal-frontend:latest
docker push packamalacr.azurecr.io/packamal-go-worker-analysis:latest
```

## Integrate ACR with AKS

```bash
az aks update -n packamal-aks -g packamal-rg --attach-acr packamalacr
```

**Command arguments explained:**
- `-n packamal-aks`: (Short for `--name`) Specifies the name of the AKS cluster.
- `-g packamal-rg`: (Short for `--resource-group`) Specifies the resource group where the cluster is located.
- `--attach-acr packamalacr`: Establishes a connection between the AKS cluster and the Container Registry named `packamalacr`.

This command grants the AKS cluster permissions to pull images from the ACR without requiring explicit authentication.

## Deploy Application Resources

### Create packamal namespace and deploy resources

```bash
bash prd/aks/apply-aks.sh
```

Or if you're already in the prd/aks directory:

```bash
./apply-aks.sh
```

## Access Services

### Get Frontend Service External IP

```bash
kubectl get svc -n packamal frontend
```

### Create Superuser

```bash
kubectl exec -it -n packamal deployment/backend -- python manage.py createsuperuser
```

## Test API Endpoint

Get the external IP from the frontend service and test the API:

```bash
# Example: Replace with your actual external IP
curl -X POST "http://<EXTERNAL_IP>/api/v1/analyze/" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"purl": "pkg:npm/react@18.2.0"}'
```

**Example:**
```bash
curl -X POST "http://20.187.145.56/api/v1/analyze/" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"purl": "pkg:npm/react@18.2.0"}'
```

### Batch Test Script

Example script to test multiple packages:

```bash
#!/bin/bash

# Replace with your actual external IP and token
API_URL="http://<EXTERNAL_IP>/api/v1/analyze/"
TOKEN="<YOUR_TOKEN>"

PACKAGES=(
  "pkg:npm/lodash@4.17.21"
  "pkg:npm/express@4.18.2"
  "pkg:npm/react@18.2.0"
  "pkg:npm/axios@1.6.2"
  "pkg:npm/moment@2.29.4"
)

for PURL in "${PACKAGES[@]}"; do
  echo "Analyzing $PURL"

  curl -s -X POST "$API_URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"purl\": \"$PURL\"}"

  echo -e "\n-----------------------------------"
done
```

**Note:** Replace `<EXTERNAL_IP>` and `<YOUR_TOKEN>` with your actual values before running the script.
