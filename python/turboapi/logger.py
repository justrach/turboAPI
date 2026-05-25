"""Structured logging for TurboAPI."""

import json
import logging
import os
import sys


class TurboJSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": record.created,
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "module": record.module,
            "trace_id": getattr(record, "trace_id", None),
        }, default=str)


def get_logger(name: str = "turboapi") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    fmt = os.environ.get("TURBO_LOG_FORMAT", "text")
    level = os.environ.get("TURBO_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(TurboJSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
    logger.addHandler(handler)
    return logger
