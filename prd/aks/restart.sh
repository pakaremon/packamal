#!/bin/bash

set -e

# Default: build only backend
BUILD_BACKEND=false
BUILD_FRONTEND=false
BUILD_WORKER=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -a)
            BUILD_BACKEND=true
            BUILD_FRONTEND=true
            BUILD_WORKER=true
            shift
            ;;
        -b)
            BUILD_BACKEND=true
            shift
            ;;
        -f)
            BUILD_FRONTEND=true
            shift
            ;;
        -w)
            BUILD_WORKER=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-a] [-b] [-f] [-w]"
            echo "  -a: Build all images (backend, frontend, worker)"
            echo "  -b: Build backend image"
            echo "  -f: Build frontend image"
            echo "  -w: Build worker image"
            exit 1
            ;;
    esac
done

# If no flags specified, default to nothing
# if [ "$BUILD_BACKEND" = false ] && [ "$BUILD_FRONTEND" = false ] && [ "$BUILD_WORKER" = false ]; then
#     BUILD_BACKEND=true
# fi

echo "Delete the packamal namespace"
kubectl delete ns packamal || echo "Namespace already deleted or doesn't exist"


# login
echo "Logging in to ACR..."
az acr login --name packamalacr


echo ""
echo "Building images based on selected flags:"
[ "$BUILD_BACKEND" = true ] && echo "  - Backend"
[ "$BUILD_FRONTEND" = true ] && echo "  - Frontend"
[ "$BUILD_WORKER" = true ] && echo "  - Worker"



# Build images
if [ "$BUILD_BACKEND" = true ]; then
    echo ""
    echo "Building backend image..."
    docker build -t packamal-backend:local /home/packamal/backend
fi

if [ "$BUILD_FRONTEND" = true ]; then
    echo ""
    echo "Building frontend image..."
    docker build -t packamal-frontend:local /home/packamal/frontend
fi

if [ "$BUILD_WORKER" = true ]; then
    echo ""
    echo "Building worker image..."
    docker build -t packamal-go-worker-analysis:local -f /home/packamal/worker/cmd/analyze/Dockerfile /home/packamal/worker
fi

# Tag images for ACR
if [ "$BUILD_BACKEND" = true ]; then
    echo ""
    echo "Tagging backend image for ACR..."
    docker tag packamal-backend:local packamalacr.azurecr.io/packamal-backend:latest
fi

if [ "$BUILD_FRONTEND" = true ]; then
    echo ""
    echo "Tagging frontend image for ACR..."
    docker tag packamal-frontend:local packamalacr.azurecr.io/packamal-frontend:latest
fi

if [ "$BUILD_WORKER" = true ]; then
    echo ""
    echo "Tagging worker image for ACR..."
    docker tag packamal-go-worker-analysis:local packamalacr.azurecr.io/packamal-go-worker-analysis:latest
fi

# Push images to ACR
if [ "$BUILD_BACKEND" = true ]; then
    echo ""
    echo "Pushing backend image to ACR..."
    docker push packamalacr.azurecr.io/packamal-backend:latest
fi

if [ "$BUILD_FRONTEND" = true ]; then
    echo ""
    echo "Pushing frontend image to ACR..."
    docker push packamalacr.azurecr.io/packamal-frontend:latest
fi

if [ "$BUILD_WORKER" = true ]; then
    echo ""
    echo "Pushing worker image to ACR..."
    docker push packamalacr.azurecr.io/packamal-go-worker-analysis:latest
fi


# Run apply-aks.sh to rebuild the namespace
echo ""
echo "Running ./apply-aks.sh to rebuild the namespace..."
cd "$(dirname "$0")"
./apply-aks.sh

# Get the IP address of frontend
echo ""
echo "Getting the IP address of frontend service..."
kubectl get svc -n packamal frontend

# Create super user 
echo ""
echo "Creating superuser..."
kubectl exec -it -n packamal deployment/backend -- python manage.py createsuperuser

