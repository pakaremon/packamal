# Hướng dẫn cấu hình GitHub Secrets cho CI/CD

## Tổng quan

Để GitHub Actions workflow có thể build, push images và deploy lên AKS, bạn cần cấu hình các secrets sau trong GitHub repository.

## Các Secrets cần thiết

### 1. ACR_USERNAME

**Mô tả**: Username để đăng nhập vào Azure Container Registry (ACR)

**Cách lấy**:
```bash
# Lấy ACR admin username
az acr credential show --name packamalacr --query username --output tsv
```

**Hoặc từ Azure Portal**:
1. Vào Azure Portal
2. Tìm Container Registry `packamalacr`
3. Vào **Settings** > **Access keys**
4. Copy **Username**

**Giá trị mẫu**: `packamalacr`

**Cách thêm vào GitHub**:
1. Vào repository trên GitHub
2. Vào **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret**
4. Name: `ACR_USERNAME`
5. Value: Paste username
6. Click **Add secret**

---

### 2. ACR_PASSWORD

**Mô tả**: Password để đăng nhập vào Azure Container Registry (ACR)

**Cách lấy**:
```bash
# Lấy ACR admin password
az acr credential show --name packamalacr --query passwords[0].value --output tsv
```

**Hoặc từ Azure Portal**:
1. Vào Azure Portal
2. Tìm Container Registry `packamalacr`
3. Vào **Settings** > **Access keys**
4. Copy **Password** (hoặc **password2**)

**Lưu ý**: 
- ACR có 2 passwords, bạn có thể dùng bất kỳ password nào
- Nếu muốn rotate password, có thể disable password cũ và enable password mới

**Cách thêm vào GitHub**:
1. Vào repository trên GitHub
2. Vào **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret**
4. Name: `ACR_PASSWORD`
5. Value: Paste password
6. Click **Add secret**

---

### 3. AZURE_CREDENTIALS

**Mô tả**: Service Principal credentials để GitHub Actions có thể authenticate với Azure và truy cập AKS cluster

**Cách tạo Service Principal**:

#### Option 1: Sử dụng Azure CLI (Recommended)

```bash
# Đăng nhập Azure
az login

# Set subscription (nếu có nhiều subscriptions)
az account set --subscription "YOUR_SUBSCRIPTION_ID"

# Tạo Service Principal với quyền Contributor
az ad sp create-for-rbac \
  --name "packamal-github-actions" \
  --role contributor \
  --scopes /subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/packamal-rg \
  --sdk-auth
```

**Output sẽ có dạng**:
```json
{
  "clientId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "clientSecret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "subscriptionId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tenantId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "activeDirectoryEndpointUrl": "https://login.microsoftonline.com",
  "resourceManagerEndpointUrl": "https://management.azure.com/",
  "activeDirectoryGraphResourceId": "https://graph.windows.net/",
  "sqlManagementEndpointUrl": "https://management.core.windows.net:8443/",
  "galleryEndpointUrl": "https://gallery.azure.com/",
  "managementEndpointUrl": "https://management.core.windows.net/"
}
```

#### Option 2: Tạo Service Principal với quyền cụ thể hơn

```bash
# Tạo Service Principal
az ad sp create-for-rbac \
  --name "packamal-github-actions" \
  --skip-assignment

# Lưu output để lấy appId và password

# Gán quyền Contributor cho Resource Group
az role assignment create \
  --assignee <appId> \
  --role "Contributor" \
  --scope /subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/packamal-rg

# Gán quyền "Azure Kubernetes Service Cluster User Role" cho AKS cluster
az role assignment create \
  --assignee <appId> \
  --role "Azure Kubernetes Service Cluster User Role" \
  --scope /subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/packamal-rg/providers/Microsoft.ContainerService/managedClusters/packamal-aks
```

**Lưu ý**: 
- `appId` là `clientId` trong output JSON
- `password` là `clientSecret` trong output JSON

#### Option 3: Sử dụng Azure Portal

1. Vào Azure Portal
2. Vào **Azure Active Directory** > **App registrations**
3. Click **New registration**
4. Name: `packamal-github-actions`
5. Click **Register**
6. Vào **Certificates & secrets** > **New client secret**
7. Copy **Value** (chỉ hiện 1 lần)
8. Vào **Overview** và copy **Application (client) ID** và **Directory (tenant) ID**
9. Gán quyền Contributor cho Resource Group:
   - Vào **Subscriptions** > **Access control (IAM)**
   - Click **Add** > **Add role assignment**
   - Role: **Contributor**
   - Assign access to: **User, group, or service principal**
   - Select: `packamal-github-actions`
   - Scope: `packamal-rg` resource group

