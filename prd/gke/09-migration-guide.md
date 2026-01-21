# Migration Guide

## Steps
1. Create GKE cluster and node pools.
2. Push images to Artifact Registry.
3. Update `01-config.yaml` and create Kubernetes secrets.
4. Apply manifests: `apply-gke.sh`.
5. Validate backend health and analysis job execution.

## Reasoning
This phased approach reduces risk by validating infrastructure and images before production traffic is shifted.
