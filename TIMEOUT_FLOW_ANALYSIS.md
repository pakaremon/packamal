# Timeout Check Flow Analysis for Go Heavy Worker

## Current Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Celery Beat (Every 60s)                      │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│  check_timeouts()        │    │  sync_k8s_job_status()       │
│  (Legacy timeout check)  │    │  (K8s job status monitor)    │
└──────────────────────────┘    └──────────────────────────────┘
              │                               │
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│ Query: status='processing'│    │ Query: status='processing'   │
│ + job_id is NULL/empty    │    │ + job_id IS NOT NULL         │
│ (Legacy container tasks)  │    │ (K8s job tasks)              │
└──────────────────────────┘    └──────────────────────────────┘
              │                               │
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│ For each task:           │    │ For each task:               │
│ task.is_timed_out()      │    │ 1. Get K8s job status        │
│   checks:                │    │ 2. Check job conditions      │
│   now > started_at +     │    │    - deadline_exceeded?      │
│          timeout_minutes │    │    - succeeded?              │
│                          │    │    - failed?                 │
└──────────────────────────┘    │    - active?                 │
              │                 └──────────────────────────────┘
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────────┐
│ If timed out:            │    │ If deadline_exceeded:        │
│ _handle_timed_out_task() │    │ _handle_timeout_task()       │
│ - Stop container (legacy)│    │ - Mark as STATUS_TIMEOUT     │
│ - Mark as 'timeout'      │    │ - Cleanup K8s job            │
└──────────────────────────┘    └──────────────────────────────┘
```

## Detailed Flow

### 1. Task Creation & K8s Job Submission

```python
# In run_dynamic_analysis() task (line 432):
Helper.run_packaml(...) 
  → K8sService.run_analysis(...)  # Returns job_name (string)
  → Creates K8s Job with activeDeadlineSeconds = POD_TIMEOUT_SECONDS (default: 1800s = 30min)
  
# Task is marked as 'processing' (line 292)
task.status = 'processing'
task.job_id = job_name  # K8s job name stored
task.started_at = timezone.now()
task.timeout_minutes = 30  # Default from model
```

### 2. Timeout Checking Mechanisms

#### A. `check_timeouts()` - Legacy/Database-based Check
- **Schedule**: Every 60 seconds (line 66 in celery.py)
- **Target**: Tasks with `status='processing'` (but likely only legacy container tasks)
- **Logic**: 
  ```python
  # Line 658-662
  timed_out_tasks = [
      task for task in AnalysisTask.objects.filter(status='processing')
      if task.is_timed_out()  # Checks: now > started_at + timeout_minutes
  ]
  ```
- **Issue**: This checks ALL processing tasks, but `_handle_timed_out_task()` tries to stop containers (line 593), which doesn't apply to K8s jobs.

#### B. `sync_k8s_job_status()` - K8s-based Check
- **Schedule**: Every 60 seconds (line 74 in celery.py)
- **Target**: Tasks with `status='processing'` AND `job_id IS NOT NULL` (line 941-944)
- **Logic**:
  ```python
  # Line 874-896
  if _has_deadline_exceeded_condition(job_status):  # Checks K8s condition
      _handle_timeout_task(...)  # Marks as STATUS_TIMEOUT
  elif job_status.succeeded:
      _handle_completed_task(...)
  elif job_status.failed:
      _handle_failed_task(...)
  ```
- **Issue**: Relies on K8s `activeDeadlineSeconds`, which may not match `task.timeout_minutes`.

## Critical Issues

### ❌ Issue 1: Timeout Value Mismatch

**Problem:**
- `check_timeouts()` uses `task.timeout_minutes` (from database, default 30 minutes)
- K8s job uses `POD_TIMEOUT_SECONDS` environment variable (default 1800s = 30 minutes)
- These values are **NOT synchronized** - if `task.timeout_minutes` is customized, K8s job still uses env var

**Location:**
- K8s job creation: `k8s_service.py` line 174
- Timeout check: `tasks.py` line 112 (in `is_timed_out()`)

**Impact:**
- If `task.timeout_minutes = 45` but `POD_TIMEOUT_SECONDS = 1800` (30 min), K8s will kill job at 30 min
- `check_timeouts()` will mark it as timeout at 45 min (too late)
- Or vice versa: K8s allows 30 min, but DB check happens at 45 min (missed timeout)

### ❌ Issue 2: Race Condition Between Two Checkers

**Problem:**
Both `check_timeouts()` and `sync_k8s_job_status()` run every 60 seconds and can check the same task:

```
Time 0:00 - Task starts (status='processing', job_id='analysis-xxx')
Time 1:00 - Both checkers run:
  - check_timeouts() checks: is_timed_out() = False (only 1 min passed)
  - sync_k8s_job_status() checks: job still active, no action
Time 29:30 - K8s kills job (activeDeadlineSeconds reached)
Time 30:00 - Both checkers run:
  - check_timeouts() checks: is_timed_out() = True (30 min passed) → tries to mark timeout
  - sync_k8s_job_status() checks: deadline_exceeded condition → marks timeout
  → Both try to update same task → potential race condition
