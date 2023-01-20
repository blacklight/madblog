#!/usr/bin/env python

import os
from setuptools import setup, find_packages


def readfile(file):
    with open(file, 'r') as f:
        return f.read()


setup(
    name='madblog',
    version='0.2.13',
    author='Fabio Manganiello',
    author_email='info@fabiomanganiello.com',
    description='A minimal platform for Markdown-based blogs',
    license='MIT',
    python_requires='>= 3.8',
    keywords='blog markdown',
    url='https://git.platypush.tech/blacklight/madblog',
    packages=find_packages(include=['madblog']),
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'madblog=madblog.cli:run',
        ],
    },
    long_description=readfile('README.md'),
    long_description_content_type='text/markdown',
    classifiers=[
        "Topic :: Utilities",
        "License :: OSI Approved :: MIT License",
        "Development Status :: 4 - Beta",
    ],
    install_requires=[
        'flask',
        'markdown',
        'pygments',
        'pyyaml',
    ],
)
