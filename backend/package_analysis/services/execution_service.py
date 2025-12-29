import os
import json
import logging
import subprocess
import shutil
import tempfile
from typing import Optional
from collections import Counter
from django.conf import settings
from ..src.internal.pkgmanager.package import pkg
from ..src.lastpymile.lastpymile.utils import Utils
from ..report_generator import Report

logger = logging.getLogger(__name__)


class ExecutionService:
    @staticmethod
    def transfer_ecosystem(ecosystem):
        mapping = {
            "crates.io": "cargo",
            "pypi": "pypi",
            "npm": "npm",
            "rubygems": "gem",
            "packagist": "composer",
            "maven": "maven",
        }
        return mapping.get(ecosystem, ecosystem)

    @staticmethod
    def get_analysis_volume_name():
        return "pack-a-mal_prd_analysis_results"

    @staticmethod
    def _get_environment_variables():
        """
        Retrieve environment variables for analysis execution.
        
        Returns:
            tuple: (internal_api_token, api_url)
        """
        return (
            os.getenv("INTERNAL_API_TOKEN"),
            os.getenv("API_URL"),
        )

    @staticmethod
    def run_packaml(
        package_name: str,
        package_version: str,
        ecosystem: str,
        task_id: Optional[str] = None,
        local_path: Optional[str] = None,
    ) -> dict:
        """
        Execute package analysis using the local analysis runner.
        
        This method runs analysis in DEBUG mode using the local Docker-based
        analysis runner instead of submitting to K8s.
        
        Args:
            package_name: Name of the package to analyze.
            package_version: Version of the package.
            ecosystem: Package ecosystem (e.g., "pypi", "npm").
            task_id: Task ID for tracking the analysis.
            local_path: Optional path to local package file.
        
        Returns:
            Dictionary containing:
                - packages: Package metadata
                - time: Analysis duration in seconds
                - job_id: Job ID if applicable (None for local execution)
                - report: Generated analysis report
        
        Raises:
            Exception: If analysis fails or times out.
        """
        logger.info(
            "Executing local package analysis: %s@%s [%s]",
            package_name,
            package_version,
            ecosystem,
        )

        internal_api_token, api_url = ExecutionService._get_environment_variables()

        try:
            from ..analysis_runner import run_packaml as runner_run_analysis
            
            result = runner_run_analysis(
                package_name=package_name,
                package_version=package_version,
                ecosystem=ecosystem,
                local_path=local_path,
                mode="dynamic",
                analysis_image=None,  # Use default image from runner
                stream_output=True,
                logger_instance=logger,
                task_id=task_id,
                internal_api_token=internal_api_token,
                api_url=api_url,
            )
            


            # try:
            #     reports = Report.generate_report(json_data)
            # except Exception as e:
            #     logger.warning(
            #         "Could not generate structured report for %s@%s: %s",
            #         package_name,
            #         package_version,
            #         e
            #     )
            #     reports = json_data

            return {
                "packages": {
                    "package_name": package_name,
                    "package_version": package_version,
                    "ecosystem": ecosystem,
                },
                "report": result,
            }

        except TimeoutError as e:
            error_msg = f"Analysis timed out for {package_name}@{package_version}"
            logger.error("%s: %s", error_msg, e)
            raise Exception(error_msg) from e
        except Exception as e:
            logger.exception(
                "Failed to analyze package %s@%s [%s]",
                package_name,
                package_version,
                ecosystem
            )
            raise

    # --- Auxiliary Analysis Tools (Docker/Subprocess) ---

    @staticmethod
    def run_oss_find_source(
        package_name: str,
        package_version: str,
        ecosystem: str,
    ) -> list:
        ecosystem_norm = ExecutionService.transfer_ecosystem(ecosystem)
        folder_path = os.path.join(settings.ANALYSIS_RESULTS_DIR, "oss-find-source")
        file_save_name = f"{package_name}.sarif"
        dst = os.path.join(folder_path, file_save_name)
        os.makedirs(folder_path, exist_ok=True)

        volume_name = ExecutionService.get_analysis_volume_name()
        command = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume_name}:/tmp/analysis-results",
            "pakaremon/ossgadget:latest",
            "bash",
            "-c",
            f'"mkdir -p /tmp/analysis-results/oss-find-source && /usr/share/dotnet/dotnet /app/src/oss-find-source/bin/Release/net8.0/oss-find-source.dll pkg:{ecosystem_norm}/{package_name} --format sarifv2 -o /tmp/analysis-results/oss-find-source/{file_save_name}"',
        ]

        try:
            subprocess.run(
                " ".join(command),
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )

            url_sources = []
            if os.path.exists(dst):
                try:
                    with open(dst, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for candidate in data["runs"][0]["results"]:
                            if candidate:
                                msg = candidate.get("message", {}).get("text")
                                if msg:
                                    url_sources.append(msg)
                except Exception:
                    pass

            return list(set(url_sources))
        except subprocess.CalledProcessError as e:
            logger.error("OSS Find Source failed: %s", e)
            raise

    @staticmethod
    def run_oss_squats(
        package_name: str,
        package_version: str,
        ecosystem: str,
    ) -> list:
        ecosystem_norm = ExecutionService.transfer_ecosystem(ecosystem)
        folder_path = os.path.join(settings.ANALYSIS_RESULTS_DIR, "oss-find-squats")
        file_save_name = f"{package_name}_{ecosystem_norm}.sarif"
        dst = os.path.join(folder_path, file_save_name)
        os.makedirs(folder_path, exist_ok=True)

        volume_name = ExecutionService.get_analysis_volume_name()
        command = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume_name}:/tmp/analysis-results",
            "pakaremon/ossgadget:latest",
            "bash",
            "-c",
            f'"mkdir -p /tmp/analysis-results/oss-find-squats && /usr/share/dotnet/dotnet /app/src/oss-find-squats/bin/Release/net8.0/oss-find-squats.dll pkg:{ecosystem_norm}/{package_name} --format sarifv2 -o /tmp/analysis-results/oss-find-squats/{file_save_name}"',
        ]

        try:
            subprocess.run(
                " ".join(command),
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )

            package_names = []
            if os.path.exists(dst):
                with open(dst, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for candidate in data["runs"][0]["results"]:
                        if candidate["message"]["text"].startswith(
                            "Potential Squat candidate"
                        ):
                            try:
                                name = (
                                    candidate["locations"][0]["physicalLocation"][
                                        "address"
                                    ]["name"]
                                    .split("/")[-1]
                                )
                                package_names.append(name)
                            except Exception:
                                pass
            return package_names
        except Exception as e:
            logger.error("Squats checking failed: %s", e)
            raise

    @staticmethod
    def run_bandit4mal(
        package_name: str,
        package_version: str,
        ecosystem: str,
    ) -> dict:
        if ecosystem.lower() != "pypi":
            return {"status": "skipped", "reason": "Bandit only supports pypi"}

        pkg_manager = pkg(package_name, package_version, ecosystem).manager
        download_directory = os.path.join(
            tempfile.gettempdir(), "bandit4mal_downloaded"
        )
        os.makedirs(download_directory, exist_ok=True)

        try:
            archive_path = pkg_manager.download_archive(
                package_name, package_version, download_directory
            )
            extract_directory = os.path.join(
                tempfile.gettempdir(),
                "bandit4mal_extracted",
                pkg_manager.get_base_filename(),
            )
            _, extracted_dir = pkg_manager.extract_archive(
                archive_path, output_dir=extract_directory
            )

            venv_bandit_path = shutil.which("bandit") or "/usr/local/bin/bandit"
            json_folder = os.path.join(
                tempfile.gettempdir(), "bandit4mal_json_results"
            )
            os.makedirs(json_folder, exist_ok=True)
            output_file = os.path.join(
                json_folder, f"{pkg_manager.get_base_filename()}.json"
            )

            command = [
                venv_bandit_path,
                "-r",
                extracted_dir,
                "-f",
                "json",
                "-o",
                output_file,
            ]
            result = subprocess.run(
                command, check=False, capture_output=True, text=True
            )

            if result.returncode not in [0, 1]:
                logger.error(
                    "Bandit failed unexpectedly with code %s: %s",
                    result.returncode,
                    result.stderr,
                )
                raise subprocess.CalledProcessError(
                    result.returncode,
                    command,
                    output=result.stdout,
                    stderr=result.stderr,
                )

            with open(output_file, "r", encoding="utf-8") as json_file:
                report = json.load(json_file)

            Utils.rmtree(extract_directory)
            Utils.rmtree(download_directory)
            return report
        except Exception as e:
            logger.error("Bandit failed: %s", e)
            raise

    @staticmethod
    def run_lastpymile(
        package_name: str,
        package_version: Optional[str] = None,
        ecosystem: str = "pypi",
    ) -> dict:
        supported = ["pypi", "npm"]
        if ecosystem.lower() not in supported:
            return {"status": "skipped", "reason": f"LastPyMile unsupported for {ecosystem}"}

        try:
            from ..src.lastpymile.app import LastPyMileApplication

            app = LastPyMileApplication()
            return app.analyze_package(
                package_name, package_version, ecosystem, print_output=False
            )
        except Exception as e:
            logger.error("LastPyMile failed: %s", e)
            return {"error": str(e)}

    @staticmethod
    def run_py2src(
        package_name: str,
        package_version: str,
        ecosystem: str,
    ) -> list:
        try:
            from ..src.py2src.py2src.url_finder import GetFinalURL

            url_data = GetFinalURL(package_name, ecosystem=ecosystem).get_final_url()
            return url_data
        except Exception as e:
            logger.error("Py2Src failed: %s", e)
            return []

