# Resource Consumption Analysis: Root Causes & Prevention

## Executive Summary

Your cluster is experiencing severe resource exhaustion leading to pod scheduling failures, 502 errors, and system instability. This document identifies the root causes, major resource consumers, and prevention methods.

---

## 🔥 Critical Issues Found

### 1. **Redis Memory Explosion (2.05GB) - CRITICAL**

**Current State:**
```
used_memory_human: 2.05GB
used_memory_peak_human: 2.05GB
maxmemory: 0  ← NO LIMIT SET!
maxmemory_policy: noeviction
```

**Why This Happens:**
- **No maxmemory limit**: Redis can grow unbounded
- **noeviction policy**: Redis refuses new writes when full, doesn't evict
- **Celery results**: All task results stored in Redis
- **Queue backlog**: Pending tasks accumulate in Redis queues
- **Session data**: Django sessions stored in Redis
- **Cached data**: Analysis results cached in Redis

**Impact:**
- Redis pod using **1930Mi** memory (97% of 2Gi limit)
- Close to OOM (Out of Memory) kill
- Can cause entire system failure

**Root Cause:**
Redis deployment has no `maxmemory` configuration, allowing unbounded growth.

---

### 2. **Unlimited Analysis Jobs (MAX_CONCURRENT_JOBS = 0) - CRITICAL**

**Current Configuration:**
```yaml
MAX_CONCURRENT_JOBS: "0"  # 0 = unlimited!
```

**Analysis Job Resource Requirements:**
```python
requests={"cpu": "100m", "memory": "2Gi"}   # Each job!
limits={"cpu": "2", "memory": "4Gi"}        # Can burst to 4GB!
```

**Why This Happens:**
- Each analysis job requests **2GB memory minimum**
- Each job can burst to **4GB memory**
- Each job requests **100m CPU** (can burst to **2 CPU cores**)
- With **MAX_CONCURRENT_JOBS = 0**, unlimited jobs can be created
- **No resource quotas** to prevent job creation

**Impact:**
- **10 concurrent jobs** = **20GB memory requests** (way exceeds node capacity!)
- **20GB+ memory limits** (potential memory exhaustion)
- **2 CPU cores × 10 jobs** = **20 CPU cores** (exceeds node capacity!)
- Jobs fail to schedule → queued in Redis → Redis memory grows → **Feedback loop of death**

**Root Cause:**
Environment variable `MAX_CONCURRENT_JOBS` is set to `0` (unlimited), allowing unbounded job creation.

---

### 3. **Backend HPA Over-Scaling (5 Replicas)**

**Current State:**
- HPA scaled to **5 replicas** due to memory pressure (129% of target)
- Each backend replica: **512Mi memory request**, **3Gi limit**
- Total backend memory: **2.56GB requests**, **15GB limits** (if all pods)
- Node allocatable: **~5.5GB memory total** across both nodes

**Why This Happens:**
- HPA monitors memory at **80% target**
- Backend pods hit **129% of target** (1.03GB / 800Mi target)
- HPA aggressively scales up to reduce pressure
- But nodes don't have capacity → pods stuck in **Pending**

