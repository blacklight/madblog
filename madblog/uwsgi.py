import os
import sys

from .cli import get_args
from .config import init_config

arg_delim_idx = [
    i for i, arg in enumerate(sys.argv) if arg == 'madblog.uwsgi'
][0]

opts, _ = get_args(sys.argv[arg_delim_idx+1:])
config_file = os.path.join(opts.dir, 'config.yaml')
init_config(config_file=config_file, content_dir=opts.dir)

from .app import app

# For gunicorn/uWSGI compatibility
application = app


# vim:sw=4:ts=4:et:
