from .config import init_config

init_config()

from .app import app

# For gunicorn/uWSGI compatibility
application = app


# vim:sw=4:ts=4:et:
