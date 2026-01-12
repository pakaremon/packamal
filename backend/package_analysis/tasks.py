"""
Celery tasks for package analysis.

This module provides background task processing for dynamic package analysis.
Tasks are executed via Celery workers with support for K8s job submission
and direct execution modes. The system provides queue management and timeout
handling via K8s job monitoring.

Migrated from QueueManager to use Celery for better scalability and monitoring.
Timeout checking is handled by sync_k8s_job_status which monitors K8s job
status and handles deadline exceeded conditions.
"""

import logging
import os
import traceback
import uuid
from datetime import timedelta

from celery import shared_task
from celery.exceptions import Retry
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .helper import Helper
from .models import AnalysisTask, ReportDynamicAnalysis
from .celery_redis_client import get_celery_redis_client
from .view_constants import (
    STATUS_PROCESSING,
    STATUS_COMPLETED,
    STATUS_QUEUED,
    STATUS_RECEIVED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    ERROR_CATEGORY_TIMEOUT_ERROR,
    ERROR_CATEGORY_K8S_JOB_FAILED,
    ERROR_CATEGORY_K8S_JOB_NOT_FOUND,
    ERROR_CATEGORY_QUEUE_ERROR,
    K8S_CONDITION_TYPE_FAILED,
    K8S_CONDITION_REASON_DEADLINE_EXCEEDED,
    K8S_HTTP_NOT_FOUND,
    CELERY_QUEUE_ANALYSIS,
)

logger = logging.getLogger(__name__)

# Constants
RETRY_DELAY_SECONDS = 30
RETRY_BACKOFF_BASE_SECONDS = 60
MAX_CONCURRENT_JOBS = int(os.environ.get('MAX_CONCURRENT_JOBS', '1'))
DEFAULT_TASK_PRIORITY = 0

# Event-driven trigger lock (Redis)
TRIGGER_LOCK_KEY = os.environ.get("ANALYSIS_TRIGGER_LOCK_KEY", "analysis:trigger_next_job_lock")
TRIGGER_LOCK_TTL_SECONDS = int(os.environ.get("ANALYSIS_TRIGGER_LOCK_TTL_SECONDS", "120"))


def _new_lock_token() -> str:
    return str(uuid.uuid4())


def _acquire_redis_lock(lock_key: str, token: str, ttl_seconds: int) -> bool:
    client = get_celery_redis_client()
    return bool(client.set(lock_key, token, nx=True, ex=ttl_seconds))


