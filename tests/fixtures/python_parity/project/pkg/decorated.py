"""Framework-decorator exclusion: exact names, suffix matches, unknown."""

import functools

import click
from flask import app


@property
def prop_like():
    return "prop-result"


@click.command()
def cli_entry():
    return "cli-result"


@app.route("/health-endpoint")
def health():
    return "ok-result"


@functools.lru_cache(maxsize=None)
def cached_func():
    return "cached-result"


@custom.event.listener
def on_event():
    return "event-result"


class Model:
    @staticmethod
    def build():
        return "build-result"

    @classmethod
    def create(cls):
        return "create-result"

    @unknown_decorator
    def plain(self):
        return "plain-result"
