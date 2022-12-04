import datetime
import os
import re
from typing import Optional, List, Tuple, Type

from flask import Flask, abort
from markdown import markdown

from .config import config
from .latex import MarkdownLatex
from ._sorters import PagesSorter, PagesSortByTime


class BlogApp(Flask):
    _title_header_regex = re.compile(r'^#\s*((\[(.*)\])|(.*))')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, template_folder=config.templates_dir, **kwargs)
        self.pages_dir = os.path.join(config.content_dir, 'markdown')
        self.img_dir = config.default_img_dir
        self.css_dir = config.default_css_dir
        self.js_dir = config.default_js_dir
        self.fonts_dir = config.default_fonts_dir

        if not os.path.isdir(self.pages_dir):
            # If the `markdown` subfolder does not exist, then the whole
            # `config.content_dir` is treated as the root for markdown files.
            self.pages_dir = config.content_dir

        img_dir = os.path.join(config.content_dir, 'img')
        if os.path.isdir(img_dir):
            self.img_dir = os.path.abspath(img_dir)
        else:
            self.img_dir = config.content_dir

        css_dir = os.path.join(config.content_dir, 'css')
        if os.path.isdir(css_dir):
            self.css_dir = os.path.abspath(css_dir)

        js_dir = os.path.join(config.content_dir, 'js')
        if os.path.isdir(js_dir):
            self.js_dir = os.path.abspath(js_dir)

        fonts_dir = os.path.join(config.content_dir, 'fonts')
        if os.path.isdir(fonts_dir):
            self.fonts_dir = os.path.abspath(fonts_dir)

        templates_dir = os.path.join(config.content_dir, 'templates')
        if os.path.isdir(templates_dir):
            self.template_folder = os.path.abspath(templates_dir)

    def get_page_metadata(self, page: str) -> dict:
        if not page.endswith('.md'):
            page = page + '.md'

        md_file = os.path.join(self.pages_dir, page)
        if not os.path.isfile(md_file):
            abort(404)

        metadata = {}
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

    def get_page(
        self,
        page: str,
        title: Optional[str] = None,
        skip_header: bool = False,
        skip_html_head: bool = False
    ):
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
                skip_header=skip_header,
                skip_html_head=skip_html_head,
            )

    def get_pages(
        self,
        with_content: bool = False,
        skip_header: bool = False,
        skip_html_head: bool = False,
        sorter: Type[PagesSorter] = PagesSortByTime,
        reverse: bool = True,
    ) -> List[Tuple[int, dict]]:
        pages_dir = app.pages_dir.rstrip('/')
        pages = [
            {
                'path': os.path.join(root[len(pages_dir)+1:], f),
                'folder': root[len(pages_dir)+1:],
                'content': (
                    self.get_page(
                        os.path.join(root, f),
                        skip_header=skip_header,
                        skip_html_head=skip_html_head,
                    )
                    if with_content else ''
                ),
                **self.get_page_metadata(
                    os.path.join(root[len(pages_dir)+1:], f)
                ),
            }
            for root, _, files in os.walk(pages_dir, followlinks=True)
            for f in files
            if f.endswith('.md')
        ]

        sorter_func = sorter(pages)
        pages.sort(key=sorter_func, reverse=reverse)
        return [(i, page) for i, page in enumerate(pages)]


app = BlogApp(__name__)


from .routes import *


# vim:sw=4:ts=4:et:
