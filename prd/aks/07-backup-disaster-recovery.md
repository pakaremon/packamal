# Backup and Disaster Recovery

## Overview

This document describes backup and disaster recovery strategies for Packamal on AKS, including database backups, persistent volume backups, and disaster recovery procedures.

## Database Backups

### PostgreSQL Backup Strategy

#### Automated Backups with CronJob

```yaml
# postgres-backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-backup
  namespace: packamal
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  successfulJobsHistoryLimit: 7
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: postgres-backup
            image: postgres:15-alpine
            env:
            - name: PGHOST
              value: database
            - name: PGPORT
              value: "5432"
            - name: PGDATABASE
              valueFrom:
                configMapKeyRef:
                  name: packamal-config
                  key: POSTGRES_DB
            - name: PGUSER
              valueFrom:
                configMapKeyRef:
                  name: packamal-config
                  key: POSTGRES_USER
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef:
                  name: packamal-secrets
                  key: POSTGRES_PASSWORD
            - name: AZURE_STORAGE_ACCOUNT
              value: "packamalbackups"
            - name: AZURE_STORAGE_KEY
              valueFrom:
                secretKeyRef:
                  name: backup-secrets
                  key: storage-key
            command:
            - /bin/sh
            - -c
            - |
              set -e
              BACKUP_FILE="/tmp/backup-$(date +%Y%m%d-%H%M%S).sql.gz"
              pg_dump -h $PGHOST -U $PGUSER -d $PGDATABASE | gzip > $BACKUP_FILE
              
              # Upload to Azure Blob Storage
              az storage blob upload \
                --account-name $AZURE_STORAGE_ACCOUNT \
                --account-key $AZURE_STORAGE_KEY \
                --container-name postgres-backups \
                --name $(basename $BACKUP_FILE) \
                --file $BACKUP_FILE
              
              echo "Backup completed: $BACKUP_FILE"
            volumeMounts:
            - name: backup-tmp
              mountPath: /tmp
          volumes:
          - name: backup-tmp
            emptyDir: {}
          restartPolicy: OnFailure
```

#### Azure Database for PostgreSQL (Managed Service)

For production, consider migrating to Azure Database for PostgreSQL:

```bash
# Create Azure Database for PostgreSQL
az postgres flexible-server create \
  --resource-group $RESOURCE_GROUP \
  --name packamal-postgres \
  --location $LOCATION \
  --admin-user packamal_db \
  --admin-password $PG_PASSWORD \
  --sku-name Standard_D2s_v3 \
  --tier GeneralPurpose \
  --storage-size 128 \
  --version 15 \
  --backup-retention 30 \
  --geo-redundant-backup Enabled
```

Managed service provides:
- Automated daily backups
- Point-in-time restore (up to 35 days)
- Geo-redundant backups
- High availability options

### Redis Backup

```yaml
# redis-backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: redis-backup
  namespace: packamal
spec:
  schedule: "0 3 * * *"  # Daily at 3 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: redis-backup
            image: redis:7-alpine
            command:
            - /bin/sh
            - -c
            - |
              redis-cli -h redis SAVE
              cp /data/dump.rdb /backup/dump-$(date +%Y%m%d).rdb
              az storage blob upload \
                --account-name $AZURE_STORAGE_ACCOUNT \
                --account-key $AZURE_STORAGE_KEY \
                --container-name redis-backups \
                --name dump-$(date +%Y%m%d).rdb \
                --file /backup/dump-$(date +%Y%m%d).rdb
            volumeMounts:
            - name: redis-data
              mountPath: /data
              readOnly: true
            - name: backup
              mountPath: /backup
          volumes:
          - name: redis-data
            persistentVolumeClaim:
              claimName: redis-pvc
          - name: backup
            emptyDir: {}
          restartPolicy: OnFailure
```

## Persistent Volume Backups

### Azure Disk Snapshots

