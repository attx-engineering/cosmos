###############################################################################
# Copyright (c) ATTX, Inc. 2026. All Rights Reserved.
#
# This software and associated documentation (the "Software") are the
# proprietary and confidential information of ATTX, LLC. The Software is
# furnished under a license agreement between ATTX and the user organization
# and may be used or copied only in accordance with the terms of the agreement.
# Refer to 'license/attx_license.adoc' for standard license terms.
#
# EXPORT CONTROL NOTICE: THIS SOFTWARE MAY INCLUDE CONTENT CONTROLLED UNDER THE
# INTERNATIONAL TRAFFIC IN ARMS REGULATIONS (ITAR) OR THE EXPORT ADMINISTRATION
# REGULATIONS (EAR99). No part of the Software may be used, reproduced, or
# transmitted in any form or by any means, for any purpose, without the express
# written permission of ATTX, LLC.
###############################################################################

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
