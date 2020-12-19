import sys
import socket

from src.server.tcp import ZTransferTCPServer
from src.server.udp import ZTransferUDPServer

hostname = socket.gethostname()
self_ip = socket.gethostbyname(hostname)

if __name__ == "__main__":
    udp_port = int(sys.argv[1])
    tcp_port = int(sys.argv[2])

    server = ZTransferTCPServer(self_ip, [tcp_port], False)
    server.listen_for_transfer()

    print(f"TCP Packets Average Transmission Time: {server.profiler.avg_trasmission_time * 1000} ms")
    print(f"TCP Communication Total Transmission Time: {server.profiler.total_transmission_time * 1000} ms")

    with open("transfer_file_TCP.txt", "wb") as fp:
        fp.write(server.recv_bytes_data)

    server = ZTransferUDPServer(self_ip, [udp_port], False)
    server.listen_for_transfer()

    print(f"UDP Packets Average Transmission Time: {server.profiler.avg_trasmission_time * 1000} ms")
    print(f"UDP Communication Total Transmission Time: {server.profiler.total_transmission_time * 1000} ms")

    with open("transfer_file_UDP.txt", "wb") as fp:
        fp.write(server.buffer_bytearray)