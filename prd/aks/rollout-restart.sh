#!/bin/bash

set -e

# Default: restart all deployments
RESTART_BACKEND=false
RESTART_FRONTEND=false
RESTART_WORKER=false
RESTART_BEAT=false
RESTART_FLOWER=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -a)
            RESTART_BACKEND=true
            RESTART_FRONTEND=true
            RESTART_WORKER=true
            RESTART_BEAT=true
            RESTART_FLOWER=true
            shift
            ;;
        -b)
            RESTART_BACKEND=true
            shift
            ;;
        -f)
            RESTART_FRONTEND=true
            shift
            ;;
        -w)
            RESTART_WORKER=true
            shift
            ;;
        -beat)
            RESTART_BEAT=true
            shift
            ;;
        -flower)
            RESTART_FLOWER=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-a] [-b] [-f] [-w] [-beat] [-flower]"
            echo "  -a: Build and restart all deployments (backend, frontend, worker, beat, flower)"
            echo "  -b: Build and restart backend deployment"
            echo "  -f: Build and restart frontend deployment"
            echo "  -w: Build worker image and restart celery-worker deployment"
            echo "  -beat: Restart celery-beat deployment (uses backend image)"
            echo "  -flower: Restart flower deployment (uses backend image)"
            exit 1
            ;;
    esac
done

# If no flags specified, default to all main services
if [ "$RESTART_BACKEND" = false ] && [ "$RESTART_FRONTEND" = false ] && [ "$RESTART_WORKER" = false ] && [ "$RESTART_BEAT" = false ] && [ "$RESTART_FLOWER" = false ]; then
    RESTART_BACKEND=true
    RESTART_FRONTEND=true
    RESTART_WORKER=true
    RESTART_BEAT=true
    RESTART_FLOWER=true
fi

NAMESPACE="packamal"

# Determine which images to build based on deployments to restart
BUILD_BACKEND=false
BUILD_FRONTEND=false
BUILD_WORKER=false

# Build backend if backend, beat, or flower needs restart (they all use backend image)
if [ "$RESTART_BACKEND" = true ] || [ "$RESTART_BEAT" = true ] || [ "$RESTART_FLOWER" = true ]; then
    BUILD_BACKEND=true
fi

# Build frontend if frontend needs restart
if [ "$RESTART_FRONTEND" = true ]; then
    BUILD_FRONTEND=true
fi

# Build worker if worker needs restart
if [ "$RESTART_WORKER" = true ]; then
    BUILD_WORKER=true
fi

echo "Build and rollout restart for selected deployments in namespace: $NAMESPACE"
echo ""
echo "Images to build:"
[ "$BUILD_BACKEND" = true ] && echo "  - Backend"
[ "$BUILD_FRONTEND" = true ] && echo "  - Frontend"
[ "$BUILD_WORKER" = true ] && echo "  - Worker (Go worker)"
echo ""
echo "Deployments to restart:"
[ "$RESTART_BACKEND" = true ] && echo "  - backend"
[ "$RESTART_FRONTEND" = true ] && echo "  - frontend"
[ "$RESTART_WORKER" = true ] && echo "  - celery-worker"
[ "$RESTART_BEAT" = true ] && echo "  - celery-beat"
[ "$RESTART_FLOWER" = true ] && echo "  - flower"
echo ""

# Login to ACR
echo "Logging in to ACR..."
az acr login --name packamalacr
echo ""

# Build images
if [ "$BUILD_BACKEND" = true ]; then
    echo "Building backend image..."
    docker build -t packamal-backend:local /home/packamal/backend
    echo ""
fi

if [ "$BUILD_FRONTEND" = true ]; then
    echo "Building frontend image..."
    docker build -t packamal-frontend:local /home/packamal/frontend
    echo ""
fi

if [ "$BUILD_WORKER" = true ]; then
    echo "Building worker image..."
    docker build -t packamal-go-worker-analysis:local -f /home/packamal/worker/cmd/analyze/Dockerfile /home/packamal/worker
    echo ""
fi

