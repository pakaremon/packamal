# Backup and Disaster Recovery

## PostgreSQL
- Use scheduled snapshots of the PD volume.
- Consider point-in-time recovery by exporting daily dumps to GCS.

## Persistent Disk PVCs
- `app-shared-pvc` and `analysis-results-pvc` are no longer used.
- For analysis results and Django static/media, use GCS buckets and enable Object Versioning + lifecycle rules.

## Reasoning
Cloud-native snapshots provide fast recovery while avoiding in-cluster backup complexity.
