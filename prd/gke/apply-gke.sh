#!/bin/bash
set -e

MANIFEST_DIR="./prd/gke/processed-k8s"

echo "=========================================="
echo "🚀 GKE Deployment Pipeline"
echo "=========================================="
echo ""

echo "📦 Phase 1: Deploying Base Infrastructure..."
kubectl apply -k "${MANIFEST_DIR}/base"
echo "✅ Base infrastructure deployed"
echo ""

echo "💾 Phase 2: Deploying Databases..."
kubectl apply -k "${MANIFEST_DIR}/data"
echo "✅ Database deployment created"
echo ""

echo "⏳ Phase 2.5: Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod -l app=database -n ${NAMESPACE} --timeout=120s
echo "✅ PostgreSQL is ready!"
echo ""

echo "🗄️  Phase 2.7: Running Database Migrations..."

# Delete old migration job if exists
kubectl delete job django-migrate -n ${NAMESPACE} --ignore-not-found=true 2>/dev/null || true
sleep 2

# Apply migration job 
kubectl apply -f "${MANIFEST_DIR}/apps/00-django-migrate-job.yaml" 

# Wait for job pod to be created and running
echo "⏳ Waiting for migration job to start..."
sleep 5
kubectl wait --for=condition=ready pod -l job-name=django-migrate -n ${NAMESPACE} --timeout=60s 2>/dev/null || {
    echo "⚠️  Pod not ready yet, checking status..."
    kubectl get pods -l job-name=django-migrate -n ${NAMESPACE}
}

# Wait for migration job to complete
echo "⏳ Waiting for migrations to complete..."
JOB_NAME="django-migrate"
kubectl wait --for=condition=complete --timeout=5m job/${JOB_NAME} -n ${NAMESPACE} || {
    echo ""
    echo "❌ Migration job failed or timed out!"
    echo ""
    echo "📋 Pod status:"
    kubectl get pods -l job-name=${JOB_NAME} -n ${NAMESPACE}
    echo ""
    echo "📝 Migration logs:"
    kubectl logs -l job-name=${JOB_NAME} -n ${NAMESPACE} --all-containers=true || true
    exit 1
}

echo "✅ Database migrations completed successfully!"
echo ""

echo "🌐 Phase 3: Deploying Applications..."
kubectl apply -k "${MANIFEST_DIR}/apps"
echo "✅ Applications deployed"
echo ""

echo "=========================================="
echo "✅ All phases deployed successfully!"
echo "=========================================="
echo ""
echo "📋 Check status:"
echo "  kubectl get pods -n ${NAMESPACE}"
echo ""
echo "📊 View migration logs:"
echo "  kubectl logs job/${JOB_NAME} -n ${NAMESPACE}"