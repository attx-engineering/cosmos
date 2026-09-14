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


from openc3.interfaces.protocols.protocol import Protocol


SSP_MIN_HEADER_SIZE = 14
CFDP_FIXED_HEADER_SIZE = 4


class CheckPattern(Protocol):
    def __init__(self, max_length=512, allow_empty_data=None):
        super().__init__(allow_empty_data=allow_empty_data)
        self.max_length = int(max_length)
        self._buffer = bytearray()

    def reset(self):
        self._buffer = bytearray()

    def connect_reset(self):
        self.reset()

    def disconnect_reset(self):
        self.reset()

    @staticmethod
    def _is_ssp_header(buf: bytes) -> bool:
        if len(buf) < SSP_MIN_HEADER_SIZE:
            return False

        return (
            (buf[0] & 0xF8) == 0x08
            and (buf[2] & 0xC0) == 0xC0
            and buf[13] == 0xBB
        )

    @staticmethod
    def _is_cfdp_header(buf: bytes) -> bool:
        if len(buf) < CFDP_FIXED_HEADER_SIZE:
            return False

        # Octet 1: 001xxx10
        # Version 1, CFDP CRC enabled, small-file mode.
        first_octet_valid = (buf[0] & 0xE3) == 0x22

        # Octet 4: 00010xxx
        # Unsegmented, 2-byte entity IDs, no segment metadata.
        fourth_octet_valid = (buf[3] & 0xF8) == 0x10

        return first_octet_valid and fourth_octet_valid

    def _ssp_full_length(self, buf: bytes) -> int:
        if len(buf) < 6:
            return 0

        packet_length = int.from_bytes(buf[4:6], "big")
        full_length = packet_length + 7

        if full_length < SSP_MIN_HEADER_SIZE:
            return -1

        if full_length > self.max_length:
            return -1

        if len(buf) < full_length:
            return 0

        return full_length

    def _cfdp_full_length(self, buf: bytes) -> int:
        if len(buf) < CFDP_FIXED_HEADER_SIZE:
            return 0

        data_length = int.from_bytes(buf[1:3], "big")

        entity_id_length = ((buf[3] >> 4) & 0x07) + 1
        sequence_number_length = (buf[3] & 0x07) + 1

        # Your implementation requires two-byte entity IDs.
        if entity_id_length != 2:
            return -1

        header_length = (
            CFDP_FIXED_HEADER_SIZE
            + (2 * entity_id_length)
            + sequence_number_length
        )

        # No separate outer CRC.
        # The inner CFDP CRC is already included in data_length.
        full_length = header_length + data_length

        if full_length > self.max_length:
            return -1

        if len(buf) < full_length:
            return 0

        return full_length

    def read_data(self, data, extra=None):
        if data is None or (
            hasattr(data, "__len__")
            and len(data) == 0
            and len(self._buffer) == 0
        ):
            return super().read_data(data, extra)

        if not isinstance(data, (bytes, bytearray)):
            return ("STOP", extra)

        self._buffer.extend(data)

        for start_byte in range(len(self._buffer)):
            view = bytes(self._buffer[start_byte:])

            if self._is_cfdp_header(view):
                full_length = self._cfdp_full_length(view)
            elif self._is_ssp_header(view):
                full_length = self._ssp_full_length(view)
            else:
                continue

            if full_length < 0:
                continue

            if full_length == 0:
                if start_byte > 0:
                    del self._buffer[:start_byte]
                return ("STOP", extra)

            packet = view[:full_length]
            del self._buffer[:start_byte + full_length]

            return (packet, extra)

        # Preserve enough bytes for a header split between reads.
        keep = SSP_MIN_HEADER_SIZE - 1
        if len(self._buffer) > keep:
            del self._buffer[:-keep]

        return ("STOP", extra)

    def read_packet(self, packet):
        return packet

    def write_packet(self, packet):
        return packet

    def write_data(self, data):
        return data

    def post_write_interface(self, packet, data):
        return None

    def protocol_cmd(self, cmd_name, *args):
        return False
