"""
Mixin for mtime-based startup synchronisation.

Tracks ``{url: mtime}`` in a JSON file so that new or modified content
files discovered on restart can be forwarded to the appropriate handler.
"""

import json
import logging
import os

from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class StartupSyncMixin(ABC):  # pylint: disable=too-few-public-methods
    """
    Provides mtime-tracking helpers and a generic ``sync_on_startup``
    method.  Subclasses must set:

    * ``self._sync_cache_file``  – :class:`Path` to the JSON cache
    * ``self._sync_pages_dir``   – :class:`str` root of the markdown tree

    and implement:

    * ``_sync_file_to_url(filepath) -> str``
    * ``_sync_notify(filepath, is_new: bool) -> None``
    """

    _sync_cache_file: Path
    _sync_pages_dir: str

    @abstractmethod
    def _sync_file_to_url(self, filepath: str) -> str: ...

    @abstractmethod
    def _sync_notify(self, filepath: str, is_new: bool) -> None: ...

    # ------------------------------------------------------------------
    # Cache I/O
    # ------------------------------------------------------------------

    def _load_sync_cache(self) -> dict:
        """Load ``{url: mtime}`` map."""
        try:
            if self._sync_cache_file.exists():
                with open(self._sync_cache_file, "r") as f:
                    data = json.load(f)
                    stored = data.get("published", data)
                    # Migrate from old list/set format
                    if isinstance(stored, list):
                        return {url: 0 for url in stored}
                    return stored
        except Exception:
            logger.warning("Failed to load sync cache %s", self._sync_cache_file)
        return {}

    def _save_sync_cache(self, cache: dict) -> None:
        try:
            with open(self._sync_cache_file, "w") as f:
                json.dump({"published": cache}, f, indent=2)
        except Exception:
            logger.warning("Failed to save sync cache %s", self._sync_cache_file)

    def _sync_mark(self, url: str, mtime: float = 0) -> None:
        cache = self._load_sync_cache()
        cache[url] = mtime
        self._save_sync_cache(cache)

    def _sync_unmark(self, url: str) -> None:
        cache = self._load_sync_cache()
        cache.pop(url, None)
        self._save_sync_cache(cache)

    def _sync_is_tracked(self, url: str) -> bool:
        return url in self._load_sync_cache()

    def _sync_get_mtime(self, url: str) -> float:
        return self._load_sync_cache().get(url, 0)

    def _sync_reset(self) -> None:
        self._save_sync_cache({})
        logger.info("Reset sync cache %s", self._sync_cache_file)

    # ------------------------------------------------------------------
    # Startup scan
    # ------------------------------------------------------------------

    def _sync_directory(
        self,
        directory: str | Path,
        file_to_url,
        notify,
        *,
        label: str = "",
    ) -> None:
        """
        Walk *directory* for ``.md`` files and call *notify* for any whose
        mtime is newer than the cached value.

        :param directory: Root directory to scan.
        :param file_to_url: ``(filepath) -> url`` mapping.
        :param notify: ``(filepath, is_new: bool) -> None`` callback.
        :param label: Human-readable label for log messages.
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            return

        md_files = list(dir_path.rglob("*.md"))
        if not md_files:
            return

        tag = f" [{label}]" if label else ""
        cache = self._load_sync_cache()
        count = 0

        for md_file in md_files:
            filepath = str(md_file)

            try:
                url = file_to_url(filepath)
                current_mtime = os.path.getmtime(filepath)
            except OSError:
                continue

            stored_mtime = cache.get(url)

            if stored_mtime is None:
                logger.info("Startup sync%s: new file %s", tag, url)
                notify(filepath, is_new=True)
                count += 1
            elif current_mtime > stored_mtime:
                logger.info("Startup sync%s: modified file %s", tag, url)
                notify(filepath, is_new=False)
                count += 1

        if count:
            logger.info(
                "Startup sync%s: processed %d file(s)",
                tag,
                count,
            )
        else:
            logger.info("Startup sync%s: all files up to date", tag)

    def sync_on_startup(self) -> None:
        """
        Scan all ``.md`` files under the pages directory.  For each file
        whose mtime is newer than the stored value (or that has never been
        seen), call ``_sync_notify``.
        """
        self._sync_directory(
            self._sync_pages_dir,
            self._sync_file_to_url,
            self._sync_notify,
            label="pages",
        )
