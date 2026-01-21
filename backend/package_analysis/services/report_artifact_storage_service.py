import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

try:
    from google.cloud import storage as gcs_storage
except Exception:  # pragma: no cover
    gcs_storage = None


@dataclass(frozen=True)
class ReportArtifactStorageConfig:
    """
    Storage-agnostic configuration for storing report artifacts.

    Today: can use a file:// bucket (local filesystem).
    Future: can be swapped to Azure Blob Storage without changing call sites.
    """

    bucket_url: str
    report_filename: str = "report.json"


class ReportArtifactStorageService:
    def __init__(self, config: Optional[ReportArtifactStorageConfig] = None):
        self._config = config or self._load_config()

    def is_enabled(self) -> bool:
        return bool(self._config and self._config.bucket_url)

    def save_report(self, task_id: int, report_payload: Dict[str, Any]) -> Optional[str]:
        if not self.is_enabled():
            return None
        return self._save_to_bucket(str(task_id), report_payload)

    def load_report(self, report_location: str) -> Dict[str, Any]:
        parsed = urlparse(report_location)
        if parsed.scheme in ("", "file"):
            path = parsed.path if parsed.scheme == "file" else report_location
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        if parsed.scheme == "gs":
            return self._load_from_gcs(parsed)
        raise ValueError(f"Unsupported report_location scheme: {parsed.scheme}")

    def _save_to_bucket(self, key_prefix: str, report_payload: Dict[str, Any]) -> str:
        bucket = self._config.bucket_url
        parsed = urlparse(bucket)
        if parsed.scheme == "gs":
            return self._save_to_gcs(parsed, key_prefix, report_payload)
        if parsed.scheme not in ("", "file"):
            raise ValueError(f"Unsupported bucket_url scheme: {parsed.scheme}")

        base_dir = parsed.path if parsed.scheme == "file" else bucket
        target_dir = os.path.join(base_dir, key_prefix)
        os.makedirs(target_dir, exist_ok=True)

        target_path = os.path.join(target_dir, self._config.report_filename)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(report_payload, f, ensure_ascii=False)

        return "file://" + target_path

    @staticmethod
    def _require_gcs():
        if gcs_storage is None:
            raise RuntimeError("google-cloud-storage is required for gs:// storage")
        return gcs_storage

    def _save_to_gcs(self, parsed_bucket, key_prefix: str, report_payload: Dict[str, Any]) -> str:
        gcs = self._require_gcs()
        bucket_name = parsed_bucket.netloc
        base_prefix = (parsed_bucket.path or "").lstrip("/").rstrip("/")
        object_prefix = "/".join([p for p in (base_prefix, key_prefix) if p])
        object_name = f"{object_prefix}/{self._config.report_filename}".lstrip("/")

        client = gcs.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(
            data=json.dumps(report_payload, ensure_ascii=False),
            content_type="application/json",
        )
        return f"gs://{bucket_name}/{object_name}"

    def _load_from_gcs(self, parsed_location) -> Dict[str, Any]:
        gcs = self._require_gcs()
        bucket_name = parsed_location.netloc
        object_name = (parsed_location.path or "").lstrip("/").rstrip("/")
        client = gcs.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        data = blob.download_as_text(encoding="utf-8")
        return json.loads(data)

    @staticmethod
    def _load_config() -> ReportArtifactStorageConfig:
        bucket_url = (os.environ.get("REPORT_ARTIFACTS_BUCKET_URL") or "").strip()
        return ReportArtifactStorageConfig(bucket_url=bucket_url)


