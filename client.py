import io
import sys
import threading

from src.client.tcp import ZTransferTCPClient
from src.client.udp import ZTransferUDPClient
from src.utils import calc_sha3_512_checksum

if __name__ == "__main__":
    server_ip = sys.argv[1]
    server_udp_port = int(sys.argv[2])
    server_tcp_port = int(sys.argv[3])
    client_udp_port = int(sys.argv[4])
    client_tcp_port = int(sys.argv[5])

    with open("transfer_file_TCP.txt", "rb") as fp:
        file_stream = io.BytesIO(fp.read())
        file_name = "transfer_file_TCP.txt"

        client = ZTransferTCPClient(server_ip, server_tcp_port,
            [client_tcp_port], file_name, file_stream, False)

        client.initiate_transfer()

    with open("transfer_file_UDP.txt", "rb") as fp:
        file_stream = io.BytesIO(fp.read())
        file_name = "transfer_file_UDP.txt"

        client = ZTransferUDPClient(server_ip, server_udp_port,
            [client_udp_port], file_name, file_stream, False)

        client.initiate_transfer()

        print(f"UDP Transmission Re-transferred Packets: {client.failed_packet_count}")