# madblog

This project provides a minimal blogging platform based on Markdown files.

## Demos

This project powers the following blogs:

- [Platypush](https://blog.platypush.tech)
- [My personal blog](https://fabiomanganiello.com)

## Installation

```shell
$ python setup.py install
```

## Usage

```shell
# The application will listen on port 8000 and it will
# serve the current folder
$ madblog
```

```
usage: madblog [-h] [--config CONFIG] [--host HOST] [--port PORT] [--debug] [dir]

Serve a Markdown folder as a web blog.

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

positional arguments:
  dir              Base path for the blog (default: current directory)

options:
  -h, --help       show this help message and exit
  --config CONFIG  Path to a configuration file (default: config.yaml in the blog root directory)
  --host HOST      Bind host/address
  --port PORT      Bind port (default: 8000)
  --debug          Enable debug mode (default: False)
```

## Configuration

The application will look for a `config.yaml` file in the current directory if none was
specified through the `-c` command-line option. The structure is the following:

```yaml
title: Blog title
description: Blog description
link: https://link.to.your.blog
# Use home_link if you have a different home/portal address
# than your blog, otherwise it's the same as `link`
home_link: https://link.to.home
# Path/URL to the logo (default: /img/icon.png)
logo: /path/or/url/here
# Blog language (for the RSS feed)
language: en-US
# Show/hide the header (default: true)
header: true

categories:
  - category1
  - category2
  - category3
```

## Markdown files

Articles are Markdown files stored under `markdown`. For an article to be correctly rendered,
you need to start the Markdown file with the following metadata header:

```markdown
[//]: # (title: Title of the article)
[//]: # (description: Short description of the content)
[//]: # (image: /img/some-header-image.png)
[//]: # (author: Author Name <email@author.me>)
[//]: # (published: 2022-01-01)
```

If no `markdown` folder exists in the base directory, then the base directory itself will be treated as a root for
Markdown files.

### Folders

You can organize Markdown files in folders. If multiple folders are present, pages on the home will be grouped by
folders.

## Images

Images are stored under `img`. You can reference them in your articles through the following syntax:

```markdown
![image description](/img/image.png)
```

You can also drop your `favicon.ico` under this folder.

## LaTeX support

LaTeX support is built-in as long as you have the `latex` executable installed on your server.

Syntax for inline LaTeX:

```markdown
And we can therefore prove that \( c^2 = a^2 + b^2 \)
```

Syntax for LaTeX expression on a new line:

```markdown
$$
c^2 = a^2 + b^2
$$
```

## RSS syndacation

RSS feeds for the blog are provided under the `/rss` URL.

By default, the whole HTML-rendered content of an article is returned under `rss.channel.item.description`.
If you only want to include the short description of an article in the feed, use `/rss?short` instead.
