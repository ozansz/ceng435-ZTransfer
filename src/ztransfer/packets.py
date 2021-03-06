import zlib
from struct import pack, unpack
from datetime import datetime as dt

from .errors import ERR_MAGIC_MISMATCH, ERR_VERSION_MISMATCH, ERR_PTYPE_DNE, ERR_ZTDATA_CHECKSUM, ZTVerificationError

ZT_RAW_DATA_BYTES_SIZE = 980

ZT_MAGIC = b"ZT"
ZT_VERSION = 5 # v0.5

ZTHEADER_SER = "!2sBBdII"
ZTPACKET_SER = f"!20s{ZT_RAW_DATA_BYTES_SIZE}s"
ZTCONNREQ_SER = "!II64s255s"
ZTACK_SER = "!I"
ZTRSND_SER = "!I"
ZTDATA_SER = f"!{ZT_RAW_DATA_BYTES_SIZE}s"
ZTPACKET_DESERIALIZE_HEADER = f"!2sBBdII{ZT_RAW_DATA_BYTES_SIZE}s"
ZTPACKET_CRC_SER = f"!2sBBdI{ZT_RAW_DATA_BYTES_SIZE}s"

ZTCONNREQ_TYPE = 0
ZTDATA_TYPE = 1
ZTACK_TYPE = 2
ZTFIN_TYPE = 3
ZTRSND_TYPE = 4

class ZTHeader(object):
    def __init__(self, packet_type: int, sequence_number: int, checksum: bytes = None, timestamp: float = None, version: int = ZT_VERSION):
        self.version = version
        self.packet_type = packet_type
        self.sequence_number = sequence_number
        self.checksum = checksum if checksum is not None else b""

        if timestamp is None:
            timestamp = dt.now().timestamp()

        self.timestamp = timestamp

    def update_checksum(self, raw_packet_data: bytes):
        self.checksum = zlib.crc32(pack(ZTPACKET_CRC_SER, ZT_MAGIC, self.packet_type,
            self.version, self.timestamp, self.sequence_number, raw_packet_data)) & 0xffffffff

    def serialize(self):
        return pack(
            ZTHEADER_SER,
            ZT_MAGIC,
            self.packet_type,
            self.version,
            self.timestamp,
            self.sequence_number,
            self.checksum
        )

    @classmethod
    def deserialize(cls, data: bytes):
        magic, ptype, version, ts, seq, chk = unpack(
            ZTHEADER_SER,
            data
        )

        return magic, cls(ptype, seq, chk, ts, version)

class ZTPacket(object):
    def __init__(self, packet_type: int, sequence_number: int, data: bytes, timestamp: float = None, version: int = ZT_VERSION):
        self.raw_data = data
        self.header = ZTHeader(packet_type, sequence_number, timestamp=timestamp, version=version)
        self.header.update_checksum(data)

    def serialize(self):
        return pack(
            ZTPACKET_SER,
            self.header.serialize(),
            self.raw_data
        )

class ZTConnReqPacket(ZTPacket):
    def __init__(self, sequence_number: int, data_size: int, last_seq: int, checksum: bytes, filename: str, timestamp: float = None, version: int = ZT_VERSION):
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.version = version

        self.data_size = data_size
        self.last_seq = last_seq
        self.checksum = checksum
        self.filename = filename

        raw_data = pack(
            ZTCONNREQ_SER,
            data_size,
            last_seq,
            checksum,
            filename.encode("utf8")
        )

        super().__init__(ZTCONNREQ_TYPE, sequence_number, raw_data, timestamp=timestamp, version=version)

    @classmethod
    def deserialize(cls, sequence_number: int, timestamp: float, version: int, raw_data: bytes):
        data_size, last_seq, checksum, filename = unpack(
            ZTCONNREQ_SER,
            raw_data[:327]
        )

        return cls(sequence_number, data_size, last_seq, checksum, filename.decode("utf8"), timestamp=timestamp, version=version)

