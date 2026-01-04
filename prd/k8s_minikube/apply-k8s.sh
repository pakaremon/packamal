#!/bin/bash
# Script to apply Kubernetes resources in the correct order
# Ensures ServiceAccount and RBAC are created before deployments

set -e

K8S_DIR="$(cd "$(dirname "$0")/k8s" && pwd)"
NAMESPACE="packamal"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Applying Kubernetes resources in phases...${NC}"
echo ""

# Phase 1: Core infrastructure (namespace, config, storage, RBAC)
echo -e "${YELLOW}Phase 1: Applying namespace, config, PVCs, and RBAC...${NC}"
kubectl apply -f "${K8S_DIR}/00-namespace.yaml"
kubectl apply -f "${K8S_DIR}/01-config.yaml"
kubectl apply -f "${K8S_DIR}/02-pvc.yaml"
kubectl apply -f "${K8S_DIR}/11-rbac.yaml"

# Wait for ServiceAccount to be ready
echo -e "${YELLOW}Waiting for ServiceAccount to be ready...${NC}"
kubectl wait --for=jsonpath='{.metadata.name}' serviceaccount/backend-serviceaccount -n "${NAMESPACE}" --timeout=30s || true
sleep 3  # Give Kubernetes a moment to fully propagate RBAC and ensure token is available

echo -e "${GREEN}✅ Phase 1 complete${NC}"
echo ""

# Phase 2: Databases and services
echo -e "${YELLOW}Phase 2: Applying databases and core services...${NC}"
kubectl apply -f "${K8S_DIR}/03-postgres.yaml"
kubectl apply -f "${K8S_DIR}/04-redis.yaml"

echo -e "${GREEN}✅ Phase 2 complete${NC}"
echo ""

# Phase 3: Application workloads
echo -e "${YELLOW}Phase 3: Applying application workloads...${NC}"
# Pre-load images on all nodes before application workloads start
echo -e "${YELLOW}  Pre-loading images on all nodes...${NC}"
kubectl apply -f "${K8S_DIR}/13-image-preloader.yaml"
kubectl apply -f "${K8S_DIR}/05-backend.yaml"
kubectl apply -f "${K8S_DIR}/06-worker.yaml"
kubectl apply -f "${K8S_DIR}/08-worker-2.yaml"
kubectl apply -f "${K8S_DIR}/09-celery-beat.yaml"
kubectl apply -f "${K8S_DIR}/10-flower.yaml"
kubectl apply -f "${K8S_DIR}/07-frontend.yaml"

# Phase 4: HPA (applied after deployments)
echo -e "${YELLOW}Phase 4: Applying HPA...${NC}"
kubectl apply -f "${K8S_DIR}/12-backend-hpa.yaml" 2>/dev/null || echo "HPA already exists or skipped"

echo -e "${GREEN}✅ Phase 3 & 4 complete${NC}"
echo ""

# Verify ServiceAccount is being used correctly
echo -e "${YELLOW}Verifying backend pod is using correct service account...${NC}"
sleep 8  # Wait for pods to start and be ready
BACKEND_POD=$(kubectl get pod -n "${NAMESPACE}" -l app=backend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$BACKEND_POD" ]; then
    SA=$(kubectl get pod "$BACKEND_POD" -n "${NAMESPACE}" -o jsonpath='{.spec.serviceAccountName}' 2>/dev/null || echo "")
    if [ "$SA" = "backend-serviceaccount" ]; then
        echo -e "${GREEN}✅ Backend pod is using 'backend-serviceaccount'${NC}"
        # Verify the token is correct (decode JWT to check service account name)
        TOKEN_SA=$(kubectl exec -n "${NAMESPACE}" "$BACKEND_POD" -- cat /var/run/secrets/kubernetes.io/serviceaccount/token 2>/dev/null | python3 -c "import sys, base64, json; token = sys.stdin.read().strip(); parts = token.split('.'); payload = json.loads(base64.urlsafe_b64decode(parts[1] + '==').decode()); print(payload.get('kubernetes.io', {}).get('serviceaccount', {}).get('name', 'unknown'))" 2>/dev/null || echo "unknown")
        if [ "$TOKEN_SA" = "backend-serviceaccount" ]; then
            echo -e "${GREEN}✅ Backend pod token verified - using correct service account${NC}"
        else
            echo -e "${YELLOW}⚠️  Token shows service account: $TOKEN_SA (may need pod restart)${NC}"
            echo -e "${YELLOW}   Run: kubectl delete pod -n ${NAMESPACE} -l app=backend${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Backend pod service account: $SA (expected: backend-serviceaccount)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Backend pod not found yet${NC}"
fi

echo ""
echo -e "${GREEN}🎉 All resources applied successfully!${NC}"
echo ""
echo "To check status:"
echo "  kubectl get pods -n ${NAMESPACE}"
echo "  kubectl get all -n ${NAMESPACE}"

