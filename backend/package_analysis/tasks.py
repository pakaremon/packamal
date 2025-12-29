"""
Celery tasks for package analysis.

This module provides background task processing for dynamic package analysis.
Tasks are executed via Celery workers with support for K8s job submission
and direct execution modes. The system ensures only one container runs at
a time and provides queue management, timeout handling, and result caching.

Migrated from QueueManager to use Celery for better scalability and monitoring.
"""

import logging
import traceback
from datetime import timedelta

from celery import shared_task
from celery.exceptions import Retry
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .container_manager import container_manager
from .helper import Helper
from .models import AnalysisTask, ReportDynamicAnalysis

logger = logging.getLogger(__name__)

# Constants
CACHE_TIMEOUT_DAYS = 7
CACHE_TIMEOUT_SECONDS = CACHE_TIMEOUT_DAYS * 24 * 60 * 60
RETRY_DELAY_SECONDS = 30
RETRY_BACKOFF_BASE_SECONDS = 60
CACHE_HIT_DURATION = 0.1
TASK_CLEANUP_DAYS = 7
CONTAINER_LOG_TAIL_LINES = 50


# Helper Functions

def _create_mock_request():
    """
    Creates a minimal request-like object for save_professional_report.
    
    Returns:
        MockRequest: Object with build_absolute_uri method that constructs
                     full URLs using BASE_URL setting.
    """
    class MockRequest:
        def build_absolute_uri(self, url):
            base_url = getattr(settings, 'BASE_URL', 'http://localhost:8000')
            return f"{base_url}{url}"
    return MockRequest()


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
        status='completed',
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
    task.status = 'completed'
    task.completed_at = timezone.now()
    task.report = existing_task.report
    task.download_url = existing_task.download_url
    task.queue_position = None
    task.save()


def _get_cache_key(task):
    """
    Generates cache key for analysis results.
    
    Parameters:
        task: AnalysisTask instance
    
    Returns:
        str: Cache key in format "analysis_{ecosystem}_{name}_{version}"
    """
    return (f"analysis_{task.ecosystem}_{task.package_name}_"
            f"{task.package_version}")


def _save_task_results(task, results, duration=None):
    """
    Saves analysis results to database and generates professional report.
    
    Parameters:
        task: AnalysisTask instance to update
        results: Dictionary containing analysis results
        duration: Optional duration in seconds
    
    Returns:
        str: Download URL for professional report if successful, None otherwise
    
    Errors:
        Logs warning and returns None if professional report save fails
    """
    from .views import save_report, save_professional_report
    
    save_report(results)
    latest_report = ReportDynamicAnalysis.objects.latest('id')
    
    try:
        mock_request = _create_mock_request()
        download_url, _ = save_professional_report(task, mock_request)
        
        with transaction.atomic():
            task.refresh_from_db()
            if task.status == 'running':
                task.status = 'completed'
                task.completed_at = timezone.now()
                if duration is not None:
                    task.duration_seconds = duration
                task.report = latest_report
                task.download_url = download_url
                task.save()
        
        return download_url
    except Exception as save_error:
        logger.warning(
            f"Failed to save professional report for task {task.id}: "
            f"{save_error}"
        )
        return None


