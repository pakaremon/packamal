#!/bin/bash

set -e

NAMESPACE="${1:-packamal-dev}"

echo "📝 Updating ConfigMap in namespace: $NAMESPACE"
echo ""

# Export environment variables for envsubst
export NAMESPACE="$NAMESPACE"
export REGION="${REGION:-us-central1}"
export PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
export REPO_NAME="${REPO_NAME:-packamal}"
export TAG="${TAG:-latest}"

echo "Using configuration:"
echo "  NAMESPACE:   $NAMESPACE"
echo "  PROJECT_ID:  $PROJECT_ID"
echo ""

# Check if envsubst is available
if ! command -v envsubst &> /dev/null; then
    echo "⚠️  envsubst not found. Installing gettext-base..."
    sudo apt-get update && sudo apt-get install -y gettext-base
fi

# Process and apply ConfigMap
echo "🔄 Processing and applying ConfigMap..."
envsubst < prd/gke/04-kubernetes-manifests/base/01-config.yaml | kubectl apply -f - -n "$NAMESPACE"

echo ""
echo "✅ ConfigMap updated!"
echo ""
echo "🔄 Restarting pods to pick up new configuration..."
echo ""

# Restart deployments
echo "  Restarting backend..."
kubectl rollout restart deployment/backend -n "$NAMESPACE"

echo "  Restarting celery-worker..."
kubectl rollout restart deployment/celery-worker -n "$NAMESPACE"

echo "  Restarting celery-beat..."
kubectl rollout restart deployment/celery-beat -n "$NAMESPACE"

echo ""
echo "⏳ Waiting for rollouts to complete..."
kubectl rollout status deployment/backend -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/celery-worker -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/celery-beat -n "$NAMESPACE" --timeout=120s

echo ""
echo "✅ All pods restarted with new configuration!"
echo ""
echo "🔍 Verifying DEBUG setting..."
BACKEND_POD=$(kubectl get pods -n "$NAMESPACE" -l app=backend -o jsonpath='{.items[0].metadata.name}')
DEBUG_VALUE=$(kubectl exec -n "$NAMESPACE" "$BACKEND_POD" -- printenv DEBUG 2>/dev/null || echo "failed to read")
echo "  DEBUG = $DEBUG_VALUE"
echo ""

if [ "$DEBUG_VALUE" = "False" ]; then
    echo "✅ SUCCESS: DEBUG is now set to False"
else
    echo "⚠️  WARNING: DEBUG is still $DEBUG_VALUE"
fi
