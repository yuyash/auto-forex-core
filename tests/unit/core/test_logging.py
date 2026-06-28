import logging
from io import StringIO

from core.logging import CORE_LOGGER_NAME, LogLevel, configure_logging, get_logger


def test_get_logger_namespaces_core_loggers() -> None:
    assert get_logger().name == CORE_LOGGER_NAME
    assert get_logger("tasks.execution").name == "core.tasks.execution"
    assert get_logger("core.events").name == "core.events"


def test_configure_logging_sets_standalone_handler() -> None:
    stream = StringIO()
    logger = configure_logging(
        level=LogLevel.INFO,
        stream=stream,
        format="%(levelname)s %(name)s %(message)s",
        replace_handlers=True,
    )
    try:
        get_logger("test").info("standalone logging works")

        assert "INFO core.test standalone logging works" in stream.getvalue()
    finally:
        for handler in tuple(logger.handlers):
            if not isinstance(handler, logging.NullHandler):
                logger.removeHandler(handler)
                handler.close()
        logger.propagate = True