def _check_and_prepare_task(task_id, celery_task):
    """
    Checks if task can run and prepares it for execution.
    
    Parameters:
        task_id: ID of AnalysisTask to check
        celery_task: Celery task instance for retry capability
    
    Returns:
        tuple: (task, early_return_dict)
               task: AnalysisTask instance if ready to run, None otherwise
               early_return_dict: Dict to return if task already completed,
                                 None otherwise
    
    Errors:
        Raises celery retry exception if another task is running
    """
    with transaction.atomic():
        task = AnalysisTask.objects.select_for_update().get(id=task_id)
        
        running_task = AnalysisTask.objects.filter(
            status='running'
        ).exclude(id=task_id).first()
        
        if running_task:
            logger.info(
                f"⏸️  Another task {running_task.id} is running. "
                f"Retrying task {task_id} in {RETRY_DELAY_SECONDS}s..."
            )
            raise celery_task.retry(
                countdown=RETRY_DELAY_SECONDS,
                exc=Exception("Another task is running")
            )
        
        if task.status == 'completed':
            logger.info(f"✅ Task {task_id} already completed, skipping")
            return (None, False, {
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
        
        task.status = 'running'
        task.started_at = timezone.now()
        task.queue_position = None
        task.last_heartbeat = timezone.now()
        task.save()
    
    return (task, None)


def _handle_cached_result(task, cache_key):
    """
    Handles case where analysis result is found in cache.
    
    Parameters:
        task: AnalysisTask instance
        cache_key: Cache key string
    
    Returns:
        dict: Success response dictionary
    """
    logger.info(
        f"✅ Using cached result for {task.package_name}@"
        f"{task.package_version}"
    )
    with transaction.atomic():
        task.refresh_from_db()
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.duration_seconds = CACHE_HIT_DURATION
        task.result = cache.get(cache_key)
        task.save()
    
    return {
        'status': 'success',
        'task_id': task.id,
        'cached': True
    }


def _handle_job_submission(task, job_id, task_id):
    """
    Handles K8s job submission case.
    
    Parameters:
        task: AnalysisTask instance
        job_id: K8s job ID string
        task_id: Task ID for logging
    
    Returns:
        dict: Submission response dictionary
    """
    with transaction.atomic():
        task.refresh_from_db()
        task.job_id = job_id
        task.status = "submitted"
        task.save()
    
    logger.info(f"✅ Task {task_id} submitted to K8s with job_id: {job_id}")
    return {
        'status': 'submitted',
        'task_id': task_id,
        'job_id': job_id,
        'message': 'Analysis job submitted. Results will be available '
                   'after completion.'
    }


def _handle_direct_execution_completion(task, results, start_time, cache_key):
    """
    Handles direct execution completion (DEBUG mode).
    
    Parameters:
        task: AnalysisTask instance
        results: Analysis results dictionary
        start_time: Start time for duration calculation
        cache_key: Cache key for storing results
    
    Returns:
        dict: Success response dictionary
    """
    with transaction.atomic():
        task.refresh_from_db()
        if task.status == 'running':
            task.last_heartbeat = timezone.now()
            task.save()
    
    end_time = timezone.now()
    duration = (end_time - start_time).total_seconds()
    
    cache.set(cache_key, results, timeout=CACHE_TIMEOUT_SECONDS)
    download_url = _save_task_results(task, results, duration)
    
    logger.info(f"✅ Task {task.id} completed in {duration:.2f}s")
    if download_url:
        logger.info(f"   Download URL: {download_url}")
    
    return {
        'status': 'success',
        'task_id': task.id,
        'duration': duration,
        'cached': False
    }


def _mark_task_failed(task_id, error):
    """
    Marks task as failed and saves error information.
    
    Parameters:
        task_id: ID of AnalysisTask
        error: Exception that caused failure
    
    Errors:
        Logs error if saving failure state fails
    """
    try:
        with transaction.atomic():
            task = AnalysisTask.objects.get(id=task_id)
            task.status = 'failed'
            task.completed_at = timezone.now()
            task.error_message = str(error)
            
            error_category = 'unknown_error'
            error_details = {}
            if hasattr(error, 'error_details'):
                error_details = error.error_details
                error_category = error_details.get(
                    'error_category',
                    'unknown_error'
                )
            
            task.error_category = error_category
            task.error_details = error_details
            task.queue_position = None
            task.save()
    except Exception as save_error:
        logger.error(f"Failed to save error state: {save_error}")


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def run_dynamic_analysis(self, task_id):
    """
    Background task for dynamic analysis with single-container execution.
    
    Ensures only one container runs at a time by checking for running tasks
    before processing. If another task is running, this task will be retried.
    Supports both K8s job submission (production) and direct execution
    (DEBUG mode).
    
    Parameters:
        self: Celery task instance (bind=True)
        task_id: ID of AnalysisTask model instance
    
    Returns:
        dict: Status dictionary with keys:
            - status: 'success', 'submitted', or 'failed'
            - task_id: Task ID
            - cached: Boolean indicating if result was cached
            - job_id: K8s job ID if submitted (optional)
            - duration: Duration in seconds (optional)
            - message: Status message (optional)
    
    Errors:
        Raises Retry exception if another task is running
        Raises exception if analysis fails permanently after max retries
    """
    logger.info(
        f"🚀 Worker {self.request.hostname} starting task {task_id}"
    )
    
    try:
        task, early_return = _check_and_prepare_task(task_id, self)
        if early_return:
            _process_next_queued_task()
            return early_return
        
        logger.info(
            f"📦 Analyzing {task.package_name}@{task.package_version} "
            f"({task.ecosystem})"
        )
        
        cache_key = _get_cache_key(task)
        cached_result = cache.get(cache_key)
        
        if cached_result:
            result = _handle_cached_result(task, cache_key)
            _process_next_queued_task()
            return result
        
        start_time = timezone.now()
        
        try:
            # when runpackamal is called, it will return the job ID, not results
            results = Helper.run_packaml(
                package_name=task.package_name,
                package_version=task.package_version,
                ecosystem=task.ecosystem,
                task_id=task_id # task ID analysis in database
            )
            
            if isinstance(results, str):
                result = _handle_job_submission(task, results, task_id)
                _process_next_queued_task()
                return result
            
            if isinstance(results, dict) and results.get("job_id"):
                result = _handle_job_submission(
                    task,
                    results.get("job_id"),
                    task_id
                )
                _process_next_queued_task()
                return result
            
            # result = _handle_direct_execution_completion(
            #     task,
            #     results,
            #     start_time,
            #     cache_key
            # )
            _process_next_queued_task()
            return None
            
        except Exception as analysis_error:
            logger.error(
                f"❌ Analysis failed for task {task_id}: "
                f"{str(analysis_error)}"
            )
            raise
        
    except Retry:
        raise
    except Exception as e:
        logger.error(f"❌ Task {task_id} failed: {str(e)}")
        logger.error(traceback.format_exc())
        
        _mark_task_failed(task_id, e)
        _process_next_queued_task()
        
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


def _process_next_queued_task():
    """
    Processes the next queued task in the analysis queue.
    
    Called after a task completes or fails to continue processing the queue.
    Checks for existing completed results before queuing new tasks. Tasks are
    selected by highest priority, then oldest queued_at time.
    
    Errors:
        Logs error if processing fails but does not raise exception
    """
    try:
        with transaction.atomic():
            if AnalysisTask.objects.filter(status='running').exists():
                return
            
            next_task = AnalysisTask.objects.filter(
                status='queued'
            ).order_by('-priority', 'queued_at').first()
            
            if not next_task:
                return
            
            existing_task = _reuse_existing_result(
                next_task,
                exclude_task_id=next_task.id
            )
            if existing_task:
                logger.info(
                    f"Task {next_task.id} already has completed result, "
                    f"marking as completed"
                )
                _mark_task_completed_from_existing(next_task, existing_task)
                _update_queue_positions()
                _process_next_queued_task()
                return
            
            logger.info(f"📤 Queuing next task {next_task.id} via Celery")
            run_dynamic_analysis.apply_async(
                args=[next_task.id],
                priority=next_task.priority,
                queue='analysis'
            )
                
    except Exception as e:
        logger.error(f"Error processing next queued task: {e}")


def _update_queue_positions():
    """
    Updates queue positions for all queued tasks.
    
    Assigns sequential position numbers based on priority (highest first)
    and queued_at time (oldest first).
    
    Errors:
        Logs error if update fails but does not raise exception
    """
    try:
        with transaction.atomic():
            queued_tasks = AnalysisTask.objects.filter(
                status='queued'
            ).order_by('-priority', 'queued_at')
            
            for index, task in enumerate(queued_tasks, 1):
                task.queue_position = index
                task.save()
    except Exception as e:
        logger.error(f"Error updating queue positions: {e}")


def _handle_timed_out_task(task):
    """
    Handles a single timed out task by stopping container and marking failed.
    
    Parameters:
        task: AnalysisTask instance that has timed out
    
    Errors:
        Logs warnings if container operations fail but continues processing
    """
    logger.warning(
        f"⏰ Task {task.id} has timed out after "
        f"{task.timeout_minutes} minutes"
    )
    
    container_stopped = None
    if task.container_id:
        logger.info(
            f"Stopping timed out container {task.container_id} "
            f"for task {task.id}"
        )
        container_stopped = container_manager.stop_container(
            task.container_id
        )
        
        if container_stopped:
            logger.info(
                f"Successfully stopped container {task.container_id}"
            )
        else:
            logger.warning(
                f"Failed to stop container {task.container_id}"
            )
        
        try:
            logs = container_manager.get_container_logs(
                task.container_id,
                tail=CONTAINER_LOG_TAIL_LINES
            )
            logger.info(
                f"Container {task.container_id} logs "
                f"(last {CONTAINER_LOG_TAIL_LINES} lines):\n{logs}"
            )
        except Exception as log_error:
            logger.warning(
                f"Could not retrieve logs for container "
                f"{task.container_id}: {log_error}"
            )
    
    task.status = 'failed'
    task.error_message = (
        f"Task timed out after {task.timeout_minutes} minutes"
    )
    task.error_category = 'timeout_error'
    task.error_details = {
        'timeout_minutes': task.timeout_minutes,
        'started_at': (
            task.started_at.isoformat()
            if task.started_at else None
        ),
        'timed_out_at': timezone.now().isoformat(),
        'container_id': task.container_id,
        'container_stopped': container_stopped
    }
    task.completed_at = timezone.now()
    task.queue_position = None
    task.save()


@shared_task
def check_timeouts():
    """
    Periodic task to check for timed out analysis tasks.
    
    Runs every 60 seconds via Celery Beat. Finds all running tasks that have
    exceeded their timeout and marks them as failed. Stops associated
    containers if they exist (legacy support).
    
    Returns:
        dict: Dictionary with keys:
            - timed_out_count: Number of tasks that timed out
            - checked_at: ISO timestamp of check
            - error: Error message if check failed (optional)
    """
    try:
        with transaction.atomic():
            timed_out_tasks = [
                task
                for task in AnalysisTask.objects.filter(status='running')
                if task.is_timed_out()
            ]
            
            if not timed_out_tasks:
                return {
                    'timed_out_count': 0,
                    'checked_at': timezone.now().isoformat()
                }
            
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


@shared_task
def cleanup_old_tasks():
    """
    Periodic task to clean up old completed/failed tasks.
    
    Runs every hour via Celery Beat. Deletes tasks older than
    TASK_CLEANUP_DAYS days that are in completed or failed status.
    
    Returns:
        dict: Dictionary with keys:
            - deleted_completed: Number of completed tasks deleted
            - deleted_failed: Number of failed tasks deleted
            - total: Total number of tasks deleted
    """
    cutoff_date = timezone.now() - timedelta(days=TASK_CLEANUP_DAYS)
    
    deleted_completed = AnalysisTask.objects.filter(
        status='completed',
        completed_at__lt=cutoff_date
    ).delete()[0]
    
    deleted_failed = AnalysisTask.objects.filter(
        status='failed',
        completed_at__lt=cutoff_date
    ).delete()[0]
    
    total_deleted = deleted_completed + deleted_failed
    
    logger.info(
        f"🧹 Cleaned up {total_deleted} old tasks "
        f"({deleted_completed} completed, {deleted_failed} failed)"
    )
    
    return {
        'deleted_completed': deleted_completed,
        'deleted_failed': deleted_failed,
        'total': total_deleted
    }


@shared_task
def reconcile_k8s_jobs():
    """
    Reconciliation loop to check K8s job status and fetch results.
    
    Runs every 5 minutes via Celery Beat. Checks status of submitted K8s
    jobs, fetches results from Redis when jobs complete, and updates
    AnalysisTask records accordingly.
    
    Returns:
        dict: Dictionary with keys:
            - checked: Number of tasks checked
            - completed: Number of tasks that completed
            - failed: Number of tasks that failed
            - still_running: Number of tasks still running
            - errors: Number of errors encountered
            - error: Error message if reconciliation failed (optional)
    """
    pass


def _handle_succeeded_job(task, status_result, client, stats):
    """
    Handles a successfully completed K8s job.
    
    Fetches results from Redis, saves reports, and marks task as completed.
    
    Parameters:
        task: AnalysisTask instance
        status_result: Dictionary with job status information
        client: Analysis client for fetching results
        stats: Dictionary to update with completion statistics
    
    Errors:
        Increments stats['errors'] and logs warning if result fetch fails
    """
    from .views import save_report
    
    try:
        result_data = client.get_job_result(task.job_id)
        
        if not result_data or not result_data.get("success"):
            logger.warning(
                f"No result data found for job {task.job_id}"
            )
            stats['errors'] += 1
            return
        
        result = result_data.get("result", {})
        report_data = result.get("report", {})
        
        with transaction.atomic():
            task.refresh_from_db()
            if task.status == 'submitted':
                task.status = 'running'
                task.started_at = (
                    status_result.get("started_at") or task.created_at
                )
                task.save()
        
        save_report({
            "packages": {
                "package_name": task.package_name,
                "package_version": task.package_version,
                "ecosystem": task.ecosystem,
            },
            "report": report_data,
        })
        
        latest_report = ReportDynamicAnalysis.objects.latest('id')
        
        duration = None
        if (status_result.get("started_at") and
                status_result.get("completed_at")):
            duration = (
                status_result["completed_at"] -
                status_result["started_at"]
            ).total_seconds()
        
        download_url = _save_task_results(task, {
            "packages": {
                "package_name": task.package_name,
                "package_version": task.package_version,
                "ecosystem": task.ecosystem,
            },
            "report": report_data,
        }, duration)
        
        with transaction.atomic():
            task.refresh_from_db()
            if task.status == 'running':
                task.status = 'completed'
                task.completed_at = (
                    status_result.get("completed_at") or timezone.now()
                )
                if (duration is not None and
                        hasattr(task, 'duration_seconds')):
                    task.duration_seconds = duration
                task.report = latest_report
                if download_url:
                    task.download_url = download_url
                task.save()
        
        logger.info(
            f"✅ Task {task.id} (job {task.job_id}) completed successfully"
        )
        stats['completed'] += 1
        
    except Exception as fetch_error:
        logger.error(
            f"Failed to fetch result for job {task.job_id}: {fetch_error}"
        )
        stats['errors'] += 1


def _handle_failed_job(task, status_result, stats):
    """
    Handles a failed K8s job by marking task as failed.
    
    Parameters:
        task: AnalysisTask instance
        status_result: Dictionary with job status information
        stats: Dictionary to update with failure statistics
    """
    with transaction.atomic():
        task.refresh_from_db()
        if task.status == 'submitted':
            task.status = 'failed'
            task.completed_at = (
                status_result.get("completed_at") or timezone.now()
            )
            task.error_message = status_result.get(
                "error",
                "Analysis job failed"
            )
            task.error_category = "k8s_job_failed"
            task.save()
    
    logger.info(f"❌ Task {task.id} (job {task.job_id}) failed")
    stats['failed'] += 1


def _handle_running_job(task, status_result, stats):
    """
    Handles a running or pending K8s job by updating task status.
    
    Parameters:
        task: AnalysisTask instance
        status_result: Dictionary with job status information
        stats: Dictionary to update with running statistics
    """
    if status_result.get("status") == "running":
        with transaction.atomic():
            task.refresh_from_db()
            if task.status == 'submitted':
                task.status = 'running'
                if status_result.get("started_at"):
                    task.started_at = status_result["started_at"]
                task.save()
    
    stats['running'] += 1
    


@shared_task
def test_task():
    """
    Simple test task to verify Celery is working.
    
    Returns:
        str: Success message confirming Celery functionality
    """
    logger.info("✅ Celery is working!")
    return "Celery is working!"
