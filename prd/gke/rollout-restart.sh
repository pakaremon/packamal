#!/bin/bash

# Dừng script ngay lập tức nếu có bất kỳ lệnh nào bị lỗi
set -e

# ==============================================================================
# CẤU HÌNH MẶC ĐỊNH
# ==============================================================================
RESTART_BACKEND=false
RESTART_FRONTEND=false
RESTART_CELERY_WORKER=false # Dành cho Python Celery Worker (dùng code Backend)
RESTART_GO_WORKER=false     # Dành cho Go Worker
RESTART_BEAT=false
RESTART_FLOWER=false

CURRENT_DIR=$(pwd)
echo "Current directory: $CURRENT_DIR"

BACKEND_DIR="${CURRENT_DIR}/backend"
FRONTEND_DIR="${CURRENT_DIR}/frontend"
WORKER_DIR="${CURRENT_DIR}/worker"

# ==============================================================================
# PHÂN TÍCH THAM SỐ ĐẦU VÀO (FLAGS)
# ==============================================================================
while [[ $# -gt 0 ]]; do
    case $1 in
        -a)
            RESTART_BACKEND=true; RESTART_FRONTEND=true; RESTART_CELERY_WORKER=true; RESTART_GO_WORKER=true; RESTART_BEAT=true; RESTART_FLOWER=true
            shift ;;
        -b) RESTART_BACKEND=true; RESTART_CELERY_WORKER=true; RESTART_BEAT=true; shift ;;
        -f) RESTART_FRONTEND=true; shift ;;
        -w) RESTART_GO_WORKER=true; shift ;;
        -beat) RESTART_BEAT=true; shift ;;
        -flower) RESTART_FLOWER=true; shift ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-a] [-b] [-f] [-w] [-beat] [-flower]"
            echo "  -a: Build and deploy ALL components"
            echo "  -b: Build and deploy Backend, Celery Worker, Beat"
            echo "  -f: Build and deploy Frontend"
            echo "  -w: Build and deploy Go Worker"
            echo "  -beat: Deploy Celery Beat"
            echo "  -flower: Deploy Flower"
            exit 1 ;;
    esac
done

# Nếu không truyền cờ nào, mặc định chạy tất cả
if [ "$RESTART_BACKEND" = false ] && [ "$RESTART_FRONTEND" = false ] && [ "$RESTART_CELERY_WORKER" = false ] && [ "$RESTART_GO_WORKER" = false ] && [ "$RESTART_BEAT" = false ] && [ "$RESTART_FLOWER" = false ]; then
    RESTART_BACKEND=true; RESTART_FRONTEND=true; RESTART_CELERY_WORKER=true; RESTART_GO_WORKER=true; RESTART_BEAT=true; RESTART_FLOWER=true
fi

# ==============================================================================
# XÁC ĐỊNH CÁC IMAGE CẦN BUILD
# ==============================================================================
BUILD_BACKEND=false
BUILD_FRONTEND=false
BUILD_GO_WORKER=false

# Backend, Celery Worker, Beat, Flower đều sử dụng CHUNG image Backend
if [ "$RESTART_BACKEND" = true ] || [ "$RESTART_CELERY_WORKER" = true ] || [ "$RESTART_BEAT" = true ] || [ "$RESTART_FLOWER" = true ]; then
    BUILD_BACKEND=true
fi

if [ "$RESTART_FRONTEND" = true ]; then BUILD_FRONTEND=true; fi
if [ "$RESTART_GO_WORKER" = true ]; then BUILD_GO_WORKER=true; fi

# ==============================================================================
# CẤU HÌNH BIẾN MÔI TRƯỜNG & UNIQUE TAG
# ==============================================================================
PROJECT_ID="${PROJECT_ID:-k8s-packamal}"
REPO_NAME="${REPO_NAME:-packamal-repo}"
REGION="${REGION:-us-central1}"
NAMESPACE="${NAMESPACE:-packamal-dev}"

# TẠO UNIQUE TAG BẰNG TIMESTAMP (Giúp K8s luôn nhận diện là image mới 100%)
TAG=$(date +%s)
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

# Khai báo tên đầy đủ của các image
BACKEND_IMAGE="${REGISTRY}/backend:${TAG}"
FRONTEND_IMAGE="${REGISTRY}/frontend:${TAG}"
GO_WORKER_IMAGE="${REGISTRY}/go-worker-analysis:${TAG}"

