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

