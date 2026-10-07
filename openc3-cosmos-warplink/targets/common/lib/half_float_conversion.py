# Copyright 2022 Ball Aerospace & Technologies Corp.
# All Rights Reserved.
#
# This program is free software; you can modify and/or redistribute it
# under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation; version 3 with
# attribution addendums as found in the LICENSE.txt
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# Modified by OpenC3, Inc.
# All changes Copyright 2025, OpenC3, Inc.
# All Rights Reserved
#
# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.
#
# Modified by ATTX, Inc.
# All changes Copyright 2026, ATTX, Inc.
# All Rights Reserved

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
