import argparse
import logging
import os
import sys
import threading

_SUBCOMMANDS = frozenset({"serve", "set-password"})


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared across subcommands."""
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


def get_args(args):
    """
    Parse command line arguments.

    Supports subcommands (``serve``, ``set-password``) while remaining
    backwards-compatible with the original ``madblog [dir]`` invocation.
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

    subparsers = parser.add_subparsers(dest="command")

    # --- serve ---
    serve_parser = subparsers.add_parser("serve", help="Run the blog server")
    _add_common_args(serve_parser)
    serve_parser.add_argument(
        "--host",
        dest="host",
        required=False,
        default=None,
        help="Bind host/address (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        dest="port",
        required=False,
        type=int,
        default=None,
        help="Bind port (default: 8000)",
    )
    serve_parser.add_argument(
        "--debug",
        dest="debug",
        required=False,
        action="store_true",
        default=None,
        help="Enable debug mode (default: False)",
    )

    # --- set-password ---
    pw_parser = subparsers.add_parser(
        "set-password", help="Set the password for a user"
    )
    _add_common_args(pw_parser)
    pw_parser.add_argument(
        "user",
        nargs="?",
        default=None,
        help="Username to set the password for (default: the default user)",
    )

    # Backwards compatibility: if the first arg is not a known subcommand,
    # treat the invocation as ``madblog serve [args...]``.
    if args and args[0] not in _SUBCOMMANDS and not args[0].startswith("-"):
        # Could be a directory path — prepend "serve"
        args = ["serve"] + list(args)
    elif not args or (args[0].startswith("-")):
        args = ["serve"] + list(args)

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


def _resolve_config(opts) -> str:
    blog_dir = opts.dir or "."
    return (
        opts.config
        or os.environ.get("MADBLOG_CONFIG")
        or os.path.join(blog_dir, "config.yaml")
    )


def _cmd_serve(opts):
    from .config import init_config

    config = init_config(config_file=_resolve_config(opts), args=opts)
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


def _cmd_set_password(opts):
    from getpass import getpass

    from .config import init_config

    config = init_config(config_file=_resolve_config(opts), args=opts)
    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    from .state import ensure_state_directory

    ensure_state_directory()

    from .auth._users import UserStore, validate_username

    default_username = (
        config.default_user or config.activitypub_username or "admin"
    )
    store = UserStore(config.auth_dir, default_username)
    username = opts.user or store.default_username

    try:
        username = validate_username(username)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    pw = os.environ.get("MADBLOG_AUTH_PASSWORD")
    if pw:
        print("Using password from MADBLOG_AUTH_PASSWORD environment variable.")
    else:
        pw = getpass("Password: ")
        confirm = getpass("Confirm: ")
        if pw != confirm:
            print("Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    if not pw:
        print("Error: password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    store.set_password(username, pw)
    print(f"Password set for user '{username}'.")


def run():
    """
    Run the application.
    """
    _apply_memory_optimizations()

    opts, _ = get_args(sys.argv[1:])
    command = getattr(opts, "command", None) or "serve"

    if command == "set-password":
        _cmd_set_password(opts)
    else:
        _cmd_serve(opts)


# vim:sw=4:ts=4:et:
