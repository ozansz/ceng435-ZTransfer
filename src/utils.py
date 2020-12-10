import sys
import struct
import random
import hashlib
import logging
import argparse

def get_logger(name: str, verbose: bool = False):
    logger = logging.getLogger(name)
    logger.propagate = True
    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s: %(message)s")

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch) 

    if verbose:
        logger.setLevel(logging.DEBUG)

    return logger

def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug messages")
    subparsers = parser.add_subparsers(dest="subparser_name")

    parser_server = subparsers.add_parser("server")
    parser_server.add_argument("bind_host")
    parser_server.add_argument("bind_ports", nargs='+', type=int)
    parser_server.add_argument("--save_path", required=False, default=None)

    parser_client = subparsers.add_parser("client")
    parser_client.add_argument("bind_ports", nargs='+', type=int)
    parser_client.add_argument("server_host")
    parser_client.add_argument("server_port", type=int)
    parser_client.add_argument("file_path")

    return parser

def calc_sha3_512_checksum(data: bytes) -> bytes:
    m = hashlib.sha3_512()
    m.update(data)

    return m.digest()

generate_random_bytes = lambda len: b"".join([struct.pack("<I", random.randint(0, 2**32 - 1)) for _ in range(len)])