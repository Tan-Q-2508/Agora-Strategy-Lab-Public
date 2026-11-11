"""Failures a data source can report, each with a plain-English message.

The cache manager decides what to do from the type: retry with back-off on
``RateLimited``, try the next source on ``EmptyResponse``/``SourceError``, and tell the
user on ``NotFound``. A source never returns an empty list to mean "something broke".
"""

from __future__ import annotations


class SourceError(Exception):
    """The source failed in a way that a retry or another source might fix."""

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class RateLimited(SourceError):
    """The source asked us to slow down."""


class Blocked(SourceError):
    """The source refuses automatic downloads altogether (e.g. a browser check): asking again
    won't help, so it is left alone for a day (D-114)."""


class EmptyResponse(SourceError):
    """The source answered but sent no usable bars where some were expected."""


class NotFound(SourceError):
    """The symbol doesn't exist at this source."""
