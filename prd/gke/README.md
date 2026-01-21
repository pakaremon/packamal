# Packamal GKE Production Deployment Plan

## Overview
This directory contains the full production deployment documentation and Kubernetes manifests for running Packamal on Google Kubernetes Engine (GKE).

## Quick Start
1. Read `00-overview.md` for architecture and rationale.
2. Follow `01-infrastructure-setup.md` to create the GKE cluster, node pools, and networking.
3. Configure Artifact Registry in `02-container-registry.md`.
4. Create secrets using Secret Manager or `01-secrets.yaml.example`.
5. Apply manifests in `04-kubernetes-manifests/` using `apply-gke.sh`.

## Manual Console Steps (Google Cloud)
These steps must be completed in the Google Cloud Console (or via gcloud) before applying manifests:

- **Enable APIs**
  - Kubernetes Engine API
  - Artifact Registry API
  - Cloud Monitoring API
  - Cloud Logging API
  - Secret Manager API
  - Cloud DNS API (if using Cloud DNS)

- **Create GKE Standard Cluster (NOT Autopilot)**
  - Autopilot does not allow privileged workloads or hostPath mounts required by Go analysis jobs.
  - Enable **Workload Identity**.
  - Enable **Network Policy**.
  - Use **VPC-native** cluster with secondary IP ranges.

- **Create Node Pools**
  - `system-pool`: small nodes for system pods.
  - `app-pool`: general workloads (backend, frontend, celery, postgres, redis).
  - `heavy-analysis`: larger nodes for privileged analysis jobs.
  - Taint `heavy-analysis` nodes: `heavy-analysis=true:NoSchedule`.

- **Create a Google Service Account (GSA)**
  - Used with Workload Identity for least-privilege access.
  - Example: `packamal-gke@PROJECT_ID.iam.gserviceaccount.com`.

- **Create Artifact Registry**
  - Docker repository for application images.
  - Update image references in `01-config.yaml`.

- **(Optional) Create additional PD StorageClasses**
  - Default `standard-rwo` is used for shared data PVCs; use `premium-rwo` for higher performance needs.

- **Configure DNS and TLS**
  - Point domain to the GKE Ingress IP.
  - ManagedCertificate is configured in `14-ingress.yaml`.

## Structure
- `00-overview.md` - Architecture and rationale
- `01-infrastructure-setup.md` - GKE infrastructure details
- `02-container-registry.md` - Artifact Registry setup
- `03-security-rbac.md` - Security controls, Workload Identity, policies
- `04-kubernetes-manifests/` - GKE-optimized Kubernetes manifests
- `05-cicd-pipeline.md` - CI/CD guidance
- `06-monitoring-logging.md` - Observability setup
- `07-backup-disaster-recovery.md` - Backups and DR
- `08-cost-optimization.md` - Cost control strategies
- `09-migration-guide.md` - Migration from local/AKS to GKE

## Why This Design
This GKE plan improves on the AKS reference by:
- Enforcing **Workload Identity** instead of static credentials.
- Using **GKE Sandbox (gVisor)** for stateless pods where safe.
- Separating **heavy analysis jobs** onto a dedicated tainted node pool.
- Using Google Persistent Disk StorageClasses for all PVCs.
- Adding **NetworkPolicies**, **PDBs**, and **resource governance**.
