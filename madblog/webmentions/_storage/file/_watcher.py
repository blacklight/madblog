import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..._model import ContentTextFormat

logger = logging.getLogger(__name__)


class ContentChangeType(str, Enum):
    """
    Content change types.
    """

    ADDED = "added"
    EDITED = "edited"
    DELETED = "deleted"


@dataclass(frozen=True)
class ContentChange:
    """
    Content change model.
    """

    change_type: ContentChangeType
    path: str
    text: str | None
    text_format: ContentTextFormat | None


class FilesystemContentWatcher:
    """
    Watches for changes to the content in the given root directory.
    """

    def __init__(
        self,
        root_dir: str,
        on_change: Callable[[ContentChange], None],
        *,
        extensions: tuple[str, ...] = (".md", ".markdown", ".txt", ".html", ".htm"),
    ):
        self.root_dir = root_dir
        self.on_change = on_change
        self.extensions = tuple(e.lower() for e in extensions)

        self._watch_observer = None
        self._watch_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._watch_stop_event = threading.Event()
        self._watch_thread: threading.Thread | None = None

        self._pending_paths: set[str] = set()
        self._last_event_at: dict[str, float] = {}
        self._debounce_seconds = 2.0
        self._min_process_interval_seconds = 2.0
        self._last_process_at = 0.0
        self._last_event_type: dict[str, str] = {}

    def start(self) -> None:
        if self._watch_observer is not None:
            return

        if not os.path.isdir(self.root_dir):
            return

        class _EventHandler(FileSystemEventHandler):
            def __init__(self, *_, enqueue_fs_event: Callable[..., None], **__):
                self._enqueue_fs_event = enqueue_fs_event

            def on_created(self, event):
                if getattr(event, "is_directory", False):
                    return
                self._enqueue_fs_event("created", getattr(event, "src_path", ""))

            def on_modified(self, event):
                if getattr(event, "is_directory", False):
                    return
                self._enqueue_fs_event("modified", getattr(event, "src_path", ""))

            def on_deleted(self, event):
                if getattr(event, "is_directory", False):
                    return
                self._enqueue_fs_event("deleted", getattr(event, "src_path", ""))

            def on_moved(self, event):
                if getattr(event, "is_directory", False):
                    return
                src = getattr(event, "src_path", "")
                dest = getattr(event, "dest_path", "")
                self._enqueue_fs_event("deleted", src)
                self._enqueue_fs_event("created", dest)

        self._watch_stop_event.clear()
        self._watch_observer = Observer()
        self._watch_observer.daemon = True
        self._watch_observer.schedule(
            _EventHandler(enqueue_fs_event=self._enqueue_fs_event),
            self.root_dir,
            recursive=True,
        )
        self._watch_observer.start()

        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            name="webmentions-watch-loop",
            daemon=True,
        )
        self._watch_thread.start()
        logger.info("Webmentions file watcher started on %s", self.root_dir)

    def stop(self) -> None:
        self._watch_stop_event.set()

        if self._watch_observer is not None:
            try:
                self._watch_observer.stop()
                self._watch_observer.join(timeout=5)
            except Exception:
                pass
            self._watch_observer = None

        self._watch_thread = None
        logger.info("Webmentions file watcher stopped")

    def _enqueue_fs_event(self, event_type: str, path: str) -> None:
        if not path:
            return

        abs_path = os.path.abspath(path)
        if not self._is_candidate_path(abs_path):
            return

        self._watch_queue.put((event_type, abs_path))

    def _is_candidate_path(self, abs_path: str) -> bool:
        try:
            root = os.path.abspath(self.root_dir)
            if not (
                abs_path.startswith(root.rstrip(os.sep) + os.sep) or abs_path == root
            ):
                return False
        except Exception:
            return False

        _, ext = os.path.splitext(abs_path)
        return ext.lower() in self.extensions

    def _watch_loop(self) -> None:
        while not self._watch_stop_event.is_set():
            try:
                event_type, path = self._watch_queue.get(timeout=0.5)
            except queue.Empty:
                self._flush_debounced()
                continue

            now = time.monotonic()
            self._pending_paths.add(path)
            self._last_event_at[path] = now
            self._last_event_type[path] = event_type
            self._flush_debounced()

    def _flush_debounced(self) -> None:
        if not self._pending_paths:
            return

        now = time.monotonic()
        if now - self._last_process_at < self._min_process_interval_seconds:
            return

        ready = [
            p
            for p in list(self._pending_paths)
            if now - self._last_event_at.get(p, now) >= self._debounce_seconds
        ]

        if not ready:
            return

        self._last_process_at = now
        for p in ready:
            self._pending_paths.discard(p)
            self._last_event_at.pop(p, None)
            event_type = self._last_event_type.pop(p, "")
            change = self._build_change(event_type, p)
            if change is None:
                continue
            try:
                self.on_change(change)
            except Exception as e:
                logger.info("Webmentions change handler failed for %s: %s", p, str(e))

    def _build_change(self, event_type: str, abs_path: str) -> ContentChange | None:
        if event_type == "deleted" or not os.path.isfile(abs_path):
            return ContentChange(
                change_type=ContentChangeType.DELETED,
                path=abs_path,
                text=None,
                text_format=None,
            )

        if event_type == "created":
            change_type = ContentChangeType.ADDED
        else:
            change_type = ContentChangeType.EDITED

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = None

        text_format = self._guess_text_format(abs_path)
        if not text_format:
            return None

        return ContentChange(
            change_type=change_type,
            path=abs_path,
            text=text,
            text_format=text_format,
        )

    @staticmethod
    def _guess_text_format(path: str) -> ContentTextFormat | None:
        _, ext = os.path.splitext(path.lower())
        if ext in (".html", ".htm"):
            return ContentTextFormat.HTML
        if ext in (".md", ".markdown"):
            return ContentTextFormat.MARKDOWN
        if ext in (".txt", ".text"):
            return ContentTextFormat.TEXT

        return None
