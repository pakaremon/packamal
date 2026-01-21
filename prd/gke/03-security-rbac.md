# Security and RBAC

## Workload Identity
- Create a Google Service Account (GSA) and bind it to the Kubernetes ServiceAccount (`backend-serviceaccount`).
- Annotate the KSA with the GSA email in `11-rbac.yaml`.

```
GSA=packamal-gke@PROJECT_ID.iam.gserviceaccount.com
KSA=backend-serviceaccount
NAMESPACE=packamal

# Bind GSA to KSA

gcloud iam service-accounts add-iam-policy-binding $GSA   --role roles/iam.workloadIdentityUser   --member "serviceAccount:PROJECT_ID.svc.id.goog[$NAMESPACE/$KSA]"
```

## Pod Security Standards
- Namespace is labeled with `pod-security.kubernetes.io/enforce=privileged` to allow analysis jobs.
- Individual pods still use restrictive `securityContext` to follow least privilege.

## Network Policies
- Default deny ingress.
- Explicit allow rules for backend, database, redis, and frontend.
- Protects stateful services from unintended access.

## Secrets Management
- Use Secret Manager + CSI driver for production secrets.
- `01-secrets.yaml.example` is a template only.

## Reasoning
- Workload Identity removes the need for static credentials.
- Default deny policies reduce blast radius.
- Pod-level security contexts provide defense-in-depth even in privileged namespaces.
