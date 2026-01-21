# GKE Manifests

## Apply
```
./apply-gke.sh
```

## Notes
- Update image references in `01-config.yaml`.
- Create secrets from Secret Manager or `01-secrets.yaml.example`.
- Update managed certificate domain in `14-ingress.yaml`.
- Configure GCS env vars in `base/01-config.yaml` (`GCS_BUCKET_NAME`, `RESULTS_BUCKET_URL`, `ANALYSIS_DYNAMIC_BUCKET_URL`).

## Architectural Rationale
- **Workload Identity** (`11-rbac.yaml`): avoids static credentials in pods.
- **GKE Sandbox** (`sandbox.gke.io/runtime: gvisor`): reduces kernel exposure for stateless pods.
- **Dedicated heavy-analysis pool** (`ANALYSIS_NODE_SELECTOR`, taints): isolates privileged jobs.
- **Persistent Disks** (`standard-rwo`/`premium-rwo` StorageClasses): used for stateful services (e.g. Postgres/Redis); app static/results are stored in GCS.
- **NetworkPolicies** (`15-network-policies.yaml`): restricts east-west traffic to only required flows.
- **PDBs and quotas** (`16-pdb.yaml`, `11-resource-quota.yaml`): improves availability and prevents noisy neighbors.
