import logging

from timeclock.technical_log import create_technical_logger


def test_technical_logger_writes_warning_and_error_but_not_info(tmp_path):
    log_path = tmp_path / "timeclockpi.log"
    logger = create_technical_logger(log_path)

    logger.info("routine activity")
    logger.warning("recoverable technical problem")
    logger.error("technical failure")

    for handler in logger.handlers:
        handler.flush()
        handler.close()
    logger.handlers.clear()

    contents = log_path.read_text(encoding="utf-8")
    assert "routine activity" not in contents
    assert "WARNING timeclockpi.technical: recoverable technical problem" in contents
    assert "ERROR timeclockpi.technical: technical failure" in contents


def test_technical_logger_reopens_file_after_external_rotation(tmp_path):
    log_path = tmp_path / "timeclockpi.log"
    rotated_path = tmp_path / "timeclockpi.log.1"
    logger = create_technical_logger(log_path)

    logger.warning("before rotation")
    for handler in logger.handlers:
        handler.flush()

    log_path.rename(rotated_path)
    log_path.touch()

    logger.error("after rotation")
    for handler in logger.handlers:
        handler.flush()
        handler.close()
    logger.handlers.clear()

    assert "before rotation" in rotated_path.read_text(encoding="utf-8")
    assert "after rotation" not in rotated_path.read_text(encoding="utf-8")
    assert "after rotation" in log_path.read_text(encoding="utf-8")