class ZTAcknowledgementPacket(ZTPacket):
    def __init__(self, sequence_number: int, seq_to_ack: int, timestamp: float = None, version: int = ZT_VERSION):
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.version = version

        self.seq_to_ack = seq_to_ack

        raw_data = pack(
            ZTACK_SER,
            seq_to_ack
        )

        super().__init__(ZTACK_TYPE, sequence_number, raw_data, timestamp=timestamp, version=version)

    @classmethod
    def deserialize(cls, sequence_number: int, timestamp: float, version: int, raw_data: bytes):
        seq_to_ack = unpack(
            ZTACK_SER,
            raw_data[:4]
        )[0]

        return cls(sequence_number, seq_to_ack, timestamp=timestamp, version=version)

class ZTResendPacket(ZTPacket):
    def __init__(self, sequence_number: int, seq_to_rsnd: int, timestamp: float = None, version: int = ZT_VERSION):
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.version = version

        self.seq_to_rsnd = seq_to_rsnd

        raw_data = pack(
            ZTRSND_SER,
            seq_to_rsnd
        )

        super().__init__(ZTRSND_TYPE, sequence_number, raw_data, timestamp=timestamp, version=version)

    @classmethod
    def deserialize(cls, sequence_number: int, timestamp: float, version: int, raw_data: bytes):
        seq_to_rsnd = unpack(
            ZTRSND_SER,
            raw_data[:4]
        )[0]

        return cls(sequence_number, seq_to_rsnd, timestamp=timestamp, version=version)
class ZTDataPacket(ZTPacket):
    def __init__(self, sequence_number: int, data: bytes, timestamp: float = None, version: int = ZT_VERSION):
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.version = version

        self.file_data = data
        
        raw_data = pack(
            ZTDATA_SER,
            data
        )

        super().__init__(ZTDATA_TYPE, sequence_number, raw_data, timestamp=timestamp, version=version)
        
    @classmethod
    def deserialize(cls, sequence_number: int, timestamp: float, version: int, raw_data: bytes):
        pkg_data = unpack(
            ZTDATA_SER,
            raw_data
        )[0]

        return cls(sequence_number, pkg_data, timestamp=timestamp, version=version)

class ZTFinishPacket(ZTPacket):
    def __init__(self, sequence_number: int, timestamp: float = None, version: int = ZT_VERSION):
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.version = version

        super().__init__(ZTFIN_TYPE, sequence_number, b"", timestamp=timestamp, version=version)

    @classmethod
    def deserialize(cls, sequence_number: int, timestamp: float, version: int, raw_data: bytes):
        return cls(sequence_number, timestamp=timestamp, version=version)

def deserialize_packet(data: bytes):
    _ptype_class_mapper = {
        ZTCONNREQ_TYPE: ZTConnReqPacket,
        ZTACK_TYPE: ZTAcknowledgementPacket,
        ZTDATA_TYPE: ZTDataPacket,
        ZTFIN_TYPE: ZTFinishPacket,
        ZTRSND_TYPE: ZTResendPacket
    }

    magic, ptype, version, ts, seq, chksum, raw_data = unpack(
        ZTPACKET_DESERIALIZE_HEADER,
        data
    )

    pkt_checksum = zlib.crc32(pack(ZTPACKET_CRC_SER, ZT_MAGIC, ptype,
        version, ts, seq, raw_data)) & 0xffffffff

    if pkt_checksum != chksum:
        raise ZTVerificationError(ERR_ZTDATA_CHECKSUM, extras={
            "checksum": pkt_checksum,
            "seq": seq,
            "ts": ts,
            "version": version,
            "ptype": ptype
        })

    if magic != ZT_MAGIC:
        raise ZTVerificationError(ERR_MAGIC_MISMATCH, extras={
            "seq": seq,
            "ts": ts,
            "version": version,
            "magic": magic,
            "ptype": ptype
        })

    if version != ZT_VERSION:
        raise ZTVerificationError(ERR_VERSION_MISMATCH, extras={
            "seq": seq,
            "ts": ts,
            "version": version,
            "magic": magic,
            "ptype": ptype
        })

    _cls = _ptype_class_mapper.get(ptype, None)

    if _cls is None:
        raise ZTVerificationError(ERR_PTYPE_DNE, extras={
            "seq": seq,
            "ts": ts,
            "version": version,
            "magic": magic,
            "ptype": ptype
        })

    return _cls.deserialize(seq, ts, version, raw_data)