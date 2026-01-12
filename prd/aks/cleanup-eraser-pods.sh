#!/bin/bash
# Manual script to cleanup failed eraser pods
# Can be run manually or from CronJob
# Usage: ./cleanup-eraser-pods.sh [--force]

set -e

FORCE="${1:-}"

echo "=== Eraser Pod Cleanup Script ==="
echo "Started at: $(date)"
echo ""

# Find eraser pods that are OOMKilled
echo "1. Checking for OOMKilled eraser pods..."
OOM_PODS=$(kubectl get pods -n kube-system \
  -l app.kubernetes.io/name=image-cleaner \
  -o jsonpath='{range .items[*]}{@.metadata.name}{"\t"}{@.status.containerStatuses[0].lastState.terminated.reason}{"\t"}{@.status.containerStatuses[0].state.waiting.reason}{"\n"}{end}' 2>/dev/null | \
  grep -E "OOMKilled|CrashLoopBackOff|Error" | cut -f1 || echo "")

# Find eraser pods that are pending for more than 10 minutes
echo "2. Checking for long-pending eraser pods (>10 minutes)..."
PENDING_PODS=$(kubectl get pods -n kube-system \
  -l app.kubernetes.io/name=image-cleaner \
  --field-selector=status.phase=Pending \
  -o json | \
  jq -r '.items[] | select(.metadata.creationTimestamp) | select((now - (.metadata.creationTimestamp | fromdateiso8601)) > 600) | .metadata.name' 2>/dev/null || echo "")

# Find eraser pods with high CPU requests that are not running
echo "3. Checking for eraser pods with high resource requests..."
HIGH_RESOURCE_PODS=$(kubectl get pods -n kube-system \
  -l app.kubernetes.io/name=image-cleaner \
  -o json | \
  jq -r '.items[] | select(.status.phase != "Running" and .status.phase != "Succeeded") | select(.spec.containers[0].resources.requests.cpu // "0" | tonumber > 200) | .metadata.name' 2>/dev/null || echo "")

# Combine all pods to delete
ALL_PODS=""
if [ -n "$OOM_PODS" ]; then
  echo "   Found OOMKilled/Crashed pods:"
  echo "$OOM_PODS" | while read pod; do
    echo "     - $pod"
  done
  ALL_PODS="$ALL_PODS $OOM_PODS"
fi

if [ -n "$PENDING_PODS" ]; then
  echo "   Found long-pending pods:"
  echo "$PENDING_PODS" | while read pod; do
    echo "     - $pod"
  done
  ALL_PODS="$ALL_PODS $PENDING_PODS"
fi

if [ -n "$HIGH_RESOURCE_PODS" ]; then
  echo "   Found high-resource failed pods:"
  echo "$HIGH_RESOURCE_PODS" | while read pod; do
    echo "     - $pod"
  done
  ALL_PODS="$ALL_PODS $HIGH_RESOURCE_PODS"
fi

# Remove duplicates and empty strings
ALL_PODS=$(echo $ALL_PODS | tr ' ' '\n' | sort -u | grep -v '^$' | tr '\n' ' ')

if [ -z "$ALL_PODS" ]; then
  echo ""
  echo "✓ No failed eraser pods found. All good!"
  echo ""
  echo "Current eraser pod status:"
  kubectl get pods -n kube-system -l app.kubernetes.io/name=image-cleaner --sort-by=.metadata.creationTimestamp
  exit 0
fi

# Show summary
echo ""
echo "=== Summary ==="
POD_COUNT=$(echo $ALL_PODS | wc -w)
echo "Found $POD_COUNT eraser pod(s) to delete:"
echo "$ALL_PODS" | tr ' ' '\n' | while read pod; do
  if [ -n "$pod" ]; then
    STATUS=$(kubectl get pod "$pod" -n kube-system -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    CPU_REQ=$(kubectl get pod "$pod" -n kube-system -o jsonpath='{.spec.containers[0].resources.requests.cpu}' 2>/dev/null || echo "Unknown")
    echo "  - $pod (Status: $STATUS, CPU Request: $CPU_REQ)"
  fi
done

# Confirm deletion unless --force flag is set
if [ "$FORCE" != "--force" ]; then
  echo ""
  read -p "Do you want to delete these pods? (y/N): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
  fi
fi

# Delete pods
echo ""
echo "Deleting eraser pods..."
DELETED_COUNT=0
for pod in $ALL_PODS; do
  if [ -n "$pod" ]; then
    echo "  Deleting: $pod"
    if kubectl delete pod "$pod" -n kube-system --force --grace-period=0 2>/dev/null; then
      DELETED_COUNT=$((DELETED_COUNT + 1))
      echo "    ✓ Deleted successfully"
    else
      echo "    ✗ Failed to delete (may already be gone)"
    fi
  fi
done

echo ""
echo "=== Cleanup Complete ==="
echo "Deleted $DELETED_COUNT pod(s)"
echo "Finished at: $(date)"

# Show node CPU allocation
echo ""
echo "=== Current Node CPU Allocation ==="
kubectl top nodes 2>/dev/null || echo "Metrics server not available"
echo ""
kubectl describe nodes | grep -A 3 "Allocated resources" | grep "cpu" || echo "Unable to get allocation details"

# Show remaining eraser pods
echo ""
echo "=== Remaining Eraser Pods ==="
kubectl get pods -n kube-system -l app.kubernetes.io/name=image-cleaner --sort-by=.metadata.creationTimestamp || echo "No eraser pods found"

