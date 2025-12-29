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
    STATUS_QUEUED,
    STATUS_COMPLETED,
    STATUS_RUNNING,
    STATUS_PENDING,
    STATUS_SUBMITTED,
    STATUS_FAILED,
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
            report__isnull=False
        ).order_by('-completed_at').first()

    @staticmethod
    def find_active_tasks_by_purl(purl: str):
        """Find active tasks (running, queued, pending) for a PURL within time window."""
        time_threshold = timezone.now() - timezone.timedelta(hours=ACTIVE_TASK_WINDOW_HOURS)
        return AnalysisTask.objects.filter(
            purl=purl,
            status__in=[STATUS_RUNNING, STATUS_QUEUED, STATUS_PENDING],
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
            status=STATUS_PENDING,
            priority=priority,
        )

    @staticmethod
    def queue_task(task: AnalysisTask) -> None:
        """Mark task as queued and calculate queue position."""
        with transaction.atomic():
            task.status = STATUS_QUEUED
            task.queued_at = timezone.now()
            queued_count = AnalysisTask.objects.filter(
                status=STATUS_QUEUED
            ).exclude(id=task.id).count()
            task.queue_position = queued_count + 1
            task.save()

    @staticmethod
    def calculate_queue_position(task: AnalysisTask) -> int:
        """Calculate queue position for a task."""
        queued_count = AnalysisTask.objects.filter(
            status=STATUS_QUEUED
        ).exclude(id=task.id).count()
        return queued_count + 1

    @staticmethod
    def get_queue_position_for_status(task: AnalysisTask) -> Optional[int]:
        """Get queue position based on task status."""
        if task.status == STATUS_QUEUED:
            return task.queue_position
        if task.status == STATUS_RUNNING:
            return 0
        return None

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
        """Check if task status can be updated (must be running or submitted)."""
        return task.status in [STATUS_RUNNING, STATUS_SUBMITTED]

    @staticmethod
    def get_all_queued_tasks():
        """Get all queued tasks ordered by position."""
        return AnalysisTask.objects.filter(
            status=STATUS_QUEUED
        ).order_by('queue_position')

    @staticmethod
    def get_all_running_tasks():
        """Get all running tasks."""
        return AnalysisTask.objects.filter(status=STATUS_RUNNING)

