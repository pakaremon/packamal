# CI/CD Documentation cho Packamal AKS

Thư mục này chứa tài liệu và cấu hình cho hệ thống CI/CD tự động của dự án Packamal.

## Cấu trúc thư mục

```
prd/cicd/
├── README.md              # Tài liệu tổng quan (file này)
├── 01-plan.md            # Kế hoạch chi tiết CI/CD pipeline
└── 02-github-secrets.md  # Hướng dẫn cấu hình GitHub Secrets

.github/workflows/
└── aks-deploy.yml        # GitHub Actions workflow file
```

## Tài liệu

### 1. [Kế hoạch CI/CD (01-plan.md)](01-plan.md)
- Kiến trúc pipeline
- Chi tiết các bước build, push và deploy
- Các file manifests được cập nhật
- Best practices và troubleshooting

### 2. [Hướng dẫn GitHub Secrets (02-github-secrets.md)](02-github-secrets.md)
- Các secrets cần thiết
- Cách lấy và cấu hình từng secret
- Security best practices
- Troubleshooting

## Workflow File

**Vị trí**: `.github/workflows/aks-deploy.yml`

**Chức năng**:
- Tự động trigger khi có push vào nhánh `main`
- Build 3 images: Backend, Frontend, Go Worker
- Push images lên ACR với tags: commit SHA và latest
- Cập nhật image tags trong Kubernetes manifests
- Deploy lên AKS cluster `packamal-aks`

## Quick Start

### 1. Cấu hình GitHub Secrets

Xem chi tiết trong [02-github-secrets.md](02-github-secrets.md)

**Tóm tắt**:
1. Lấy ACR credentials:
   ```bash
   az acr credential show --name packamalacr
   ```
2. Tạo Service Principal:
   ```bash
   az ad sp create-for-rbac \
     --name "packamal-github-actions" \
     --role contributor \
     --scopes /subscriptions/SUBSCRIPTION_ID/resourceGroups/packamal-rg \
     --sdk-auth
   ```
3. Thêm 3 secrets vào GitHub:
   - `ACR_USERNAME`
   - `ACR_PASSWORD`
   - `AZURE_CREDENTIALS`

### 2. Test Workflow

1. Push code vào nhánh `main` để trigger workflow tự động
2. Hoặc manual trigger từ GitHub Actions tab
3. Xem logs trong GitHub Actions để theo dõi progress

### 3. Verify Deployment

```bash
# Kết nối tới AKS
az aks get-credentials --resource-group packamal-rg --name packamal-aks

# Kiểm tra deployments
kubectl get deployments -n packamal

# Kiểm tra pods
kubectl get pods -n packamal

# Kiểm tra image versions
kubectl get deployments -n packamal -o jsonpath='{range .items[*]}{.metadata.name}{":\t"}{.spec.template.spec.containers[*].image}{"\n"}{end}'
```

## Workflow Jobs

### Job 1: build-and-push
- Build Backend image từ `./backend/Dockerfile`
- Build Frontend image từ `./frontend/Dockerfile`
- Build Go Worker image từ `./worker/cmd/analyze/Dockerfile`
- Push tất cả images lên `packamalacr.azurecr.io`
- Tag với commit SHA và `latest`

### Job 2: deploy
- Login vào Azure
- Kết nối tới AKS cluster
- Cập nhật image tags trong manifests
- Deploy tất cả manifests vào namespace `packamal`
- Verify deployment và health check

## Images được build

| Image | Dockerfile | Registry Path |
|-------|-----------|---------------|
| Backend | `./backend/Dockerfile` | `packamalacr.azurecr.io/packamal-backend` |
| Frontend | `./frontend/Dockerfile` | `packamalacr.azurecr.io/packamal-frontend` |
| Go Worker | `./worker/cmd/analyze/Dockerfile` | `packamalacr.azurecr.io/packamal-go-worker-analysis` |

## Manifests được cập nhật

Workflow tự động cập nhật image tags trong các file sau:

1. **05-backend.yaml**
   - Backend deployment (initContainer và main container)

2. **07-frontend.yaml**
   - Frontend deployment

3. **06-worker.yaml**
   - Celery worker deployment (sử dụng backend image)

4. **08-worker-2.yaml**
   - Celery worker 2 deployment (sử dụng backend image)

5. **01-config.yaml**
   - ANALYSIS_IMAGE config value

6. **13-image-preloader.yaml**
   - Image preloader deployment

## Troubleshooting

### Workflow không trigger
- ✅ Kiểm tra file `.github/workflows/aks-deploy.yml` đã được commit chưa
- ✅ Kiểm tra push vào đúng nhánh `main`
- ✅ Kiểm tra GitHub Actions đã được enable cho repository

### Build failures
- ✅ Kiểm tra Dockerfile syntax
- ✅ Kiểm tra build context paths
- ✅ Kiểm tra ACR credentials

### Deploy failures
- ✅ Kiểm tra Azure credentials
- ✅ Kiểm tra AKS cluster status
- ✅ Kiểm tra Service Principal permissions
- ✅ Kiểm tra kubectl connection

### Image pull failures
- ✅ Đảm bảo AKS có quyền pull từ ACR:
  ```bash
  az aks update -n packamal-aks -g packamal-rg --attach-acr packamalacr
  ```

Xem thêm troubleshooting trong [01-plan.md](01-plan.md).

## Security

- ✅ Sử dụng GitHub Secrets để lưu credentials
- ✅ Sử dụng Service Principal thay vì user account
- ✅ Giới hạn quyền tối thiểu cho Service Principal
- ✅ Rotate credentials định kỳ

Xem thêm security best practices trong [02-github-secrets.md](02-github-secrets.md).

## Monitoring

### GitHub Actions
- Xem logs trong GitHub Actions tab
- Mỗi workflow run có logs chi tiết
- Có thể download logs

### Kubernetes
```bash
# Xem deployment status
kubectl get deployments -n packamal

# Xem pod logs
kubectl logs -f deployment/backend -n packamal

# Xem rollout status
kubectl rollout status deployment/backend -n packamal
```

## Rollback

Nếu deployment thất bại:

```bash
# Rollback deployment
kubectl rollout undo deployment/backend -n packamal
kubectl rollout undo deployment/frontend -n packamal
kubectl rollout undo deployment/celery-worker -n packamal

# Hoặc rollback về image cũ bằng cách update manifest với commit SHA cũ
```

## Next Steps

1. ✅ Đọc [01-plan.md](01-plan.md) để hiểu chi tiết pipeline
2. ✅ Cấu hình GitHub Secrets theo [02-github-secrets.md](02-github-secrets.md)
3. ✅ Test workflow với test commit
4. ⏳ Monitor first deployment
5. ⏳ Setup notifications (optional)
6. ⏳ Add integration tests (optional)
7. ⏳ Add security scanning (optional)

## Tài liệu tham khảo

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Azure Container Registry](https://docs.microsoft.com/en-us/azure/container-registry/)
- [Azure Kubernetes Service](https://docs.microsoft.com/en-us/azure/aks/)
- [Kubernetes Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

