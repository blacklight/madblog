"""
Generic filesystem monitor that watches a directory for changes to
content files and dispatches events to registered callbacks.

Consumer-agnostic: any number of listeners can subscribe via
:meth:`ContentMonitor.register`.
"""

import logging
import os
import queue
import threading
import time
from enum import Enum
from typing import Callable, List

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """
    Enumeration of file change types.
    """

    ADDED = "created"
    EDITED = "modified"
    DELETED = "deleted"


# Callback signature: (change_type: ChangeType, filepath: str) -> None
OnContentChange = Callable[[ChangeType, str], None]


class ContentMonitor:
    """
    Watches *root_dir* for changes to files matching *extensions* and
    dispatches ``(ChangeType, filepath)`` events to every registered
    callback.

    :param root_dir: Directory tree to watch.
    :param extensions: Tuple of file extensions (with leading dot) to
        monitor.  Default: Markdown files.
    :param throttle_seconds: Minimum quiet-time per path before an
        event is dispatched, to debounce rapid writes.
    """

    def __init__(
        self,
        root_dir: str,
        *,
        extensions: tuple[str, ...] = (".md", ".markdown"),
        throttle_seconds: float = 10.0,
    ):
        self._root_dir = os.path.abspath(root_dir)
        self._extensions = tuple(e.lower() for e in extensions)
        self._throttle_seconds = throttle_seconds

        self._callbacks: List[OnContentChange] = []
        self._observer: Observer | None = None
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._stop_event = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._pending: set[str] = set()
        self._last_event_at: dict[str, float] = {}
        self._last_event_type: dict[str, str] = {}
        self._last_processed_at: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, callback: OnContentChange) -> None:
        """Add a listener that will be called on every content change."""
        with self._lock:
            self._callbacks.append(callback)

    def start(self) -> None:
        """Start the watchdog observer and the dispatch loop."""
        if self._observer is not None:
            return

        if not os.path.isdir(self._root_dir):
            return

        monitor = self  # capture for inner class

        class _Handler(FileSystemEventHandler):
            def __init__(self, enqueue: Callable[[str, str], None]) -> None:
                super().__init__()
                self._enqueue = enqueue

            def on_created(self, event):
                if not getattr(event, "is_directory", False):
                    self._enqueue("created", getattr(event, "src_path", ""))

            def on_modified(self, event):
                if not getattr(event, "is_directory", False):
                    self._enqueue("modified", getattr(event, "src_path", ""))

            def on_deleted(self, event):
                if not getattr(event, "is_directory", False):
                    self._enqueue("deleted", getattr(event, "src_path", ""))

            def on_moved(self, event):
                if not getattr(event, "is_directory", False):
                    self._enqueue("deleted", getattr(event, "src_path", ""))
                    self._enqueue("created", getattr(event, "dest_path", ""))

        self._stop_event.clear()
        self._observer = Observer()
        if not self._observer:
            raise RuntimeError("Failed to create watchdog observer")  # for mypy

        self._observer.daemon = True
        self._observer.schedule(
            _Handler(monitor._enqueue), self._root_dir, recursive=True
        )
        self._observer.start()

        self._loop_thread = threading.Thread(
            target=self._dispatch_loop,
            name="content-monitor-loop",
            daemon=True,
        )
        self._loop_thread.start()
        logger.info("Content monitor started on %s", self._root_dir)

    def stop(self) -> None:
        """Stop the observer and dispatch loop."""
        self._stop_event.set()

        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                pass
            self._observer = None

        self._loop_thread = None
        logger.info("Content monitor stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _enqueue(self, event_type: str, path: str) -> None:
        if not path:
            return
        abs_path = os.path.abspath(path)
        if not self._is_candidate(abs_path):
            return
        self._queue.put((event_type, abs_path))

    def _is_candidate(self, abs_path: str) -> bool:
        root = self._root_dir.rstrip(os.sep) + os.sep
        if not (abs_path.startswith(root) or abs_path == self._root_dir):
            return False
        _, ext = os.path.splitext(abs_path)
        return ext.lower() in self._extensions

    def _dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                event_type, path = self._queue.get(timeout=0.5)
            except queue.Empty:
                self._flush()
                continue

            now = time.monotonic()
            self._pending.add(path)
            self._last_event_at[path] = now
            self._last_event_type[path] = event_type
            self._flush()

    def _flush(self) -> None:
        if not self._pending:
            return

        now = time.monotonic()
        if now - self._last_processed_at < self._throttle_seconds:
            return

        ready = [
            p
            for p in list(self._pending)
            if now - self._last_event_at.get(p, now) >= self._throttle_seconds
        ]

        if not ready:
            return

        self._last_processed_at = now
        for p in ready:
            self._pending.discard(p)
            self._last_event_at.pop(p, None)
            raw_type = self._last_event_type.pop(p, "modified")

            if raw_type == "deleted":
                change = ChangeType.DELETED
            elif raw_type == "created":
                change = ChangeType.ADDED
            else:
                change = ChangeType.EDITED

            with self._lock:
                callbacks = list(self._callbacks)

            for cb in callbacks:
                try:
                    cb(change, p)
                except Exception:
                    logger.exception("Content monitor callback %s failed for %s", cb, p)
