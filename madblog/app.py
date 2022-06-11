import datetime
import os
import re
from glob import glob
from typing import Optional

from flask import Flask, abort
from markdown import markdown

from .config import config
from .latex import MarkdownLatex


class BlogApp(Flask):
    _title_header_regex = re.compile(r'^#\s*((\[(.*)\])|(.*))')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, template_folder=config.templates_dir, **kwargs)
        self.pages_dir = os.path.join(config.content_dir, 'markdown')
        self.img_dir = config.default_img_dir
        self.css_dir = config.default_css_dir
        self.fonts_dir = config.default_fonts_dir

        if not os.path.isdir(self.pages_dir):
            # If the `markdown` subfolder does not exist, then the whole
            # `config.content_dir` is treated as the root for markdown files.
            self.pages_dir = os.path.join(config.content_dir)

        img_dir = os.path.join(config.content_dir, 'img')
        if os.path.isdir(img_dir):
            self.img_dir = os.path.abspath(img_dir)

        css_dir = os.path.join(config.content_dir, 'css')
        if os.path.isdir(css_dir):
            self.css_dir = os.path.abspath(css_dir)

        fonts_dir = os.path.join(config.content_dir, 'fonts')
        if os.path.isdir(fonts_dir):
            self.fonts_dir = os.path.abspath(fonts_dir)

        templates_dir = os.path.join(config.content_dir, 'templates')
        if os.path.isdir(templates_dir):
            self.template_folder = os.path.abspath(templates_dir)

    def get_page_metadata(self, page: str) -> dict:
        if not page.endswith('.md'):
            page = page + '.md'

        if not os.path.isfile(os.path.join(self.pages_dir, page)):
            abort(404)

        metadata = {}
        md_file = os.path.join(self.pages_dir, page)
        with open(md_file, 'r') as f:
            metadata['uri'] = '/article/' + page[:-3]

            for line in f.readlines():
                if not line:
                    continue

                if not (m := re.match(r'^\[//]: # \(([^:]+):\s*([^)]+)\)\s*$', line)):
                    break

                if m.group(1) == 'published':
                    metadata[m.group(1)] = datetime.date.fromisoformat(m.group(2))
                else:
                    metadata[m.group(1)] = m.group(2)

        if not metadata.get('title'):
            # If the `title` header isn't available in the file,
            # infer it from the first line of the file
            with open(md_file, 'r') as f:
                header = ''
                for line in f.readlines():
                    header = line
                    break

            metadata['title_inferred'] = True
            m = self._title_header_regex.search(header)
            if m:
                metadata['title'] = m.group(3) or m.group(1)
            else:
                metadata['title'] = os.path.basename(md_file)

        if not metadata.get('published'):
            # If the `published` header isn't available in the file,
            # infer it from the file's creation date
            metadata['published'] = datetime.date.fromtimestamp(os.stat(md_file).st_ctime)
            metadata['published_inferred'] = True

        return metadata

    def get_page(self, page: str, title: Optional[str] = None, skip_header: bool = False):
        if not page.endswith('.md'):
            page = page + '.md'

        metadata = self.get_page_metadata(page)
        # Don't duplicate the page title if it's been inferred
        if not (title or metadata.get('title_inferred')):
            title = metadata.get('title', config.title)

        with open(os.path.join(self.pages_dir, page), 'r') as f:
            return render_template(
                'article.html',
                config=config,
                title=title,
                image=metadata.get('image'),
                description=metadata.get('description'),
                author=(
                    re.match(r'(.+?)\s+<([^>]+>)', metadata['author'])[1]
                    if 'author' in metadata else None
                ),
                author_email=(
                    re.match(r'(.+?)\s+<([^>]+)>', metadata['author'])[2]
                    if 'author' in metadata else None
                ),
                published=(
                    metadata['published'].strftime('%b %d, %Y')
                    if metadata.get('published') and not metadata.get('published_inferred')
                    else None
                ),
                content=markdown(f.read(), extensions=['fenced_code', 'codehilite', MarkdownLatex()]),
                skip_header=skip_header
            )

    def get_pages(self, with_content: bool = False, skip_header: bool = False) -> list:
        return sorted(
            [
                {
                    'path': path[len(app.pages_dir)+1:],
                    'content': self.get_page(path[len(app.pages_dir)+1:], skip_header=skip_header) if with_content else '',
                    **self.get_page_metadata(os.path.basename(path)),
                }
                for path in glob(os.path.join(app.pages_dir, '*.md'))
            ],
            key=lambda page: page.get('published', datetime.date.fromtimestamp(0)),
            reverse=True
        )


app = BlogApp(__name__)


from .routes import *


# vim:sw=4:ts=4:et:
