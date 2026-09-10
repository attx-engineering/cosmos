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
