import os
import yaml

from dataclasses import dataclass


@dataclass
class Config:
    title = 'Blog'
    description = ''
    link = '/'
    home_link = '/'
    language = 'en-US'
    logo = '/img/icon.png'
    header = True
    content_dir = '.'
    categories = None

    basedir = os.path.abspath(os.path.dirname(__file__))
    templates_dir = os.path.join(basedir, 'templates')
    static_dir = os.path.join(basedir, 'static')
    default_css_dir = os.path.join(static_dir, 'css')
    default_js_dir = os.path.join(static_dir, 'js')
    default_fonts_dir = os.path.join(static_dir, 'fonts')
    default_img_dir = os.path.join(static_dir, 'img')


config = Config()


def init_config(content_dir='.', config_file='config.yaml'):
    cfg = {}
    config.content_dir = content_dir

    if os.path.isfile(config_file):
        with open(config_file, 'r') as f:
            cfg = yaml.safe_load(f)

    if cfg.get('title'):
        config.title = cfg['title']
    if cfg.get('description'):
        config.description = cfg['description']
    if cfg.get('link'):
        config.link = cfg['link']
    if cfg.get('home_link'):
        config.home_link = cfg['home_link']
    if cfg.get('logo') is not None:
        config.logo = cfg['logo']
    if cfg.get('language'):
        config.language = cfg['language']
    if cfg.get('header') is False:
        config.header = False

    config.categories = cfg.get('categories', [])


# vim:sw=4:ts=4:et:
