# Troubleshooting Guide

## Common Issues and Solutions

### 1. Pods Stuck in Pending Status

**Common causes:**
- PVC requests exceed available capacity in the `standard-rwo`/`premium-rwo` classes.
- Missing default StorageClass or incorrect `storageClassName` on the PVC.
- Nodes are unschedulable due to taints or resource pressure.

**What to check:**
1. Verify PVCs are bound:
```bash
kubectl get pvc -n packamal
```
2. Confirm a default StorageClass exists (should be `standard-rwo`):
```bash
kubectl get storageclass
```
3. Inspect events on pending pods:
```bash
kubectl describe pod <pod-name> -n packamal
```

### 2. Redis Pods in CrashLoopBackOff

#### Issue: Redis cannot write to `/data` directory

**Symptoms:**
- Redis pods restarting with error: "chown: .: Operation not permitted"
- Pods in CrashLoopBackOff status

**Root Cause:**
Redis runs as user ID 999, but the PVC is mounted with incorrect permissions.

**Solution:**
The Redis deployment has been updated with:
- `fsGroup: 999` in pod securityContext
- InitContainer to fix permissions before Redis starts
- Proper `runAsUser: 999` in container securityContext

Apply the fix:
```bash
kubectl apply -f ./prd/gke/04-kubernetes-manifests/data/04-redis.yaml
```

### 3. Checking Pod Status

Use these commands to diagnose issues:

```bash
# Check pod status
kubectl get pods -n packamal

# Describe a specific pod
kubectl describe pod <pod-name> -n packamal

# Check events
kubectl get events -n packamal --sort-by='.lastTimestamp'

# Check PVC status
kubectl get pvc -n packamal

# Check logs for crashing pods
kubectl logs <pod-name> -n packamal --previous
```

### 6. Static/media/results not loading (GCS)

If static/media or dynamic analysis results are stored on GCS:

- Ensure the GKE Workload Identity GSA (see `11-rbac.yaml`) has the needed GCS permissions.
- Ensure `GCS_BUCKET_NAME`, `RESULTS_BUCKET_URL`, and `ANALYSIS_DYNAMIC_BUCKET_URL` are set in `packamal-config`.

### 4. Resource Constraints

If pods are pending due to resource constraints:

```bash
# Check node resources
kubectl describe node <node-name>

# Check resource requests/limits in deployments
kubectl describe deployment <deployment-name> -n packamal
```

### 5. Network Issues

If services can't communicate:

```bash
# Check services
kubectl get svc -n packamal

# Check endpoints
kubectl get endpoints -n packamal

# Test connectivity from a pod
kubectl run -it --rm debug --image=busybox:1.36 --restart=Never -n packamal -- sh
```