```bash
# Get PVC details
PVC_NAME="postgres-pvc"
NAMESPACE="packamal"

# Get disk name
DISK_NAME=$(kubectl get pvc $PVC_NAME -n $NAMESPACE -o jsonpath='{.spec.volumeName}')

# Get disk resource ID
DISK_ID=$(az disk show --name $DISK_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)

# Create snapshot
az snapshot create \
  --resource-group $RESOURCE_GROUP \
  --name "${PVC_NAME}-snapshot-$(date +%Y%m%d)" \
  --source $DISK_ID \
  --tags BackupType=Daily Environment=Production
```

### Automated Snapshot Script

```bash
#!/bin/bash
# backup-pvc.sh

RESOURCE_GROUP="packamal-rg"
NAMESPACE="packamal"
PVC_LIST=("postgres-pvc" "redis-pvc" "app-shared-pvc" "analysis-results-pvc")

for PVC_NAME in "${PVC_LIST[@]}"; do
  echo "Backing up $PVC_NAME..."
  
  # Get disk name
  DISK_NAME=$(kubectl get pvc $PVC_NAME -n $NAMESPACE -o jsonpath='{.spec.volumeName}' 2>/dev/null)
  
  if [ -z "$DISK_NAME" ]; then
    echo "Warning: PVC $PVC_NAME not found, skipping..."
    continue
  fi
  
  # Get disk resource ID
  DISK_ID=$(az disk show --name $DISK_NAME --resource-group $RESOURCE_GROUP --query id -o tsv 2>/dev/null)
  
  if [ -z "$DISK_ID" ]; then
    echo "Warning: Disk $DISK_NAME not found, skipping..."
    continue
  fi
  
  # Create snapshot
  SNAPSHOT_NAME="${PVC_NAME}-snapshot-$(date +%Y%m%d-%H%M%S)"
  az snapshot create \
    --resource-group $RESOURCE_GROUP \
    --name $SNAPSHOT_NAME \
    --source $DISK_ID \
    --tags BackupType=Automated PVC=$PVC_NAME Date=$(date +%Y-%m-%d)
  
  echo "Snapshot created: $SNAPSHOT_NAME"
done
```

### Velero (Kubernetes Backup Tool)

Install Velero for comprehensive Kubernetes backup:

```bash
# Install Velero CLI
wget https://github.com/vmware-tanzu/velero/releases/download/v1.11.0/velero-v1.11.0-linux-amd64.tar.gz
tar -xzf velero-v1.11.0-linux-amd64.tar.gz
sudo mv velero-v1.11.0-linux-amd64/velero /usr/local/bin/

# Create Azure storage account for Velero
az storage account create \
  --name packamalvelero \
  --resource-group $RESOURCE_GROUP \
  --sku Standard_LRS

# Install Velero
velero install \
  --provider azure \
  --plugins velero/velero-plugin-for-microsoft-azure:v1.6.0 \
  --bucket velero \
  --secret-file ./credentials-velero \
  --backup-location-config resourceGroup=$RESOURCE_GROUP,storageAccount=packamalvelero \
  --snapshot-location-config apiTimeout=5m,resourceGroup=$RESOURCE_GROUP

# Create backup schedule
velero schedule create packamal-daily \
  --schedule="0 2 * * *" \
  --include-namespaces packamal \
  --ttl 30d
```

## Disaster Recovery Plan

### RTO and RPO Targets

- **RTO (Recovery Time Objective)**: 4 hours
- **RPO (Recovery Point Objective)**: 1 hour (for database)

### Recovery Procedures

#### 1. Full Cluster Failure

```bash
# 1. Create new AKS cluster
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name packamal-aks-dr \
  --location $DR_LOCATION \
  --node-count 3 \
  --node-vm-size Standard_D4s_v3

# 2. Restore from Velero backup
velero restore create packamal-restore \
  --from-backup packamal-daily-$(date +%Y%m%d) \
  --include-namespaces packamal

# 3. Restore persistent volumes from snapshots
# (See restore procedures below)
```

#### 2. Database Recovery

