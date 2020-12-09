import io
import os

from src.utils import get_parser, get_logger
from src.client.tcp import ZTransferTCPClient
from src.server.tcp import ZTransferTCPServer

if __name__ == "__main__":
    parser = get_parser()
    args = parser.parse_args()

    cli_logger = get_logger("cli", args.verbose)

    if args.subparser_name == "client":
        cli_logger.debug("Reading file")

        with open(args.file_path, "rb") as fp:
            file_stream = io.BytesIO(fp.read())
            file_name = args.file_path.split(os.sep)[-1]

            cli_logger.debug("Initializing client")

            client = ZTransferTCPClient(args.server_host, args.server_port,
                args.bind_ports, file_name, file_stream, args.verbose)

            client.initiate_transfer()
    elif args.subparser_name == "server":
        cli_logger.debug("Initializing server")

        server = ZTransferTCPServer(args.bind_host, args.bind_ports,
            args.verbose)

        server.listen_for_transfer()