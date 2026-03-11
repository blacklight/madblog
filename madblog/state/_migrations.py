"""
Migration utilities for Madblog state directories.

Handles automatic detection and migration of legacy directory layouts.
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_legacy_layout(content_dir: Path, state_dir: Path) -> dict:
    """
    Detect legacy directory structure.

    Returns dict with keys for each legacy path that exists:
    - 'activitypub': Path to <content_dir>/activitypub
    - 'mentions': Path to <content_dir>/mentions
    """
    legacy = {}

    # Check for legacy activitypub/ at content root
    legacy_ap = content_dir / "activitypub"
    if legacy_ap.is_dir():
        # Verify it's pubby storage (has followers/, objects/, or private_key.pem)
        if any(
            (legacy_ap / sub).exists()
            for sub in ["followers", "objects", "private_key.pem"]
        ):
            # Don't migrate if new layout already exists
            new_ap_state = state_dir / "activitypub" / "state"
            if not new_ap_state.exists():
                legacy["activitypub"] = legacy_ap

    # Check for legacy mentions/ at content root
    legacy_mentions = content_dir / "mentions"
    if legacy_mentions.is_dir():
        # Verify it's webmentions storage (has incoming/ or outgoing/)
        if any((legacy_mentions / sub).exists() for sub in ["incoming", "outgoing"]):
            # Don't migrate if new layout already exists
            new_mentions = state_dir / "mentions"
            if not new_mentions.exists():
                legacy["mentions"] = legacy_mentions

    return legacy


def _move_directory_preserve_mtime(src: Path, dst: Path) -> None:
    """
    Move directory tree preserving file modification times.

    Uses shutil.move for atomic moves when possible, falls back to
    copy+delete for cross-filesystem moves.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Collect mtimes before move
    mtimes = {}
    for root, _, files in os.walk(src):
        for name in files:
            fpath = Path(root) / name
            try:
                mtimes[fpath.relative_to(src)] = os.stat(fpath).st_mtime
            except OSError:
                pass

    # Move the directory
    shutil.move(str(src), str(dst))

    # Restore mtimes (shutil.move may update them)
    for rel_path, mtime in mtimes.items():
        fpath = dst / rel_path
        if fpath.exists():
            try:
                os.utime(fpath, (mtime, mtime))
            except OSError:
                pass


def _migrate_activitypub_key(src_dir: Path, state_dir: Path) -> None:
    """
    Migrate ActivityPub private key from old location to new location.

    Old: <content_dir>/activitypub/private_key.pem
    New: <state_dir>/activitypub/private_key.pem
    """
    old_key = src_dir / "private_key.pem"
    if not old_key.exists():
        return

    new_key_dir = state_dir / "activitypub"
    new_key_dir.mkdir(parents=True, exist_ok=True)
    new_key = new_key_dir / "private_key.pem"

    if new_key.exists():
        logger.debug("ActivityPub key already exists at %s, skipping", new_key)
        return

    # Preserve mtime
    try:
        mtime = os.stat(old_key).st_mtime
    except OSError:
        mtime = None

    shutil.move(str(old_key), str(new_key))

    if mtime is not None:
        try:
            os.utime(new_key, (mtime, mtime))
        except OSError:
            pass

    logger.info("Migrated ActivityPub key: %s -> %s", old_key, new_key)


def migrate_legacy_state(content_dir: Path, state_dir: Path) -> bool:
    """
    Migrate legacy state directories to new layout.

    Preserves file mtimes to avoid reprocessing.

    Returns True if any migration was performed.
    """
    legacy = detect_legacy_layout(content_dir, state_dir)

    if not legacy:
        return False

    logger.info("Detected legacy state layout, migrating to %s", state_dir)

    migrated = False

    # Migrate activitypub/ -> state_dir/activitypub/state/
    if "activitypub" in legacy:
        src = legacy["activitypub"]

        # First extract private_key.pem to activitypub/ level
        _migrate_activitypub_key(src, state_dir)

        # Then move the rest to state/
        dst = state_dir / "activitypub" / "state"

        # Only move if source still has content (key may have been the only file)
        if src.exists() and any(src.iterdir()):
            _move_directory_preserve_mtime(src, dst)
            logger.info("Migrated %s -> %s", src, dst)
            migrated = True
        elif src.exists():
            # Remove empty directory
            src.rmdir()
            logger.info("Removed empty legacy directory: %s", src)

    # Migrate mentions/ -> state_dir/mentions/
    if "mentions" in legacy:
        src = legacy["mentions"]
        dst = state_dir / "mentions"
        _move_directory_preserve_mtime(src, dst)
        logger.info("Migrated %s -> %s", src, dst)
        migrated = True

    return migrated
