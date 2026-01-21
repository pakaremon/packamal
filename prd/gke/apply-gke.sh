#!/bin/bash
MANIFEST_DIR="./prd/gke/processed-k8s"

echo "🚀 Phase 1: Deploying Base Infrastructure..."
kubectl apply -k "${MANIFEST_DIR}/base"

echo "💾 Phase 2: Deploying Databases..."
kubectl apply -k "${MANIFEST_DIR}/data"

echo "⏳ Waiting for Postgres to be ready..."
kubectl wait --for=condition=ready pod -l app=database -n ${NAMESPACE} --timeout=90s

echo "🌐 Phase 3: Deploying Applications..."
kubectl apply -k "${MANIFEST_DIR}/apps"

echo "✅ All phases deployed successfully!"