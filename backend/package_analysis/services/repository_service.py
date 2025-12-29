import requests
import os
import json
import csv
import git
from datetime import datetime
from collections import defaultdict
from functools import lru_cache
from bs4 import BeautifulSoup
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class RepositoryService:
    @staticmethod
    def get_latest_package_version(package_name, ecosystem):
        url = f"https://api.deps.dev/v3/systems/{ecosystem}/packages/{package_name}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                versions = data.get("versions", [])
                latest_version = None

                for version in versions:
                    ts = version.get("publishedAt")
                    if ts:
                        ts = ts.replace("Z", "+00:00")
                        current_date = datetime.fromisoformat(ts)

                        if latest_version is None:
                            latest_version = version
                        elif current_date > datetime.fromisoformat(
                            latest_version.get("publishedAt").replace("Z", "+00:00")
                        ):
                            latest_version = version

                if latest_version and "versionKey" in latest_version:
                    return latest_version["versionKey"]["version"]
        except Exception as e:
            logger.warning("Error fetching version for %s: %s", package_name, e)

        logger.warning("Failed to fetch data for package: %s", package_name)
        return None

    @staticmethod
    def get_source_url(package_name, ecosystem):
        """get source url of the package from deps.dev"""
        latest_version = RepositoryService.get_latest_package_version(
            package_name, ecosystem
        )
        if latest_version is None:
            return None

        url = (
            f"https://api.deps.dev/v3alpha/systems/{ecosystem}/packages/"
            f"{package_name}/versions/{latest_version}"
        )
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for link in data.get("links", []):
                    if link.get("label") == "SOURCE_REPO":
                        return link["url"]
        except Exception:
            pass
        return None

    @staticmethod
    @lru_cache(maxsize=1)
    def get_pypi_packages():
        pypi_packages_path = settings.RESOURCES_DIR / "pypi_package_names.csv"
        if os.path.exists(pypi_packages_path):
            try:
                with open(pypi_packages_path, "r", encoding="utf-8") as file:
                    reader = csv.reader(file)
                    next(reader, None)  # skip header
                    packages = [row[0] for row in reader if row]
                return {"packages": packages}
            except Exception as e:
                logger.error("Error reading pypi packages: %s", e)

        try:
            url = "https://pypi.org/simple/"
            response = requests.get(url, timeout=30)
            soup = BeautifulSoup(response.text, "html.parser")
            package_names = [a.text for a in soup.find_all("a")]

            os.makedirs(os.path.dirname(pypi_packages_path), exist_ok=True)
            with open(pypi_packages_path, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["Package Name"])
                for package in package_names:
                    writer.writerow([package])

            return {"packages": package_names}
        except Exception as e:
            logger.error("Failed to fetch PyPI packages: %s", e)
            return {"packages": []}

    @staticmethod
    @lru_cache(maxsize=1)
    def get_npm_packages():
        npm_packages_path = settings.RESOURCES_DIR / "npm_package_names.json"
        if os.path.exists(npm_packages_path):
            try:
                with open(npm_packages_path, "r", encoding="utf-8") as file:
                    packages = json.load(file)
                return {"packages": packages}
            except Exception:
                pass

        try:
            url = "https://github.com/nice-registry/all-the-package-names/raw/refs/heads/master/names.json"
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                os.makedirs(os.path.dirname(npm_packages_path), exist_ok=True)
                with open(npm_packages_path, "w", encoding="utf-8") as file:
                    json.dump(data, file)
                return {"packages": data}
        except Exception as e:
            logger.error("Failed to fetch NPM packages: %s", e)

        return {"packages": []}

    @staticmethod
    @lru_cache(maxsize=1)
    def get_rubygems_packages():
        rubygems_packages_path = settings.RESOURCES_DIR / "rubygems_package_names.csv"
        if os.path.exists(rubygems_packages_path):
            with open(rubygems_packages_path, "r", encoding="utf-8") as file:
                reader = csv.reader(file)
                next(reader, None)
                packages = [row[0] for row in reader if row]
            return {"packages": packages}

        try:
            url = "https://rubygems.org/names"
            response = requests.get(url, timeout=30)
            gem_names = response.text.splitlines()

            os.makedirs(os.path.dirname(rubygems_packages_path), exist_ok=True)
            with open(rubygems_packages_path, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["Package Name"])
                for gem in gem_names:
                    writer.writerow([gem])
            return {"packages": gem_names}
        except Exception as e:
            logger.error("Failed to fetch RubyGems: %s", e)
            return {"packages": []}

    @staticmethod
    @lru_cache(maxsize=1)
    def fetch_crates_package_list():
        root_path = settings.BASE_DIR
        # index_dir = os.path.join(root_path, "web", "crates.io-index")
        # create temp dir for crates.io-index
        import tempfile
        index_dir = tempfile.mkdtemp()
        os.makedirs(index_dir, exist_ok=True)

        if not os.path.exists(index_dir):
            try:
                git.Repo.clone_from(
                    "https://github.com/rust-lang/crates.io-index.git", index_dir
                )
            except Exception as e:
                logger.error("Failed to clone crates.io index: %s", e)
                return {}

        def get_all_crates(index_path):
            crates = defaultdict(list)
            for root, _, files in os.walk(index_path):
                if ".git" in root:
                    continue
                for file in files:
                    if file in ["README.md", "config.json"]:
                        continue
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            for line in f:
                                try:
                                    info = json.loads(line)
                                    crates[info["name"]].append(info["vers"])
                                except Exception:
                                    pass
                    except Exception:
                        pass
            return crates

        crates_list = get_all_crates(index_dir)
        return crates_list

    @staticmethod
    @lru_cache(maxsize=1)
    def get_rust_packages():
        rust_packages_path = settings.RESOURCES_DIR / "crates_packages.json"
        if os.path.exists(rust_packages_path):
            with open(rust_packages_path, "r", encoding="utf-8") as file:
                return json.load(file)

        packages = RepositoryService.fetch_crates_package_list()
        os.makedirs(os.path.dirname(rust_packages_path), exist_ok=True)
        with open(rust_packages_path, "w", encoding="utf-8") as file:
            json.dump(packages, file)
        return packages

    @staticmethod
    @lru_cache(maxsize=1)
    def get_packagist_packages():
        packagist_packages_path = settings.RESOURCES_DIR / "packagist_package_names.json"
        if os.path.exists(packagist_packages_path):
            with open(packagist_packages_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                return {"packages": data.get("packageNames", [])}

        try:
            url = "https://packagist.org/packages/list.json"
            response = requests.get(url, timeout=30)
            data = response.json()
            os.makedirs(os.path.dirname(packagist_packages_path), exist_ok=True)
            with open(packagist_packages_path, "w", encoding="utf-8") as file:
                json.dump(data, file)
            return {"packages": data.get("packageNames", [])}
        except Exception:
            return {"packages": []}

    @staticmethod
    def fetch_wolfi_package_list():
        urls = [
            "https://apk.dag.dev/https/packages.wolfi.dev/os/x86_64/APKINDEX.tar.gz/APKINDEX",
            "https://apk.dag.dev/https/packages.cgr.dev/os/x86_64/APKINDEX.tar.gz/APKINDEX",
            "https://apk.dag.dev/https/packages.cgr.dev/extras/x86_64/APKINDEX.tar.gz/APKINDEX",
        ]
        package_list = []
        for url in urls:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    package_list.extend(
                        map(lambda x: x.removesuffix(".apk"), response.text.splitlines())
                    )
            except Exception:
                pass
        return package_list

    @staticmethod
    @lru_cache(maxsize=1)
    def get_wolfi_packages():
        wolfi_packages_path = settings.RESOURCES_DIR / "wolfi_package_names.json"
        if os.path.exists(wolfi_packages_path):
            with open(wolfi_packages_path, "r", encoding="utf-8") as file:
                return {"packages": json.load(file)}

        package_list = RepositoryService.fetch_wolfi_package_list()
        os.makedirs(os.path.dirname(wolfi_packages_path), exist_ok=True)
        with open(wolfi_packages_path, "w", encoding="utf-8") as file:
            json.dump(package_list, file)
        return {"packages": package_list}

    @staticmethod
    @lru_cache(maxsize=1)
    def get_maven_packages():
        resources_dir = settings.RESOURCES_DIR / "maven_package_names"
        combined_data = {}
        if os.path.exists(resources_dir):
            for filename in os.listdir(resources_dir):
                if filename.endswith(".json"):
                    filepath = os.path.join(resources_dir, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            combined_data.update(json.load(f))
                    except Exception:
                        pass
        return combined_data