```

**Location:**
- `tasks.py` line 656-685 (`check_timeouts`)
- `tasks.py` line 926-965 (`sync_k8s_job_status`)

**Impact:**
- Duplicate timeout handling attempts
- Potential transaction conflicts
- Inconsistent task state

### ❌ Issue 3: Legacy Container Handling in K8s Context

**Problem:**
`_handle_timed_out_task()` (line 572-638) tries to:
- Stop containers using `container_manager.stop_container()` (line 593)
- Get container logs (line 607)
- But for K8s jobs, `task.container_id` is likely NULL/empty

**Location:**
- `tasks.py` line 572-638

**Impact:**
- Wasted operations (trying to stop non-existent containers)
- Misleading logs
- Confusion between legacy Docker and K8s execution modes

### ❌ Issue 4: Incomplete Query Filtering

**Problem:**
`check_timeouts()` queries ALL `status='processing'` tasks (line 660), but should only handle:
- Legacy container tasks (where `job_id IS NULL`)
- OR skip tasks that have `job_id` (let `sync_k8s_job_status()` handle them)

**Current Code:**
```python
# Line 658-662 - checks ALL processing tasks
timed_out_tasks = [
    task
    for task in AnalysisTask.objects.filter(status='processing')  # ❌ No filter for job_id
    if task.is_timed_out()
]
```

**Should be:**
```python
# Only check tasks WITHOUT K8s job_id (legacy container tasks)
timed_out_tasks = [
    task
    for task in AnalysisTask.objects.filter(
        status='processing',
        job_id__isnull=True  # ✅ Only legacy tasks
    )
    if task.is_timed_out()
]
```

### ❌ Issue 5: Missing Timeout Synchronization on Job Creation

**Problem:**
When creating K8s job, `timeout_minutes` from the task is NOT used. The job always uses `POD_TIMEOUT_SECONDS` env var.

**Location:**
- `k8s_service.py` line 174:
  ```python
  pod_timeout_seconds = int(os.environ.get("POD_TIMEOUT_SECONDS", "1800"))
  ```
- Should use: `task.timeout_minutes * 60`

**Impact:**
- Custom timeout values are ignored
- Inconsistent timeout behavior

### ❌ Issue 6: No Coordination After Timeout

**Problem:**
After timeout is detected, `_process_next_queued_task()` is called (line 676, 839, 850, 861), but:
- Both `check_timeouts()` and `sync_k8s_job_status()` call it
- Can trigger duplicate queue processing attempts

## Recommended Fixes

### Fix 1: Use task.timeout_minutes in K8s Job Creation

```python
# In k8s_service.py run_analysis() method
def run_analysis(self, ecosystem, package_name, task_id, package_version="latest", timeout_minutes=None):
    # Use provided timeout or default
    if timeout_minutes is None:
        timeout_minutes = int(os.environ.get("POD_TIMEOUT_SECONDS", "1800")) // 60
    pod_timeout_seconds = timeout_minutes * 60
    
    job_spec = client.V1JobSpec(
        # ...
        active_deadline_seconds=pod_timeout_seconds
    )
```

### Fix 2: Separate Legacy and K8s Timeout Checking

```python
@shared_task
def check_timeouts():
    """Only check legacy container tasks (no job_id)."""
    timed_out_tasks = [
        task
        for task in AnalysisTask.objects.filter(
            status='processing',
            job_id__isnull=True  # Only legacy container tasks
        )
        if task.is_timed_out()
    ]
    # ... rest of handling
```

### Fix 3: Remove Container Operations from K8s Tasks

```python
def _handle_timed_out_task(task):
    """Handle timeout - only for legacy container tasks."""
    if task.job_id:
        # K8s jobs are handled by sync_k8s_job_status()
        logger.warning(f"Task {task.id} has job_id, should be handled by sync_k8s_job_status()")
        return
    
    # Only handle container stopping for legacy tasks
    if task.container_id:
        container_manager.stop_container(task.container_id)
        # ...
```

### Fix 4: Add Transaction Locking to Prevent Race Conditions

```python
def _handle_timeout_task(task, job_name, k8s_service, stats):
    """Handle task that timed out - with proper locking."""
    logger.warning(f"Task {task.id} (job {job_name}) timed out")
    with transaction.atomic():
        # Use select_for_update to lock the row
        task = AnalysisTask.objects.select_for_update().get(id=task.id)
        if task.status == STATUS_PROCESSING:  # Double-check after lock
            _mark_task_as_timeout(task, job_name)
            stats['timeout'] += 1
            _cleanup_completed_task(task, k8s_service)
```

### Fix 5: Pass timeout_minutes to K8s Service

```python
# In tasks.py run_dynamic_analysis()
results = Helper.run_packaml(
    package_name=task.package_name,
    package_version=task.package_version,
    ecosystem=task.ecosystem,
    task_id=task_id,
    timeout_minutes=task.timeout_minutes  # Pass timeout
)

# In helper.py
def run_packaml(..., timeout_minutes=None):
    if settings.DEBUG:
        # ...
    else:
        k8s_service = K8sService()
        return k8s_service.run_analysis(
            ecosystem=ecosystem,
            package_name=package_name,
            task_id=task_id,
            package_version=package_version,
            timeout_minutes=timeout_minutes  # Pass to K8s service
        )
```

## Summary

The current timeout checking has **two parallel systems** that don't coordinate:
1. **Legacy system** (`check_timeouts()`) - for Docker containers
2. **K8s system** (`sync_k8s_job_status()`) - for K8s jobs

**Key Problems:**
- Timeout values can be out of sync
- Both systems can process the same task (race condition)
- Legacy code tries to handle K8s tasks incorrectly
- No proper separation between legacy and K8s execution modes

**Recommendation:**
- Fix timeout synchronization (use `task.timeout_minutes` when creating K8s job)
- Separate legacy and K8s timeout checking (filter by `job_id`)
- Add proper transaction locking to prevent race conditions
- Remove legacy container operations for K8s tasks

