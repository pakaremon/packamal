"""
Service for managing analysis reports.
Follows Single Responsibility Principle - handles report-related business logic.
"""
from typing import Tuple, Dict, Any, Optional
from datetime import datetime
import json
from django.http import HttpRequest
from django.conf import settings
from django.urls import reverse
from ..models import AnalysisTask, Package, ReportDynamicAnalysis
from ..redis_client import get_redis_client
from ..view_constants import DEFAULT_TTL_HOURS, HOURS_IN_DAY, SECONDS_IN_MINUTE


def normalize_package_name_for_storage(raw_name: str) -> str:
    """Normalize package name for storage keys and URLs."""
    return raw_name.replace('/', '_').replace('\\', '_')


class ReportService:
    """Service for report operations."""

    @staticmethod
    def build_redis_key(ecosystem: str, package_name: str, version: str) -> str:
        """Build Redis key for storing report."""
        safe_package = normalize_package_name_for_storage(package_name)
        return f"ecosystem:{ecosystem.lower()}:{safe_package}:{version}"

    @staticmethod
    def build_download_path(ecosystem: str, package_name: str, version: str) -> str:
        """Build download path for report."""
        safe_package = normalize_package_name_for_storage(package_name)
        return f"/reports/{ecosystem.lower()}/{safe_package}/{version}.json"

    @staticmethod
    def get_ttl_seconds() -> int:
        """Get TTL in seconds from settings or default."""
        return getattr(settings, "PROFESSIONAL_REPORT_TTL_SECONDS", DEFAULT_TTL_HOURS * HOURS_IN_DAY * SECONDS_IN_MINUTE)

    @staticmethod
    def extract_report_data_from_task(task: AnalysisTask) -> Dict[str, Any]:
        """Extract report data from task's report field."""
        report_data = task.report
        if hasattr(report_data, 'report'):
            return report_data.report
        return report_data

    @staticmethod
    def build_enhanced_report(task: AnalysisTask, report_json: Dict[str, Any]) -> Dict[str, Any]:
        """Build enhanced report with metadata."""
        now = datetime.now()
        return {
            "metadata": {
                "created_at": now.isoformat(),
                "package": {
                    "name": task.package_name,
                    "version": task.package_version,
                    "ecosystem": task.ecosystem,
                    "purl": task.purl,
                },
                "analysis": {
                    "status": "completed",
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "duration_seconds": task.report.time if hasattr(task.report, 'time') else None,
                },
                "api": {
                    "version": "1.0",
                    "endpoint": "analyze_api",
                    "generated_by": "Pack-a-mal Analysis Platform",
                },
            },
            "analysis_results": report_json,
        }

    @staticmethod
    def save_professional_report(task: AnalysisTask, request: HttpRequest) -> Tuple[str, Dict[str, Any]]:
        """Save analysis report to Redis and return download URL and metadata."""
        report_json = ReportService.extract_report_data_from_task(task)
        ecosystem = task.ecosystem.lower()
        package_name = normalize_package_name_for_storage(task.package_name)
        version = task.package_version
        now = datetime.now()

        redis_client = get_redis_client()
        redis_key = ReportService.build_redis_key(ecosystem, task.package_name, version)
        ttl_seconds = ReportService.get_ttl_seconds()

        existing_blob = redis_client.get(redis_key)
        if existing_blob:
            return ReportService._build_response_for_existing_report(
                existing_blob, redis_key, redis_client, ttl_seconds, ecosystem, package_name, version, request
            )

        enhanced_report = ReportService.build_enhanced_report(task, report_json)
        json_payload = json.dumps(enhanced_report, ensure_ascii=False)
        redis_client.setex(redis_key, ttl_seconds, json_payload)

        download_path = ReportService.build_download_path(ecosystem, task.package_name, version)
        download_url = request.build_absolute_uri(download_path)

        report_metadata = {
            "filename": f"{version}.json",
            "size_bytes": len(json_payload.encode("utf-8")),
            "created_at": now.isoformat(),
            "download_url": download_url,
            "folder_structure": f"reports/{ecosystem}/{package_name}/",
            "redis_key": redis_key,
            "expires_in_seconds": ttl_seconds,
        }

        return download_url, report_metadata

    @staticmethod
    def _build_response_for_existing_report(
        existing_blob: bytes,
        redis_key: str,
        redis_client,
        ttl_seconds: int,
        ecosystem: str,
        package_name: str,
        version: str,
        request: HttpRequest
    ) -> Tuple[str, Dict[str, Any]]:
        """Build response for existing cached report."""
        download_path = ReportService.build_download_path(ecosystem, package_name, version)
        download_url = request.build_absolute_uri(download_path)

        try:
            existing_json = json.loads(existing_blob)
            created_at = existing_json.get("metadata", {}).get("created_at")
        except Exception:
            created_at = None

        ttl_remaining = redis_client.ttl(redis_key)
        expires_in = ttl_remaining if ttl_remaining and ttl_remaining > 0 else ttl_seconds

        report_metadata = {
            "filename": f"{version}.json",
            "size_bytes": len(existing_blob),
            "created_at": created_at,
            "download_url": download_url,
            "folder_structure": f"reports/{ecosystem}/{package_name}/",
            "redis_key": redis_key,
            "expires_in_seconds": expires_in,
        }

        return download_url, report_metadata

    @staticmethod
    def get_report_from_redis(ecosystem: str, package_name: str, version: str) -> Optional[bytes]:
        """Retrieve report from Redis by key."""
        redis_client = get_redis_client()
        redis_key = ReportService.build_redis_key(ecosystem, package_name, version)
        return redis_client.get(redis_key)

    @staticmethod
    def save_report_to_database(report_data: Dict[str, Any]) -> ReportDynamicAnalysis:
        """Save report to database."""
        package, _ = Package.objects.get_or_create(
            package_name=report_data['packages']['package_name'],
            package_version=report_data['packages']['package_version'],
            ecosystem=report_data['packages']['ecosystem']
        )
        report, created = ReportDynamicAnalysis.objects.update_or_create(
            package=package,
            defaults={'report': report_data}
        )
        return report

