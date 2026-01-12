# Recommended Fixes for Timeout Handling

## Fix 1: Synchronize Timeout Values

### Problem
K8s job uses `POD_TIMEOUT_SECONDS` env var, but task has `timeout_minutes` field. They can be out of sync.

### Solution
Pass `task.timeout_minutes` to K8s service when creating job.

**File: `helper.py`**
```python
@staticmethod
def run_packaml(
    package_name: str,
    package_version: str,
    ecosystem: str,
    task_id: str,
    local_path: Optional[str] = None,
    timeout_minutes: Optional[int] = None,  # ADD THIS
):
    if settings.DEBUG:
        return ExecutionService.run_packaml(...)
    else:
        k8s_service = K8sService()
        return k8s_service.run_analysis(
            ecosystem=ecosystem,
            package_name=package_name,
            task_id=task_id,
            package_version=package_version,
            timeout_minutes=timeout_minutes,  # PASS THIS
        )
```

**File: `tasks.py` (line 432)**
```python
results = Helper.run_packaml(
    package_name=task.package_name,
    package_version=task.package_version,
    ecosystem=task.ecosystem,
    task_id=task_id,
    timeout_minutes=task.timeout_minutes,  # ADD THIS
)
```

**File: `k8s_service.py` (line 32)**
```python
def run_analysis(self, ecosystem, package_name, task_id, package_version="latest", timeout_minutes=None):
    # ...
    # Use provided timeout_minutes or fallback to env var
    if timeout_minutes is None:
        timeout_minutes = int(os.environ.get("POD_TIMEOUT_SECONDS", "1800")) // 60
    pod_timeout_seconds = timeout_minutes * 60  # Convert to seconds
    
    job_spec = client.V1JobSpec(
        template=template,
        backoff_limit=0,
        ttl_seconds_after_finished=600,
        active_deadline_seconds=pod_timeout_seconds  # Use synchronized timeout
    )
```

---

## Fix 2: Separate Legacy and K8s Timeout Checking

### Problem
`check_timeouts()` checks ALL processing tasks, including K8s jobs, causing race condition.

### Solution
Filter `check_timeouts()` to only handle legacy container tasks.

**File: `tasks.py` (line 656-662)**
```python
@shared_task
def check_timeouts():
    """
    Periodic task to check for timed out analysis tasks.
    
    Only checks legacy container tasks (no job_id). K8s jobs are handled
    by sync_k8s_job_status().
    """
    try:
        with transaction.atomic():
            # Only check legacy container tasks (no K8s job_id)
            timed_out_tasks = [
                task
                for task in AnalysisTask.objects.filter(
                    status='processing',
                    job_id__isnull=True  # ADD THIS FILTER
                )
                if task.is_timed_out()
            ]
            # ... rest unchanged
```

---

## Fix 3: Skip Container Operations for K8s Jobs

### Problem
`_handle_timed_out_task()` tries to stop containers for K8s jobs where `container_id` is NULL.

### Solution
Add early return if task has `job_id` (K8s job).

**File: `tasks.py` (line 572-638)**
```python
def _handle_timed_out_task(task):
    """
    Handles a single timed out task by stopping container and marking failed.
    
    Only handles legacy container tasks. K8s jobs are handled by sync_k8s_job_status().
    """
    # Skip if this is a K8s job (handled by sync_k8s_job_status)
    if task.job_id:
        logger.warning(
            f"Task {task.id} has job_id={task.job_id}, "
            f"should be handled by sync_k8s_job_status()"
        )
        return
    
    logger.warning(
        f"⏰ Task {task.id} has timed out after "
        f"{task.timeout_minutes} minutes"
    )
    
    container_stopped = None
    if task.container_id:
        # ... rest of container handling unchanged
```

---

## Fix 4: Add Transaction Locking to Prevent Race Conditions

### Problem
`sync_k8s_job_status()` updates tasks without proper locking, risking concurrent updates.

