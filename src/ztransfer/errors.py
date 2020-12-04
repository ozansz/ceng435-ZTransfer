ERR_MAGIC_MISMATCH = 1
ERR_VERSION_MISMATCH = 2
ERR_PTYPE_DNE = 3
ERR_ZTDATA_CHECKSUM = 4

class ZTVerificationError(Exception):
    def __init__(self, code, message="Verification error", extras=None):
        self.err_code = code
        self.extras = extras if extras is not None else {}

        super().__init__(message)