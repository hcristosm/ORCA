"""ORCA: dashboard local de risco geológico x chuva (CPRM/SGB + INMET)."""

import logging
import os

logging.basicConfig(
    level=os.environ.get("ORCA_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
