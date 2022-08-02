import argparse
import os
import sys


def get_args(args):
    parser = argparse.ArgumentParser(description='''Serve a Markdown folder as a web blog.

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

''', formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('dir', nargs='?', default='.', help='Base path for the blog (default: current directory)')
    parser.add_argument('--config', dest='config', default='config.yaml', required=False, help='Path to a configuration file (default: config.yaml in the blog root directory)')
    parser.add_argument('--host', dest='host', required=False, default='0.0.0.0', help='Bind host/address')
    parser.add_argument('--port', dest='port', required=False, type=int, default=8000, help='Bind port (default: 8000)')
    parser.add_argument('--debug', dest='debug', required=False, action='store_true', default=False,
                        help='Enable debug mode (default: False)')

    return parser.parse_known_args(args)


def run():
    from .config import init_config
    opts, _ = get_args(sys.argv[1:])
    config_file = os.path.join(opts.dir, 'config.yaml')
    init_config(config_file=config_file, content_dir=opts.dir)

    from .app import app
    app.run(host=opts.host, port=opts.port, debug=opts.debug)


# vim:sw=4:ts=4:et:
