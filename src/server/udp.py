import os
import sys
import errno
import socket
import logging

PACKAGE_PARENT = '..'
SCRIPT_DIR = os.path.dirname(
    os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
sys.path.append(os.path.normpath(
    os.path.join(SCRIPT_DIR, PACKAGE_PARENT, PACKAGE_PARENT)))

from src.utils import get_logger, calc_sha3_512_checksum
from src.ztransfer.profiler import Profiler
from src.ztransfer.packets import (ZTConnReqPacket, ZTDataPacket,
                                   ZTAcknowledgementPacket, ZTFinishPacket,
                                   ZTResendPacket, deserialize_packet,
                                   ZT_RAW_DATA_BYTES_SIZE)
from src.ztransfer.errors import (ZTVerificationError, ERR_VERSION_MISMATCH,
                                  ERR_ZTDATA_CHECKSUM, ERR_MAGIC_MISMATCH,
                                  ERR_PTYPE_DNE)

DATA_SEQ_FIRST = 1

class ZTransferUDPServer(object):
    STATE_INIT = 0
    STATE_WAIT_CCREQ = 1
    STATE_TRANSFER = 2
    STATE_FIN = 3

    def __init__(self, bind_host: str, port_pool: list, logger_verbose: bool = False):
        self.bind_host = bind_host
        self.port_pool = port_pool
        self.port_occupied = None
        
        self.buffer_bytearray = None
        self.buffer_memview = None
        self.file_overall_checksum = None
        self.file_name = None
        self.last_data_packet_seq = None
        self.last_data_packet_data_size = None

        self.remaining_data_seqs = None

        self.client_addr = None

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.logger = get_logger("ZTransferUDPServer", logger_verbose)
        self.logger.debug(f"Constructed ZTransferUDPServer({bind_host}, {port_pool})")

    def listen_for_transfer(self):
        state = self.STATE_INIT
        curr_seq_number = 1

        while True:
            if state == self.STATE_INIT:
                self.logger.debug(f"State: INIT")

                for port in self.port_pool:
                    try:
                        self.socket.bind((self.bind_host, port))
                    except socket.error as e:
                        if e.errno == errno.EADDRINUSE:
                            continue
                    else:
                        self.port_occupied = port
                        break

                if self.port_occupied is None:
                    self.logger.error(f"Could not bind to any ports from: {self.port_pool}")
                    self.clear()
                    return

                self.logger.debug(f"Bound to port: {self.port_occupied}")

                state = self.STATE_WAIT_CCREQ
            elif state == self.STATE_WAIT_CCREQ:
                self.logger.debug(f"State: WAIT_CCREQ")

                recv_data, client_addr = self.socket.recvfrom(1000)

                self.logger.debug(f"Received {len(recv_data)} bytes from the client")

                if len(recv_data) != 1000:
                    self.logger.debug(f"Packet probably corrupt (data size != 1000), dropping packet")
                    continue

                try:
                    self.logger.debug(f"Deserializing received packet data...")
                    packet = deserialize_packet(recv_data)
                except ZTVerificationError as e:
                    if e.err_code == ERR_MAGIC_MISMATCH:
                        self.logger.warning(f"Wrong magic number '{e.extras['magic']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                    if e.err_code == ERR_VERSION_MISMATCH:
                        self.logger.warning(f"Mismatched version number '{e.extras['version']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                    if e.err_code == ERR_PTYPE_DNE:
                        self.logger.warning(f"Not known packet type '{e.extras['ptype']}' (seq: {e.extras['seq']}, ts: {e.extras['ts']})")
                    if e.err_code == ERR_ZTDATA_CHECKSUM:
                        self.logger.warning(f"Corrupt packet. (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")

                    continue

                self.logger.debug(f"Packet OK: {packet.__class__.__name__} ({packet.sequence_number})")

                if not isinstance(packet, ZTConnReqPacket):
                    self.logger.warning(f"Was waiting for CREQ, got '{packet.__class__.__name__}'")
                else:
                    # Got first packet, start profiling.
                    self.profiler = Profiler()

                    self.file_name = packet.filename
                    self.file_overall_checksum = packet.checksum
                    self.last_data_packet_seq = packet.last_seq
                    self.last_data_packet_data_size = packet.data_size - (ZT_RAW_DATA_BYTES_SIZE * (packet.last_seq - 1))

                    self.all_data_seqs = set(range(DATA_SEQ_FIRST, DATA_SEQ_FIRST + self.last_data_packet_seq))

                    self.buffer_bytearray = bytearray(packet.data_size)
                    self.buffer_memview = memoryview(self.buffer_bytearray)

                    self.client_addr = client_addr

                    ack_packet = ZTAcknowledgementPacket(curr_seq_number, packet.sequence_number)
                    self.socket.sendto(ack_packet.serialize(), self.client_addr)

                    self.logger.debug(f"Sent ACK to CREQ to server {self.client_addr}")

                    curr_seq_number += 1
                    state = self.STATE_TRANSFER
            elif state == self.STATE_TRANSFER:
                self.logger.debug(f"State: TRANSFER")

                if len(self.all_data_seqs) == 0:
                    self.logger.debug(f"All packets recvd, updated state to FIN")
                    state = self.STATE_FIN
                    continue

                recv_data, recv_addr = self.socket.recvfrom(1000)

                if recv_addr != self.client_addr:
                    # Discard packet
                    self.logger.debug(f"Another client ({recv_addr}) sent the packet, discarding.")
                    continue

                if len(recv_data) != 1000:
                    self.logger.debug(f"Packet probably corrupt (data size != 1000), dropping packet")
                    continue

                self.logger.debug(f"Received {len(recv_data)} bytes from the client")

                try:
                    self.logger.debug(f"Deserializing received packet data...")
                    packet = deserialize_packet(recv_data)
                except ZTVerificationError as e:
                    if e.err_code == ERR_MAGIC_MISMATCH:
                        self.logger.warning(f"Wrong magic number '{e.extras['magic']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                    if e.err_code == ERR_VERSION_MISMATCH:
                        self.logger.warning(f"Mismatched version number '{e.extras['version']}' (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")
                    if e.err_code == ERR_PTYPE_DNE:
                        self.logger.warning(f"Not known packet type '{e.extras['ptype']}' (seq: {e.extras['seq']}, ts: {e.extras['ts']})")
                    if e.err_code == ERR_ZTDATA_CHECKSUM:
                        self.logger.warning(f"Corrupt packet. (seq: {e.extras['seq']}, ptype: {e.extras['ptype']}, ts: {e.extras['ts']})")

                    continue

                self.logger.debug(f"Packet OK: {packet.__class__.__name__} ({packet.sequence_number})")

                if isinstance(packet, ZTDataPacket):
                    # Check for valid data seq num
                    if 1 <= packet.sequence_number <= self.last_data_packet_seq:
                        self.profiler.pkt_tick(packet)
                        
                        if packet.sequence_number == self.last_data_packet_seq:
                            self.buffer_memview[(packet.sequence_number - 1) * ZT_RAW_DATA_BYTES_SIZE : ] = packet.file_data[:self.last_data_packet_data_size]
                        else:
                            self.buffer_memview[(packet.sequence_number - 1) * ZT_RAW_DATA_BYTES_SIZE : packet.sequence_number * ZT_RAW_DATA_BYTES_SIZE] = packet.file_data

                        self.all_data_seqs.discard(packet.sequence_number)

                        ack_packet = ZTAcknowledgementPacket(curr_seq_number, packet.sequence_number)
                        self.socket.sendto(ack_packet.serialize(), self.client_addr)

                        self.logger.debug(f"Sent ACK for data packet #{packet.sequence_number}")

                        curr_seq_number += 1
                    else:
                        self.logger.debug(f"Data packet has seq out of ranges: {packet.sequence_number}, dropped.")
                elif isinstance(packet, ZTConnReqPacket):
                    ack_packet = ZTAcknowledgementPacket(curr_seq_number, packet.sequence_number)
                    self.socket.sendto(ack_packet.serialize(), self.client_addr)

                    curr_seq_number += 1
                #elif isinstance(packet, ZTFinishPacket):
                #    state = self.STATE_FIN
            elif state == self.STATE_FIN:
                buffer_checksum = calc_sha3_512_checksum(self.buffer_bytearray)

                if buffer_checksum != self.file_overall_checksum:
                    self.logger.critical(f"File checksum mismatch!")
                else:
                    self.logger.debug(f"File checksum OK")

                self.clear()
                break

    def clear(self):
        if self.socket is not None:
            self.socket.close()
