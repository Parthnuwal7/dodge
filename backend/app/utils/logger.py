import logging
import sys

from app.config.constants import APP_NAME


def setup_logger(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(APP_NAME)

    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logger.level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s.%(module)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False

    return logger


def get_logger(module_name: str | None = None) -> logging.Logger:
    name = f"{APP_NAME}.{module_name}" if module_name else APP_NAME
    return logging.getLogger(name)
