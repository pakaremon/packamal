"""
Service for managing analysis tasks.
Follows Single Responsibility Principle - handles task-related business logic.
"""
from typing import Optional, Dict, Any
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from ..models import AnalysisTask
from ..view_constants import (
    STATUS_RECEIVED,
    STATUS_QUEUED,
    STATUS_PROCESSING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    # Legacy status constants for backward compatibility
    STATUS_RUNNING,
    STATUS_PENDING,
    STATUS_SUBMITTED,
    ACTIVE_TASK_WINDOW_HOURS,
    RACE_CONDITION_CHECK_MINUTES,
)


class TaskService:
    """Service for analysis task operations."""

    @staticmethod
    def find_completed_task_by_purl(purl: str) -> Optional[AnalysisTask]:
        """Find the most recent completed task for a given PURL."""
        return AnalysisTask.objects.filter(
            purl=purl,
            status=STATUS_COMPLETED,
        ).order_by('-completed_at').first()

    @staticmethod
    def find_active_tasks_by_purl(purl: str):
        """Find active tasks (processing, queued, received) for a PURL within time window."""
        time_threshold = timezone.now() - timezone.timedelta(hours=ACTIVE_TASK_WINDOW_HOURS)
        return AnalysisTask.objects.filter(
            purl=purl,
            status__in=[STATUS_PROCESSING, STATUS_QUEUED, STATUS_RECEIVED],
            created_at__gte=time_threshold
        ).order_by('-created_at')

    @staticmethod
    def find_recent_task_by_purl(purl: str) -> Optional[AnalysisTask]:
        """Find most recent task created within race condition check window."""
        time_threshold = timezone.now() - timezone.timedelta(minutes=RACE_CONDITION_CHECK_MINUTES)
        return AnalysisTask.objects.filter(
            purl=purl,
            created_at__gte=time_threshold
        ).first()

    @staticmethod
    def create_task(
        api_key,
        purl: str,
        package_name: str,
        package_version: str,
        ecosystem: str,
        priority: int = 0
    ) -> AnalysisTask:
        """Create a new analysis task."""
        return AnalysisTask.objects.create(
            api_key=api_key,
            purl=purl,
            package_name=package_name,
            package_version=package_version,
            ecosystem=ecosystem,
            status=STATUS_RECEIVED,
            priority=priority,
        )

    @staticmethod
    def queue_task(task: AnalysisTask) -> None:
        """Mark task as queued."""
        task.status = STATUS_QUEUED
        task.save()

    @staticmethod
    def mark_task_as_queued(task: AnalysisTask) -> None:
        """Mark task as queued (alias for queue_task for consistency)."""
        TaskService.queue_task(task)

    @staticmethod
    def mark_task_as_failed(task: AnalysisTask, error_message: str, error_category: str = 'unknown') -> None:
        """Mark a task as failed with error information."""
        task.status = STATUS_FAILED
        task.error_message = error_message
        task.error_category = error_category
        task.completed_at = timezone.now()
        task.save()

    @staticmethod
    def can_update_task_status(task: AnalysisTask) -> bool:
        """Check if task status can be updated (must be processing)."""
        return task.status == STATUS_PROCESSING

    @staticmethod
    def get_all_queued_tasks():
        """Get all queued tasks ordered by priority and creation time."""
        return AnalysisTask.objects.filter(
            status=STATUS_QUEUED
        ).order_by('-priority', 'created_at')

    @staticmethod
    def get_all_running_tasks():
        """Get all processing tasks."""
        return AnalysisTask.objects.filter(status=STATUS_PROCESSING)

