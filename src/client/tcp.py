import io
import os
import sys
import socket
import logging
import hashlib

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

class ZTransferTCPClient(object):
    STATE_INIT = 0
    STATE_WAIT_ACK = 1
    STATE_TRANSFER = 2
    STATE_FIN = 3

    def __init__(self, server_host: str, server_port: int, file_name: str, file_stream: io.BytesIO):
        self.server_host = server_host
        self.server_port = server_port
        self.file_name = file_name
        self.file_stream = file_stream
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.logger = get_logger("ZTransferTCPClient")
        self.logger.setLevel(logging.DEBUG)
        self.logger.debug(f"Constructed ZTransferTCPClient({server_host}, {server_port}, ...)")

    def initiate_transfer(self):
        file_size_bytes = self.file_stream.getbuffer().nbytes
        num_data_packets = file_size_bytes // 988

        if file_size_bytes % 988 > 0:
            num_data_packets += 1

        m = hashlib.sha3_512()
        m.update(self.file_stream.getvalue())
        file_checksum = m.digest()

        state = self.STATE_INIT
        current_sequence_num = 1
        _creq_seq = current_sequence_num
        current_byte_position = 0
        is_last_transfer_packet = False

        self.logger.debug(f"File size: {file_size_bytes} bytes")
        self.logger.debug(f"File checksum (SHA3-512): {file_checksum[:10]}...")
        self.logger.debug(f"Total {num_data_packets} data packets will be sent")

        while state != self.STATE_FIN:
            self.logger.debug(f"Current sequence number: {current_sequence_num}")

            if state == self.STATE_INIT:
                self.logger.debug(f"State: INIT")
                
                self.socket.connect((self.server_host, self.server_port))
                self.logger.debug(f"Connected to server at {(self.server_host, self.server_port)}")

                creq_packet = ZTConnReqPacket(current_sequence_num, file_size_bytes,
                    num_data_packets + 1, file_checksum, self.file_name)

                try:
                    self.socket.sendall(creq_packet.serialize())
                except Exception as e:
                    self.logger.error(f"Error occured while self.socket.sendall(): {e}")
                    self.clear()
                    return
                
                state = self.STATE_WAIT_ACK
                self.logger.debug(f"Sent CREQ packet and updated state to WAIT_ACK")
            elif state == self.STATE_WAIT_ACK:
                self.logger.debug(f"State: WAIT_ACK")

                recv_data = self.socket.recv(1000)
                self.logger.debug(f"Received {len(recv_data)} bytes from the server")

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

                self.logger.debug(f"Packet OK: {packet.__class__.__name__}")

                if not isinstance(packet, ZTAcknowledgementPacket):
                    self.logger.warning(f"Was waiting for ACK, got '{e.extras['ptype']}' (seq: {e.extras['seq']}, ts: {e.extras['ts']})")
                    self.clear()
                    return

                if packet.seq_to_ack != _creq_seq:
                    self.logger.warning(f"Not ACKed to my CREQ seq (mine was {_creq_seq} but it ACKed to {packet.seq_to_ack})")
                    self.clear()
                    return

                state = self.STATE_TRANSFER
                current_sequence_num -= 1
                self.logger.debug(f"ACK OK, updated state to TRANSFER")
            elif state == self.STATE_TRANSFER:
                self.logger.debug(f"State: TRANSFER")

                if file_size_bytes - current_byte_position <  988:
                    file_bytes_to_send = self.file_stream.read()
                    is_last_transfer_packet = True
                else:
                    file_bytes_to_send = self.file_stream.read(988)
                    current_byte_position += 988

                self.logger.debug(f"Will send {len(file_bytes_to_send)} bytes of file data to server")

                data_packet = ZTDataPacket(current_sequence_num, file_bytes_to_send)

                try:
                    self.socket.sendall(data_packet.serialize())
                except Exception as e:
                    self.logger.error(f"Error occured while self.socket.sendall(): {e}")
                    self.clear()
                    return

                if is_last_transfer_packet:
                    state = self.STATE_FIN
                    self.logger.debug(f"Data packet OK, set state to FIN")
                else:
                    self.logger.debug(f"Data packet OK, state unchanged")

            current_sequence_num += 1

        self.logger.debug(f"State: FIN")
        self.logger.debug(f"Current sequence number: {current_sequence_num}")

        fin_packet = ZTFinishPacket(current_sequence_num)
        self.socket.sendall(fin_packet.serialize())

        self.clear()

    def clear(self):
        self.socket.close()