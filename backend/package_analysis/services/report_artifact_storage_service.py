import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse


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
        raise ValueError(f"Unsupported report_location scheme: {parsed.scheme}")

    def _save_to_bucket(self, key_prefix: str, report_payload: Dict[str, Any]) -> str:
        bucket = self._config.bucket_url
        parsed = urlparse(bucket)
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
    def _load_config() -> ReportArtifactStorageConfig:
        bucket_url = (os.environ.get("REPORT_ARTIFACTS_BUCKET_URL") or "").strip()
        return ReportArtifactStorageConfig(bucket_url=bucket_url)


