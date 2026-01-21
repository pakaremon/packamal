import os
from django.conf import settings
from .execution_service import ExecutionService


class FileService:
    @staticmethod
    def get_analysis_volume_name():
        """Get the Docker volume name for analysis results."""
        return "pack-a-mal_prd_analysis_results"

    @staticmethod
    def handle_uploaded_file(file_path, package_name, package_version, ecosystem):
        """
        Prepare uploaded file path and forward to the analysis runner.
        The provided path should be a local filesystem path (temporary upload).
        """
        real_path = os.path.abspath(str(file_path))

        report = ExecutionService.run_packaml(
            package_name=package_name,
            package_version=package_version,
            ecosystem=ecosystem,
            local_path=real_path,
        )

        if os.path.exists(real_path):
            try:
                os.remove(real_path)
            except OSError:
                pass

        return report

