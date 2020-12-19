import os
import json
from functools import lru_cache

SCRIPT_DIR = os.path.dirname(os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
CONF_FILE_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "config.json"))

@lru_cache(maxsize=None)
def get_config():
    with open(CONF_FILE_PATH, "r") as fp:
        return json.load(fp)