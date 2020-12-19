import os
import io
import sys
import errno
import signal
import socket
import logging

PACKAGE_PARENT = '..'
SCRIPT_DIR = os.path.dirname(
    os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
sys.path.append(os.path.normpath(
    os.path.join(SCRIPT_DIR, PACKAGE_PARENT, PACKAGE_PARENT)))

from src.config import get_config
from src.utils import get_logger, calc_sha3_512_checksum
from src.ztransfer.packets import (ZTConnReqPacket, ZTDataPacket,
                                   ZTAcknowledgementPacket, ZTFinishPacket,
                                   ZTResendPacket, deserialize_packet,
                                   ZT_RAW_DATA_BYTES_SIZE)
from src.ztransfer.errors import (ZTVerificationError, ERR_VERSION_MISMATCH,
                                  ERR_ZTDATA_CHECKSUM, ERR_MAGIC_MISMATCH,
                                  ERR_PTYPE_DNE)

config = get_config()

CREQ_SEQ = 0
DATA_SEQ_FIRST = 1

CREQ_TIMER_DURATION = config["udp"]["client"].get("creq_timer_duration", 1)
RAPID_RECV_TIMER_DURATION = config["udp"]["client"].get("rapid_recv_timer_duraton", 1)
MAX_RESENDS_BEFORE_TIMEOUT = config["udp"]["client"].get("max_resends_before_timeout", 20)

WINDOW_SIZE_START = config["udp"]["client"].get("window_size_start", 100)
WINDOW_SIZE_INC_RAP = config["udp"]["client"].get("window_increase_factor_rapid_start", 2)
WINDOW_SIZE_INC_REG = config["udp"]["client"].get("window_increase_factor_regular", 10)
WINDOW_SIZE_DEC_REG = config["udp"]["client"].get("window_decrease_factor_regular", 2)
WS_RAPID_START_MAX = config["udp"]["client"].get("ws_rapid_start_max", 1000)

class CREQTimeout(Exception):
    pass

class RRecvTimeout(Exception):
    pass

class ZTransferUDPClient(object):
    STATE_INIT = 0
    STATE_WAIT_CREQ_ACK = 1
    STATE_RAPID_SEND = 2
    STATE_RAPID_RECV = 3
    STATE_FIN = 4

    def __init__(self, server_host: str, server_port: int, port_pool: list, file_name: str, file_stream: io.BytesIO, logger_verbose: bool = False):
        self.server_addr = (server_host, server_port)
        self.port_pool = port_pool
        self.port_occupied = None

        self.file_name = file_name
        self.file_stream = file_stream
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.acked_packet_seqs = set()
        self.all_data_seqs = set()
        self.to_send_seqs = set()
        self.session_sent_seqs = set()

        self.failed_packet_count = 0
        self._server_disconnect_ctr = 0
        self._acks_got_up_to_timeout = 0

        self.old_drop_factor = 100
        self.window_size = WINDOW_SIZE_START
        self.__in_rapid_start = True

        self.buffer_memview = None

        self.logger = get_logger("ZTransferUDPClient", logger_verbose)
        self.logger.debug(f"Constructed ZTransferUDPClient({server_host}, {server_port}, ...)")

        self.logger.debug(f"WINDOW_SIZE: {self.window_size}")
        self.logger.debug(f"CREQ_TIMER_DURATION: {CREQ_TIMER_DURATION}")
        self.logger.debug(f"RAPID_RECV_TIMER_DURATION: {RAPID_RECV_TIMER_DURATION}")

    def _creq_timer_handler(self, *args, **kwargs):
        raise CREQTimeout()

    def _rrecv_timer_handler(self, *args, **kwargs):
        raise RRecvTimeout()

    def initiate_transfer(self):
        self.buffer_memview = self.file_stream.getbuffer()
        file_size_bytes = self.buffer_memview.nbytes
        num_data_packets = file_size_bytes // ZT_RAW_DATA_BYTES_SIZE

        if file_size_bytes % ZT_RAW_DATA_BYTES_SIZE > 0:
            num_data_packets += 1

        self.last_data_seq = DATA_SEQ_FIRST + num_data_packets - 1
        self.all_data_seqs = set(range(DATA_SEQ_FIRST, DATA_SEQ_FIRST + num_data_packets))

        file_checksum = calc_sha3_512_checksum(self.file_stream.getvalue())
        state = self.STATE_INIT

        self.logger.debug(f"File size: {file_size_bytes} bytes")
        self.logger.debug(f"File checksum (SHA3-512): {file_checksum[:10]}...")
        self.logger.debug(f"Total {num_data_packets} data packets will be sent")

        while True:
            try:   
                if state == self.STATE_INIT:
                    self.logger.debug(f"State: INIT")
                    
                    for port in self.port_pool:
                        try:
                            self.socket.bind(("0.0.0.0", port))
                        except socket.error as e:
                            if e.errno == errno.EADDRINUSE:
                                continue
                        else:
                            self.port_occupied = port
                            break

                    if self.port_occupied is None:
                        self.logger.critical(f"Could not bind to any ports from: {self.port_pool}")
                        self.clear()
                        return

                    self.logger.debug(f"Bound to port: {self.port_occupied}")

                    self._creq_packet = ZTConnReqPacket(CREQ_SEQ, file_size_bytes,
                        self.last_data_seq, file_checksum, self.file_name)

                    try:
                        self.socket.sendto(self._creq_packet.serialize(), self.server_addr)
                    except Exception as e:
                        self.logger.critical(f"Error occured while self.socket.sendto(): {e}")
                        self.clear()
                        return

                    signal.signal(signal.SIGALRM, self._creq_timer_handler)
                    signal.alarm(CREQ_TIMER_DURATION)

                    state = self.STATE_WAIT_CREQ_ACK

                    self.logger.debug(f"Sent CREQ packet and updated state to WAIT_CREQ_ACK")
                elif state == self.STATE_WAIT_CREQ_ACK:
                    self.logger.debug(f"State: WAIT_CREQ_ACK")

                    recv_data, server_addr = self.socket.recvfrom(1000)

                    self.logger.debug(f"Received {len(recv_data)} bytes from the server")

                    if server_addr != self.server_addr:
                        # Discard packet
                        self.logger.debug(f"Another server ({server_addr}) sent the packet, discarding.")
                        continue

                    if len(recv_data) != 1000:
                        self.logger.debug(f"Packet probably corrupt (data size != 1000), resending CREQ packet")
                        
                        # Stop CREQ timer
                        signal.alarm(0)

                        try:
                            self.socket.sendto(self._creq_packet.serialize(), self.server_addr)
                        except Exception as e:
                            self.logger.critical(f"Error occured while self.socket.sendto(): {e}")
                            self.clear()
                            return

                        signal.signal(signal.SIGALRM, self._creq_timer_handler)
                        signal.alarm(CREQ_TIMER_DURATION)

                        self.logger.debug(f"Sent CREQ packet again and restarted timer")
                        continue

                    try:
                        self.logger.debug(f"Deserializing received packet data...")
                        packet = deserialize_packet(recv_data)
                    except ZTVerificationError as e:
                        # Stop CREQ timer
                        signal.alarm(0)

                        try:
                            self.socket.sendto(self._creq_packet.serialize(), self.server_addr)
                        except Exception as e:
                            self.logger.critical(f"Error occured while self.socket.sendto(): {e}")
                            self.clear()
                            return

                        signal.signal(signal.SIGALRM, self._creq_timer_handler)
                        signal.alarm(CREQ_TIMER_DURATION)

                        self.logger.debug(f"Sent CREQ packet again and restarted timer")
                    else:
                        self.logger.debug(f"Packet OK: {packet.__class__.__name__} ({packet.sequence_number})")

                        if not isinstance(packet, ZTAcknowledgementPacket):
                            self.logger.warning(f"Was waiting for ACK, got '{packet.ptype}'")
                            
                            # Stop CREQ timer
                            signal.alarm(0)

                            try:
                                self.socket.sendto(self._creq_packet.serialize(), self.server_addr)
                            except Exception as e:
                                self.logger.critical(f"Error occured while self.socket.sendto(): {e}")
                                self.clear()
                                return

                            signal.signal(signal.SIGALRM, self._creq_timer_handler)
                            signal.alarm(CREQ_TIMER_DURATION)

                            self.logger.debug(f"Sent CREQ packet again and restarted timer")
                        else:
                            if packet.seq_to_ack != CREQ_SEQ:
                                # Stop CREQ timer
                                signal.alarm(0)

                                try:
                                    self.socket.sendto(self._creq_packet.serialize(), self.server_addr)
                                except Exception as e:
                                    self.logger.critical(f"Error occured while self.socket.sendto(): {e}")
                                    self.clear()
                                    return

                                signal.signal(signal.SIGALRM, self._creq_timer_handler)
                                signal.alarm(CREQ_TIMER_DURATION)

                                self.logger.debug(f"Sent CREQ packet again and restarted timer")
                            else:
                                # Stop CREQ timer
                                signal.alarm(0)

                                state = self.STATE_RAPID_SEND
                                self.logger.debug(f"ACK OK, updated state to RAPID_SEND")
                elif state == self.STATE_RAPID_SEND:
                    self.logger.debug(f"State: RAPID_SEND")

                    # Ensure timer is stopped
                    signal.alarm(0)

                    self.failed_packet_count += len(self.session_sent_seqs - self.acked_packet_seqs)

                    self.to_send_seqs = self.all_data_seqs - self.acked_packet_seqs
                    self.session_sent_seqs = set()
                    self.session_acked_seqs = set()

                    if len(self.to_send_seqs) == 0:
                        state = self.STATE_FIN
                        self.logger.debug(f"Got all ACKs, updated state to FIN")
                        continue

                    _window_ctr = 0

                    for packet_seq in self.to_send_seqs:
                        if _window_ctr >= self.window_size:
                            break

                        self.file_stream.seek((packet_seq - 1) * ZT_RAW_DATA_BYTES_SIZE)

                        if packet_seq == self.last_data_seq:
                            _data_bytes = self.file_stream.read()
                        else:
                            _data_bytes = self.file_stream.read(ZT_RAW_DATA_BYTES_SIZE)
                            
                        data_packet = ZTDataPacket(packet_seq, _data_bytes)
                        self.logger.debug(f"==> Data pkt #{packet_seq} ({(packet_seq - 1) * ZT_RAW_DATA_BYTES_SIZE}:{(packet_seq - 1) * ZT_RAW_DATA_BYTES_SIZE + len(_data_bytes)})")

                        try:
                            self.socket.sendto(data_packet.serialize(), self.server_addr)
                        except Exception as e:
                            self.logger.critical(f"Error occured while self.socket.sendto(): {e}")
                            self.clear()
                            return
                        
                        self.session_sent_seqs.add(packet_seq)
                        _window_ctr += 1

                    signal.signal(signal.SIGALRM, self._rrecv_timer_handler)
                    signal.alarm(RAPID_RECV_TIMER_DURATION)

                    self._acks_got_up_to_timeout = 0
                    state = self.STATE_RAPID_RECV
                    self.logger.debug(f"Sent {len(self.to_send_seqs)} data packets and started RAPID_RECV timer")
                elif state == self.STATE_RAPID_RECV:
                    self.logger.debug(f"State: RAPID_RECV")

                    if self.acked_packet_seqs == self.all_data_seqs:
                        signal.alarm(0)
                        state = self.STATE_FIN
                        self.logger.debug(f"Got all ACKs, updated state to FIN")
                        continue

                    if self.session_sent_seqs.issubset(self.acked_packet_seqs):
                        self.logger.debug(f"All window packets ACKed, updated state to RAPID_SEND")

                        self.to_send_seqs = self.all_data_seqs - self.acked_packet_seqs
                        state = self.STATE_RAPID_SEND
                        continue

                    recv_data, server_addr = self.socket.recvfrom(1000)

                    self.logger.debug(f"Received {len(recv_data)} bytes from the server")

                    if server_addr != self.server_addr:
                        # Discard packet
                        self.logger.debug(f"Another server ({server_addr}) sent the packet, discarding.")
                        continue

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

                    if isinstance(packet, ZTAcknowledgementPacket):
                        if DATA_SEQ_FIRST <= packet.seq_to_ack <= (2**32 - 2):
                            self.acked_packet_seqs.add(packet.seq_to_ack)
                            self.session_acked_seqs.add(packet.seq_to_ack)
                            self.logger.debug(f"ACK received for data packet #{packet.seq_to_ack}")

                            self._acks_got_up_to_timeout += 1
                        else:
                            self.logger.debug(f"ACK packet has seq_to_ack out of ranges: {packet.seq_to_ack}, dropped.")
                    elif isinstance(packet, ZTResendPacket):
                        if DATA_SEQ_FIRST <= packet.seq_to_rsnd <= (2**32 - 2):
                            self.acked_packet_seqs.discard(packet.seq_to_rsnd)
                            self.session_acked_seqs.discard(packet.seq_to_rsnd)
                            self.logger.debug(f"RSND received for data packet #{packet.seq_to_rsnd}")

                            self._acks_got_up_to_timeout += 1
                        else:
                            self.logger.debug(f"RSND packet has seq_to_rsnd out of ranges: {packet.seq_to_rsnd}, dropped.")
                    elif isinstance(packet, ZTFinishPacket):
                        self.logger.debug(f"Received FIN packet, premature finish, updated state to FIN.")
                        state = self.STATE_FIN
                        continue
                    else:
                        self.logger.warning(f"Was waiting for ACK or RSND, got '{packet.ptype}', discarded.")
                        pass
                elif state == self.STATE_FIN:
                    self.logger.debug(f"State: FIN")
                    self.clear()
                    break
            except CREQTimeout:
                self.logger.debug(f"Timeout: Hit to CREQTimeout")

                try:
                    self.socket.sendto(self._creq_packet.serialize(), self.server_addr)
                except Exception as e:
                    self.logger.critical(f"Error occured while self.socket.sendto(): {e}")
                    self.clear()
                    return

                signal.signal(signal.SIGALRM, self._creq_timer_handler)
                signal.alarm(CREQ_TIMER_DURATION)

                self.logger.debug(f"Sent CREQ packet again and restarted timer")
            except RRecvTimeout:
                self.logger.debug(f"Timeout: Hit to RRecvTimeout")

                if self._acks_got_up_to_timeout == 0:
                    self._server_disconnect_ctr += 1
                else:
                    self._server_disconnect_ctr = 0

                self.logger.debug(f"server_disconnect_ctr: {self._server_disconnect_ctr}")
                
                if self._server_disconnect_ctr >= MAX_RESENDS_BEFORE_TIMEOUT:
                    # Server is probably down.
                    self.logger.debug(f"Resent the same window for {self._server_disconnect_ctr} times. The server is probably down. Updated state to FIN.")
                    state = self.STATE_FIN
                else:
                    # This must not be but for protection anyway
                    if len(self.session_sent_seqs) > 0:
                        drop_factor = len(self.session_sent_seqs - self.session_acked_seqs) / len(self.session_sent_seqs)
                        drop_factor *= 100

                        if drop_factor < self.old_drop_factor:
                            self.logger.debug(f"Drop factor ({drop_factor}) is less than old one ({self.old_drop_factor})")

                            if self.__in_rapid_start:
                                self.window_size *= WINDOW_SIZE_INC_RAP
                            else:
                                self.window_size += WINDOW_SIZE_INC_REG
                        else:
                            self.logger.debug(f"Drop factor ({drop_factor}) is greater than old one ({self.old_drop_factor})")

                            self.window_size = max(WINDOW_SIZE_START, self.window_size / WINDOW_SIZE_DEC_REG)
                            self.__in_rapid_start = False

                        self.old_drop_factor = drop_factor

                        self.logger.debug(f"New window size: {self.window_size}")

                    self.to_send_seqs = self.all_data_seqs - self.acked_packet_seqs
                    state = self.STATE_RAPID_SEND
            except Exception as e:
                self.logger.critical(f"UNEXPECTED: {e}")
                self.clear()
                return

    def clear(self):
        self.socket.close()
