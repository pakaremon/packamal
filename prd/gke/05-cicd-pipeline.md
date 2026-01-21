# CI/CD Pipeline (GKE)

## Recommended Flow
1. Build images (backend, frontend, analysis worker)
2. Push to Artifact Registry
3. Deploy via `kubectl apply -k` or GitOps
4. Run smoke tests against `/health`

## Reasoning
GKE works best with declarative Kubernetes deploys. GitOps or a simple pipeline keeps the cluster state consistent and auditable.
