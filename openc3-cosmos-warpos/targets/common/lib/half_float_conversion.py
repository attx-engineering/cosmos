# half_float_conversion.py
import struct
import numpy as np
from openc3.conversions.conversion import Conversion

class HalfFloatConversion(Conversion):
    """
    Convert IEEE-754 binary16 (half.hpp) -> Python float.
    Assumes the telemetry item is defined as BIG_ENDIAN UINT16.
    """

    def __init__(self):
        super().__init__()
        self.converted_type = "FLOAT"
        self.converted_bit_size = 32

    def call(self, value, packet, buffer):
        # COSMOS already parsed the bytes into an integer
        # Now interpret the bits as a float16
        b = struct.pack(">H", value)
        return float(np.frombuffer(b, dtype=">f2")[0])
