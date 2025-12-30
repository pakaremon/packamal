# Security and RBAC Configuration

## Overview

This document covers security best practices for the Packamal AKS deployment, including RBAC, network policies, secrets management, and pod security.

## Azure Key Vault Integration

### Create Key Vault

```bash
# Variables
RESOURCE_GROUP="packamal-rg"
KEY_VAULT_NAME="packamal-kv"
LOCATION="eastus"

# Create Key Vault
az keyvault create \
  --name $KEY_VAULT_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --enable-rbac-authorization true
```

### Store Secrets

```bash
# Store database password
az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name postgres-password \
  --value "YourSecurePassword123!"

# Store Django secret key
az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name django-secret-key \
  --value "your-secret-key-here"

# Store internal API token
az keyvault secret set \
  --vault-name $KEY_VAULT_NAME \
  --name internal-api-token \
  --value "your-internal-api-token-here"
```

### Install Secrets Store CSI Driver

```bash
# Add Helm repo
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts
helm repo update

# Install
helm install csi-secrets-store secrets-store-csi-driver/secrets-store-csi-driver \
  --namespace kube-system \
  --set syncSecret.enabled=true
```

### Grant AKS Access to Key Vault

```bash
# Get AKS managed identity
CLUSTER_IDENTITY=$(az aks show \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --query identity.principalId -o tsv)

# Grant Key Vault access
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee $CLUSTER_IDENTITY \
  --scope /subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.KeyVault/vaults/{key-vault-name}
```

### Create SecretProviderClass

```yaml
# secret-provider-class.yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: packamal-secrets
  namespace: packamal
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"
    userAssignedIdentityID: "<managed-identity-id>"
    keyvaultName: "packamal-kv"
    objects: |
      array:
        - |
          objectName: postgres-password
          objectType: secret
          objectVersion: ""
        - |
          objectName: django-secret-key
          objectType: secret
          objectVersion: ""
        - |
          objectName: internal-api-token
          objectType: secret
          objectVersion: ""
    tenantId: "<azure-tenant-id>"
  secretObjects:
  - secretName: packamal-secrets
    type: Opaque
    data:
    - objectName: postgres-password
      key: POSTGRES_PASSWORD
    - objectName: django-secret-key
      key: SECRET_KEY
    - objectName: internal-api-token
      key: INTERNAL_API_TOKEN
```

## RBAC Configuration

### Service Account for Backend

```yaml
# service-account.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: backend-serviceaccount
  namespace: packamal
  annotations:
    azure.workload.identity/client-id: "<managed-identity-client-id>"
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: backend-job-creator
  namespace: packamal
rules:
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["create", "get", "list", "watch", "delete"]
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: backend-job-creator-binding
  namespace: packamal
subjects:
  - kind: ServiceAccount
    name: backend-serviceaccount
    namespace: packamal
roleRef:
  kind: Role
  name: backend-job-creator
  apiGroup: rbac.authorization.k8s.io
```

### Workload Identity (Alternative to Service Principal)

```bash
# Enable OIDC issuer
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --enable-oidc-issuer \
  --enable-workload-identity

# Create user-assigned managed identity
az identity create \
  --name packamal-identity \
  --resource-group $RESOURCE_GROUP

# Get identity details
IDENTITY_CLIENT_ID=$(az identity show \
  --name packamal-identity \
  --resource-group $RESOURCE_GROUP \
  --query clientId -o tsv)

IDENTITY_RESOURCE_ID=$(az identity show \
  --name packamal-identity \
  --resource-group $RESOURCE_GROUP \
  --query id -o tsv)

# Get OIDC issuer URL
OIDC_ISSUER=$(az aks show \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)

# Establish federated credential
az identity federated-credential create \
  --name packamal-federated-credential \
  --identity-name packamal-identity \
  --resource-group $RESOURCE_GROUP \
  --issuer $OIDC_ISSUER \
  --subject system:serviceaccount:packamal:backend-serviceaccount \
  --audience api://AzureADTokenExchange
```

## Pod Security Standards

### Pod Security Policy (Deprecated - Use Pod Security Standards)

For Kubernetes 1.23+, use Pod Security Standards:

```yaml
# pod-security-policy.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: packamal
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

### Security Context for Pods

```yaml
# Example: Backend deployment security context
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
  capabilities:
    drop:
    - ALL
