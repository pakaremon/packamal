import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple
import re


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

        # In AKS, `analysis-results-pvc` is mounted at `/data/results` (see `prd/aks/.../05-backend.yaml`).
        # Keep MOUNT_PATH as an override for non-AKS environments.
        mount_path = (os.environ.get("MOUNT_PATH") or "/data/results").strip()
        base_dirs = (mount_path,)
        self._config = ResultStorageConfig(base_dirs=base_dirs)

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