### Solution
Use `select_for_update()` to lock rows during update.

**File: `tasks.py` (line 831-839)**
```python
def _handle_timeout_task(task, job_name, k8s_service, stats):
    """Handle task that timed out with proper locking."""
    logger.warning(f"Task {task.id} (job {job_name}) timed out due to activeDeadlineSeconds")
    with transaction.atomic():
        # Lock the row to prevent concurrent updates
        task = AnalysisTask.objects.select_for_update().get(id=task.id)
        if task.status == STATUS_PROCESSING:  # Double-check after lock
            _mark_task_as_timeout(task, job_name)
            stats['timeout'] += 1
            _cleanup_completed_task(task, k8s_service)
```

**Also apply to other handlers:**
```python
def _handle_completed_task(task, job_name, k8s_service, stats):
    """Handle successfully completed task with proper locking."""
    logger.info(f"Task {task.id} (job {job_name}) completed successfully")
    with transaction.atomic():
        task = AnalysisTask.objects.select_for_update().get(id=task.id)
        if task.status == STATUS_PROCESSING:
            _mark_task_as_completed(task)
            stats['completed'] += 1
            _cleanup_completed_task(task, k8s_service)

def _handle_failed_task(task, job_name, job_status, k8s_service, stats):
    """Handle failed task (non-timeout) with proper locking."""
    logger.warning(f"Task {task.id} (job {job_name}) failed (not timeout)")
    with transaction.atomic():
        task = AnalysisTask.objects.select_for_update().get(id=task.id)
        if task.status == STATUS_PROCESSING:
            _mark_task_as_failed(task, job_name, job_status, k8s_service)
            stats['failed'] += 1
            _cleanup_completed_task(task, k8s_service)
```

---

## Fix 5: Improve Error Handling in check_timeouts

### Problem
`check_timeouts()` doesn't filter out K8s jobs, causing unnecessary processing.

### Solution
Already addressed in Fix 2, but also add logging for clarity.

**File: `tasks.py` (line 656-685)**
```python
@shared_task
def check_timeouts():
    """
    Periodic task to check for timed out analysis tasks.
    
    Only handles legacy container tasks (job_id is NULL).
    K8s jobs are monitored by sync_k8s_job_status().
    """
    try:
        with transaction.atomic():
            # Only check legacy container tasks
            legacy_tasks = AnalysisTask.objects.filter(
                status='processing',
                job_id__isnull=True
            )
            
            timed_out_tasks = [
                task for task in legacy_tasks
                if task.is_timed_out()
            ]
            
            if not timed_out_tasks:
                return {
                    'timed_out_count': 0,
                    'checked_at': timezone.now().isoformat()
                }
            
            logger.info(
                f"⏰ Found {len(timed_out_tasks)} timed out legacy tasks"
            )
            
            for task in timed_out_tasks:
                _handle_timed_out_task(task)
            
            logger.info(
                f"⏰ Handled {len(timed_out_tasks)} timed out tasks"
            )
            _process_next_queued_task()
            
            return {
                'timed_out_count': len(timed_out_tasks),
                'checked_at': timezone.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error checking timeouts: {e}")
        return {'error': str(e)}
```

---

## Summary of Changes

1. ✅ **Synchronize timeout values** - Pass `task.timeout_minutes` to K8s job creation
2. ✅ **Separate legacy/K8s checking** - Filter `check_timeouts()` to only legacy tasks
3. ✅ **Skip container ops for K8s** - Early return in `_handle_timed_out_task()` if `job_id` exists
4. ✅ **Add transaction locking** - Use `select_for_update()` in all status update handlers
5. ✅ **Improve logging** - Better logging to distinguish legacy vs K8s timeout handling

These fixes will:
- Eliminate race conditions between two timeout checkers
- Synchronize timeout values between DB and K8s
- Properly separate legacy container and K8s job handling
- Prevent concurrent updates to task status

