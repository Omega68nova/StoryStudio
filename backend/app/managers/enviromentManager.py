"""Deprecated typo compatibility shim. Use environmentManager instead."""
from app.managers.environmentManager import EnvironmentManager, ResolvedEnvironment

__all__ = ["EnvironmentManager", "ResolvedEnvironment"]
