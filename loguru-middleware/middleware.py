import json
import logging
import sys
import time
import traceback
from types import FrameType
from typing import cast

from loguru import Message, logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        # Find caller that originated the logged message..
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = cast(FrameType, frame.f_back)
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


def sink_serializer(message: Message) -> None:
    record = message.record
    simplified = {
        "level": record["level"].name,
        "message": record["message"],
        "timestamp": record["time"].timestamp(),
    }
    if record["exception"]:
        exc = record["exception"]
        simplified["exception"] = {
            "type": exc.type.__name__,
            "content": str(exc.value),
            "traceback": "".join(traceback.format_tb(exc.traceback)),
        }

    serialized = json.dumps(simplified)
    print(serialized, file=sys.stderr)


def configure_logging() -> None:
    logging.getLogger().handlers = [InterceptHandler()]
    loggers = ("uvicorn.asgi", "uvicorn.access")
    logging_level = logging.INFO
    for logger_name in loggers:
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler(level=logging_level)]

    logger.configure(
        handlers=[
            {
                "sink": sink_serializer,
                "level": logging_level,
                "serialize": True,
            }
        ],
    )


class AccessLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        time_delta = time.time() - start

        path = request.scope["path"]
        ignored = {"/status", "/metrics"}

        if path not in ignored and logging.getLogger("uvicorn.access"):
            access_log = {
                "req": {
                    "id": request.headers.get("id", "MISSING"),
                    "method": request.method,
                    "path": request.scope["path"],
                    "body": await request.body(),
                },
                "res": {
                    "length_bytes": int(response.headers.get("content-length", 0)),
                    "duration_ms": round(time_delta * 1000, 3),
                    "status": response.status_code,
                },
            }
            logger.info(access_log)

        return response
