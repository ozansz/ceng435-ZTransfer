import argparse

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