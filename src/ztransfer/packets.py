import zlib
from struct import pack, unpack
from datetime import datetime as dt

from .errors import ERR_MAGIC_MISMATCH, ERR_VERSION_MISMATCH, ERR_PTYPE_DNE, ERR_ZTDATA_CHECKSUM, ZTVerificationError

ZT_MAGIC = b"ZT"
ZT_VERSION = 3 # v0.3

ZTHEADER_SER = "!2sBBII"
ZTPACKET_SER = "!12s988s"
ZTCONNREQ_SER = "!II64s255s"
ZTACK_SER = "!I"
ZTDATA_SER = "!I984s"
ZTPACKET_DESERIALIZE_HEADER = "!2sBBII988s"

ZTCONNREQ_TYPE = 0
ZTDATA_TYPE = 1
ZTACK_TYPE = 2
ZTFIN_TYPE = 3

class ZTHeader(object):
    def __init__(self, packet_type: int, sequence_number: int, timestamp: int = None, version: int = ZT_VERSION):
        self.version = version
        self.packet_type = packet_type
        self.sequence_number = sequence_number

        if timestamp is None:
            timestamp = int(dt.now().timestamp())

        self.timestamp = timestamp

    def serialize(self):
        return pack(
            ZTHEADER_SER,
            ZT_MAGIC,
            self.packet_type,
            self.version,
            self.timestamp,
            self.sequence_number
        )

    @classmethod
    def deserialize(cls, data: bytes):
        magic, ptype, version, ts, seq = unpack(
            ZTHEADER_SER,
            data
        )

        return magic, cls(ptype, seq, ts, version)

class ZTPacket(object):
    def __init__(self, packet_type: int, sequence_number: int, data: bytes, timestamp: int = None, version: int = ZT_VERSION):
        self.raw_data = data
        self.header = ZTHeader(packet_type, sequence_number, timestamp=timestamp, version=version)

    def serialize(self):
        return pack(
            ZTPACKET_SER,
            self.header.serialize(),
            self.raw_data
        )

class ZTConnReqPacket(ZTPacket):
    def __init__(self, sequence_number: int, data_size: int, last_seq: int, checksum: bytes, filename: str, timestamp: int = None, version: int = ZT_VERSION):
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
    def deserialize(cls, sequence_number: int, timestamp: int, version: int, raw_data: bytes):
        data_size, last_seq, checksum, filename = unpack(
            ZTCONNREQ_SER,
            raw_data[:327]
        )

        return cls(sequence_number, data_size, last_seq, checksum, filename.decode("utf8"), timestamp=timestamp, version=version)

class ZTAcknowledgementPacket(ZTPacket):
    def __init__(self, sequence_number: int, seq_to_ack: int, timestamp: int = None, version: int = ZT_VERSION):
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
    def deserialize(cls, sequence_number: int, timestamp: int, version: int, raw_data: bytes):
        seq_to_ack = unpack(
            ZTACK_SER,
            raw_data[:4]
        )[0]

        return cls(sequence_number, seq_to_ack, timestamp=timestamp, version=version)

class ZTDataPacket(ZTPacket):
    def __init__(self, sequence_number: int, data: bytes, timestamp: int = None, version: int = ZT_VERSION):
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.version = version

        self.file_data = data

        crc_checksum = zlib.crc32(pack("!984s", data)) & 0xffffffff
        
        raw_data = pack(
            ZTDATA_SER,
            crc_checksum,
            data
        )

        super().__init__(ZTDATA_TYPE, sequence_number, raw_data, timestamp=timestamp, version=version)
        
    @classmethod
    def deserialize(cls, sequence_number: int, timestamp: int, version: int, raw_data: bytes):
        crc_checksum, pkg_data = unpack(
            ZTDATA_SER,
            raw_data
        )

        pkg_data_checksum = zlib.crc32(pkg_data) & 0xffffffff

        if pkg_data_checksum != crc_checksum:
            raise ZTVerificationError(ERR_ZTDATA_CHECKSUM, extras={
                "checksum": pkg_data_checksum,
                "seq": sequence_number,
                "ts": timestamp,
                "version": version
            })

        return cls(sequence_number, pkg_data, timestamp=timestamp, version=version)

class ZTFinishPacket(ZTPacket):
    def __init__(self, sequence_number: int, timestamp: int = None, version: int = ZT_VERSION):
        self.sequence_number = sequence_number
        self.timestamp = timestamp
        self.version = version

        super().__init__(ZTFIN_TYPE, sequence_number, b"", timestamp=timestamp, version=version)

    @classmethod
    def deserialize(cls, sequence_number: int, timestamp: int, version: int, raw_data: bytes):
        return cls(sequence_number, timestamp=timestamp, version=version)

def deserialize_packet(data: bytes):
    _ptype_class_mapper = {
        ZTCONNREQ_TYPE: ZTConnReqPacket,
        ZTACK_TYPE: ZTAcknowledgementPacket,
        ZTDATA_TYPE: ZTDataPacket,
        ZTFIN_TYPE: ZTFinishPacket
    }

    magic, ptype, version, ts, seq, raw_data = unpack(
        ZTPACKET_DESERIALIZE_HEADER,
        data
    )

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