echo "========================================================="
echo "🚀 STARTING BUILD & DEPLOY WITH UNIQUE TAG: $TAG"
echo "========================================================="

# Xác thực Docker với Artifact Registry
echo "Configuring docker auth for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
echo ""

# ==========================================================
# BƯỚC 1: BUILD VÀ PUSH IMAGES LÊN ARTIFACT REGISTRY
# ==========================================================
if [ "$BUILD_BACKEND" = true ]; then
    echo "📦 Building BACKEND image..."
    docker build --no-cache -t "${BACKEND_IMAGE}" "${BACKEND_DIR}"
    echo "☁️ Pushing BACKEND image..."
    docker push "${BACKEND_IMAGE}"
    echo ""
fi

if [ "$BUILD_FRONTEND" = true ]; then
    echo "📦 Building FRONTEND image..."
    docker build --no-cache -t "${FRONTEND_IMAGE}" "${FRONTEND_DIR}"
    echo "☁️ Pushing FRONTEND image..."
    docker push "${FRONTEND_IMAGE}"
    echo ""
fi

if [ "$BUILD_GO_WORKER" = true ]; then
    echo "📦 Building GO WORKER image..."
    docker build --no-cache -t "${GO_WORKER_IMAGE}" -f "${WORKER_DIR}/cmd/analyze/Dockerfile" "${WORKER_DIR}"
    echo "☁️ Pushing GO WORKER image..."
    docker push "${GO_WORKER_IMAGE}"
    echo ""
fi

# Kiểm tra Namespace trước khi deploy
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "❌ Error: Namespace '$NAMESPACE' does not exist."
    exit 1
fi

# ==========================================================
# BƯỚC 2: DEPLOY LÊN KUBERNETES BẰNG KUBECTL SET IMAGE
# ==========================================================
echo "========================================================="
echo "🔄 ROLLING OUT NEW IMAGES TO KUBERNETES..."
echo "========================================================="

if [ "$RESTART_BACKEND" = true ]; then
    echo "-> Updating Backend Deployment..."
    # Cập nhật cả init container (migrate DB) và container chính
    kubectl set image deployment/backend django-setup="${BACKEND_IMAGE}" backend="${BACKEND_IMAGE}" -n "$NAMESPACE"
    kubectl rollout status deployment/backend -n "$NAMESPACE" --timeout=300s
    echo "✅ Backend updated successfully!"
    echo ""
fi

if [ "$RESTART_CELERY_WORKER" = true ]; then
    echo "-> Updating Celery Worker Deployment..."
    # Celery Worker sử dụng image Backend
    kubectl set image deployment/celery-worker celery-worker="${BACKEND_IMAGE}" -n "$NAMESPACE"
    kubectl rollout status deployment/celery-worker -n "$NAMESPACE" --timeout=300s
    echo "✅ Celery Worker updated successfully!"
    echo ""
fi

if [ "$RESTART_BEAT" = true ]; then
    echo "-> Updating Celery Beat Deployment..."
    # Celery Beat sử dụng image Backend
    kubectl set image deployment/celery-beat celery-beat="${BACKEND_IMAGE}" -n "$NAMESPACE"
    kubectl rollout status deployment/celery-beat -n "$NAMESPACE" --timeout=300s
    echo "✅ Celery Beat updated successfully!"
    echo ""
fi

if [ "$RESTART_FLOWER" = true ]; then
    echo "-> Updating Flower Deployment..."
    # Flower sử dụng image Backend (nếu có deployment)
    if kubectl get deployment flower -n "$NAMESPACE" &>/dev/null; then
        kubectl set image deployment/flower flower="${BACKEND_IMAGE}" -n "$NAMESPACE"
        kubectl rollout status deployment/flower -n "$NAMESPACE" --timeout=300s
        echo "✅ Flower updated successfully!"
    else
        echo "⚠️  Flower deployment not found, skipping."
    fi
    echo ""
fi

if [ "$RESTART_FRONTEND" = true ]; then
    echo "-> Updating Frontend Deployment..."
    kubectl set image deployment/frontend frontend="${FRONTEND_IMAGE}" -n "$NAMESPACE"
    kubectl rollout status deployment/frontend -n "$NAMESPACE" --timeout=300s
    echo "✅ Frontend updated successfully!"
    echo ""
fi

# ==========================================================
# TỔNG KẾT
# ==========================================================
echo "🎉 ALL DONE! System is running the latest code with Tag: $TAG"
echo ""
echo "Current Pods status:"
kubectl get pods -n "$NAMESPACE"