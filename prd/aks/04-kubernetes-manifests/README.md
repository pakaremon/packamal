# AKS-Optimized Kubernetes Manifests

## Overview

This directory contains Kubernetes manifests optimized for Azure Kubernetes Service (AKS). These manifests are adapted from the Minikube versions with the following changes:

1. **Image References**: Updated to use Azure Container Registry (ACR)
2. **Storage Classes**: Using Azure managed premium disks
3. **Service Types**: LoadBalancer for external services
4. **Security**: Enhanced security contexts and pod security
5. **Networking**: Optimized for Azure networking
6. **Resource Limits**: Adjusted for AKS node sizes

## Deployment Order

Apply manifests in this order:

```bash
# 1. Namespace and RBAC
kubectl apply -f 00-namespace.yaml
kubectl apply -f 11-rbac.yaml

# 2. Config and Secrets (update with your values)
kubectl apply -f 01-config.yaml
kubectl apply -f 01-secrets.yaml  # Create from Key Vault or manually

# 3. Storage
kubectl apply -f 02-pvc.yaml

# 4. Databases
kubectl apply -f 03-postgres.yaml
kubectl apply -f 04-redis.yaml

# 5. Image preloader (for large analysis image)
kubectl apply -f 13-image-preloader.yaml

# 6. Application components
kubectl apply -f 05-backend.yaml
kubectl apply -f 06-worker.yaml
kubectl apply -f 08-worker-2.yaml
kubectl apply -f 09-celery-beat.yaml
kubectl apply -f 10-flower.yaml
kubectl apply -f 07-frontend.yaml

# 7. Autoscaling
kubectl apply -f 12-backend-hpa.yaml

# 8. Ingress
kubectl apply -f 14-ingress.yaml
```

## Configuration

Before deploying, update:

1. **ACR Name**: Replace `packamalacr.azurecr.io` with your ACR login server
2. **Image Tags**: Update to use specific tags (not `latest` for production)
3. **Secrets**: Create `01-secrets.yaml` from Azure Key Vault or manually
4. **Domain**: Update ingress hostname in `14-ingress.yaml`
5. **Resource Limits**: Adjust based on your node sizes

## Differences from Minikube

| Component | Minikube | AKS |
|-----------|----------|-----|
| Images | `packamal-*:local` | `acr.azurecr.io/packamal-*:tag` |
| Storage | Local volumes | Azure managed disks |
| Services | NodePort | LoadBalancer/Ingress |
| Image Pull | `IfNotPresent` | `Always` (or specific tag) |
| HostPath | Used for containers | Azure Disk preferred |

## Notes

- The image preloader (13-image-preloader.yaml) is optional but recommended for the 10GB analysis image
- Analysis jobs require privileged mode for Podman - this is configured in the RBAC
- All persistent volumes use `managed-premium` storage class
- Network policies are configured separately (see 03-security-rbac.md)

