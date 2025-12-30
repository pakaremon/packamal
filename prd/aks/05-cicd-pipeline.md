# CI/CD Pipeline Documentation

## Overview

This document describes CI/CD pipeline setup for automated building, testing, and deployment of Packamal to AKS.

## Pipeline Architecture

### Components

1. **Source Control**: Git repository (GitHub, Azure DevOps, GitLab)
2. **Build**: Azure Container Registry (ACR) Tasks or GitHub Actions
3. **Test**: Unit tests, integration tests, security scanning
4. **Deploy**: Helm charts or kubectl apply
5. **Monitor**: Deployment status and rollback

## Option 1: GitHub Actions

### Workflow Structure

```yaml
# .github/workflows/ci-cd.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  ACR_NAME: packamalacr
  AKS_NAME: packamal-aks
  RESOURCE_GROUP: packamal-rg
  NAMESPACE: packamal

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2
      
      - name: Login to ACR
        uses: docker/login-action@v2
        with:
          registry: ${{ env.ACR_NAME }}.azurecr.io
          username: ${{ secrets.ACR_USERNAME }}
          password: ${{ secrets.ACR_PASSWORD }}
      
      - name: Build and push backend
        uses: docker/build-push-action@v4
        with:
          context: ./backend
          push: true
          tags: |
            ${{ env.ACR_NAME }}.azurecr.io/packamal-backend:${{ github.sha }}
            ${{ env.ACR_NAME }}.azurecr.io/packamal-backend:latest
          cache-from: type=registry,ref=${{ env.ACR_NAME }}.azurecr.io/packamal-backend:buildcache
          cache-to: type=registry,ref=${{ env.ACR_NAME }}.azurecr.io/packamal-backend:buildcache,mode=max
      
      - name: Build and push frontend
        uses: docker/build-push-action@v4
        with:
          context: ./frontend
          push: true
          tags: |
            ${{ env.ACR_NAME }}.azurecr.io/packamal-frontend:${{ github.sha }}
            ${{ env.ACR_NAME }}.azurecr.io/packamal-frontend:latest
      
      - name: Build and push Go worker
        uses: docker/build-push-action@v4
        with:
          context: ./worker
          file: ./worker/cmd/analyze/Dockerfile
          push: true
          tags: |
            ${{ env.ACR_NAME }}.azurecr.io/packamal-go-worker-analysis:${{ github.sha }}
            ${{ env.ACR_NAME }}.azurecr.io/packamal-go-worker-analysis:latest

  test:
    runs-on: ubuntu-latest
    needs: build-and-push
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          cd backend
          python manage.py test
      
      - name: Security scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.ACR_NAME }}.azurecr.io/packamal-backend:${{ github.sha }}
          format: 'sarif'
          output: 'trivy-results.sarif'
      
      - name: Upload Trivy results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results.sarif'

  deploy:
    needs: [build-and-push, test]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      
      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      
      - name: Get AKS credentials
        run: |
          az aks get-credentials \
            --resource-group ${{ env.RESOURCE_GROUP }} \
            --name ${{ env.AKS_NAME }} \
            --overwrite-existing
      
      - name: Update image tags in manifests
        run: |
          sed -i "s|packamal-backend:.*|packamal-backend:${{ github.sha }}|g" prd/aks/04-kubernetes-manifests/*.yaml
          sed -i "s|packamal-frontend:.*|packamal-frontend:${{ github.sha }}|g" prd/aks/04-kubernetes-manifests/*.yaml
          sed -i "s|packamal-go-worker-analysis:.*|packamal-go-worker-analysis:${{ github.sha }}|g" prd/aks/04-kubernetes-manifests/*.yaml
      
      - name: Deploy to AKS
        run: |
          kubectl apply -f prd/aks/04-kubernetes-manifests/ --namespace ${{ env.NAMESPACE }}
      
      - name: Wait for rollout
        run: |
          kubectl rollout status deployment/backend -n ${{ env.NAMESPACE }}
          kubectl rollout status deployment/frontend -n ${{ env.NAMESPACE }}
      
      - name: Health check
        run: |
          kubectl get pods -n ${{ env.NAMESPACE }}
          kubectl get services -n ${{ env.NAMESPACE }}
```

### GitHub Secrets

Configure these secrets in GitHub repository settings:

- `ACR_USERNAME`: ACR admin username
- `ACR_PASSWORD`: ACR admin password
- `AZURE_CREDENTIALS`: Azure service principal JSON

## Option 2: Azure DevOps Pipelines

### azure-pipelines.yml