```

### Privileged Pods (Analysis Worker)

The Go analysis worker requires privileged mode for Podman. Use Pod Security Admission exemptions:

```yaml
# pod-security-exemption.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: packamal
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
    # Exempt analysis jobs from restricted policy
    pod-security.kubernetes.io/enforce-version: v1.24
    pod-security.kubernetes.io/audit-version: v1.24
    pod-security.kubernetes.io/warn-version: v1.24
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: "exempt-analysis-jobs"
spec:
  matchConstraints:
    resourceRules:
    - apiGroups: ["batch"]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["jobs"]
  validations:
  - expression: "object.metadata.labels['app'] != 'analysis-job' || object.spec.template.spec.securityContext.privileged == true"
    message: "Analysis jobs require privileged mode"
```

## Network Policies

### Default Deny All

```yaml
# network-policy-default-deny.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: packamal
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
```

### Allow Specific Traffic

```yaml
# network-policy-allow-backend.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend
  namespace: packamal
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8000
  - from:
    - podSelector:
        matchLabels:
          app: celery-worker
    ports:
    - protocol: TCP
      port: 8000
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: database
    ports:
    - protocol: TCP
      port: 5432
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379
  - to: []  # Allow DNS
    ports:
    - protocol: UDP
      port: 53
```

## Image Security

### Image Pull Secrets (if not using ACR attachment)

```bash
# Create image pull secret
kubectl create secret docker-registry acr-secret \
  --docker-server=$ACR_LOGIN_SERVER \
  --docker-username=$ACR_NAME \
  --docker-password=$(az acr credential show --name $ACR_NAME --query "passwords[0].value" -o tsv) \
  --namespace packamal
```

### Image Scanning

Use Azure Security Center or Trivy for vulnerability scanning:

```bash
# Install Trivy operator
helm repo add aqua https://aquasecurity.github.io/helm-charts/
helm install trivy-operator aqua/trivy-operator \
  --namespace trivy-system \
  --create-namespace
```

## TLS/SSL Certificates

### Install cert-manager

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Wait for cert-manager to be ready
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/instance=cert-manager \
  -n cert-manager \
  --timeout=300s
```

### Create ClusterIssuer (Let's Encrypt)

```yaml
# cluster-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@packamal.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
```

## Azure AD Integration

### Enable Azure AD RBAC

```bash
# Enable Azure AD integration
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --enable-aad \
  --enable-azure-rbac
```

### Create Azure AD Groups

```bash
# Create admin group
az ad group create --display-name "AKS Admins" --mail-nickname "aksadmins"

# Create developer group
az ad group create --display-name "AKS Developers" --mail-nickname "aksdevelopers"

# Assign roles
az role assignment create \
  --role "Azure Kubernetes Service Cluster Admin Role" \
  --assignee <admin-group-id> \
  --scope /subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.ContainerService/managedClusters/{cluster-name}
```

## Security Best Practices Checklist

- [ ] Enable Azure AD RBAC for cluster access
- [ ] Use managed identities instead of service principals
- [ ] Store secrets in Azure Key Vault
- [ ] Enable network policies
- [ ] Use Pod Security Standards
- [ ] Scan container images for vulnerabilities
- [ ] Enable TLS/SSL for all external traffic
- [ ] Use least-privilege RBAC roles
- [ ] Enable audit logging
- [ ] Regularly rotate secrets
- [ ] Use specific image tags (not `latest`)
- [ ] Enable Azure Defender for Kubernetes
- [ ] Implement pod security contexts
- [ ] Use resource quotas and limit ranges
- [ ] Enable Azure Policy for Kubernetes

## Azure Defender for Kubernetes

```bash
# Enable Defender
az security pricing create \
  --name "ContainerRegistry" \
  --tier "Standard"

az security pricing create \
  --name "KubernetesService" \
  --tier "Standard"
```

## Audit Logging

Enable audit logging in AKS:

```bash
# Enable diagnostic settings
az monitor diagnostic-settings create \
  --name aks-diagnostics \
  --resource /subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.ContainerService/managedClusters/{cluster-name} \
  --workspace <log-analytics-workspace-id> \
  --logs '[{"category":"kube-audit","enabled":true}]'
```

## Next Steps

1. Configure Key Vault and secrets
2. Set up RBAC and service accounts
3. Apply network policies
4. Configure TLS certificates
5. Review security checklist