# Tag images for ACR
if [ "$BUILD_BACKEND" = true ]; then
    echo "Tagging backend image for ACR..."
    docker tag packamal-backend:local packamalacr.azurecr.io/packamal-backend:latest
    echo ""
fi

if [ "$BUILD_FRONTEND" = true ]; then
    echo "Tagging frontend image for ACR..."
    docker tag packamal-frontend:local packamalacr.azurecr.io/packamal-frontend:latest
    echo ""
fi

if [ "$BUILD_WORKER" = true ]; then
    echo "Tagging worker image for ACR..."
    docker tag packamal-go-worker-analysis:local packamalacr.azurecr.io/packamal-go-worker-analysis:latest
    echo ""
fi

# Push images to ACR
if [ "$BUILD_BACKEND" = true ]; then
    echo "Pushing backend image to ACR..."
    docker push packamalacr.azurecr.io/packamal-backend:latest
    echo ""
fi

if [ "$BUILD_FRONTEND" = true ]; then
    echo "Pushing frontend image to ACR..."
    docker push packamalacr.azurecr.io/packamal-frontend:latest
    echo ""
fi

if [ "$BUILD_WORKER" = true ]; then
    echo "Pushing worker image to ACR..."
    docker push packamalacr.azurecr.io/packamal-go-worker-analysis:latest
    echo ""
fi

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "Error: Namespace '$NAMESPACE' does not exist."
    echo "Please run ./apply-aks.sh first to create the namespace and deployments."
    exit 1
fi

# Restart deployments (rollout restart will pull the latest images)
if [ "$RESTART_BACKEND" = true ]; then
    echo "Restarting backend deployment..."
    kubectl rollout restart deployment/backend -n "$NAMESPACE"
    kubectl rollout status deployment/backend -n "$NAMESPACE" --timeout=300s
    echo "✓ Backend restarted successfully"
    echo ""
    # restart celery-worker deployment
    echo "Restarting celery-worker deployment..."
    kubectl rollout restart deployment/celery-worker -n "$NAMESPACE"
    kubectl rollout status deployment/celery-worker -n "$NAMESPACE" --timeout=300s
    echo "✓ Celery-worker restarted successfully"
    echo ""
    # restart celery beat deployment
    echo "Restarting celery beat deployment..."
    kubectl rollout restart deployment/celery-beat -n "$NAMESPACE"
    kubectl rollout status deployment/celery-beat -n "$NAMESPACE" --timeout=300s
    echo "✓ Celery-beat restarted successfully"
    echo ""
fi

if [ "$RESTART_FRONTEND" = true ]; then
    echo "Restarting frontend deployment..."
    kubectl rollout restart deployment/frontend -n "$NAMESPACE"
    kubectl rollout status deployment/frontend -n "$NAMESPACE" --timeout=300s
    echo "✓ Frontend restarted successfully"
    echo ""
fi

if [ "$RESTART_WORKER" = true ]; then
    echo "Restarting celery-worker deployment..."
    kubectl rollout restart deployment/celery-worker -n "$NAMESPACE"
    kubectl rollout status deployment/celery-worker -n "$NAMESPACE" --timeout=300s
    echo "✓ Celery-worker restarted successfully"
    echo ""
fi

if [ "$RESTART_BEAT" = true ]; then
    echo "Restarting celery-beat deployment..."
    kubectl rollout restart deployment/celery-beat -n "$NAMESPACE"
    kubectl rollout status deployment/celery-beat -n "$NAMESPACE" --timeout=300s
    echo "✓ Celery-beat restarted successfully"
    echo ""
fi

if [ "$RESTART_FLOWER" = true ]; then
    echo "Restarting flower deployment..."
    kubectl rollout restart deployment/flower -n "$NAMESPACE"
    kubectl rollout status deployment/flower -n "$NAMESPACE" --timeout=300s
    echo "✓ Flower restarted successfully"
    echo ""
fi

echo "✅ All selected deployments restarted successfully!"
echo ""
echo "Getting deployment status..."
kubectl get deployments -n "$NAMESPACE"

