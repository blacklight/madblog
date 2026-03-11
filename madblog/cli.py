import argparse
import logging
import os
import sys
import threading


def get_args(args):
    """
    Parse command line arguments.
    """

    parser = argparse.ArgumentParser(
        description="""Serve a Markdown folder as a web blog.

The folder should have the following structure:

.
  -> config.yaml [recommended]
  -> markdown
    -> article-1.md
    -> article-2.md
    -> ...
  -> img [recommended]
    -> favicon.ico
    -> icon.png
    -> image-1.png
    -> image-2.png
    -> ...

""",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "dir",
        nargs="?",
        default=None,
        help="Base path for the blog (default: current directory)",
    )
    parser.add_argument(
        "--config",
        dest="config",
        default=None,
        required=False,
        help="Path to a configuration file (default: config.yaml in the blog root directory)",
    )
    parser.add_argument(
        "--host",
        dest="host",
        required=False,
        default=None,
        help="Bind host/address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        dest="port",
        required=False,
        type=int,
        default=None,
        help="Bind port (default: 8000)",
    )
    parser.add_argument(
        "--debug",
        dest="debug",
        required=False,
        action="store_true",
        default=None,
        help="Enable debug mode (default: False)",
    )

    return parser.parse_known_args(args)


def _apply_memory_optimizations():
    """
    Limit glibc per-thread malloc arenas to reduce virtual memory
    overhead.  Each arena reserves ~64 MB of address space; the
    default (8 × number-of-cores) causes VmSize to balloon even
    though actual RSS stays small.  mallopt() works at runtime;
    the env-var is a fallback for any child processes.
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

    # Shrink the default thread stack from 8 MB to 2 MB.  The daemon
    # threads created by Madblog (content monitor, AP startup, etc.)
    # need very little stack space.
    threading.stack_size(2 * 1024 * 1024)


def run():
    """
    Run the application.
    """
    _apply_memory_optimizations()

    from .config import init_config

    opts, _ = get_args(sys.argv[1:])
    blog_dir = opts.dir or "."
    config_file = (
        opts.config
        or os.environ.get("MADBLOG_CONFIG")
        or os.path.join(blog_dir, "config.yaml")
    )
    config = init_config(config_file=config_file, args=opts)
    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    from .state import ensure_state_directory

    ensure_state_directory()

    from .app import app

    try:
        app.start()
        app.run(host=config.host, port=config.port, debug=config.debug)
    finally:
        app.stop()


# vim:sw=4:ts=4:et:
