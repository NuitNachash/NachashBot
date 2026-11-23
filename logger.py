import logging
import os
from datetime import datetime

def setup_logger(log_path=os.path.expanduser("~/twitch/logs/nachashbot.log")):
    os.makedirs(os.path.dirname(log_path), exist_ok=True) if os.path.dirname(log_path) else None
    
    logger = logging.getLogger("bot")
    logger.setLevel(logging.DEBUG)

    # File handler
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    # Console handler
    #ch = logging.StreamHandler()
    #ch.setLevel(logging.INFO)

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    #ch.setFormatter(formatter)

    logger.addHandler(fh)
    #logger.addHandler(ch)

    return logger

logger = setup_logger("nachashbot.log")