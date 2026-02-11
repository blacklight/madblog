import os
import sys
import logging
import fcntl

from .cli import get_args
from .config import init_config

# When running under gunicorn/uWSGI, sys.argv usually belongs to the process
# manager, not to madblog. Prefer environment variables for configuration.
env_blog_dir = os.environ.get("MADBLOG_CONTENT_DIR")
env_config_file = os.environ.get("MADBLOG_CONFIG")

opts = None
blog_dir = env_blog_dir
config_file = env_config_file

if not blog_dir and not config_file:
    try:
        parsed, _ = get_args(sys.argv[1:])
        # Only trust the positional dir if it's a real directory.
        if parsed.dir and os.path.isdir(parsed.dir):
            opts = parsed
            blog_dir = parsed.dir

        # Only trust the config path if it points to an actual file.
        if parsed.config and os.path.isfile(os.path.expanduser(parsed.config)):
            opts = parsed
            config_file = os.path.expanduser(parsed.config)
    except Exception:
        pass

if not config_file:
    blog_dir = blog_dir or "."
    config_file = os.path.join(blog_dir, "config.yaml")

config = init_config(config_file=config_file, args=opts)

logging.basicConfig(
    level=logging.DEBUG if getattr(config, "debug", False) else logging.INFO,
    format="%(levelname)s: %(message)s",
)

from .app import app

# For gunicorn/uWSGI compatibility
application = app

_monitor_lock_f = None


def _start_monitor_once() -> None:
    if not getattr(config, "enable_webmentions", False):
        return

    global _monitor_lock_f

    lock_path = os.path.join(
        getattr(config, "content_dir", "."), ".madblog-webmentions-monitor.lock"
    )
    try:
        _monitor_lock_f = open(lock_path, "w")
        fcntl.flock(_monitor_lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        return

    try:
        app.start()
        logging.getLogger(__name__).info("Started webmentions filesystem monitor")
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed to start webmentions filesystem monitor"
        )


try:
    import uwsgi  # type: ignore

    @uwsgi.postfork
    def _uwsgi_postfork():
        # Only start the monitor in one worker to avoid duplicated watchers.
        # (If you want one monitor per worker, remove this guard.)
        if getattr(uwsgi, "worker_id", lambda: 0)() != 1:
            return
        _start_monitor_once()

except Exception:
    # Not running under uWSGI - start when imported (e.g. gunicorn workers).
    _start_monitor_once()


# vim:sw=4:ts=4:et:
