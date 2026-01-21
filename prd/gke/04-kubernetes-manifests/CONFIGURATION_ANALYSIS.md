# Configuration Analysis Report

This document compares the infrastructure setup (`01-infrastructure-setup.md` lines 21-60) with the Kubernetes manifests and `k8s_service.py` to ensure consistency.

## Infrastructure Setup (Reference)

From `01-infrastructure-setup.md` lines 39-60:

### App Pool (lines 41-48)
```bash
gcloud container node-pools create app-pool \
    --node-labels "role=app-node"
```
- **Node Label**: `role=app-node`
- **Taint**: None

### Analysis Pool (lines 52-60)
```bash
gcloud container node-pools create analysis-pool \
    --node-taints "dedicated=analysis:NoSchedule" \
    --node-labels "role=analysis-worker"
```
- **Node Label**: `role=analysis-worker`
- **Taint**: `dedicated=analysis:NoSchedule`

## Configuration Files Check

### ✅ Node Selectors (MATCH)

| File | Configuration | Status |
|------|--------------|--------|
| `base/01-config.yaml:35` | `ANALYSIS_NODE_SELECTOR: "role=analysis-worker"` | ✅ Matches |
| `apps/13-image-preloader.yaml:17` | `nodeSelector: { role: analysis-worker }` | ✅ Matches |
| `k8s_service.py:271` | Uses `self.analysis_node_selector` from env | ✅ Matches |

### ✅ Fixed Issues

#### 1. Toleration Mismatch in `k8s_service.py` (FIXED)
**Before:**
- Toleration: `heavy-analysis=true:NoSchedule`
- Comment referenced wrong taint name

**After:**
- Toleration: `dedicated=analysis:NoSchedule`
- Matches infrastructure setup taint

**Location:** `backend/package_analysis/services/k8s_service.py:249-258`

#### 2. Missing Toleration in `image-preloader.yaml` (FIXED)
**Before:**
- Had `nodeSelector: { role: analysis-worker }` but no toleration
- Would fail to schedule on tainted analysis pool

**After:**
- Added toleration: `dedicated=analysis:NoSchedule`
- Can now schedule on analysis pool

**Location:** `prd/gke/04-kubernetes-manifests/apps/13-image-preloader.yaml`

## Configuration Summary

### Analysis Jobs (k8s_service.py)
- **Node Selector**: `role=analysis-worker` (from `ANALYSIS_NODE_SELECTOR` env var)
- **Toleration**: `dedicated=analysis:NoSchedule`
- **Priority Class**: `packamal-app-priority`

### Image Preloader Job
- **Node Selector**: `role=analysis-worker`
- **Toleration**: `dedicated=analysis:NoSchedule`
- **Purpose**: Pre-pulls dynamic-analysis image to analysis nodes

### App Services (Backend, Workers, etc.)
- **Node Selector**: None (can schedule on any pool)
- **Toleration**: None
- **Priority Class**: `packamal-app-priority`

## Notes

1. **App Pool Label**: The infrastructure setup creates `role=app-node` label, but no manifests currently use it. This is acceptable - app services can run on any available node.

2. **Infrastructure Setup Document Inconsistency**: 
   - Lines 16-19 mention `heavy-analysis=true:NoSchedule` and `nodepool=heavy-analysis`
   - Lines 52-60 (actual commands) use `dedicated=analysis:NoSchedule` and `role=analysis-worker`
   - **The actual commands (lines 52-60) are the source of truth** and have been used as reference

3. **All configurations now match** the infrastructure setup commands (lines 39-60).

## Verification Checklist

- [x] Analysis jobs have correct node selector (`role=analysis-worker`)
- [x] Analysis jobs have correct toleration (`dedicated=analysis:NoSchedule`)
- [x] Image preloader has correct node selector (`role=analysis-worker`)
- [x] Image preloader has correct toleration (`dedicated=analysis:NoSchedule`)
- [x] ConfigMap has correct `ANALYSIS_NODE_SELECTOR` value
- [x] `k8s_service.py` correctly uses environment variable for node selector
- [x] All comments and documentation match actual configuration
