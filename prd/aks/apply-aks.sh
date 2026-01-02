#!/bin/bash
# Script to apply AKS Kubernetes resources in the correct order
# Ensures dependencies are created before resources that need them
# Optimized for Azure Kubernetes Service (AKS)

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AKS_MANIFESTS_DIR="${SCRIPT_DIR}/04-kubernetes-manifests"
NAMESPACE="packamal"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}❌ kubectl is not installed or not in PATH${NC}"
    exit 1
fi

# Check if manifests directory exists
if [ ! -d "$AKS_MANIFESTS_DIR" ]; then
    echo -e "${RED}❌ Manifests directory not found: $AKS_MANIFESTS_DIR${NC}"
    exit 1
fi

echo -e "${BLUE}🚀 Applying AKS Kubernetes resources in phases...${NC}"
echo -e "${BLUE}   Target namespace: ${NAMESPACE}${NC}"
echo -e "${BLUE}   Manifests directory: ${AKS_MANIFESTS_DIR}${NC}"
echo ""

# Verify AKS context
CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")
if [[ "$CURRENT_CONTEXT" == *"aks"* ]] || [[ "$CURRENT_CONTEXT" == *"packamal"* ]]; then
    echo -e "${GREEN}✓ Using AKS context: ${CURRENT_CONTEXT}${NC}"
else
    echo -e "${YELLOW}⚠️  Current context: ${CURRENT_CONTEXT}${NC}"
    echo -e "${YELLOW}   Make sure you're connected to the correct AKS cluster${NC}"
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""

# Phase 1: Core infrastructure (namespace, config, storage, RBAC)
echo -e "${YELLOW}Phase 1: Applying namespace, config, secrets, PVCs, and RBAC...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/00-namespace.yaml"
kubectl apply -f "${AKS_MANIFESTS_DIR}/01-config.yaml"
kubectl apply -f "${AKS_MANIFESTS_DIR}/02-pvc.yaml"
kubectl apply -f "${AKS_MANIFESTS_DIR}/11-rbac.yaml"

# Wait for ServiceAccount to be ready
echo -e "${YELLOW}  Waiting for ServiceAccount to be ready...${NC}"
kubectl wait --for=jsonpath='{.metadata.name}' serviceaccount/backend-serviceaccount -n "${NAMESPACE}" --timeout=30s || true
sleep 3  # Give Kubernetes a moment to fully propagate RBAC and ensure token is available

# Verify PVCs are being created
echo -e "${YELLOW}  Verifying PVCs...${NC}"
sleep 2
PVC_COUNT=$(kubectl get pvc -n "${NAMESPACE}" --no-headers 2>/dev/null | wc -l || echo "0")
if [ "$PVC_COUNT" -ge 4 ]; then
    echo -e "${GREEN}  ✓ ${PVC_COUNT} PVCs found${NC}"
else
    echo -e "${YELLOW}  ⚠️  Only ${PVC_COUNT} PVCs found (expected at least 4)${NC}"
fi

echo -e "${GREEN}✅ Phase 1 complete${NC}"
echo ""

# Phase 2: Databases and core services
echo -e "${YELLOW}Phase 2: Applying databases and core services...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/03-postgres.yaml"
kubectl apply -f "${AKS_MANIFESTS_DIR}/04-redis.yaml"

# Wait for databases to be ready (optional but helpful)
echo -e "${YELLOW}  Waiting for databases to start...${NC}"
sleep 5
kubectl wait --for=condition=ready pod -l app=database -n "${NAMESPACE}" --timeout=120s || echo -e "${YELLOW}  ⚠️  Database pod not ready yet (may take longer)${NC}"
kubectl wait --for=condition=ready pod -l app=redis -n "${NAMESPACE}" --timeout=60s || echo -e "${YELLOW}  ⚠️  Redis pod not ready yet (may take longer)${NC}"

echo -e "${GREEN}✅ Phase 2 complete${NC}"
echo ""

# Phase 3: Application workloads
echo -e "${YELLOW}Phase 3: Applying application workloads...${NC}"
# Pre-load images on all nodes before application workloads start
echo -e "${YELLOW}  Pre-loading images on all nodes (DaemonSet)...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/13-image-preloader.yaml"

# Apply backend first (other services depend on it)
echo -e "${YELLOW}  Applying backend...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/05-backend.yaml"

# Apply workers and celery components
echo -e "${YELLOW}  Applying workers and celery components...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/06-worker.yaml"
kubectl apply -f "${AKS_MANIFESTS_DIR}/08-worker-2.yaml"
kubectl apply -f "${AKS_MANIFESTS_DIR}/09-celery-beat.yaml"
kubectl apply -f "${AKS_MANIFESTS_DIR}/10-flower.yaml"