```yaml
trigger:
  branches:
    include:
    - main
    - develop

variables:
  acrName: 'packamalacr'
  aksName: 'packamal-aks'
  resourceGroup: 'packamal-rg'
  namespace: 'packamal'

stages:
- stage: Build
  jobs:
  - job: BuildImages
    pool:
      vmImage: 'ubuntu-latest'
    steps:
    - task: Docker@2
      displayName: 'Build and push backend'
      inputs:
        containerRegistry: 'ACR Connection'
        repository: 'packamal-backend'
        command: 'buildAndPush'
        Dockerfile: 'backend/Dockerfile'
        tags: |
          $(Build.BuildId)
          latest
    
    - task: Docker@2
      displayName: 'Build and push frontend'
      inputs:
        containerRegistry: 'ACR Connection'
        repository: 'packamal-frontend'
        command: 'buildAndPush'
        Dockerfile: 'frontend/Dockerfile'
        tags: |
          $(Build.BuildId)
          latest
    
    - task: Docker@2
      displayName: 'Build and push Go worker'
      inputs:
        containerRegistry: 'ACR Connection'
        repository: 'packamal-go-worker-analysis'
        command: 'buildAndPush'
        Dockerfile: 'worker/cmd/analyze/Dockerfile'
        tags: |
          $(Build.BuildId)
          latest

- stage: Test
  dependsOn: Build
  jobs:
  - job: RunTests
    pool:
      vmImage: 'ubuntu-latest'
    steps:
    - task: UsePythonVersion@0
      inputs:
        versionSpec: '3.11'
    
    - script: |
        cd backend
        pip install -r requirements.txt
        python manage.py test
      displayName: 'Run backend tests'
    
    - task: Trivy@0
      inputs:
        imageName: '$(acrName).azurecr.io/packamal-backend:$(Build.BuildId)'
        severity: 'CRITICAL,HIGH'

- stage: Deploy
  dependsOn: Test
  condition: and(succeeded(), eq(variables['Build.SourceBranch'], 'refs/heads/main'))
  jobs:
  - deployment: DeployToAKS
    pool:
      vmImage: 'ubuntu-latest'
    environment: 'production'
    strategy:
      runOnce:
        deploy:
          steps:
          - task: Kubernetes@1
            displayName: 'Deploy to AKS'
            inputs:
              connectionType: 'Azure Resource Manager'
              azureSubscriptionEndpoint: 'Azure Service Connection'
              azureResourceGroup: '$(resourceGroup)'
              kubernetesCluster: '$(aksName)'
              namespace: '$(namespace)'
              command: 'apply'
              arguments: '-f prd/aks/04-kubernetes-manifests/'
          
          - task: Kubernetes@1
            displayName: 'Wait for rollout'
            inputs:
              connectionType: 'Azure Resource Manager'
              azureSubscriptionEndpoint: 'Azure Service Connection'
              azureResourceGroup: '$(resourceGroup)'
              kubernetesCluster: '$(aksName)'
              namespace: '$(namespace)'
              command: 'rollout'
              arguments: 'status deployment/backend'
```

## Option 3: ACR Tasks

### acr-task.yaml

```yaml
version: v1.1.0
steps:
  - build: -t {{.Run.Registry}}/packamal-backend:{{.Run.ID}} -t {{.Run.Registry}}/packamal-backend:latest ./backend
  - build: -t {{.Run.Registry}}/packamal-frontend:{{.Run.ID}} -t {{.Run.Registry}}/packamal-frontend:latest ./frontend
  - build: -f ./worker/cmd/analyze/Dockerfile -t {{.Run.Registry}}/packamal-go-worker-analysis:{{.Run.ID}} -t {{.Run.Registry}}/packamal-go-worker-analysis:latest ./worker
```

### Create ACR Task

```bash
az acr task create \
  --registry $ACR_NAME \
  --name build-packamal \
  --context https://github.com/your-org/packamal.git \
  --file acr-task.yaml \
  --git-access-token $GITHUB_TOKEN \
  --schedule "0 2 * * *"  # Nightly builds
```

## Deployment Strategies

### Blue-Green Deployment

```yaml
# Deploy new version alongside existing
kubectl apply -f backend-blue.yaml  # New version
kubectl apply -f backend-green.yaml  # Old version

# Switch traffic
kubectl patch service backend -p '{"spec":{"selector":{"version":"blue"}}}'

# Verify and delete old version
kubectl delete deployment backend-green
```

### Canary Deployment

```yaml
# Deploy canary (10% traffic)
apiVersion: v1
kind: Service
metadata:
  name: backend
spec:
  selector:
    app: backend
  ports:
  - port: 8000
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-stable
spec:
  replicas: 9
  selector:
    matchLabels:
      app: backend
      version: stable
  template:
    metadata:
      labels:
        app: backend
        version: stable
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-canary
spec:
  replicas: 1
  selector:
    matchLabels:
      app: backend
      version: canary
  template:
    metadata:
      labels:
        app: backend
        version: canary
```

### Rolling Update (Default)

```bash
# Update image
kubectl set image deployment/backend \
  backend=$ACR_LOGIN_SERVER/packamal-backend:new-tag \
  -n packamal

# Monitor rollout
kubectl rollout status deployment/backend -n packamal

# Rollback if needed
kubectl rollout undo deployment/backend -n packamal
```

## Helm Charts (Recommended)

### Chart Structure

```
packamal-chart/
├── Chart.yaml
├── values.yaml
├── values.prod.yaml
├── templates/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── ingress.yaml
└── charts/
```

### Deploy with Helm

```bash
# Install/upgrade
helm upgrade --install packamal ./packamal-chart \
  --namespace packamal \
  --create-namespace \
  --values values.prod.yaml \
  --set image.tag=$BUILD_ID \
  --wait

# Rollback
helm rollback packamal -n packamal
```

## GitOps with Flux or ArgoCD

### Flux Example

```bash
# Install Flux
flux install

# Create GitRepository
flux create source git packamal \
  --url=https://github.com/your-org/packamal \
  --branch=main \
  --interval=1m

# Create Kustomization
flux create kustomization packamal \
  --source=packamal \
  --path="./prd/aks/04-kubernetes-manifests" \
  --prune=true \
  --interval=5m
```

## Best Practices

1. **Use semantic versioning** for image tags
2. **Tag images with commit SHA** for traceability
3. **Run tests before deployment**
4. **Scan images for vulnerabilities**
5. **Use staging environment** before production
6. **Implement rollback procedures**
7. **Monitor deployments** with health checks
8. **Use feature flags** for gradual rollouts
9. **Automate database migrations** carefully
10. **Document deployment procedures**

## Next Steps

1. Choose CI/CD platform (GitHub Actions, Azure DevOps, or ACR Tasks)
2. Set up pipeline configuration
3. Configure secrets and credentials
4. Test pipeline in staging environment
5. Deploy to production