def _release_redis_lock(lock_key: str, token: str) -> None:
    """
    Release lock only if still owned by this token.
    Prevents accidentally deleting another worker's lock if TTL expired and got re-acquired.
    """
    client = get_celery_redis_client()
    lua = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    end
    return 0
    """
    try:
        client.eval(lua, 1, lock_key, token)
    except Exception:
        # Best-effort unlock; lock TTL guarantees eventual release.
        logger.warning("Failed to release Redis lock (best-effort)", exc_info=True)


def _count_active_k8s_jobs() -> int | None:
    """
    Count active/scheduled analysis jobs in K8s.
    Returns None if K8s API fails (caller can decide fallback).
    """
    return _count_processing_k8s_jobs()


def _find_oldest_queued_task_for_trigger() -> AnalysisTask | None:
    """
    Find the oldest task eligible for triggering.
    Eligible statuses: queued/received/pending (legacy).
    Must not already have job_id set.
    """
    return (
        AnalysisTask.objects.filter(
            status__in=[STATUS_QUEUED, STATUS_RECEIVED],
        )
        .filter(Q(job_id__isnull=True) | Q(job_id=''))
        .order_by('created_at', 'id')
        .first()
    )


def _reserve_task_for_processing(task_id: int) -> AnalysisTask | None:
    """
    Atomically reserve a queued task for processing.
    Uses SELECT FOR UPDATE to prevent multiple triggers from reserving the same task.
    """
    with transaction.atomic():
        task = (
            AnalysisTask.objects.select_for_update()
            .filter(id=task_id)
            .first()
        )
        if not task:
            return None

        if task.status not in [STATUS_QUEUED, STATUS_RECEIVED]:
            return None

        if task.job_id:
            return None

        task.status = STATUS_PROCESSING
        task.started_at = timezone.now()
        task.save()
        return task


def _mark_task_submission_failed(task: AnalysisTask, error: Exception) -> None:
    task.status = STATUS_FAILED
    task.completed_at = timezone.now()
    task.error_message = str(error)
    task.error_category = ERROR_CATEGORY_QUEUE_ERROR
    details = task.error_details or {}
    details['k8s_submission_error'] = {
        'message': str(error),
        'type': error.__class__.__name__,
        'at': timezone.now().isoformat(),
    }
    task.error_details = details
    task.save()


def trigger_next_analysis_if_slot_available() -> dict:
    """
    Shared event-driven trigger logic.
    - Checks real active K8s jobs.
    - If slot available, reserves the oldest queued task and submits it to K8s.
    - Protected by a Redis lock to avoid duplicate job creation from concurrent callbacks.
    """
    if MAX_CONCURRENT_JOBS <= 0:
        return {'triggered': False, 'reason': 'max_concurrent_jobs_disabled'}

    lock_token = _new_lock_token()
    if not _acquire_redis_lock(TRIGGER_LOCK_KEY, lock_token, TRIGGER_LOCK_TTL_SECONDS):
        return {'triggered': False, 'reason': 'lock_not_acquired'}

    try:
        active_jobs = _count_active_k8s_jobs()
        if active_jobs is None:
            active_jobs = _count_processing_tasks_with_jobs()

        if _is_limit_reached(active_jobs):
            return {'triggered': False, 'reason': 'limit_reached', 'active_jobs': active_jobs}

        candidate = _find_oldest_queued_task_for_trigger()
        if not candidate:
            return {'triggered': False, 'reason': 'no_queued_tasks'}

        reserved = _reserve_task_for_processing(candidate.id)
        if not reserved:
            return {'triggered': False, 'reason': 'candidate_not_reservable'}

        try:
            from .services.k8s_service import K8sService
            k8s_service = K8sService()
            job_name = k8s_service.run_analysis(
                ecosystem=reserved.ecosystem,
                package_name=reserved.package_name,
                task_id=reserved.id,
                package_version=reserved.package_version or "latest",
            )
        except Exception as submission_error:
            _mark_task_submission_failed(reserved, submission_error)
            return {'triggered': False, 'reason': 'k8s_submission_failed', 'task_id': reserved.id}

        with transaction.atomic():
            task = AnalysisTask.objects.select_for_update().get(id=reserved.id)
            task.job_id = job_name
            task.save()

        return {'triggered': True, 'task_id': reserved.id, 'job_id': job_name}
    finally:
        _release_redis_lock(TRIGGER_LOCK_KEY, lock_token)


def _reuse_existing_result(task, exclude_task_id=None):
    """
    Checks if there's an existing completed result for this PURL.
    
    Parameters:
        task: AnalysisTask instance to check for existing results
        exclude_task_id: Optional task ID to exclude from search
    
    Returns:
        AnalysisTask: Existing completed task with same PURL if found,
                      None otherwise
    
    Preconditions:
        task must have a purl attribute set
    """
    if not task.purl:
        return None
    
    query = AnalysisTask.objects.filter(
        purl=task.purl,
        status= STATUS_COMPLETED,
        report__isnull=False
    )
    
    if exclude_task_id:
        query = query.exclude(id=exclude_task_id)
    
    return query.order_by('-completed_at').first()


def _mark_task_completed_from_existing(task, existing_task):
    """
    Marks task as completed by copying data from existing completed task.
    
    Parameters:
        task: AnalysisTask to mark as completed
        existing_task: Completed AnalysisTask to copy data from
    
    Preconditions:
        existing_task must have status='completed' and a report
    """
    task.status = STATUS_COMPLETED
    task.completed_at = timezone.now()
    task.report = existing_task.report
    task.download_url = existing_task.download_url
    task.save()


def _count_processing_tasks_with_jobs():
    """Count processing tasks that have job_id set."""
    return AnalysisTask.objects.filter(
        status=STATUS_PROCESSING,
        job_id__isnull=False
    ).exclude(job_id='').count()


def _count_processing_k8s_jobs():
    """
    Count K8s jobs that are active or scheduled but not yet completed.
    
    Counts jobs that are either:
    - Active (status.active > 0): jobs with running pods
    - Scheduled but not completed (status.active = 0, succeeded = 0, failed = 0): 
      jobs that have been created but pods haven't started yet (e.g., pending due to 
      resource constraints), or jobs waiting to be processed.
    
    Excludes jobs that are completed (succeeded > 0) or have Complete condition,
    even if other status fields are None or 0.
    
    This ensures we count all jobs that are consuming or will consume cluster resources,
    not just jobs with active pods.
    
    Returns:
        int: Number of active/scheduled K8s jobs, or None if K8s API call fails
        
    Errors:
        Logs warning and returns None if K8s API call fails
    """
    try:
        from .services.k8s_service import K8sService
        
        k8s_service = K8sService()
        jobs = k8s_service.list_jobs(label_selector='app=analysis-job')
        
        # Count jobs that are active OR scheduled but not completed
        # Jobs are considered "scheduled" if they haven't completed (succeeded=0, failed=0)
        # even if active=0 (waiting for resources, pending, etc.)
        count = 0
        for job in jobs.items:
            if not job.status:
                continue
            
            # Check conditions first - if job has Complete condition, it's done
            if job.status.conditions:
                is_complete = any(
                    condition.type == "Complete" and condition.status == "True"
                    for condition in job.status.conditions
                )
                if is_complete:
                    # Job is completed, skip it
                    continue
            
            active = getattr(job.status, 'active', None)
            succeeded = getattr(job.status, 'succeeded', None)
            failed = getattr(job.status, 'failed', None)
            
            # Convert None to 0 for comparison
            active_val = active if active is not None else 0
            succeeded_val = succeeded if succeeded is not None else 0
            failed_val = failed if failed is not None else 0
            
            # Exclude jobs that have completed (succeeded > 0)
            if succeeded_val > 0:
                continue
            
            # Count if active > 0 OR if job is scheduled but not completed
            if active_val > 0:
                count += 1
            elif succeeded_val == 0 and failed_val == 0:
                # Job is scheduled but not completed (pending, waiting for resources, etc.)
                count += 1
        
        logger.debug(f"Found {count} active/scheduled K8s jobs (active > 0 or pending, excluding completed)")
        return count
        
    except Exception as e:
        logger.warning(
            f"Failed to count processing K8s jobs via API, will fallback to database check: {e}",
            exc_info=True
        )
        return None


def _is_limit_reached(current_count):
    """Check if concurrent job limit is reached."""
    return MAX_CONCURRENT_JOBS > 0 and current_count >= MAX_CONCURRENT_JOBS


def _check_and_prepare_task(task_id, celery_task):
    """
    Checks if task can run and prepares it for execution.
    
    Handles early exits (completed) and marks task as queued.
    
    Parameters:
        task_id: ID of AnalysisTask to check
        celery_task: Celery task instance (unused, kept for compatibility)
    
    Returns:
        tuple: (task, early_return_dict)
               task: AnalysisTask instance if ready to run, None otherwise
               early_return_dict: Dict to return if task already completed,
                                 None otherwise
    """
    with transaction.atomic():
        task = AnalysisTask.objects.select_for_update().get(id=task_id)
        
        if task.status == STATUS_COMPLETED:
            logger.info(f"✅ Task {task_id} already completed, skipping")
            return (None, {
                'status': 'success',
                'task_id': task_id,
                'cached': True,
                'message': 'Task already completed'
            })
        
        existing_task = _reuse_existing_result(task, exclude_task_id=task_id)
        if existing_task:
            logger.info(
                f"✅ Found existing completed result for {task.purl}, reusing"
            )
            _mark_task_completed_from_existing(task, existing_task)
            return (None, {
                'status': 'success',
                'task_id': task_id,
                'cached': True,
                'message': 'Reused existing result'
            })
        
        if task.status == STATUS_PROCESSING and task.job_id:
            return (None, {
                'status': 'success',
                'task_id': task_id,
                'cached': False,
                'message': 'Task already processing (job already submitted)',
                'job_id': task.job_id,
            })

        if task.status in [STATUS_RECEIVED, STATUS_QUEUED]:
            task.status = STATUS_QUEUED
            task.save()
    
    return (task, None)






def _extract_error_category(error):
    """Extract error category from error object."""
    if hasattr(error, 'error_details'):
        return error.error_details.get('error_category', 'unknown_error')
    return 'unknown_error'


def _extract_error_details(error):
    """Extract error details from error object."""
    if hasattr(error, 'error_details'):
        return error.error_details
    return {}


def _mark_task_failed(task_id, error):
    """Marks task as failed and saves error information."""
    try:
        with transaction.atomic():
            task = AnalysisTask.objects.get(id=task_id)
            task.status = STATUS_FAILED
            task.completed_at = timezone.now()
            task.error_message = str(error)
            task.error_category = _extract_error_category(error)
            task.error_details = _extract_error_details(error)
            task.save()
    except Exception as save_error:
        logger.error(f"Failed to save error state: {save_error}")


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def run_dynamic_analysis(self, task_id):
    """
    Background task for dynamic analysis.

    Event-driven model: this task no longer waits/retries on a fixed countdown.
    It ensures the task is queued and then attempts to trigger the next available
    analysis slot immediately via shared trigger logic.
    """
    logger.info(
        f"🚀 Worker {self.request.hostname} starting task {task_id}"
    )
    
    try:
        task, early_return = _check_and_prepare_task(task_id, self)
        if early_return:
            return early_return

        # Attempt to fill a slot immediately (FIFO).
        trigger_result = trigger_next_analysis_if_slot_available()
        return {
            'status': 'success',
            'task_id': task_id,
            'trigger': trigger_result,
        }
        
    except Retry:
        raise
    except Exception as e:
        logger.error(f"❌ Task {task_id} failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        _mark_task_failed(task_id, e)
        
        if self.request.retries < self.max_retries:
            retry_countdown = (RETRY_BACKOFF_BASE_SECONDS *
                              (2 ** self.request.retries))
            logger.info(
                f"🔄 Retrying task {task_id} in {retry_countdown}s "
                f"(attempt {self.request.retries + 1}/{self.max_retries})"
            )
            raise self.retry(exc=e, countdown=retry_countdown)
        else:
            logger.error(
                f"💀 Task {task_id} failed permanently after "
                f"{self.max_retries} retries"
            )
            raise


def _is_deadline_exceeded(condition):
    """Check if condition indicates deadline exceeded."""
    return (condition.type == K8S_CONDITION_TYPE_FAILED and 
            condition.reason == K8S_CONDITION_REASON_DEADLINE_EXCEEDED)


def _has_deadline_exceeded_condition(job_status):
    """Check if job status has deadline exceeded condition."""
    if not job_status or not job_status.conditions:
        return False
    return any(_is_deadline_exceeded(c) for c in job_status.conditions)


def _mark_task_as_timeout(task, job_name):
    """Mark task as timed out."""
    task.status = STATUS_TIMEOUT
    task.completed_at = timezone.now()
    task.error_message = f"Job exceeded activeDeadlineSeconds ({task.timeout_minutes} minutes)"
    task.error_category = ERROR_CATEGORY_TIMEOUT_ERROR
    task.error_details = {
        'reason': K8S_CONDITION_REASON_DEADLINE_EXCEEDED,
        'job_name': job_name,
        'timed_out_at': timezone.now().isoformat(),
    }
    task.save()


def _mark_task_as_completed(task):
    """Mark task as completed."""
    task.status = STATUS_COMPLETED
    task.completed_at = timezone.now()
    task.save()


def _get_pod_logs_for_job(k8s_service, job_name):
    """Retrieve pod logs for a job."""
    try:
        pods = k8s_service.list_pods_for_job(job_name)
        if pods.items:
            pod = pods.items[0]
            return k8s_service.get_pod_logs(pod.metadata.name, tail_lines=200)
    except Exception as log_error:
        logger.warning(f"Could not retrieve logs for job {job_name}: {log_error}")
    return None


def _mark_task_as_failed(task, job_name, job_status, k8s_service):
    """Mark task as failed with error details."""
    task.status = STATUS_FAILED
    task.completed_at = timezone.now()
    task.error_message = "K8s job failed"
    task.error_category = ERROR_CATEGORY_K8S_JOB_FAILED
    task.error_details = {
        'job_name': job_name,
        'failed_count': job_status.failed,
    }
    logs = _get_pod_logs_for_job(k8s_service, job_name)
    if logs:
        task.error_details['pod_logs'] = logs
    task.save()


def _mark_task_as_job_not_found(task, job_name, api_error):
    """Mark task as failed due to job not found."""
    task.status = STATUS_FAILED
    task.completed_at = timezone.now()
    task.error_message = f"K8s job {job_name} not found"
    task.error_category = ERROR_CATEGORY_K8S_JOB_NOT_FOUND
    task.error_details = {
        'job_name': job_name,
        'error': str(api_error),
    }
    task.save()


def _handle_timeout_task(task, job_name, k8s_service, stats):
    """Handle task that timed out."""
    logger.warning(f"Task {task.id} (job {job_name}) timed out due to activeDeadlineSeconds")
    with transaction.atomic():
        task.refresh_from_db()
        if task.status == STATUS_PROCESSING:
            _mark_task_as_timeout(task, job_name)
    stats['timeout'] += 1
    _cleanup_completed_task(task, k8s_service)


def _handle_completed_task(task, job_name, k8s_service, stats):
    """Handle successfully completed task."""
    logger.info(f"Task {task.id} (job {job_name}) completed successfully")
    with transaction.atomic():
        task.refresh_from_db()
        if task.status == STATUS_PROCESSING:
            _mark_task_as_completed(task)
    stats['completed'] += 1
    _cleanup_completed_task(task, k8s_service)


def _handle_failed_task(task, job_name, job_status, k8s_service, stats):
    """Handle failed task (non-timeout)."""
    logger.warning(f"Task {task.id} (job {job_name}) failed (not timeout)")
    with transaction.atomic():
        task.refresh_from_db()
        if task.status == STATUS_PROCESSING:
            _mark_task_as_failed(task, job_name, job_status, k8s_service)
    stats['failed'] += 1
    _cleanup_completed_task(task, k8s_service)


def _handle_job_not_found(task, job_name, api_error, stats):
    """Handle case where job is not found in K8s."""
    logger.warning(f"Job {job_name} not found in K8s for task {task.id}. Marking as failed.")
    with transaction.atomic():
        task.refresh_from_db()
        if task.status == STATUS_PROCESSING:
            _mark_task_as_job_not_found(task, job_name, api_error)
    stats['failed'] += 1


def _process_job_status(task, job_status, job_name, k8s_service, stats):
    """Process job status and update task accordingly."""
    # Check conditions first (they are more reliable indicators of job state)
    if job_status and job_status.conditions:
        # Check for completion conditions first
        for condition in job_status.conditions:
            if condition.type == "Complete" and condition.status == "True":
                # Job is complete but succeeded count might not be updated yet
                logger.info(f"Task {task.id} (job {job_name}) has Complete condition, treating as completed")
                _handle_completed_task(task, job_name, k8s_service, stats)
                return True
        
        # Check for deadline exceeded condition
        if _has_deadline_exceeded_condition(job_status):
            _handle_timeout_task(task, job_name, k8s_service, stats)
            return True
    
    # Get status values, treating None as 0 (not initialized yet)
    succeeded = getattr(job_status, 'succeeded', None) if job_status else None
    failed = getattr(job_status, 'failed', None) if job_status else None
    active = getattr(job_status, 'active', None) if job_status else None
    
    # Convert None to 0 for comparison, but track if all are None (unusual state)
    succeeded_val = succeeded or 0
    failed_val = failed or 0
    active_val = active or 0
    
    # Log job status values for debugging (INFO level so it's always visible)
    logger.info(
        f"Task {task.id} (job {job_name}) status: "
        f"succeeded={succeeded_val}, failed={failed_val}, active={active_val}"
    )
    
    # If all status fields are None (unusual state), check if job has conditions
    if job_status and (succeeded is None and failed is None and active is None):
        # This is the "unusual status" case - if no conditions indicate completion,
        # we should still treat it as processing, but log a warning
        if not job_status.conditions:
            logger.warning(
                f"Job {job_name} for task {task.id} has unusual status (all fields None, no conditions). "
                f"Treating as still processing, but this may indicate a K8s API issue."
            )
            stats['still_processing'] += 1
            return True
    
    if succeeded_val > 0:
        _handle_completed_task(task, job_name, k8s_service, stats)
        return True
    
    if failed_val > 0:
        if not _has_deadline_exceeded_condition(job_status):
            _handle_failed_task(task, job_name, job_status, k8s_service, stats)
            return True
    
    if active_val > 0:
        stats['still_processing'] += 1
        logger.debug(f"Task {task.id} (job {job_name}) still processing (active pods: {active_val})")
        return True
    
    # All counters are 0/None - job may be in initial state or completed but not yet updated
    stats['still_processing'] += 1
    logger.debug(f"Task {task.id} (job {job_name}) has no active pods and no completion indicators, keeping as processing")
    return True


def _sync_single_task(task, k8s_service, stats):
    """Sync status for a single task."""
    from kubernetes.client.rest import ApiException
    
    stats['checked'] += 1
    job_name = task.job_id
    
    try:
        job = k8s_service.get_job(job_name)
        if not job:
            logger.warning(f"Job {job_name} not found in K8s for task {task.id}")
            stats['errors'] += 1
            return
        
        # Log detailed job info if status fields are all None (unusual state)
        if job.status and (
            getattr(job.status, 'succeeded', None) is None and
            getattr(job.status, 'failed', None) is None and
            getattr(job.status, 'active', None) is None
        ):
            logger.warning(
                f"Job {job_name} for task {task.id} has unusual status: "
                f"status object exists but all fields are None. "
                f"Job metadata: creation_time={getattr(job.metadata, 'creation_timestamp', None)}"
            )
        
        _process_job_status(task, job.status, job_name, k8s_service, stats)
        
    except ApiException as api_error:
        if api_error.status == K8S_HTTP_NOT_FOUND:
            _handle_job_not_found(task, job_name, api_error, stats)
        else:
            logger.error(f"K8s API error checking job {job_name} for task {task.id}: {api_error}")
            stats['errors'] += 1
    except Exception as e:
        logger.error(f"Error checking job {job_name} for task {task.id}: {e}", exc_info=True)
        stats['errors'] += 1


@shared_task
def maintenance_sync_k8s_status():
    """
    Periodic safety net (Celery beat).
    Only handles "missed" cases (e.g. job deleted unexpectedly, callback not received).
    """
    from .services.k8s_service import K8sService
    
    stats = {
        'checked': 0,
        'completed': 0,
        'failed': 0,
        'timeout': 0,
        'still_processing': 0,
        'errors': 0,
    }
    
    try:
        processing_tasks = AnalysisTask.objects.filter(
            status=STATUS_PROCESSING,
            job_id__isnull=False
        ).exclude(job_id='')
        
        if not processing_tasks.exists():
            logger.debug("No processing tasks to check")
            return stats
        
        k8s_service = K8sService()
        for task in processing_tasks:
            _sync_single_task(task, k8s_service, stats)
        
        logger.info(
            f"K8s job status sync completed: {stats['checked']} checked, "
            f"{stats['completed']} completed, {stats['failed']} failed, "
            f"{stats['timeout']} timeout, {stats['still_processing']} still processing"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Error in maintenance_sync_k8s_status: {e}", exc_info=True)
        stats['error'] = str(e)
        return stats


@shared_task
def sync_k8s_job_status():
    """
    Backward-compatible alias.
    Prefer `maintenance_sync_k8s_status`.
    """
    return maintenance_sync_k8s_status()


@shared_task
def check_and_trigger_next_analysis():
    """Event-driven trigger entrypoint used by callbacks and maintenance tasks."""
    return trigger_next_analysis_if_slot_available()


def _save_pod_logs_to_task(task, k8s_service, job_name):
    """Save pod logs to task error_details if not already present."""
    if 'pod_logs' in task.error_details:
        return
    
    try:
        pods = k8s_service.list_pods_for_job(job_name)
        if pods.items:
            pod = pods.items[0]
            logs = k8s_service.get_pod_logs(pod.metadata.name, tail_lines=500)
            if not task.error_details:
                task.error_details = {}
            task.error_details['pod_logs'] = logs
            task.save()
    except Exception as log_error:
        logger.warning(f"Could not retrieve logs for job {job_name} before cleanup: {log_error}")


def _cleanup_completed_task(task, k8s_service):
    """Cleanup K8s job for completed/failed/timeout tasks."""
    if not task.job_id:
        return
    
    job_name = task.job_id
    
    try:
        if task.status in [STATUS_FAILED, STATUS_TIMEOUT]:
            with transaction.atomic():
                task.refresh_from_db()
                _save_pod_logs_to_task(task, k8s_service, job_name)
        
        k8s_service.delete_job(job_name, propagation_policy="Background")
        logger.info(f"Deleted K8s job {job_name} for task {task.id}")
        
    except Exception as cleanup_error:
        logger.warning(f"Error during cleanup for task {task.id} (job {job_name}): {cleanup_error}")




@shared_task
def process_queued_tasks():
    """
    Legacy periodic job (Celery beat) kept as a fallback.
    Instead of re-queueing every 30s, we now attempt a single event-driven trigger.
    """
    return {
        'legacy': True,
        'trigger': trigger_next_analysis_if_slot_available(),
    }


@shared_task
def test_task():
    """
    Simple test task to verify Celery is working.
    
    Returns:
        str: Success message confirming Celery functionality
    """
    logger.info("✅ Celery is working!")
    return "Celery is working!"
