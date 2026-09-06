from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from .context import request_id_var

# LogRecord가 항상 들고 다니는 기본 속성들. 여기에 없는 값만 호출부가 extra=로
# 덧붙인 것으로 보고 함께 남긴다.
_RECORD_ATTRIBUTES = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "stacklevel",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        # extra=로 넘긴 값을 버리면 어떤 작업이 왜 실패했는지 로그만 보고는 알 수 없다.
        # 실제로 AI 작업 실패 로그에 작업 id도 에러 코드도 남지 않고 있었다.
        for key, value in record.__dict__.items():
            if key in _RECORD_ATTRIBUTES or key in payload or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # 직렬화할 수 없는 값이 하나 섞였다고 로그 자체가 사라지면 안 된다.
        return json.dumps(payload, ensure_ascii=False, default=str)
