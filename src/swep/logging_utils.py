"""Logging helpers.

Two audiences are served:

* a human reading ``artifacts/run.log`` while debugging, and
* a machine reading ``artifacts/requests.jsonl`` to audit every LLM call
  (model, tokens, cost, latency, retry count) as required by REQ-1.7.

No API key ever reaches these sinks: callers pass only model names and token
counts (SEC-1.2).
"""

import json
import logging
import sys
import threading
import time
from pathlib import Path

LOGGER_NAME = "swep"

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(log_file=None, level="INFO", stream=True):
    """Configure and return the package logger.

    Repeated calls replace the previous handlers so that tests and CLI runs do
    not accumulate duplicates.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    if stream:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        logger.addHandler(console)

    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def get_logger():
    """Return the package logger, configuring a console-only fallback."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        setup_logger()
    return logger


class JsonlWriter:
    """Append-only JSON Lines writer, flushed on every record.

    Flushing per record keeps the audit trail valid even when the run is
    interrupted (which is exactly when it is needed).
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._handle = self.path.open("a", encoding="utf-8")

    def write(self, record):
        payload = dict(record)
        payload.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock:
            self._handle.write(line + "\n")
            self._handle.flush()
        return payload

    def close(self):
        with self._lock:
            if not self._handle.closed:
                self._handle.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
