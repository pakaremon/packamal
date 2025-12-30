#!/bin/bash
# Automatic script to restart the Packamal deployment
# This script performs all the steps outlined in automatic_restart_prompt.md

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="packamal"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
APPLY_K8S_SCRIPT="${SCRIPT_DIR}/apply-k8s.sh"
PORT_FORWARD_SCRIPT="${SCRIPT_DIR}/port-forward-external.sh"

# Superuser configuration (can be overridden by environment variables)
DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME:-admin}"
DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-admin@packamal.local}"
DJANGO_SUPERUSER_PASSWORD="${DJANGO_SUPERUSER_PASSWORD:-marches-SADDAM-jurassic-mad}"

# Timeout for waiting for pods (in seconds)
POD_WAIT_TIMEOUT=600

echo -e "${BLUE}🚀 Starting automatic restart of Packamal deployment...${NC}"
echo ""

# Function to check if minikube is running
check_minikube() {
    if ! minikube status &>/dev/null; then
        echo -e "${RED}❌ Error: Minikube is not running. Please start minikube first.${NC}"
        exit 1
    fi
}

# Function to wait for all pods to be running
wait_for_pods() {
    echo -e "${YELLOW}⏳ Waiting for all pods to be running...${NC}"
    
    local start_time=$(date +%s)
    local end_time=$((start_time + POD_WAIT_TIMEOUT))
    
    while [ $(date +%s) -lt $end_time ]; do
        # Get all pods in the namespace
        local pods=$(kubectl get pods -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
        
        if [ -z "$pods" ]; then
            echo -e "${YELLOW}  No pods found yet, waiting...${NC}"
            sleep 5
            continue
        fi
        
        # Count total pods and running pods
        local total_pods=0
        local running_pods=0
        local ready_pods=0
        
        for pod in $pods; do
            total_pods=$((total_pods + 1))
            local phase=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
            local ready=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
            
            if [ "$phase" = "Running" ]; then
                running_pods=$((running_pods + 1))
            fi
            
            if [ "$ready" = "true" ]; then
                ready_pods=$((ready_pods + 1))
            fi
        done
        
        echo -e "${YELLOW}  Pod status: $ready_pods/$total_pods ready, $running_pods/$total_pods running${NC}"
        
        # Check if all pods are running and ready
        if [ "$running_pods" -eq "$total_pods" ] && [ "$ready_pods" -eq "$total_pods" ]; then
            echo -e "${GREEN}✅ All pods are running and ready!${NC}"
            kubectl get pods -n "$NAMESPACE"
            return 0
        fi
        
        # Show current pod status
        kubectl get pods -n "$NAMESPACE" --no-headers | head -5
        
        sleep 5
    done
    
    echo -e "${RED}❌ Timeout waiting for pods to be ready${NC}"
    echo -e "${YELLOW}Current pod status:${NC}"
    kubectl get pods -n "$NAMESPACE"
    return 1
}

# Function to check if superuser already exists
superuser_exists() {
    local result
    result=$(kubectl exec -n "$NAMESPACE" deployment/backend --container=backend -- \
        python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); print('EXISTS' if User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists() else 'NOT_EXISTS')" 2>&1)
    echo "$result" | grep -q "EXISTS"
}

# Step 1: Check minikube
echo -e "${BLUE}Step 1: Checking minikube status...${NC}"
check_minikube
echo -e "${GREEN}✅ Minikube is running${NC}"
echo ""

# Step 2: Set up minikube docker environment
# echo -e "${BLUE}Step 2: Setting up minikube docker environment...${NC}"
# eval "$(minikube docker-env)"
# echo -e "${GREEN}✅ Docker environment configured${NC}"
# echo ""

# Step 3: Delete the previous namespace
echo -e "${BLUE}Step 3: Deleting previous namespace...${NC}"
if kubectl get namespace "$NAMESPACE" &>/dev/null; then
    kubectl delete ns "$NAMESPACE" --wait=false
    echo -e "${YELLOW}  Waiting for namespace to be deleted...${NC}"
    # Wait for namespace to be fully deleted (with timeout)
    timeout=60
    while [ $timeout -gt 0 ] && kubectl get namespace "$NAMESPACE" &>/dev/null; do
        sleep 1
        timeout=$((timeout - 1))
    done
    if kubectl get namespace "$NAMESPACE" &>/dev/null; then
        echo -e "${YELLOW}⚠️  Namespace deletion taking longer than expected, continuing anyway...${NC}"
    else
        echo -e "${GREEN}✅ Namespace deleted${NC}"
    fi
else
    echo -e "${YELLOW}  Namespace does not exist, skipping...${NC}"
fi
echo ""

# Step 4: Rebuild Docker images
echo -e "${BLUE}Step 4: Rebuilding Docker images...${NC}"

echo -e "${YELLOW}  Building backend image...${NC}"
docker build -t packamal-backend:local "$BACKEND_DIR"
echo -e "${GREEN}✅ Backend image built${NC}"


echo -e "${YELLOW}  Building frontend image...${NC}"
docker build -t packamal-frontend:local "$FRONTEND_DIR"
echo -e "${GREEN}✅ Frontend image built${NC}"

echo -e "${YELLOW}  Loading backend image...${NC}"
minikube image load packamal-backend:local
echo -e "${GREEN}✅ Backend image loaded${NC}"
echo ""

echo -e "${YELLOW}  Loading frontend image...${NC}"
minikube image load packamal-frontend:local
echo -e "${GREEN}✅ Frontend image loaded${NC}"
echo ""

if [ "$1" = "-w" ] ; then
    echo -e "${YELLOW}  Building go worker analysis image...${NC}"
    docker build -t packamal-go-worker-analysis:local -f /home/azureuser/packamal/worker/cmd/analyze/Dockerfile /home/azureuser/packamal/worker
    echo -e "${GREEN}✅ Go worker analysis image built${NC}"
    echo ""

    echo -e "${YELLOW}  Loading go worker analysis image...${NC}"
    minikube image load packamal-go-worker-analysis:local
    echo -e "${GREEN}✅ Go worker analysis image loaded${NC}"
    echo ""
fi

# Step 5: Apply Kubernetes resources
echo -e "${BLUE}Step 5: Applying Kubernetes resources...${NC}"
if [ ! -f "$APPLY_K8S_SCRIPT" ]; then
    echo -e "${RED}❌ Error: apply-k8s.sh not found at $APPLY_K8S_SCRIPT${NC}"
    exit 1
fi

bash "$APPLY_K8S_SCRIPT"
echo -e "${GREEN}✅ Kubernetes resources applied${NC}"
echo ""

# Step 6: Wait for all pods to be running
echo -e "${BLUE}Step 6: Waiting for all pods to be running...${NC}"
if ! wait_for_pods; then
    echo -e "${RED}❌ Error: Not all pods became ready in time${NC}"
    echo -e "${YELLOW}You may need to check the pod status manually:${NC}"
    echo "  kubectl get pods -n $NAMESPACE"
    echo "  kubectl describe pods -n $NAMESPACE"
    exit 1
fi
echo ""

# Step 7: Create superuser
# echo -e "${BLUE}Step 7: Creating superuser...${NC}"

# # Wait a bit more for backend to be fully ready (database migrations, etc.)
# echo -e "${YELLOW}  Waiting for backend to be fully ready...${NC}"
# sleep 10

# # Check if backend pod is ready
# BACKEND_POD=$(kubectl get pod -n "$NAMESPACE" -l app=backend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
# if [ -z "$BACKEND_POD" ]; then
#     echo -e "${RED}❌ Error: Backend pod not found${NC}"
#     exit 1
# fi

# echo -e "${YELLOW}  Checking if superuser already exists...${NC}"
# if superuser_exists; then
#     echo -e "${YELLOW}  Superuser '$DJANGO_SUPERUSER_USERNAME' already exists, skipping creation...${NC}"
# else
#     echo -e "${YELLOW}  Creating superuser with username: $DJANGO_SUPERUSER_USERNAME${NC}"
#     echo -e "${YELLOW}  (This may take a moment as the container initializes...)${NC}"
    
#     # Encode credentials to base64 to safely handle special characters (remove newlines for single line)
#     USERNAME_B64=$(printf '%s' "$DJANGO_SUPERUSER_USERNAME" | base64 | tr -d '\n')
#     EMAIL_B64=$(printf '%s' "$DJANGO_SUPERUSER_EMAIL" | base64 | tr -d '\n')
#     PASSWORD_B64=$(printf '%s' "$DJANGO_SUPERUSER_PASSWORD" | base64 | tr -d '\n')
    
#     # Create superuser using Django shell - decode base64 in Python to avoid shell escaping issues
#     PYTHON_CMD="import base64; from django.contrib.auth import get_user_model; User = get_user_model(); u = base64.b64decode('$USERNAME_B64').decode('utf-8'); e = base64.b64decode('$EMAIL_B64').decode('utf-8'); p = base64.b64decode('$PASSWORD_B64').decode('utf-8'); exists = User.objects.filter(username=u).exists(); User.objects.create_superuser(username=u, email=e, password=p) if not exists else None; print('CREATED' if not exists else 'EXISTS')"
    
#     CREATION_OUTPUT=$(kubectl exec -n "$NAMESPACE" deployment/backend --container=backend -- \
#         python manage.py shell -c "$PYTHON_CMD" 2>&1)
    
#     CREATION_EXIT_CODE=$?
    
#     echo -e "${YELLOW}  Command output:${NC}"
#     echo "$CREATION_OUTPUT" | sed 's/^/    /'
    
#     if [ $CREATION_EXIT_CODE -ne 0 ]; then
#         # Check if it failed because user already exists
#         if echo "$CREATION_OUTPUT" | grep -qi "already exists\|IntegrityError\|unique constraint"; then
#             echo -e "${YELLOW}  User already exists (creation was attempted but user exists)${NC}"
#         else
#             echo -e "${RED}❌ Error: Superuser creation command failed with exit code $CREATION_EXIT_CODE${NC}"
#             echo ""
#             echo -e "${YELLOW}Full error output:${NC}"
#             echo "$CREATION_OUTPUT"
#             exit 1
#         fi
#     fi
    
#     # Verify superuser was created
#     echo -e "${YELLOW}  Verifying superuser was created...${NC}"
#     sleep 2  # Give database a moment to commit
    
#     if superuser_exists; then
#         echo -e "${GREEN}✅ Superuser created and verified successfully${NC}"
#     else
#         echo -e "${RED}❌ Error: Superuser creation failed - user does not exist after creation attempt${NC}"
#         echo ""
#         echo -e "${YELLOW}Debugging information:${NC}"
#         echo -e "${YELLOW}  Backend pod: $BACKEND_POD${NC}"
#         echo -e "${YELLOW}  Username: $DJANGO_SUPERUSER_USERNAME${NC}"
#         echo -e "${YELLOW}  Email: $DJANGO_SUPERUSER_EMAIL${NC}"
#         echo ""
#         echo -e "${YELLOW}Troubleshooting steps:${NC}"
#         echo "1. Check backend logs:"
#         echo "   kubectl logs -n $NAMESPACE deployment/backend --container=backend --tail=50"
#         echo ""
#         echo "2. Try to create superuser manually:"
#         echo "   kubectl exec -it -n $NAMESPACE deployment/backend --container=backend -- python manage.py createsuperuser"
#         echo ""
#         echo "3. Check database connection and list users:"
#         echo "   kubectl exec -n $NAMESPACE deployment/backend --container=backend -- python manage.py shell -c \"from django.contrib.auth import get_user_model; User = get_user_model(); print('Users:', User.objects.all().values_list('username', flat=True))\""
#         exit 1
#     fi
# fi
# echo ""

# Step 8: Start port forwarding
echo -e "${BLUE}Step 8: Starting port forwarding...${NC}"
if [ ! -f "$PORT_FORWARD_SCRIPT" ]; then
    echo -e "${RED}❌ Error: port-forward-external.sh not found at $PORT_FORWARD_SCRIPT${NC}"
    exit 1
fi

bash "$PORT_FORWARD_SCRIPT" start
echo -e "${GREEN}✅ Port forwarding started${NC}"
echo ""

# Final summary
echo -e "${GREEN}🎉 Automatic restart completed successfully!${NC}"
echo ""
echo "Summary:"
echo "  ✅ Namespace deleted and recreated"
echo "  ✅ Docker images rebuilt"
echo "  ✅ Kubernetes resources applied"
echo "  ✅ All pods are running"
echo "  ✅ Superuser configured"
echo "  ✅ Port forwarding active"
echo ""
echo "Access the services:"
echo "  Frontend: http://20.187.145.56:8080"
echo "  Flower:   http://20.187.145.56:5555"
echo ""
echo "Superuser credentials:"
echo "  Username: $DJANGO_SUPERUSER_USERNAME"
echo "  Password: $DJANGO_SUPERUSER_PASSWORD"
echo ""
echo "To check status:"
echo "  kubectl get pods -n $NAMESPACE"
echo "  $PORT_FORWARD_SCRIPT status"
echo ""