**Tạo JSON credentials**:
```json
{
  "clientId": "YOUR_APPLICATION_CLIENT_ID",
  "clientSecret": "YOUR_CLIENT_SECRET_VALUE",
  "subscriptionId": "YOUR_SUBSCRIPTION_ID",
  "tenantId": "YOUR_TENANT_ID",
  "activeDirectoryEndpointUrl": "https://login.microsoftonline.com",
  "resourceManagerEndpointUrl": "https://management.azure.com/",
  "activeDirectoryGraphResourceId": "https://graph.windows.net/",
  "sqlManagementEndpointUrl": "https://management.core.windows.net:8443/",
  "galleryEndpointUrl": "https://gallery.azure.com/",
  "managementEndpointUrl": "https://management.core.windows.net/"
}
```

**Cách thêm vào GitHub**:
1. Vào repository trên GitHub
2. Vào **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret**
4. Name: `AZURE_CREDENTIALS`
5. Value: Paste toàn bộ JSON (format trên)
6. Click **Add secret**

---

## Kiểm tra Secrets đã cấu hình

### Trên GitHub
1. Vào repository
2. Vào **Settings** > **Secrets and variables** > **Actions**
3. Bạn sẽ thấy 3 secrets:
   - ✅ `ACR_USERNAME`
   - ✅ `ACR_PASSWORD`
   - ✅ `AZURE_CREDENTIALS`

### Test kết nối

#### Test ACR Login
```bash
# Sử dụng ACR credentials
docker login packamalacr.azurecr.io -u <ACR_USERNAME> -p <ACR_PASSWORD>
```

#### Test Azure Login
```bash
# Sử dụng Service Principal
az login --service-principal \
  --username <clientId> \
  --password <clientSecret> \
  --tenant <tenantId>

# Test AKS access
az aks get-credentials \
  --resource-group packamal-rg \
  --name packamal-aks \
  --overwrite-existing

kubectl get nodes
```

---

## Security Best Practices

### 1. Sử dụng Service Principal thay vì User Account
- ✅ Service Principal có thể được rotate dễ dàng
- ✅ Có thể giới hạn quyền cụ thể
- ✅ Không ảnh hưởng đến user account chính

### 2. Giới hạn quyền tối thiểu
- Chỉ cấp quyền cần thiết cho Service Principal
- Sử dụng scope cụ thể (Resource Group thay vì Subscription)

### 3. Rotate Credentials định kỳ
- Rotate ACR password mỗi 90 ngày
- Rotate Service Principal secret mỗi 180 ngày

### 4. Sử dụng Azure Key Vault (Advanced)
- Lưu secrets trong Azure Key Vault
- GitHub Actions lấy secrets từ Key Vault
- Tự động rotate secrets

### 5. Audit và Monitoring
- Enable Azure Activity Log
- Monitor Service Principal usage
- Set up alerts cho suspicious activities

---

## Troubleshooting

### Lỗi: "Failed to login to ACR"
- ✅ Kiểm tra ACR_USERNAME và ACR_PASSWORD đúng chưa
- ✅ Kiểm tra ACR admin user đã được enable chưa:
  ```bash
  az acr update --name packamalacr --admin-enabled true
  ```

### Lỗi: "Failed to authenticate with Azure"
- ✅ Kiểm tra AZURE_CREDENTIALS JSON format đúng chưa
- ✅ Kiểm tra Service Principal có quyền Contributor không
- ✅ Kiểm tra Service Principal chưa bị disable

### Lỗi: "Failed to get AKS credentials"
- ✅ Kiểm tra Service Principal có quyền "Azure Kubernetes Service Cluster User Role" không
- ✅ Kiểm tra AKS cluster name và resource group đúng chưa
- ✅ Kiểm tra AKS cluster đang running

### Lỗi: "Failed to pull image"
- ✅ Kiểm tra AKS cluster có quyền pull từ ACR không
- ✅ Kiểm tra ACR network rules không block AKS
- ✅ Attach ACR to AKS:
  ```bash
  az aks update -n packamal-aks -g packamal-rg --attach-acr packamalacr
  ```

---

## Tóm tắt các bước

1. ✅ Lấy ACR username và password
2. ✅ Tạo Service Principal với quyền Contributor
3. ✅ Tạo JSON credentials cho AZURE_CREDENTIALS
4. ✅ Thêm 3 secrets vào GitHub:
   - `ACR_USERNAME`
   - `ACR_PASSWORD`
   - `AZURE_CREDENTIALS`
5. ✅ Test kết nối
6. ✅ Chạy workflow test

---

## Tài liệu tham khảo

- [GitHub Secrets Documentation](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Azure Service Principal](https://docs.microsoft.com/en-us/azure/active-directory/develop/app-objects-and-service-principals)
- [ACR Authentication](https://docs.microsoft.com/en-us/azure/container-registry/container-registry-authentication)
- [AKS Authentication](https://docs.microsoft.com/en-us/azure/aks/concepts-identity)

