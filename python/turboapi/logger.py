import json
import logging
import os
import sys


class TurboJSONFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": record.created,
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "module": record.module,
        }
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            entry["trace_id"] = trace_id
        return json.dumps(entry, default=str)


def get_logger(name="turboapi"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = os.environ.get("TURBO_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    handler = logging.StreamHandler(sys.stderr)
    fmt = os.environ.get("TURBO_LOG_FORMAT", "text")
    if fmt == "json":
        handler.setFormatter(TurboJSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    logger.addHandler(handler)
    return logger
