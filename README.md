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

See [config.example.yaml](./config.example.yaml) for an example configuration
file, and copy it to `config.yaml` in your blog root directory to customize
your blog.

All the configuration options are also available as environment variables, with
the prefix `MADBLOG_`.

For example, the `title` configuration option can be set through the `MADBLOG_TITLE`
environment variable.

### Webmentions

Webmentions allow other sites to notify your blog when they link to one of your
articles. Madblog exposes a Webmention endpoint and stores inbound mentions under
your `content_dir`.

Webmentions configuration options:

- **Enable/disable**
  - Config file: `enable_webmentions: true|false`
  - Environment variable: `MADBLOG_ENABLE_WEBMENTIONS=1` (enable) or `0` (disable)

- **Site link requirement**
  - Set `link` (or `MADBLOG_LINK`) to the public base URL of your blog.
  - Incoming Webmentions are only accepted if the `target` URL domain matches the
    configured `link` domain.

- **Endpoint**
  - The Webmention endpoint is available at: `/webmentions`.

- **Storage**
  - Inbound Webmentions are stored as Markdown files under:
    `content_dir/mentions/incoming/<post-slug>/`.

Removed Webmentions are handled as follows (for example when the source URL returns
404/410 or it no longer links to the target).

- **Default**: soft-delete (the stored mention file is kept, but marked as deleted and
  excluded from rendering).
- **Hard delete**: the stored mention file is removed.

You can enable hard-deletes with either:

- **Config file**: `webmentions_hard_delete: true`
- **Environment variable**: `MADBLOG_WEBMENTIONS_HARD_DELETE=1`

Outgoing Webmentions will be automatically processed when the modification time of
a Markdown file is updated.

By default the throttle for outgoing Webmentions is set to one batch of requests every 10 seconds.

You can tweak this either through:

- **Config file**: `throttle_seconds_on_update`
- **Environment variable**: `MADBLOG_THROTTLE_SECONDS_ON_UPDATE`

## Markdown files

Articles are Markdown files stored under `markdown`. For an article to be correctly rendered,
you need to start the Markdown file with the following metadata header:

```markdown
[//]: # (title: Title of the article)
[//]: # (description: Short description of the content)
[//]: # (image: /img/some-header-image.png)
[//]: # (author: Author Name <https://author.me>)
[//]: # (author_photo: https://author.me/avatar.png)
[//]: # (published: 2022-01-01)
```

Or, if you want to pass an email rather than a URL for the author:

```markdown
[//]: # (author: Author Name <mailto:email@author.me>)
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

If you want the short feed (i.e. without the fully rendered article as a
description) to be always returned, then you can specify `short_feed=true` in
your configuration.
