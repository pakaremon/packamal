# Kế hoạch CI/CD Tự động cho Packamal AKS

## Tổng quan

Tài liệu này mô tả kế hoạch chi tiết để thiết lập hệ thống CI/CD tự động hoàn toàn cho dự án Packamal, tự động build, push và deploy lên Azure Kubernetes Service (AKS) khi có commit vào nhánh `main`.

## Kiến trúc CI/CD Pipeline

```
┌─────────────────┐
│  Git Push to    │
│  main branch    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  GitHub Actions Workflow Trigger    │
│  (.github/workflows/aks-deploy.yml) │
└────────┬────────────────────────────┘
         │
         ├─────────────────┬─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Build        │  │ Build        │  │ Build        │
│ Backend      │  │ Frontend     │  │ Go Worker    │
│ Image        │  │ Image        │  │ Image        │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┴─────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Push to ACR         │
              │  packamalacr.        │
              │  azurecr.io          │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Update Image Tags    │
              │  in K8s Manifests     │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Connect to AKS      │
              │  packamal-aks        │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Deploy Manifests    │
              │  to namespace        │
              │  packamal            │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Verify Deployment   │
              │  & Health Check      │
              └──────────────────────┘
```

## Các thành phần chính

### 1. GitHub Workflow File

**Vị trí**: `.github/workflows/aks-deploy.yml`

**Chức năng**:
- Trigger tự động khi có push vào nhánh `main`
- Hỗ trợ manual trigger (workflow_dispatch)
- Thực hiện 2 jobs chính:
  - `build-and-push`: Build và push images
  - `deploy`: Deploy lên AKS

### 2. Build Images

#### Backend Image
- **Dockerfile**: `./backend/Dockerfile`
- **Image name**: `packamalacr.azurecr.io/packamal-backend`
- **Tags**: 
  - `${{ github.sha }}` (commit SHA)
  - `latest`
- **Sử dụng trong**:
  - `05-backend.yaml` (2 vị trí: initContainer và main container)
  - `06-worker.yaml` (celery-worker deployment)
  - `08-worker-2.yaml` (celery-worker-2 deployment)

#### Frontend Image
- **Dockerfile**: `./frontend/Dockerfile`
- **Image name**: `packamalacr.azurecr.io/packamal-frontend`
- **Tags**: 
  - `${{ github.sha }}` (commit SHA)
  - `latest`
- **Sử dụng trong**:
  - `07-frontend.yaml`

#### Go Worker Image
- **Dockerfile**: `./worker/cmd/analyze/Dockerfile`
- **Image name**: `packamalacr.azurecr.io/packamal-go-worker-analysis`
- **Tags**: 
  - `${{ github.sha }}` (commit SHA)
  - `latest`
- **Sử dụng trong**:
  - `01-config.yaml` (ANALYSIS_IMAGE config)
  - `13-image-preloader.yaml` (image-preloader deployment)

### 3. Push to ACR

**Registry**: `packamalacr.azurecr.io`

**Quy trình**:
1. Login vào ACR sử dụng credentials từ GitHub Secrets
2. Build images với Docker Buildx (hỗ trợ cache)
3. Push images với 2 tags: commit SHA và latest
4. Sử dụng registry cache để tăng tốc build

### 4. Deploy to AKS

**Cluster**: `packamal-aks`  
**Resource Group**: `packamal-rg`  
**Namespace**: `packamal`

**Quy trình**:
1. Login vào Azure sử dụng Service Principal
2. Lấy AKS credentials
3. Cập nhật image tags trong manifests:
   - `05-backend.yaml`: Backend image (2 vị trí)
   - `07-frontend.yaml`: Frontend image
   - `06-worker.yaml`: Backend image (cho celery-worker)
   - `08-worker-2.yaml`: Backend image (cho celery-worker-2)
   - `01-config.yaml`: ANALYSIS_IMAGE config
   - `13-image-preloader.yaml`: Go worker image
4. Đảm bảo namespace tồn tại
5. Apply tất cả manifests
6. Chờ rollout hoàn tất
7. Verify deployment và health check

## Chi tiết các bước thực hiện

### Bước 1: Build và Push Images

```yaml
build-and-push:
  - Checkout code
  - Setup Docker Buildx
  - Login to ACR
  - Build & Push Backend (tag: SHA + latest)
  - Build & Push Frontend (tag: SHA + latest)
  - Build & Push Go Worker (tag: SHA + latest)
```

**Tối ưu hóa**:
- Sử dụng Docker Buildx cache từ registry
- Build song song các images
- Tag với commit SHA để traceability

### Bước 2: Update Image Tags

Workflow sẽ tự động cập nhật image tags trong các file YAML:

```bash
# Backend image updates
sed -i "s|packamalacr.azurecr.io/packamal-backend:.*|packamalacr.azurecr.io/packamal-backend:${COMMIT_SHA}|g" \
  prd/aks/04-kubernetes-manifests/05-backend.yaml

# Frontend image updates
sed -i "s|packamalacr.azurecr.io/packamal-frontend:.*|packamalacr.azurecr.io/packamal-frontend:${COMMIT_SHA}|g" \
  prd/aks/04-kubernetes-manifests/07-frontend.yaml

# Go Worker image updates
sed -i "s|packamalacr.azurecr.io/packamal-go-worker-analysis:.*|packamalacr.azurecr.io/packamal-go-worker-analysis:${COMMIT_SHA}|g" \
  prd/aks/04-kubernetes-manifests/01-config.yaml \
  prd/aks/04-kubernetes-manifests/13-image-preloader.yaml
```

