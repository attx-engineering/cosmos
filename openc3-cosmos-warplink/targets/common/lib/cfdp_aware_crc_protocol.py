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


from openc3.interfaces.protocols.crc_protocol import CrcProtocol


class CfdpAwareCrcProtocol(CrcProtocol):
    """
    Same as the stock CrcProtocol, except write_packet() skips packets that
    have no item named write_item_name (e.g. "CRC") instead of raising.

    The bare-CFDP-PDU commands on this interface (e.g. STORAGE_MANAGER_CFDP)
    have no separate outer CRC field: their own inner CFDP CRC is already
    baked into the raw PDU bytes by the CFDP microservice before cmd() is
    ever called, so there's nothing for this protocol to compute or fill in
    for them. Every other (CCSDS-wrapped) command still gets the normal
    item-based CRC fill, unchanged.
    """

    def write_packet(self, packet):
        if self.write_item_name:
            try:
                packet.get_item(self.write_item_name)
            except (RuntimeError, ValueError):
                return packet
        return super().write_packet(packet)

