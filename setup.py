#!/usr/bin/env python

from setuptools import setup, find_packages


def readfile(file):
    with open(file, "r") as f:
        return f.read()


setup(
    name="madblog",
    version="0.9.10",
    author="Fabio Manganiello",
    author_email="info@fabiomanganiello.com",
    description="A minimal platform for Markdown-based blogs",
    license="AGPL-3.0-only",
    python_requires=">= 3.8",
    keywords="blog markdown",
    url="https://git.fabiomanganiello.com/madblog",
    packages=find_packages(include=["madblog", "madblog.*"]),
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "madblog=madblog.cli:run",
        ],
    },
    long_description=readfile("README.md"),
    long_description_content_type="text/markdown",
    classifiers=[
        "Topic :: Utilities",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Development Status :: 4 - Beta",
    ],
    extras_require={
        "mermaid": ["nodejs-wheel"],
        "test": ["pytest"],
        "dev": ["pytest", "nodejs-wheel"],
    },
    install_requires=[
        "feedgen2",
        "feedparser",
        "flask",
        "markdown",
        "pubby",
        "pygments",
        "pyyaml",
        "requests",
        "watchdog",
        "webmentions[file]",
    ],
)
