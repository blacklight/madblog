"""
State directory management for Madblog.

Provides utilities for managing the state directory and migrating
from legacy directory layouts.
"""

from ._state import ensure_state_directory

__all__ = ["ensure_state_directory"]
