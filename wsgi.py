import logging

from app import app, finalize_pending_branding
from timeclock.database import init_database
from timeclock.technical_log import create_technical_logger


technical_logger = create_technical_logger()
try:
    init_database()
except Exception:
    technical_logger.exception("Database initialization failed")
    raise

try:
    finalize_pending_branding(startup=True)
except Exception:
    technical_logger.exception("Pending branding restore finalization failed")

logging.getLogger("timeclockpi").addHandler(technical_logger.handlers[0])
