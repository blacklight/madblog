import os
import sys
import logging

from .cli import get_args
from .config import init_config

arg_delim_idx = [i for i, arg in enumerate(sys.argv) if arg == "madblog.uwsgi"][0]

opts, _ = get_args(sys.argv[arg_delim_idx + 1 :])
config_file = opts.config if opts.config else os.path.join(opts.dir, "config.yaml")
config = init_config(config_file=config_file, args=opts)

logging.basicConfig(
    level=logging.DEBUG if getattr(config, "debug", False) else logging.INFO,
    format="%(levelname)s: %(message)s",
)

from .app import app

# For gunicorn/uWSGI compatibility
application = app


def _start_monitor_once() -> None:
    if not getattr(config, "enable_webmentions", False):
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
    # Not running under uWSGI - ignore.
    pass


# vim:sw=4:ts=4:et:
