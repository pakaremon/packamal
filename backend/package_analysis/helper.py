import logging
import os
from typing import Optional
from django.conf import settings
from .src.utils import log_function_output

# Service layer imports
from .services.repository_service import RepositoryService
from .services.execution_service import ExecutionService
from .services.file_service import FileService
from .services.k8s_service import K8sService
# Configure helper logging
current_path = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(current_path, "logs", "helper.log")
# if os.path.exists(log_file):
#     try:
#         os.remove(log_file)
#     except Exception:
#         pass
os.makedirs(os.path.dirname(log_file), exist_ok=True)
logger = log_function_output(
    file_level=logging.DEBUG,
    console_level=logging.CRITICAL,
    log_filepath=log_file,
)


class Helper:
    """
    Facade maintained for backward compatibility.
    Delegates work to dedicated services under package_analysis.services.
    """

    # Repository lookups
    @staticmethod
    def get_latest_package_version(package_name, ecosystem):
        return RepositoryService.get_latest_package_version(package_name, ecosystem)

    @staticmethod
    def get_source_url(package_name, ecosystem):
        return RepositoryService.get_source_url(package_name, ecosystem)

    @staticmethod
    def get_pypi_packages():
        return RepositoryService.get_pypi_packages()

    @staticmethod
    def get_npm_packages():
        return RepositoryService.get_npm_packages()

    @staticmethod
    def get_rubygems_packages():
        return RepositoryService.get_rubygems_packages()

    @staticmethod
    def get_rust_packages():
        return RepositoryService.get_rust_packages()

    @staticmethod
    def get_wolfi_packages():
        return RepositoryService.get_wolfi_packages()

    @staticmethod
    def get_packagist_packages():
        return RepositoryService.get_packagist_packages()

    @staticmethod
    def get_maven_packages():
        return RepositoryService.get_maven_packages()

    # Analysis runners
    @staticmethod
    def run_packaml(
        package_name: str,
        package_version: str,
        ecosystem: str,
        task_id: str,
        local_path: Optional[str] = None,
    ):
        """
        Run package analysis using either local execution (DEBUG) or K8s service.
        
        Args:
            package_name: Name of the package to analyze.
            package_version: Version of the package.
            ecosystem: Package ecosystem.
            task_id: Task ID for tracking.
            local_path: Optional path to local package file.
        
        Returns:
            Analysis results dictionary.
        """
        if settings.DEBUG:
            return ExecutionService.run_packaml(
                package_name=package_name,
                package_version=package_version,
                ecosystem=ecosystem,
                task_id=task_id,
                local_path=local_path,
            )
        else:
            k8s_service = K8sService()
            return k8s_service.run_analysis(
                ecosystem=ecosystem,
                package_name=package_name,
                task_id=task_id,
                package_version=package_version,
            )
        
    @staticmethod
    def run_oss_find_source(package_name, package_version, ecosystem):
        return ExecutionService.run_oss_find_source(
            package_name, package_version, ecosystem
        )

    @staticmethod
    def run_oss_squats(package_name, package_version, ecosystem):
        return ExecutionService.run_oss_squats(package_name, package_version, ecosystem)

    @staticmethod
    def run_bandit4mal(package_name, package_version, ecosystem):
        return ExecutionService.run_bandit4mal(package_name, package_version, ecosystem)

    @staticmethod
    def run_lastpymile(package_name, package_version=None, ecosystem="pypi"):
        return ExecutionService.run_lastpymile(package_name, package_version, ecosystem)

    @staticmethod
    def run_py2src(package_name, package_version, ecosystem):
        return ExecutionService.run_py2src(package_name, package_version, ecosystem)

    # File handling helpers
    @staticmethod
    def find_root_path():
        return str(settings.BASE_DIR)

    @staticmethod
    def get_analysis_volume_name():
        return FileService.get_analysis_volume_name()

    @staticmethod
    def handle_uploaded_file(file_path, package_name, package_version, ecosystem):
        return FileService.handle_uploaded_file(
            file_path, package_name, package_version, ecosystem
        )

    @staticmethod
    def transfer_ecosystem(ecosystem):
        return ExecutionService.transfer_ecosystem(ecosystem)

