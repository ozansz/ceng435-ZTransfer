import sys
import logging

def get_logger(name):
    logger = logging.getLogger(name)
    logger.propagate = True
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s")

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch) 

    return logger