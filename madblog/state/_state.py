"""
State directory management for Madblog.
"""

import logging
from pathlib import Path

from madblog.config import config

from ._migrations import migrate_legacy_state

logger = logging.getLogger(__name__)


def ensure_state_directory() -> Path:
    """
    Ensure the state directory exists and migrate legacy layout if needed.

    This should be called early in application initialization, after
    config is loaded but before any subsystem accesses state directories.

    Returns the resolved state directory path.
    """
    state_dir = config.resolved_state_dir
    content_dir = Path(config.content_dir).resolve()

    # Run migration if needed
    if migrate_legacy_state(content_dir, state_dir):
        logger.info("Legacy state migration completed")

    # Ensure state directory exists
    state_dir.mkdir(parents=True, exist_ok=True)

    return state_dir
