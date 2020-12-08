import os
import sys
import socket
import hashlib
import logging

PACKAGE_PARENT = '..'
SCRIPT_DIR = os.path.dirname(
    os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
sys.path.append(os.path.normpath(
    os.path.join(SCRIPT_DIR, PACKAGE_PARENT, PACKAGE_PARENT)))

from src.logger import get_logger
from src.ztransfer.packets import (ZTConnReqPacket, ZTDataPacket,
                                   ZTAcknowledgementPacket, ZTFinishPacket,
                                   deserialize_packet)
from src.ztransfer.errors import (ZTVerificationError, ERR_VERSION_MISMATCH,
                                  ERR_ZTDATA_CHECKSUM, ERR_MAGIC_MISMATCH,
                                  ERR_PTYPE_DNE)

class ZTransferTCPServer(object):
    STATE_INIT = 0
    STATE_WAIT_CCREQ = 1
    STATE_TRANSFER = 2
    STATE_FIN = 3

    def __init__(self, bind_host: str, bind_port: int, logger_verbose: bool = False):
        self.bind_host = bind_host
        self.bind_port = bind_port
        
        self.recv_bytes_data = b""
        self.file_overall_checksum = None
        self.file_name = None

        self.client_socket = None
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.logger = get_logger("ZTransferTCPServer")
        
        if logger_verbose:
            self.logger.setLevel(logging.DEBUG)
            
        self.logger.debug(f"Constructed ZTransferTCPServer({bind_host}, {bind_port})")

    def listen_for_transfer(self):
        state = self.STATE_INIT

        while state != self.STATE_FIN:
            if state == self.STATE_INIT:
                self.socket.bind((self.bind_host, self.bind_port))
                self.socket.listen()

                self.client_socket, client_addr = self.socket.accept()

                state = self.STATE_WAIT_CCREQ
            elif state == self.STATE_WAIT_CCREQ:
                recv_data = self.client_socket.recv(1000)

                self.logger.debug(f"Received {len(recv_data)} bytes from the client")

                try:
                    self.logger.debug(f"Deserializing received packet data...")
                    packet = deserialize_packet(recv_data)
                except ZTVerificationError as e:
                    if e.err_code == ERR_MAGIC_MISMATCH:
                        self.logger.warning(f"Wrong magic number '{e.extras['magic']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                        self.clear()
                        return
                    if e.err_code == ERR_VERSION_MISMATCH:
                        self.logger.warning(f"Mismatched version number '{e.extras['version']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                        self.clear()
                        return
                    if e.err_code == ERR_PTYPE_DNE:
                        self.logger.warning(f"Not known packet type '{e.extras['ptype']}' (seq: {e.extras['seq']}, ts: {e.extras['ts']})")
                        self.clear()
                        return

                self.logger.debug(f"Packet OK: {packet.__class__.__name__} ({packet.sequence_number})")

                if not isinstance(packet, ZTConnReqPacket):
                    self.logger.warning(f"Was waiting for CREQ, got '{packet.ptype}'")
                    self.clear()
                    return

                self.file_name = packet.filename
                self.file_overall_checksum = packet.checksum

                ack_packet = ZTAcknowledgementPacket(1, packet.sequence_number)
                self.client_socket.sendall(ack_packet.serialize())

                state = self.STATE_TRANSFER
            elif state == self.STATE_TRANSFER:
                recv_data = self.client_socket.recv(1000)

                self.logger.debug(f"Received {len(recv_data)} bytes from the client")

                try:
                    self.logger.debug(f"Deserializing received packet data...")
                    packet = deserialize_packet(recv_data)
                except ZTVerificationError as e:
                    if e.err_code == ERR_MAGIC_MISMATCH:
                        self.logger.warning(f"Wrong magic number '{e.extras['magic']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                        self.clear()
                        return
                    if e.err_code == ERR_VERSION_MISMATCH:
                        self.logger.warning(f"Mismatched version number '{e.extras['version']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                        self.clear()
                        return
                    if e.err_code == ERR_PTYPE_DNE:
                        self.logger.warning(f"Not known packet type '{e.extras['ptype']}' (seq: {e.extras['seq']}, ts: {e.extras['ts']})")
                        self.clear()
                        return
                    if e.err_code == ERR_ZTDATA_CHECKSUM:
                        self.logger.warning(f"Data packet checksum failed (seq: {e.extras['seq']}, ts: {e.extras['ts']})")
                        self.clear()
                        return

                self.logger.debug(f"Packet OK: {packet.__class__.__name__} ({packet.sequence_number})")

                if isinstance(packet, ZTDataPacket):
                    self.recv_bytes_data += packet.file_data.replace(b"\x00", b"")
                elif isinstance(packet, ZTFinishPacket):
                    state = self.STATE_FIN
                else:
                    self.logger.warning(f"Was waiting for DATA, got '{packet.ptype}'")
                    self.clear()
                    return

        self.clear()

    def clear(self):
        self.socket.close()

        if self.client_socket is not None:
            self.client_socket.close()
