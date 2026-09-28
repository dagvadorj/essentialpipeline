"""
Centralized, structured logging for EssentialPipeline.

Before this, code across the app called logging.getLogger(__name__) and
.info()/.warning()/.error() at dozens of call sites (services/scheduler.py,
security_scan.py, deployment.py, ...) but nothing ever configured the
root logger - config.LOG_LEVEL was read from the environment and then
never applied anywhere, so Python's logging default (WARNING+ to
stderr, no timestamps, no structure) is what actually ran. This wires
LOG_LEVEL up and gives every existing call site structured JSON-line
output, without having to touch any of them.
"""

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'timestamp': self.formatTime(record, '%Y-%m-%dT%H:%M:%S'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(app) -> None:
    """
    Idempotent: safe to call every time create_app() runs, even more
    than once in the same process (e.g. under pytest, or repeated manual
    create_app() calls) - it only ever adds its own handler once, and
    otherwise leaves the root logger's other handlers (pytest's own log
    capture, for one) alone rather than clearing them.
    """
    root = logging.getLogger()
    root.setLevel(app.config.get('LOG_LEVEL', 'INFO'))

    if any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