```bash
# Restore from backup
BACKUP_FILE="backup-20240101-020000.sql.gz"

# Download from Azure Blob Storage
az storage blob download \
  --account-name packamalbackups \
  --container-name postgres-backups \
  --name $BACKUP_FILE \
  --file /tmp/$BACKUP_FILE

# Restore to database
gunzip -c /tmp/$BACKUP_FILE | psql -h database -U packamal_db -d packamal
```

#### 3. Persistent Volume Recovery

```bash
# List snapshots
az snapshot list --resource-group $RESOURCE_GROUP --query "[].{Name:name,Date:timeCreated}" -o table

# Create disk from snapshot
SNAPSHOT_NAME="postgres-pvc-snapshot-20240101"
NEW_DISK_NAME="postgres-pvc-restored"

az disk create \
  --resource-group $RESOURCE_GROUP \
  --name $NEW_DISK_NAME \
  --source $SNAPSHOT_NAME \
  --sku Premium_LRS

# Update PVC to use new disk (requires manual intervention)
```

### Multi-Region Setup

#### Primary Region (East US)
- AKS cluster
- Application deployments
- Active database

#### Secondary Region (West US 2)
- Standby AKS cluster (or use AKS multi-cluster)
- Database replication
- Blob storage replication

#### Setup Geo-Replication

```bash
# Enable geo-replication for storage account
az storage account update \
  --name packamalbackups \
  --resource-group $RESOURCE_GROUP \
  --enable-geo-replication true
```

## Backup Retention Policy

### Retention Schedule

- **Daily backups**: Keep for 7 days
- **Weekly backups**: Keep for 4 weeks
- **Monthly backups**: Keep for 12 months
- **Yearly backups**: Keep indefinitely

### Cleanup Script

```bash
#!/bin/bash
# cleanup-old-backups.sh

# Delete snapshots older than retention period
az snapshot list --resource-group $RESOURCE_GROUP --query "[?timeCreated<='$(date -d '30 days ago' -u +%Y-%m-%dT%H:%M:%SZ)'].name" -o tsv | \
  xargs -I {} az snapshot delete --resource-group $RESOURCE_GROUP --name {}

# Delete blob backups older than retention
az storage blob list \
  --account-name packamalbackups \
  --container-name postgres-backups \
  --query "[?properties.lastModified<='$(date -d '30 days ago' -u +%Y-%m-%dT%H:%M:%SZ)'].name" -o tsv | \
  xargs -I {} az storage blob delete \
    --account-name packamalbackups \
    --container-name postgres-backups \
    --name {}
```

## Testing Backups

### Backup Verification

```bash
# Test database backup restore
# 1. Create test database
createdb -h database -U packamal_db packamal_test

# 2. Restore backup
gunzip -c backup.sql.gz | psql -h database -U packamal_db -d packamal_test

# 3. Verify data
psql -h database -U packamal_db -d packamal_test -c "SELECT COUNT(*) FROM your_table;"

# 4. Cleanup
dropdb -h database -U packamal_db packamal_test
```

### Disaster Recovery Drill

Schedule quarterly DR drills:

1. Simulate cluster failure
2. Restore from backups
3. Verify application functionality
4. Document issues and improvements
5. Update DR procedures

## Cost Optimization

- Use Azure Blob Storage (Cool tier) for old backups
- Enable lifecycle management for automatic tier transitions
- Delete old backups according to retention policy
- Use Velero for efficient incremental backups

## Best Practices

1. **Automate backups**: Use CronJobs or Velero schedules
2. **Test restores**: Regularly test backup restoration
3. **Monitor backups**: Alert on backup failures
4. **Document procedures**: Maintain runbooks
5. **Geo-replication**: Use for critical data
6. **Encryption**: Encrypt backups at rest
7. **Access control**: Limit backup access
8. **Versioning**: Keep multiple backup versions

## Next Steps

1. Set up automated database backups
2. Configure Velero for Kubernetes backups
3. Create DR runbooks
4. Schedule DR drills
5. Monitor backup health