# Apply frontend last
echo -e "${YELLOW}  Applying frontend...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/07-frontend.yaml"

echo -e "${GREEN}✅ Phase 3 complete${NC}"
echo ""

# Phase 4: HPA (applied after deployments exist)
echo -e "${YELLOW}Phase 4: Applying HPA...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/12-backend-hpa.yaml" 2>/dev/null || echo -e "${YELLOW}  ⚠️  HPA already exists or skipped${NC}"

echo -e "${GREEN}✅ Phase 4 complete${NC}"
echo ""

# Phase 5: Ingress (AKS-specific, applied after all services exist)
echo -e "${YELLOW}Phase 5: Applying Ingress...${NC}"
kubectl apply -f "${AKS_MANIFESTS_DIR}/14-ingress.yaml"

# Verify ingress controller exists
INGRESS_CLASS=$(kubectl get ingressclass nginx -o name 2>/dev/null || echo "")
if [ -z "$INGRESS_CLASS" ]; then
    echo -e "${YELLOW}  ⚠️  NGINX Ingress Controller may not be installed${NC}"
    echo -e "${YELLOW}     Install with: kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml${NC}"
else
    echo -e "${GREEN}  ✓ NGINX Ingress Controller found${NC}"
fi

echo -e "${GREEN}✅ Phase 5 complete${NC}"
echo ""

# Verification steps
echo -e "${YELLOW}Verifying deployment...${NC}"
sleep 8  # Wait for pods to start

# Verify ServiceAccount is being used correctly
BACKEND_POD=$(kubectl get pod -n "${NAMESPACE}" -l app=backend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$BACKEND_POD" ]; then
    SA=$(kubectl get pod "$BACKEND_POD" -n "${NAMESPACE}" -o jsonpath='{.spec.serviceAccountName}' 2>/dev/null || echo "")
    if [ "$SA" = "backend-serviceaccount" ]; then
        echo -e "${GREEN}✓ Backend pod is using 'backend-serviceaccount'${NC}"
    else
        echo -e "${YELLOW}⚠️  Backend pod service account: $SA (expected: backend-serviceaccount)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Backend pod not found yet${NC}"
fi

# Check pod status
echo ""
echo -e "${YELLOW}Pod status summary:${NC}"
kubectl get pods -n "${NAMESPACE}" -o wide

# Check services
echo ""
echo -e "${YELLOW}Service status:${NC}"
kubectl get svc -n "${NAMESPACE}"

# Check ingress
echo ""
echo -e "${YELLOW}Ingress status:${NC}"
kubectl get ingress -n "${NAMESPACE}" || echo -e "${YELLOW}  No ingress found (may take a moment to create)${NC}"

# ACR verification (optional)
echo ""
echo -e "${YELLOW}ACR Image Pull Status:${NC}"
if [ -n "$BACKEND_POD" ]; then
    IMAGE=$(kubectl get pod "$BACKEND_POD" -n "${NAMESPACE}" -o jsonpath='{.spec.containers[0].image}' 2>/dev/null || echo "")
    if [[ "$IMAGE" == *"azurecr.io"* ]]; then
        echo -e "${GREEN}✓ Using ACR image: ${IMAGE}${NC}"
        # Check if image pull was successful
        IMAGE_PULL_STATUS=$(kubectl get pod "$BACKEND_POD" -n "${NAMESPACE}" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
        if [ "$IMAGE_PULL_STATUS" = "true" ]; then
            echo -e "${GREEN}✓ Image pulled successfully${NC}"
        else
            echo -e "${YELLOW}⚠️  Image may still be pulling or container not ready${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Not using ACR image: ${IMAGE}${NC}"
    fi
fi

echo ""
echo -e "${GREEN}🎉 All resources applied successfully!${NC}"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo "  kubectl get pods -n ${NAMESPACE}"
echo "  kubectl get all -n ${NAMESPACE}"
echo "  kubectl get ingress -n ${NAMESPACE}"
echo "  kubectl logs -n ${NAMESPACE} -l app=backend --tail=50"
echo "  kubectl describe ingress packamal-ingress -n ${NAMESPACE}"
echo ""
echo -e "${YELLOW}Note: If pods are in ImagePullBackOff, verify ACR is attached to AKS:${NC}"
echo "  az aks show -n packamal-aks -g packamal-rg --query 'servicePrincipalProfile'"
echo "  az aks update -n packamal-aks -g packamal-rg --attach-acr packamalacr"

