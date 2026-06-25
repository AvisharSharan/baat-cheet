import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

def unlink_with_retry(path: Path, attempts: int = 5, delay_s: float = 0.25) -> None:
    if not path.exists():
        return
    for attempt in range(attempts):
        try:
            path.unlink()
            return
        except OSError:
            if attempt == attempts - 1:
                logger.warning("Could not delete %s after %d attempts.", path, attempts, exc_info=True)
            time.sleep(delay_s)
