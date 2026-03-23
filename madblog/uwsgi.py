import os
import sys
import logging
import fcntl
import threading


def _apply_memory_optimizations():
    """
    Reduce per-process memory overhead.

    * Limit glibc per-thread malloc arenas (each reserves ~64 MB of
      address space).
    * Shrink the default thread stack from 8 MB to 2 MB — the daemon
      threads created by Madblog need very little stack space.
    """
    try:
        import ctypes
        import ctypes.util

        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        _M_ARENA_MAX = -8
        _libc.mallopt(_M_ARENA_MAX, 2)
    except Exception:
        pass

    os.environ.setdefault("MALLOC_ARENA_MAX", "2")
    threading.stack_size(2 * 1024 * 1024)


_apply_memory_optimizations()

from .config import init_config

# When running under gunicorn/uWSGI, sys.argv usually belongs to the process
# manager, not to madblog. Prefer environment variables for configuration.
env_blog_dir = os.environ.get("MADBLOG_CONTENT_DIR")
env_config_file = os.environ.get("MADBLOG_CONFIG")

opts = None
blog_dir = env_blog_dir
config_file = env_config_file

if not blog_dir or not config_file:
    # Under gunicorn/uWSGI, sys.argv contains the process manager's arguments.
    # --config in particular conflicts with gunicorn's own --config flag, so we
    # only inspect positional args (potential blog dir) from the raw argv, and
    # skip argparse entirely to avoid misinterpreting process-manager flags.
    for arg in reversed(sys.argv[1:]):
        if not arg.startswith("-") and os.path.isdir(arg):
            blog_dir = blog_dir or arg
            break

if not config_file:
    blog_dir = blog_dir or "."
    config_file = os.path.join(blog_dir, "config.yaml")

config = init_config(config_file=config_file, args=opts)

logging.basicConfig(
    level=logging.DEBUG if getattr(config, "debug", False) else logging.INFO,
    format="%(levelname)s: %(message)s",
)

from .state import ensure_state_directory

ensure_state_directory()

from .app import app

# For gunicorn/uWSGI compatibility
application = app

_monitor_lock_f = None
_monitor_started = False
lock_path = os.path.join(
    getattr(config, "content_dir", "."), ".madblog-content-monitor.lock"
)


def _start_monitor_once() -> None:
    """
    Acquire an exclusive file lock and start the content monitor.

    Only the first worker to acquire the lock actually starts the monitor;
    all other workers return immediately.  This is safe to call multiple
    times — subsequent calls are no-ops.
    """
    global _monitor_lock_f, _monitor_started

    if _monitor_started:
        return
    _monitor_started = True

    try:
        _monitor_lock_f = open(lock_path, "w")
        fcntl.flock(_monitor_lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        return

    try:
        app.start()
    except Exception:
        logging.getLogger(__name__).exception("Failed to start content monitor")


# Defer monitor startup so that threads (file watchers) are created *after*
# fork when using ``gunicorn --preload``.  Without this, the master process
# would start threads that silently die when workers are forked.

try:
    import uwsgi  # type: ignore

    @uwsgi.postfork
    def _uwsgi_postfork():
        # Only start the monitor in one worker to avoid duplicated watchers.
        if getattr(uwsgi, "worker_id", lambda: 0)() != 1:
            return
        _start_monitor_once()

except Exception:
    # Not running under uWSGI (e.g. gunicorn).  Start the monitor lazily
    # on the first HTTP request so that ``--preload`` works correctly.

    @app.before_request
    def _ensure_monitor_started():
        _start_monitor_once()


# vim:sw=4:ts=4:et:
