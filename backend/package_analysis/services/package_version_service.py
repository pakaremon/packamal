"""
Service for fetching package versions from various registries.
Follows Single Responsibility Principle - handles package version lookups.
"""
import requests
from typing import List, Optional
from django.http import HttpRequest


class PackageVersionService:
    """Service for fetching package versions from registries."""

    @staticmethod
    def get_rubygems_versions(package_name: str) -> List[str]:
        """Get all versions for a RubyGems package."""
        url = f"https://rubygems.org/api/v1/versions/{package_name}.json"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return [version['number'] for version in data]
        return []

    @staticmethod
    def get_packagist_versions(package_name: str) -> List[str]:
        """Get all versions for a Packagist package."""
        url = f"https://repo.packagist.org/p2/{package_name}.json"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return [version['version'] for version in data['packages'].get(package_name, [])]
        return []

    @staticmethod
    def get_npm_versions(package_name: str) -> Optional[List[str]]:
        """Get all versions for an npm package."""
        url = f'https://registry.npmjs.org/{package_name}'
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return list(data.get('versions', {}).keys())
        return None

    @staticmethod
    def get_pypi_versions(package_name: str) -> List[str]:
        """Get all versions for a PyPI package."""
        url = f"https://pypi.org/pypi/{package_name}/json"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return list(data['releases'].keys())
        return []

    @staticmethod
    def get_versions_for_ecosystem(ecosystem: str, package_name: str) -> List[str]:
        """Get versions for a package in a specific ecosystem."""
        ecosystem_map = {
            'rubygems': PackageVersionService.get_rubygems_versions,
            'packagist': PackageVersionService.get_packagist_versions,
            'npm': PackageVersionService.get_npm_versions,
            'pypi': PackageVersionService.get_pypi_versions,
        }
        fetcher = ecosystem_map.get(ecosystem.lower())
        if not fetcher:
            return []
        result = fetcher(package_name)
        return result if result else []

