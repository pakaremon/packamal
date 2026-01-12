import os
from celery import Celery
from kombu import Queue

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'packamal.settings')

app = Celery('packamal')

# Load config from Django settings with CELERY_ namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Configuration
app.conf.update(
    # Worker settings - Allow parallel processing with configurable concurrency
    worker_prefetch_multiplier=1,  # Process one task at a time per worker (prevents task hoarding)
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory cleanup)
    
    # Task acknowledgment
    task_acks_late=True,  # Acknowledge task only after completion
    task_reject_on_worker_lost=True,  # Re-queue if worker crashes
    
    # Connection loss behavior - Explicitly set to avoid deprecation warning
    # With task_acks_late=True, tasks are not acknowledged until completion, so they will be
    # automatically redelivered on connection loss. Setting to False ensures tasks continue
    # executing and get redelivered if needed rather than being cancelled.
    worker_cancel_long_running_tasks_on_connection_loss=False,
    
    # Broker connection settings - Retry and resilience for Redis connection issues
    broker_connection_retry_on_startup=True,  # Retry connection on startup
    broker_connection_retry=True,  # Enable automatic connection retry
    broker_connection_max_retries=10,  # Maximum retry attempts
    broker_connection_timeout=30,  # Connection timeout in seconds
    broker_pool_limit=10,  # Connection pool size
    
    # Time limits - Extended for long-running analysis tasks
    task_time_limit=1800,  # 30 minutes hard limit (matches timeout_minutes default)
    task_soft_time_limit=1740,  # 29 minutes soft limit (warning)
    
    # Result backend
    result_expires=3600,  # Results expire after 1 hour
    
    # Task routing - Analysis queue for parallel execution, maintenance for cleanup
    # NOTE: All maintenance tasks are routed to 'analysis' queue since celery-worker-2 is disabled
    # celery-worker listens to both 'analysis' and 'maintenance' queues to process these tasks
    # Parallel execution is controlled by MAX_CONCURRENT_JOBS environment variable
    task_routes={
        'package_analysis.tasks.run_dynamic_analysis': {'queue': 'analysis'},
        'package_analysis.tasks.maintenance_sync_k8s_status': {'queue': 'analysis'},  # Safety net / missed callbacks
        'package_analysis.tasks.sync_k8s_job_status': {'queue': 'analysis'},  # Backward-compatible alias
        'package_analysis.tasks.check_and_trigger_next_analysis': {'queue': 'analysis'},  # Event-driven trigger
        'package_analysis.tasks.process_queued_tasks': {'queue': 'analysis'},  # Legacy fallback trigger
    },
    
    # Queue definitions with priority support
    task_queues=(
        Queue('analysis', routing_key='analysis', queue_arguments={'x-max-priority': 10}),
        Queue('maintenance', routing_key='maintenance'),
        Queue('celery', routing_key='celery'),  # Default queue
    ),
    
    # Priority support (0-10, higher = more priority)
    task_default_priority=0,
    task_inherit_parent_priority=True,
    
    # Task serialization
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Beat schedule for periodic tasks
    beat_schedule={
        'maintenance-sync-k8s-status': {
            'task': 'package_analysis.tasks.maintenance_sync_k8s_status',
            'schedule': 60.0,  # Every 60 seconds - safety net for missed edge cases
        },
        'process-queued-tasks': {
            'task': 'package_analysis.tasks.process_queued_tasks',
            'schedule': 30.0,  # Every 30 seconds - legacy fallback trigger (should be mostly idle now)
        }
    },
)

@app.task(bind=True)
def debug_task(self):
    """Debug task to test Celery is working"""
    print(f'Request: {self.request!r}')
