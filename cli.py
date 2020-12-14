import io
import os
import pathlib

from src.client.tcp import ZTransferTCPClient
from src.client.udp import ZTransferUDPClient
from src.server.tcp import ZTransferTCPServer
from src.server.udp import ZTransferUDPServer
from src.utils import get_parser, get_logger, calc_sha3_512_checksum

if __name__ == "__main__":
    parser = get_parser()
    args = parser.parse_args()

    cli_logger = get_logger("   command-line   ", args.verbose)

    if args.subparser_name == "tcp-client":
        cli_logger.debug("Reading file")

        with open(args.file_path, "rb") as fp:
            file_stream = io.BytesIO(fp.read())
            file_name = args.file_path.split(os.sep)[-1]

            cli_logger.debug("Initializing TCP client")

            client = ZTransferTCPClient(args.server_host, args.server_port,
                args.bind_ports, file_name, file_stream, args.verbose)

            client.initiate_transfer()
    elif args.subparser_name == "tcp-server":
        cli_logger.debug("Initializing TCP server")

        server = ZTransferTCPServer(args.bind_host, args.bind_ports,
            args.verbose)

        server.listen_for_transfer()

        checksum = calc_sha3_512_checksum(server.recv_bytes_data)

        if checksum != server.file_overall_checksum:
            cli_logger.debug(f"Checksum mismatch: \n{checksum}\n{server.file_overall_checksum}")
        else:
            cli_logger.debug(f"Checksum OK")

        if args.save_path is None:
            save_path = pathlib.Path(__file__).parent.absolute()
        else:
            save_path = args.save_path

        save_path = os.path.join(save_path, server.file_name.replace("\x00", ""))

        with open(save_path, "wb") as fp:
            fp.write(server.recv_bytes_data)
    elif args.subparser_name == "udp-client":
        cli_logger.debug("Reading file")

        with open(args.file_path, "rb") as fp:
            file_stream = io.BytesIO(fp.read())
            file_name = args.file_path.split(os.sep)[-1]

            cli_logger.debug("Initializing UDP client")

            client = ZTransferUDPClient(args.server_host, args.server_port,
                args.bind_ports, file_name, file_stream, args.verbose)

            client.initiate_transfer()
    elif args.subparser_name == "udp-server":
        cli_logger.debug("Initializing UDP server")

        server = ZTransferUDPServer(args.bind_host, args.bind_ports,
            args.verbose)

        server.listen_for_transfer()

        if args.save_path is None:
            save_path = pathlib.Path(__file__).parent.absolute()
        else:
            save_path = args.save_path

        save_path = os.path.join(save_path, server.file_name.replace("\x00", ""))

        with open(save_path, "wb") as fp:
            fp.write(server.buffer_bytearray)