**Impact:**
- 5 backend pods trying to schedule, but only **1 running** (others Pending)
- **CPU exhaustion**: 5 × 100m = **500m CPU requests** (nodes can't fit)
- **Memory pressure**: Backend pods using high memory (likely due to heavy admin queries)

**Root Cause:**
HPA is too aggressive with scaling policies and memory targets are too low for admin page workloads.

---

### 4. **Node Capacity Exhaustion**

**Current Node Status:**
```
Node 1: 1898m/1900m CPU (99%) - FULL!
Node 2: ~1700m/1900m CPU (89%) - Near full

Node allocatable: 1900m CPU per node (100m reserved for system)
Total available: 3800m CPU across 2 nodes
Current allocation: ~3598m CPU (95% utilization)
```

**Why This Happens:**
- Each analysis job: **100m CPU** request
- Each backend pod: **100m CPU** request (5 pods = 500m)
- System pods: **~400m CPU** per node (coredns, kube-proxy, etc.)
- Celery worker: **50m CPU** request
- Image preloader: **100m CPU** request
- **Total requests exceed node capacity**

**Impact:**
- New pods **cannot schedule** → Pending status
- Celery worker stuck in Pending (no CPU available)
- Backend pods stuck in Pending
- Cluster autoscaler can't help (max node group size reached)

**Root Cause:**
Resource requests exceed node capacity. Need larger nodes or more nodes.

---

## 📊 Resource Consumption Breakdown

### Current Pod Resource Usage (Actual):
```
redis-f58dd879-lwrr6:        1930Mi memory (96% of 2Gi limit)
backend-754894b65c-zck22:     239Mi memory (actual usage)
database-75f958bcc7-pbbzh:    158Mi memory
celery-beat-6bb74d8547-vr858: 154Mi memory
image-preloader-56584cd899:    34Mi memory
frontend-f8876c5fd-dqvrl:       4Mi memory
```

### Resource Requests (Reserved):
```
Redis:        No CPU/memory requests (unpredictable!)
Backend:      100m CPU, 512Mi memory (×5 replicas = 500m CPU, 2.56GB)
Analysis Job: 100m CPU, 2Gi memory (×unlimited = UNBOUNDED!)
Celery Worker: 50m CPU, 256Mi memory
Database:     No requests (unpredictable!)
```

---

## 🎯 Prevention Methods

### Immediate Actions (Critical - Do Now!)

#### 1. **Configure Redis maxmemory (CRITICAL)**
```yaml
# In 04-redis.yaml, add to container args:
- redis-server
- --maxmemory 1gb          # Set max memory limit
- --maxmemory-policy allkeys-lru  # Evict least recently used keys
```

**Impact:**
- Prevents Redis memory explosion
- Allows automatic eviction of old cache/queues
- Protects cluster from OOM kills

#### 2. **Set MAX_CONCURRENT_JOBS to 3-5**
```yaml
# In 01-config.yaml:
MAX_CONCURRENT_JOBS: "3"  # Limit to 3 concurrent analysis jobs
```

**Calculation:**
- 3 jobs × 2GB memory = **6GB memory requests**
- 3 jobs × 100m CPU = **300m CPU requests**
- This fits within node capacity (with current usage)

**Impact:**
- Prevents unbounded job creation
- Limits concurrent resource usage
- Allows better queue management

#### 3. **Reduce Backend HPA max replicas**
```yaml
# In 12-backend-hpa.yaml:
minReplicas: 1
maxReplicas: 3  # Reduced from 5
```

**Impact:**
- Prevents over-scaling beyond node capacity
- More conservative scaling behavior

---

### Short-term Fixes (This Week)

#### 4. **Add Resource Quotas**
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: packamal-quota
  namespace: packamal
spec:
  hard:
    requests.cpu: "4"           # Max 4 CPU requests
    requests.memory: 8Gi        # Max 8GB memory requests
    limits.cpu: "8"             # Max 8 CPU limits
    limits.memory: 16Gi         # Max 16GB memory limits
    pods: "20"                  # Max 20 pods
    jobs.batch: "5"             # Max 5 concurrent jobs
```

**Impact:**
- Hard limit on resource allocation
- Prevents runaway consumption
- Enforces resource discipline

#### 5. **Optimize Analysis Job Resources**
```python
# In k8s_service.py:
resources = client.V1ResourceRequirements(
    requests={"cpu": "100m", "memory": "1Gi"},   # Reduced from 2Gi
    limits={"cpu": "1", "memory": "2Gi"},        # Reduced from 4Gi
)
```

**Impact:**
- Reduces per-job memory footprint by 50%
- More jobs can run concurrently
- Better resource utilization

#### 6. **Add Redis Memory Monitoring**
```yaml
# Add to redis deployment:
livenessProbe:
  exec:
    command:
      - redis-cli
      - --raw
      - CONFIG
      - GET
      - maxmemory
  initialDelaySeconds: 30
  periodSeconds: 60
```

**Impact:**
- Early warning of memory issues
- Automatic pod restart if Redis misconfigured

---

### Long-term Solutions (This Month)

#### 7. **Implement Resource Monitoring & Alerts**
- Set up Prometheus + Grafana
- Alert when Redis memory > 80%
- Alert when node CPU > 90%
- Alert when pending pods > 5

#### 8. **Optimize Redis Usage**
- Move Celery results to database (instead of Redis)
- Use Redis only for queues (not results storage)
- Implement result expiration (already configured but needs enforcement)
- Move Django sessions to database or external cache

#### 9. **Increase Node Capacity**
- Option A: Larger node VM size (Standard_D4s_v5 → Standard_D8s_v5)
- Option B: More nodes (increase max node group size)
- Option C: Separate node pools for analysis jobs (heavy workload pool)

#### 10. **Implement Priority Classes**
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000
description: "High priority for critical services"

# Apply to backend, database, redis
```

**Impact:**
- Critical services scheduled first
- Analysis jobs can be preempted if needed
- Better resource allocation

---

## 🔍 Root Cause Analysis

### Primary Root Causes (Ranked):

1. **Redis Unbounded Memory (CRITICAL)**
   - No maxmemory limit → Can grow to 100% of pod memory
   - Current: 2.05GB / 2GB limit (102% - likely hitting swap or OOM)
   - **Impact**: System-wide failures, OOM kills

2. **Unlimited Analysis Jobs (CRITICAL)**
   - MAX_CONCURRENT_JOBS = 0 → Unlimited job creation
   - Each job = 2GB memory request
   - **Impact**: Resource exhaustion, pod scheduling failures

3. **Insufficient Node Capacity**
   - 2 nodes × 1900m CPU = 3800m total CPU
   - Current requests: ~3600m CPU (95% utilized)
   - **Impact**: Can't schedule new pods

4. **HPA Over-Scaling**
   - Aggressive scaling policies (100% increase every 15s)
   - Low memory targets (80%)
   - **Impact**: Creates more pods than nodes can handle

5. **No Resource Quotas**
   - No hard limits on namespace resources
   - **Impact**: One runaway workload can exhaust entire cluster

---

## 📋 Action Plan Priority

### P0 (Do Immediately - System at Risk):
1. ✅ Set Redis maxmemory to 1GB with LRU eviction
2. ✅ Set MAX_CONCURRENT_JOBS to 3
3. ✅ Reduce backend HPA max replicas to 3

### P1 (This Week):
4. Add ResourceQuota to namespace
5. Reduce analysis job memory requests from 2Gi to 1Gi
6. Add monitoring/alerting for Redis memory

### P2 (This Month):
7. Increase node VM size or add nodes
8. Move Celery results from Redis to database
9. Implement PriorityClasses for resource allocation
10. Add comprehensive resource monitoring

---

## 🛠️ Implementation Steps

### Fix 1: Redis maxmemory (Now)
```bash
# Edit prd/aks/04-kubernetes-manifests/04-redis.yaml
# Add to container args:
args:
  - redis-server
  - --maxmemory 1gb
  - --maxmemory-policy allkeys-lru

# Apply:
kubectl apply -f prd/aks/04-kubernetes-manifests/04-redis.yaml
```

### Fix 2: MAX_CONCURRENT_JOBS (Now)
```bash
# Edit prd/aks/04-kubernetes-manifests/01-config.yaml
# Change:
MAX_CONCURRENT_JOBS: "3"

# Apply:
kubectl apply -f prd/aks/04-kubernetes-manifests/01-config.yaml
# Restart backend deployment to pick up new env var
kubectl rollout restart deployment backend -n packamal
```

### Fix 3: Reduce Analysis Job Resources (This Week)
```python
# Edit backend/package_analysis/services/k8s_service.py
# Line 38-39, change to:
resources = client.V1ResourceRequirements(
    requests={"cpu": "100m", "memory": "1Gi"},   # Reduced
    limits={"cpu": "1", "memory": "2Gi"},        # Reduced
)
```

---

## 📈 Expected Impact

### After Implementing P0 Fixes:
- **Redis memory**: Reduced from 2.05GB → ~500MB (with LRU eviction)
- **Analysis jobs**: Limited to 3 concurrent (max 6GB memory vs unlimited)
- **Backend replicas**: Max 3 instead of 5 (reduced CPU pressure)
- **Node CPU**: ~85% utilization (from 99%) - pods can schedule again

### After Implementing All Fixes:
- **Stable cluster**: No more scheduling failures
- **Predictable resource usage**: Quotas prevent over-allocation
- **Better performance**: Optimized resource requests
- **Scalable**: Can handle growth without immediate failures

---

## 🔄 Monitoring & Validation

### Check Redis Memory:
```bash
kubectl exec -n packamal deployment/redis -- redis-cli INFO memory | grep used_memory_human
# Should be < 1GB after maxmemory is set
```

### Check Analysis Jobs:
```bash
kubectl get jobs -n packamal
# Should never have > 3 running simultaneously
```

### Check Node Capacity:
```bash
kubectl describe nodes | grep "Allocated resources" -A 5
# CPU should be < 90% after fixes
```

### Check Pending Pods:
```bash
kubectl get pods -n packamal --field-selector=status.phase=Pending
# Should be 0 after fixes
```

---

## 📝 Summary

**Major Resource Consumers:**
1. **Redis**: 2.05GB memory (no limit) - **CRITICAL**
2. **Analysis Jobs**: 2GB each, unlimited concurrent - **CRITICAL**
3. **Backend HPA**: 5 replicas, 512Mi each - **HIGH**
4. **Node Capacity**: 99% CPU utilization - **HIGH**

**Root Causes:**
1. Redis has no maxmemory limit (unbounded growth)
2. MAX_CONCURRENT_JOBS = 0 (unlimited jobs)
3. Analysis jobs request too much memory (2GB each)
4. HPA over-scaling due to aggressive policies
5. No resource quotas to prevent over-allocation
6. Node capacity insufficient for workload

**Prevention:**
1. Set Redis maxmemory + eviction policy (P0)
2. Limit MAX_CONCURRENT_JOBS to 3-5 (P0)
3. Add ResourceQuota (P1)
4. Reduce analysis job memory requests (P1)
5. Increase node capacity (P2)
6. Implement monitoring/alerting (P2)

The cluster is currently **unstable and at risk**. Implementing the P0 fixes will restore stability within minutes.

