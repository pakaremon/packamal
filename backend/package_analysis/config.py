"""
Execution configuration helper for determining runtime behavior.

This module centralizes all execution mode logic to avoid scattered conditionals
throughout the codebase. Use this instead of checking settings.DEBUG directly.
"""
from django.conf import settings


class ExecutionConfig:
    """
    Centralized configuration for execution modes.
    
    Modes:
    - 'local': Full local development mode (Docker volumes, local execution)
    - 'k8s': K8s testing mode (filesystem results, K8s execution)
    - 'production': Production mode (filesystem results, K8s execution)
    """
    
    MODE_LOCAL = 'local'
    MODE_K8S = 'k8s'
    MODE_PRODUCTION = 'production'
    
    @staticmethod
    def get_mode():
        """Get the current execution mode."""
        mode = getattr(settings, 'EXECUTION_MODE', ExecutionConfig.MODE_LOCAL)
        # Validate mode
        valid_modes = [ExecutionConfig.MODE_LOCAL, ExecutionConfig.MODE_K8S, ExecutionConfig.MODE_PRODUCTION]
        if mode not in valid_modes:
            raise ValueError(f"Invalid EXECUTION_MODE: {mode}. Must be one of {valid_modes}")
        return mode
    
    @staticmethod
    def is_local_mode():
        """Check if running in local development mode."""
        return ExecutionConfig.get_mode() == ExecutionConfig.MODE_LOCAL
    
    @staticmethod
    def is_k8s_mode():
        """Check if running in K8s mode (testing or production)."""
        mode = ExecutionConfig.get_mode()
        return mode in [ExecutionConfig.MODE_K8S, ExecutionConfig.MODE_PRODUCTION]
    
    @staticmethod
    def should_use_filesystem_results():
        """
        Determine if results should be read from filesystem (K8s PVC).
        Returns True for k8s and production modes, False for local mode.
        """
        return ExecutionConfig.is_k8s_mode()
    
    @staticmethod
    def should_use_k8s_execution():
        """
        Determine if analysis should run via K8s service.
        Returns True for k8s and production modes, False for local mode.
        """
        return ExecutionConfig.is_k8s_mode()
    
    @staticmethod
    def get_mode_description():
        """Get human-readable description of current mode."""
        mode = ExecutionConfig.get_mode()
        descriptions = {
            ExecutionConfig.MODE_LOCAL: "Local development (Docker volumes, local execution)",
            ExecutionConfig.MODE_K8S: "K8s testing (filesystem results, K8s execution)",
            ExecutionConfig.MODE_PRODUCTION: "Production (filesystem results, K8s execution)",
        }
        return descriptions.get(mode, f"Unknown mode: {mode}")

