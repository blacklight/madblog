"""Shared file-based cache for rendered content (LaTeX, Mermaid, etc.)."""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Optional


class RenderCache:
    """
    A simple JSON-file-backed cache mapping content hashes to rendered output.

    Each instance uses its own subdirectory under the system temp dir.
    """

    def __init__(self, namespace: str):
        self.cache_dir = Path(tempfile.gettempdir()) / f"markdown-{namespace}"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / f"{namespace}.cache"
        self._data: dict[str, str] = {}
        self._load()

    def _load(self):
        try:
            self._data = json.loads(self.cache_file.read_text())
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def _save(self):
        self.cache_file.write_text(json.dumps(self._data))

    @staticmethod
    def hash(content: str, *extra: str) -> str:
        """SHA-1 hash of content + optional extra keys (e.g. theme)."""
        h = hashlib.sha1(content.encode())
        for e in extra:
            h.update(e.encode())
        return h.hexdigest()

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def put(self, key: str, value: str):
        self._data[key] = value
        self._save()

    @property
    def tmpdir(self) -> Path:
        return self.cache_dir
