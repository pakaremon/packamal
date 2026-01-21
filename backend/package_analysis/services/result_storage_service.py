import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple
import re
from urllib.parse import urlparse
import logging

try:
    from google.cloud import storage as gcs_storage
except Exception:  # pragma: no cover
    gcs_storage = None


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultStorageConfig:
    """
    Storage-agnostic configuration for dynamic analysis results.

    Today: base_dirs point at PVC mounts on the backend container.
    Future: this config can be swapped to a Blob provider without changing views/tasks.
    """

    # Candidate directories where the PVC is mounted in the backend container.
    # We try them in order until we find a result file.
    base_dirs: Tuple[str, ...]

    # Deterministic filename under the task directory.
    report_filename: str = "report.json"

    # Optional remote bucket base URL for results, e.g.:
    # - gs://my-bucket/dynamic-results
    bucket_url: str = ""


class ResultStorageService:
    """
    Resolver for fetching raw dynamic analysis results by task_id/result_key.

    Current implementation reads from local filesystem (PVC mount).
    Future implementation can read from Azure Blob Storage by swapping provider logic
    while keeping the same interface.
    """

    def __init__(self, config: Optional[ResultStorageConfig] = None):
        if config is not None:
            self._config = config
            return

        bucket_url = (os.environ.get("RESULTS_BUCKET_URL") or "").strip()

        # Local fallback:
        # In AKS, `analysis-results-pvc` is mounted at `/data/results` (see `prd/aks/.../05-backend.yaml`).
        # Keep MOUNT_PATH as an override for non-AKS environments.
        mount_path = (os.environ.get("MOUNT_PATH") or "/data/results").strip()
        base_dirs = (mount_path,)
        self._config = ResultStorageConfig(base_dirs=base_dirs, bucket_url=bucket_url)

    @staticmethod
    def _normalize_result_key(result_key: str) -> str:
        """
        Contract: result_key is task_id, so it must be a simple integer string.
        This also prevents path traversal via separators like "../".
        """
        key = str(result_key).strip()
        if not re.fullmatch(r"\d+", key):
            raise ValueError("result_key must be a numeric task_id")
        return key

    def _candidate_paths(self, result_key: str) -> Iterable[str]:
        key = self._normalize_result_key(result_key)
        for base in self._config.base_dirs:
            yield os.path.join(base, key, self._config.report_filename)

    def get_result_content(self, result_key: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Fetch raw dynamic analysis JSON by deterministic key (currently task_id).

        Returns:
            (content, location)
            - content: parsed JSON dict, or None if not found
            - location: concrete filesystem path used, or None if not found
        """
        # Prefer remote bucket when configured.
        if self._config.bucket_url:
            parsed = urlparse(self._config.bucket_url)
            if parsed.scheme == "gs":
                return self._get_from_gcs(parsed, result_key)

        for p in self._candidate_paths(result_key):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f), p
            except FileNotFoundError:
                continue
            except json.JSONDecodeError:
                # File exists but is invalid; treat as missing content, but return the location for debugging.
                return None, p
            except Exception:
                continue

        # Not found anywhere.
        return None, None

    @staticmethod
    def _require_gcs():
        if gcs_storage is None:
            raise RuntimeError("google-cloud-storage is required for gs:// storage")
        return gcs_storage

    def _get_from_gcs(self, parsed_bucket, result_key: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        gcs = self._require_gcs()
        key = self._normalize_result_key(result_key)
        bucket_name = parsed_bucket.netloc
        base_prefix = (parsed_bucket.path or "").lstrip("/").rstrip("/")
        object_prefix = "/".join([p for p in (base_prefix, key) if p]).strip("/")

        # NOTE: Some writers (notably the Go worker via go-cloud blob) may upload objects
        # with a leading "/" in the object name when the configured bucket URL includes
        # a path like "gs://bucket/dynamic-results/" (i.e. bucketURL.Path starts with "/").
        #
        # Example object names:
        # - "dynamic-results/11/report.json"   (preferred)
        # - "/dynamic-results/11/report.json"  (legacy/buggy but seen in the wild)
        candidates = [
            f"{object_prefix}/{self._config.report_filename}".lstrip("/"),
            f"/{object_prefix}/{self._config.report_filename}".replace("//", "/"),
        ]

        client = gcs.Client()
        bucket = client.bucket(bucket_name)
        last_location: Optional[str] = None
        for object_name in candidates:
            location = f"gs://{bucket_name}/{object_name}"
            last_location = location
            blob = bucket.blob(object_name)
            try:
                data = blob.download_as_text(encoding="utf-8")
                return json.loads(data), location
            except Exception as e:
                # Keep trying other candidate keys; log at debug to avoid noisy logs.
                logger.debug("Failed to download/parse GCS result", extra={"location": location, "error": str(e)})
                continue

        return None, last_location


