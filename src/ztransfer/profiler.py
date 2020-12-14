from datetime import datetime as dt

from .packets import ZTPacket

class Profiler(object):
    def __init__(self, start_ts: float = None):
        self.__packet_transmission_times = dict()
        self.__lost_packets_freq = dict()

        self.__start_ts = start_ts

        if self.__start_ts is None:
            self.__start_ts = dt.now().timestamp()

    def pkt_tick(self, packet: ZTPacket):
        if isinstance(packet, ZTPacket):
            self.__packet_transmission_times[packet.header.sequence_number] = dt.now().timestamp() - packet.header.timestamp

    def lost_tick(self, seq: int):
        if type(seq) == int:
            if seq not in self.__lost_packets_freq:
                self.__lost_packets_freq[seq] = 0
            
            self.__lost_packets_freq[seq] += 1

    @property
    def avg_trasmission_time(self):
        return sum(self.__packet_transmission_times.values()) / len(self.__packet_transmission_times)

    @property
    def total_transmission_time(self):
        return dt.now().timestamp() - self.__start_ts

    @property
    def lost_packet_count(self):
        return sum(self.__lost_packets_freq.values())