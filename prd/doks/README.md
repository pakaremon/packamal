# DigitalOcean Kubernetes Service (DOKS) Deployment

## Overview

This directory contains Kubernetes manifests optimized for DigitalOcean Kubernetes Service (DOKS). The deployment has been migrated from Azure AKS with the following key changes:

1. **Stateless Design**: Removed all ReadWriteMany PVCs (not supported on DOKS)
2. **Object Storage**: Migrated to DigitalOcean Spaces (S3-compatible) for analysis results
3. **Storage Classes**: Using `do-block-storage` for ReadWriteOnce volumes (Postgres, Redis)
4. **Container Registry**: Updated to use DigitalOcean Container Registry

## Key Differences from AKS

| Component | AKS | DOKS |
|-----------|-----|------|
| Storage Class | `managed-csi`, `azurefile-csi` | `do-block-storage` |
| Shared Storage | Azure Files (ReadWriteMany) | DO Spaces (S3) |
| Container Registry | Azure Container Registry (ACR) | DO Container Registry |
| PVC Support | ReadWriteMany + ReadWriteOnce | ReadWriteOnce only |
| Static Files | PVC mount | Ephemeral storage or CDN |

## Architecture

### Storage Strategy

- **Postgres**: Persistent volume (ReadWriteOnce) - `postgres-pvc`
- **Redis Celery**: Persistent volume (ReadWriteOnce) - `redis-celery-pvc`
- **Analysis Results**: DigitalOcean Spaces (S3-compatible) - `packamal-results` bucket
- **Static Files**: Ephemeral storage in backend pods (or serve via CDN)

### Stateless Components

All application components are now stateless:
- Backend (Django)
- Celery Workers
- Celery Beat
- Frontend (Nginx)

## Prerequisites

1. **DigitalOcean Account** with:
   - DOKS cluster created
   - DO Spaces bucket created (`packamal-results`)
   - DO Container Registry configured
   - Spaces access keys generated

2. **kubectl** configured to connect to your DOKS cluster

3. **Required Tools**:
   - `kubectl`
   - `doctl` (DigitalOcean CLI) - optional but recommended

## Setup Instructions

For a detailed, phased setup (build/push images, Spaces, secrets, security hardening, automation scripts), see:
- `setup.md`

### 1. Create DO Spaces Bucket

```bash
# Using doctl
doctl spaces create packamal-results --region nyc3

# Or via DigitalOcean Dashboard:
# Networking > Spaces > Create Spaces Bucket
# Name: packamal-results
# Region: nyc3 (or your preferred region)
```

### 2. Generate Spaces Access Keys

```bash
# Via DigitalOcean Dashboard:
# API > Tokens/Keys > Spaces Keys > Generate New Key
# Save the Access Key and Secret Key
```

### 3. Create Kubernetes Secrets

```bash
# Create packamal-secrets
kubectl create secret generic packamal-secrets \
  --from-literal=POSTGRES_PASSWORD='your-secure-password' \
  --from-literal=SECRET_KEY='your-django-secret-key' \
  --from-literal=INTERNAL_API_TOKEN='your-internal-api-token' \
  --from-literal=AUTH_TOKEN='your-auth-token' \
  --namespace packamal

# Create storage-secrets (DO Spaces credentials)
kubectl create secret generic storage-secrets \
  --from-literal=STORAGE_ACCESS_KEY='your-spaces-access-key' \
  --from-literal=STORAGE_SECRET_KEY='your-spaces-secret-key' \
  --namespace packamal
```

### 4. Update Configuration

Edit `01-config.yaml` and update:
- `STORAGE_ENDPOINT`: Your DO Spaces endpoint (e.g., `https://nyc3.digitaloceanspaces.com`)
- `STORAGE_BUCKET`: Your bucket name (e.g., `packamal-results`)
- `STORAGE_REGION`: Your region (e.g., `nyc3`)
- `ANALYSIS_IMAGE`: Your DO Container Registry image path


### Important 
doctl kubernetes cluster registry autoconnect packamal-registry
### 5. Deploy Manifests

Apply manifests in order:

