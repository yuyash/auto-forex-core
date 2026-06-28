"""Logging utilities for Core library users."""

from __future__ import annotations

import logging
from typing import TextIO

CORE_LOGGER_NAME = "core"
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a Core logger without configuring output handlers."""
    if name is None or name == CORE_LOGGER_NAME:
        return logging.getLogger(CORE_LOGGER_NAME)
    if name.startswith(f"{CORE_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{CORE_LOGGER_NAME}.{name}")


def configure_logging(
    *,
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
    handler: logging.Handler | None = None,
    format: str = DEFAULT_LOG_FORMAT,
    datefmt: str | None = None,
    propagate: bool = False,
    replace_handlers: bool = False,
) -> logging.Logger:
    """Configure Core logging for standalone scripts and local tools.

    Applications embedding Core can ignore this function and configure the
    standard Python logging tree themselves.
    """
    logger = get_logger()
    logger.setLevel(level)
    logger.propagate = propagate

    if replace_handlers:
        for existing_handler in tuple(logger.handlers):
            if not isinstance(existing_handler, logging.NullHandler):
                logger.removeHandler(existing_handler)

    output_handler = handler or logging.StreamHandler(stream)
    if handler is None:
        output_handler.setFormatter(logging.Formatter(format, datefmt=datefmt))
    if output_handler not in logger.handlers:
        logger.addHandler(output_handler)
        logger.debug(
            "Added Core logging handler",
            extra={
                "logger_name": CORE_LOGGER_NAME,
                "handler_class": output_handler.__class__.__name__,
            },
        )
    logger.info(
        "Configured Core logging",
        extra={
            "logger_name": CORE_LOGGER_NAME,
            "logging_level": logging.getLevelName(logger.level),
            "propagate": logger.propagate,
            "handler_count": len(logger.handlers),
        },
    )
    return logger


def _install_null_handler() -> None:
    logger = get_logger()
    if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        logger.addHandler(logging.NullHandler())


_install_null_handler()
