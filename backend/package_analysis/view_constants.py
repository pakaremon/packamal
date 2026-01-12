"""
Constants used in views module.
Following Clean Code principle: Replace magic numbers with named constants.
"""

# Time constants
HOURS_IN_DAY = 24
MINUTES_IN_HOUR = 60
SECONDS_IN_MINUTE = 60
DEFAULT_TTL_HOURS = 24
RACE_CONDITION_CHECK_MINUTES = 1
ACTIVE_TASK_WINDOW_HOURS = 24

# Pagination constants
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_NUMBER = 1

# Task status values
STATUS_RECEIVED = 'received'
STATUS_QUEUED = 'queued'
STATUS_PROCESSING = 'processing'
STATUS_COMPLETED = 'completed'
STATUS_FAILED = 'failed'
STATUS_TIMEOUT = 'timeout'
# Legacy status values (for backward compatibility during migration)
STATUS_RUNNING = 'running'
STATUS_PENDING = 'pending'
STATUS_SUBMITTED = 'submitted'

# HTTP status codes
HTTP_STATUS_OK = 200
HTTP_STATUS_CREATED = 202
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_METHOD_NOT_ALLOWED = 405
HTTP_STATUS_INTERNAL_SERVER_ERROR = 500

# Report paths
REPORTS_PATH_TEMPLATE = "/reports/{ecosystem}/{package_name}/{version}.json"

# Error categories
ERROR_CATEGORY_RESULTS_NOT_FOUND = 'results_not_found'
ERROR_CATEGORY_QUEUE_ERROR = 'queue_error'
ERROR_CATEGORY_CALLBACK_ERROR = 'callback_error'
ERROR_CATEGORY_TIMEOUT_ERROR = 'timeout_error'
ERROR_CATEGORY_K8S_JOB_FAILED = 'k8s_job_failed'
ERROR_CATEGORY_K8S_JOB_NOT_FOUND = 'k8s_job_not_found'

# K8s job condition constants
K8S_CONDITION_TYPE_FAILED = 'Failed'
K8S_CONDITION_REASON_DEADLINE_EXCEEDED = 'DeadlineExceeded'
K8S_HTTP_NOT_FOUND = 404

# Environment constants
DEFAULT_RESULTS_VOLUME = "analysis_results"
DEFAULT_MOUNT_PATH = "/data/results"
CELERY_QUEUE_ANALYSIS = 'analysis'

# Ecosystem constants
ECOSYSTEM_PYPI = "pypi"

# File extensions
JSON_FILE_EXTENSION = ".json"

