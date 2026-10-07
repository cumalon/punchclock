import logging
from logging.handlers import WatchedFileHandler
from pathlib import Path


DEFAULT_LOG_PATH = Path("/var/log/timeclockpi/timeclockpi.log")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def create_technical_logger(log_path=DEFAULT_LOG_PATH):
    """Create the persistent technical logger.

    The deployment is responsible for creating the parent directory with
    permissions that allow the backend service account to write to it.
    """
    logger = logging.getLogger("timeclockpi.technical")
    logger.setLevel(logging.WARNING)
    logger.propagate = False

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    handler = WatchedFileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger.addHandler(handler)
    return logger