```bash  
# 1. Namespace and RBAC
kubectl apply -f 00-namespace.yaml
kubectl apply -f 11-rbac.yaml
kubectl apply -f 12-priority-class.yaml

# 2. Config and Secrets
kubectl apply -f 01-config.yaml
# Note: Create secrets manually (see step 3)

# 3. Storage (Postgres, Redis only - no shared PVCs)
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

## Environment Variables

### Storage Configuration

The following environment variables are used for DO Spaces:

- `STORAGE_ENDPOINT`: DO Spaces endpoint URL
- `STORAGE_BUCKET`: Bucket name for analysis results
- `STORAGE_REGION`: DO Spaces region
- `STORAGE_ACCESS_KEY`: Spaces access key (from Secret)
- `STORAGE_SECRET_KEY`: Spaces secret key (from Secret)

### Backward Compatibility

The code also supports `SPACES_*` environment variables for backward compatibility:
- `SPACES_ENDPOINT` → `STORAGE_ENDPOINT`
- `SPACES_BUCKET_NAME` → `STORAGE_BUCKET`
- `SPACES_REGION` → `STORAGE_REGION`
- `SPACES_ACCESS_KEY` → `STORAGE_ACCESS_KEY`
- `SPACES_SECRET_KEY` → `STORAGE_SECRET_KEY`

## Storage Flow

### Analysis Results

1. **Go Worker** uploads results directly to DO Spaces:
   - Key format: `reports/{year}/{month}/{task_id}.json` (computed by backend, injected to worker via `REPORT_PATH`)
   - Uses S3-compatible API via `gocloud.dev/blob/s3blob`

2. **Backend** reads results from DO Spaces:
   - Stores only the object key in DB (`AnalysisTask.report_url`)
   - Verifies object exists before marking task completed
   - Generates presigned URLs for user downloads

### Static Files

**Default Solution (Proxy to Backend):**
- Backend collects static files during init container to `/tmp/static` (ephemeral storage)
- Frontend nginx proxies `/static/` and `/media/` requests to backend service
- Backend serves static files via Django's static file serving
- **Note**: Static files are lost when backend pod restarts (ephemeral storage)

**Production Solution (DO Spaces CDN) - ✅ IMPLEMENTED:**
- ✅ Backend automatically uploads static files to DO Spaces after `collectstatic` (if `STATIC_FILES_BUCKET` is set)
- ✅ Frontend nginx automatically serves from CDN if `STATIC_CDN_URL` is configured
- ✅ Django automatically uses CDN URL in templates if `STATIC_CDN_URL` is set
- **Benefits**: Better performance, global CDN caching, files persist across pod restarts
- **To enable**: Set `STATIC_FILES_BUCKET` and `STATIC_CDN_URL` in ConfigMap (see `setup.md` for details)

## Troubleshooting

### Storage Issues

**Problem**: Analysis results not found
- Check Spaces bucket exists and is accessible
- Verify `storage-secrets` contains correct credentials
- Check Go worker logs for S3 upload errors

**Problem**: Backend cannot read from Spaces
- Verify `STORAGE_*` environment variables are set
- Check `storage-secrets` is mounted correctly
- Review backend logs for boto3 connection errors

### PVC Issues

**Problem**: Postgres/Redis PVC not created
- Verify `do-block-storage` storage class exists in cluster
- Check node pool has sufficient storage capacity
- Review PVC status: `kubectl get pvc -n packamal`

## Cost Optimization

### DOKS Recommendations

1. **Node Pools**: Use appropriate node sizes for your workload
2. **Spaces**: Enable CDN for static files to reduce egress costs
3. **Autoscaling**: Configure HPA to scale down during low traffic
4. **Image Caching**: Image preloader reduces image pull costs

### Storage Costs

- **DO Spaces**: Pay for storage + egress (CDN reduces egress)
- **Block Storage**: Pay per GB provisioned (Postgres, Redis)
- **No Shared PVCs**: Eliminates ReadWriteMany storage costs

## Migration Notes

### Removed Components

- `app-shared-pvc`: Static files now use ephemeral storage
- `analysis-results-pvc`: Results stored in DO Spaces
- Azure-specific storage classes (`azurefile-csi`, `managed-csi`)
- ACR image references (replaced with DO Container Registry)

### Code Changes

- `k8s_service.py`: Removed PVC mounts from analysis jobs
- `result_storage_service.py`: Updated to read from DO Spaces
- Backend deployments: Removed PVC volume mounts

## Security

1. **Secrets Management**: Use DigitalOcean Secrets Manager for production
2. **Spaces Access**: Use least-privilege access keys
3. **Network Policies**: Consider implementing network policies
4. **TLS**: Configure TLS certificates for ingress

## Monitoring

Monitor the following:
- DO Spaces bucket usage and costs
- Block storage usage (Postgres, Redis)
- Pod resource usage
- Analysis job completion rates
- S3 upload/download success rates

## Support

For issues or questions:
1. Check logs: `kubectl logs -n packamal <pod-name>`
2. Verify secrets: `kubectl get secrets -n packamal`
3. Check Spaces bucket: `doctl spaces list` or DO Dashboard
4. Review this documentation and migration notes

#DEBUG

Cách sử dụng khi debug:
Uncomment lines 273-274 trong k8s_service.py để chạy bash shell:
   command=["/bin/bash"],   args=["-c", "sleep 3600"],
Vào pod và chạy lệnh analyze thủ công. Có hai cách:
Cách 1: Dùng env var (không cần -dynamic-bucket):

```sh
podman run --rm -it \
  --pull=never \
  --entrypoint /bin/sh \
  docker.io/pakaremon/dynamic-analysis:latest
/app # 
```

```sh
   export INTERNAL_API_BASE_URL="love"
   analyze -ecosystem npm -package graphql -version 16.8.1 -sandbox-image docker.io/pakaremon/dynamic-analysis -mode dynamic -nopull
```
Cách 2: Dùng flag với giá trị từ env var:
   analyze -dynamic-bucket "$DYNAMIC_BUCKET" -ecosystem npm -package graphql -version 16.8.1 -sandbox-image docker.io/pakaremon/dynamic-analysis -mode dynamic -nopull
Giá trị DYNAMIC_BUCKET được tự động set từ self._build_s3_bucket_url(), giống như giá trị truyền vào flag -dynamic-bucket.