"""Finite Gunicorn operational categories; never record request/error payloads."""
from __future__ import annotations

import logging
from gunicorn.glogging import Logger


class PrivacySafeLogger(Logger):
    def _emit_category(self, level: int) -> None:
        labels = {
            logging.DEBUG: "debug",
            logging.INFO: "info",
            logging.WARNING: "warning",
            logging.ERROR: "error",
            logging.CRITICAL: "critical",
        }
        category = labels.get(level, "error")
        if level not in labels:
            level = logging.ERROR
        self.error_log.log(level, "collector_runtime_" + category)

    def debug(self, msg, *args, **kwargs):
        self._emit_category(logging.DEBUG)

    def info(self, msg, *args, **kwargs):
        self._emit_category(logging.INFO)

    def warning(self, msg, *args, **kwargs):
        self._emit_category(logging.WARNING)

    def error(self, msg, *args, **kwargs):
        self._emit_category(logging.ERROR)

    def critical(self, msg, *args, **kwargs):
        self._emit_category(logging.CRITICAL)

    def exception(self, msg, *args, **kwargs):
        self._emit_category(logging.ERROR)

    def log(self, level, msg, *args, **kwargs):
        self._emit_category(level)

    def access(self, resp, req, environ, request_time):
        # Gunicorn error handling can synthesize an access record even before
        # WSGI execution. Discard it without inspecting any of its arguments.
        return None