### Bước 3: Deploy to AKS

```yaml
deploy:
  - Azure Login
  - Get AKS credentials
  - Verify kubectl connection
  - Update image tags in manifests
  - Ensure namespace exists
  - Deploy all manifests
  - Wait for rollouts
  - Verify deployments
  - Health check
```

**Rollout Strategy**:
- Rolling update (default Kubernetes behavior)
- Timeout: 5 phút cho mỗi deployment
- Verify từng deployment trước khi tiếp tục

### Bước 4: Verification

Workflow sẽ verify:
- Tất cả deployments đã rollout thành công
- Pods đang ở trạng thái Running
- Services đã được tạo
- Image versions đã được cập nhật đúng

## Các file cần cập nhật

### Kubernetes Manifests được cập nhật tự động:

1. **05-backend.yaml**
   - Line 31: `django-setup` initContainer image
   - Line 73: `backend` container image

2. **07-frontend.yaml**
   - Line 19: `frontend` container image

3. **06-worker.yaml**
   - Line 20: `celery-worker` container image (sử dụng backend image)

4. **08-worker-2.yaml**
   - Line 20: `celery-worker-2` container image (sử dụng backend image)

5. **01-config.yaml**
   - Line 30: `ANALYSIS_IMAGE` config value

6. **13-image-preloader.yaml**
   - Line 25: `image-preloader` container image

## GitHub Secrets cần thiết

Xem chi tiết trong file `02-github-secrets.md`

### Tóm tắt:
- `ACR_USERNAME`: ACR admin username
- `ACR_PASSWORD`: ACR admin password
- `AZURE_CREDENTIALS`: Azure Service Principal JSON

## Workflow Triggers

### Automatic Trigger
- **Khi nào**: Push vào nhánh `main`
- **Jobs chạy**: Tất cả (build-and-push + deploy)

### Manual Trigger
- **Khi nào**: Manual trigger từ GitHub Actions UI
- **Jobs chạy**: Tất cả (build-and-push + deploy)

## Rollback Strategy

Nếu deployment thất bại:

1. **Tự động rollback**: Kubernetes sẽ tự động rollback nếu health check fail
2. **Manual rollback**: 
   ```bash
   kubectl rollout undo deployment/backend -n packamal
   kubectl rollout undo deployment/frontend -n packamal
   kubectl rollout undo deployment/celery-worker -n packamal
   ```
3. **Rollback về image cũ**: Sử dụng image tag từ commit SHA trước đó

## Monitoring và Logging

### GitHub Actions Logs
- Xem logs trong GitHub Actions tab
- Mỗi step có log riêng
- Có thể download logs

### Kubernetes Logs
```bash
# Xem logs của pods
kubectl logs -f deployment/backend -n packamal
kubectl logs -f deployment/frontend -n packamal
kubectl logs -f deployment/celery-worker -n packamal
```

### Deployment Status
```bash
# Xem trạng thái deployment
kubectl get deployments -n packamal
kubectl rollout status deployment/backend -n packamal
```

## Best Practices

1. **Image Tagging**: Luôn tag với commit SHA để có thể trace và rollback
2. **Cache Strategy**: Sử dụng registry cache để tăng tốc build
3. **Health Checks**: Verify deployment trước khi hoàn tất
4. **Namespace Isolation**: Sử dụng namespace riêng cho production
5. **Resource Limits**: Đảm bảo resource limits đã được set trong manifests
6. **Security**: Sử dụng Service Principal thay vì user credentials
7. **Rollout Strategy**: Sử dụng rolling update để zero-downtime

## Troubleshooting

### Build Failures
- Kiểm tra Dockerfile syntax
- Kiểm tra dependencies
- Kiểm tra ACR credentials

### Push Failures
- Kiểm tra ACR credentials
- Kiểm tra network connectivity
- Kiểm tra ACR quota

### Deploy Failures
- Kiểm tra Azure credentials
- Kiểm tra AKS cluster status
- Kiểm tra kubectl connection
- Kiểm tra image pull permissions

### Rollout Failures
- Kiểm tra pod logs
- Kiểm tra resource limits
- Kiểm tra health check endpoints
- Kiểm tra ConfigMaps và Secrets

## Next Steps

1. ✅ Tạo GitHub Workflow file
2. ✅ Cấu hình build và push images
3. ✅ Cấu hình deploy to AKS
4. ⏳ Thêm GitHub Secrets (xem `02-github-secrets.md`)
5. ⏳ Test workflow với test commit
6. ⏳ Monitor first deployment
7. ⏳ Setup notifications (optional)
8. ⏳ Add integration tests (optional)
9. ⏳ Add security scanning (optional)

## Tài liệu tham khảo

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Azure Container Registry](https://docs.microsoft.com/en-us/azure/container-registry/)
- [Azure Kubernetes Service](https://docs.microsoft.com/en-us/azure/aks/)
- [Kubernetes Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

