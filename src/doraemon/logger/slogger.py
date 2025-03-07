from __future__ import annotations
import logging
import os
import sys
from typing import Optional

import structlog
from structlog.dev import ConsoleRenderer
from structlog.typing import EventDict, WrappedLogger
from structlog_sentry import SentryProcessor

from doraemon.logger.file_handler import get_file_handler

DEFAULT_LOG_LEVEL_NAME = "INFO"
DEFAULT_LOG_PATH = "./log"
FORCE_JSON_LOGGING = os.environ.get("FORCE_JSON_LOGGING")


def create_logger(
    module_name: str = "",
    log_level: int = logging.getLevelName(DEFAULT_LOG_LEVEL_NAME),
    log_file_path: str = DEFAULT_LOG_PATH,
):
    configure_structlog(log_level=log_level, log_file_path=log_file_path)
    return structlog.get_logger(module_name) if module_name else structlog.get_logger()


class HumanConsoleRenderer(ConsoleRenderer):
    """Console renderer that outputs human-readable logs."""

    def __call__(self, logger: WrappedLogger, name: str, event_dict: EventDict) -> str:
        if "event_info" in event_dict:
            event_key = event_dict["event"]
            event_dict["event"] = event_dict["event_info"]
            event_dict["event_key"] = event_key
            del event_dict["event_info"]

        return super().__call__(logger, name, event_dict)


def configure_structlog(
    log_level: Optional[int] = None,
    log_file_path: str = DEFAULT_LOG_PATH,
) -> None:
    """Configure logging of the server."""
    # check if log_file_path folder exist, if not create
    if not os.path.exists(log_file_path):  # 检查文件夹是否存在
        os.makedirs(log_file_path)

    if log_level is None:
        log_level = logging.getLevelName(DEFAULT_LOG_LEVEL_NAME)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # ===> Config handlers
    handlers = [
        get_file_handler(logging.DEBUG, os.path.join(log_file_path, "local.log")),
    ]
    logger = logging.getLogger()
    for handler in handlers:
        logger.addHandler(handler)

    # ===> Config processors
    shared_processors = [
        # Processors that have nothing to do with output,
        # e.g., add timestamps or log level names.
        # If log level is too low, abort pipeline and throw away log entry.
        structlog.stdlib.filter_by_level,
        structlog.contextvars.merge_contextvars,
        # Add the name of the logger to event dict.
        # structlog.stdlib.add_logger_name,
        # Add log level to event dict.
        structlog.processors.add_log_level,
        # If the "stack_info" key in the event dict is true, remove it and
        # render the current stack trace in the "stack" key.
        structlog.processors.StackInfoRenderer(),
        # If some value is in bytes, decode it to a unicode str.
        structlog.processors.UnicodeDecoder(),
        structlog.dev.set_exc_info,
        # add structlog sentry integration. only log fatal log entries
        # as events as we are tracking exceptions anyways
        SentryProcessor(event_level=logging.FATAL),
    ]

    if not FORCE_JSON_LOGGING and sys.stderr.isatty():
        # Pretty printing when we run in a terminal session.
        # Automatically prints pretty tracebacks when "rich" is installed
        processors = shared_processors + [
            HumanConsoleRenderer(),
        ]
    else:
        # Print JSON when we run, e.g., in a Docker container.
        # Also print structured tracebacks.
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,  # type: ignore
        context_class=dict,
        # `logger_factory` is used to create wrapped loggers that are used for
        # OUTPUT. This one returns a `logging.Logger`. The final value (a JSON
        # string) from the final processor (`JSONRenderer`) will be passed to
        # the method of the same name as that you've called on the bound logger.
        logger_factory=structlog.stdlib.LoggerFactory(),
        # `wrapper_class` is the bound logger that you get back from
        # get_logger(). This one imitates the API of `logging.Logger`.
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        # Effectively freeze configuration after creating the first bound
        # logger.
        cache_logger_on_first_use=True,
    )
