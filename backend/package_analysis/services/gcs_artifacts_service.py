"""
Service for managing GCS artifacts with deterministic paths.

Both backend and worker use the same path structure to ensure reliability.
If callback fails, maintenance tasks can reconstruct URLs from GCS.
"""
import os
from typing import Dict, List, Optional
from urllib.parse import quote


# Constants
DEFAULT_BUCKET_NAME = 'analysis-results'
GCS_PROTOCOL = 'gs://'
HTTPS_STORAGE_BASE = 'https://storage.googleapis.com'

# Phase 1: Single consolidated file at {task_id}/report.json
# Matches worker: internal/worker/save_data.go line 30
SINGLE_RESULT_FILENAME = 'report.json'  # Worker uploads to: {task_id}/report.json


class GCSArtifactsService:
    """Manages GCS artifact paths with deterministic structure."""
    
    def __init__(self, bucket_name: str = None):
        self.bucket_name = bucket_name or self._get_bucket_from_env()
    
    def get_bucket_path(self, task_id: int) -> str:
        """
        Returns deterministic bucket path: {prefix}/{task_id}/

        Matches worker's path structure.
        Worker uploads to: {bucket}/{prefix}/{task_id}/report.json
        """
        prefix = self._get_bucket_prefix_from_env()
        return f"{prefix}/{task_id}/"
    
    def get_single_result_url(self, task_id: int, use_public_url: bool = True) -> str:
        """
        Returns URL for single consolidated result file (Phase 1).

        Matches worker path: {bucket}/{prefix}/{task_id}/report.json
        Worker uploads to: gs://packamal-{PROJECT_ID}/dynamic-results/{task_id}/report.json
        """
        bucket_path = self.get_bucket_path(task_id)

        if use_public_url:
            return f"{HTTPS_STORAGE_BASE}/{self.bucket_name}/{bucket_path}{SINGLE_RESULT_FILENAME}"
        return f"{GCS_PROTOCOL}{self.bucket_name}/{bucket_path}{SINGLE_RESULT_FILENAME}"
    
    def check_single_result_exists(self, task_id: int) -> bool:
        """Checks if single consolidated result file exists at {prefix}/{task_id}/report.json"""
        try:
            blob = self._get_single_result_blob(task_id)
            return blob.exists()
        except Exception as error:
            self._log_gcs_check_failure(error)
            return False
    
    def get_existing_artifacts(
        self,
        task_id: int,
        use_public_urls: bool = True
    ) -> Optional[str]:
        """
        Returns URLs for artifacts that exist in GCS.

        Phase 1: Checks for single {prefix}/{task_id}/report.json file
        Matches worker upload path: {bucket}/{prefix}/{task_id}/report.json

        Returns None if no artifacts found.
        """
        # Phase 1: Check single consolidated file at {prefix}/{task_id}/report.json
        if self.check_single_result_exists(task_id):
            single_url = self.get_single_result_url(task_id, use_public_urls)
            return single_url

        # Phase 2 would check multiple files (future)
        # For now, return None if single file not found
        return None
    
    # Private methods - Implementation details
    
    @staticmethod
    def _get_bucket_from_env() -> str:
        return os.environ.get('GCS_ANALYSIS_BUCKET', DEFAULT_BUCKET_NAME)

    @staticmethod
    def _get_bucket_prefix_from_env() -> str:
        """Returns bucket prefix for worker compatibility."""
        return os.environ.get('GCS_ANALYSIS_BUCKET_PREFIX', 'dynamic-results')
    
    def _get_single_result_blob(self, task_id: int):
        """Returns GCS blob object for single result file at {prefix}/{task_id}/report.json"""
        from google.cloud import storage
        
        client = storage.Client()
        bucket = client.bucket(self.bucket_name)
        bucket_path = self.get_bucket_path(task_id)
        blob_name = f"{bucket_path}{SINGLE_RESULT_FILENAME}"
        
        return bucket.blob(blob_name)
    
    @staticmethod
    def _log_gcs_check_failure(error: Exception):
        """Logs GCS check failure."""
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to check if artifact exists in GCS: {error}")
