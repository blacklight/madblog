import os

from .cli import get_args
from .config import init_config

opts, _ = get_args()
config_file = os.path.join(opts.dir, 'config.yaml')
init_config(config_file=config_file, content_dir=opts.dir)

from .app import app

# For gunicorn/uWSGI compatibility
application = app


# vim:sw=4:ts=4:et:
