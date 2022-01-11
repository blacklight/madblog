# mdblog

This project provides a minimal blogging platform based on Markdown files.

## Installation

```shell
$ python setup.py install
```

## Usage

```shell
# The application will listen on port 8000 and it will
# serve the current folder
$ madness
```

```
usage: madblog [-h] [--host HOST] [--port PORT] [--debug] [path]

Serve a Markdown folder as a web blog.

The folder should have the following structure:

.
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
  -> css [optional]
    -> custom-1.css
    -> custom-2.css
    -> ...
  -> fonts [optional]
    -> custom-1.ttf
    -> custom-1.css
    -> ...
  -> templates [optional]
    -> index.html [for a custom index template]
    -> article.html [for a custom article template]

positional arguments:
  path         Base path for the blog

options:
  -h, --help   show this help message and exit
  --host HOST  Bind host/address
  --port PORT  Bind port (default: 8000)
  --debug      Enable debug mode (default: False)
```

## Markdown files

Articles are Markdown files stored under `pages`. For an article to be correctly rendered,
you need to start the Markdown file with the following metadata header:

```markdown
[//]: # (title: Title of the article)
[//]: # (description: Short description of the content)
[//]: # (image: /img/some-header-image.png)
[//]: # (author: Author Name <email@author.me>)
[//]: # (published: 2022-01-01)
```

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

