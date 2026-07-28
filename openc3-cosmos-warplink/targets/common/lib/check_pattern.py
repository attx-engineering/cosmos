# ...imports...
from openc3.interfaces.protocols.protocol import Protocol
from typing import Optional, Union

BIT_RULES = [
    (0, [0,0,0,0,1]),       # Bits 0-4
    (16, [1,1]),            # Bits 16-17
    (104, [1,0,1,1,1,0,1,1])# Bits 104-111
]

class CheckPattern(Protocol):
    """ Class to handle checking for a specific bit pattern in a byte stream.
        This pattern matches the specific CCSDS Header bits as defined by
        WarpOS. This class allows us to extract CCSDS packets from a raw bitstream and
        pass them to the WarpLink protocol handler.

    Args:
        Protocol (openC3 object): Inheritss from Protocol base class
    """
    def __init__(self, max_length = 250, allow_empty_data = None):
        """ Sets the internal buffer and checks max length of packets passed in

        Args:
            max_length (int, optional): Max length of a packet received. Defaults to 250.
            allow_empty_data (bool, optional): Used by base class, not used. Defaults to None.
        """
        super().__init__(allow_empty_data=allow_empty_data)
        self.max_length = max_length

        # internal buffer for accumulating read bytes
        self._buffer = bytearray()

    def reset(self): self._buffer = bytearray()
    def connect_reset(self): self.reset()
    def disconnect_reset(self): self.reset()

    @staticmethod
    def _bit_from_bytes(buf: bytes, bit_index: int) -> int | None:
        """ Return the bit value (0 or 1) at the given bit index from the byte buffer.
            If the bit index is out of range, return None."""
        byte_index = bit_index // 8
        bit_offset = bit_index % 8
        if byte_index >= len(buf):
            return None
        # MSB-first (bit 7 is first)
        return (buf[byte_index] >> (7 - bit_offset)) & 1

    def _pattern_matches(self, buf: bytes, start_bit: int) -> bool:
        """Checks to see if the bits scanned match the pattern of the CCSDS
            Header as defined by BIT_RULES. Used to identify the start of a CCSDS packet.

        Args:
            buf (bytes): buffer of bytes that potentially holds the pattern of bits
            start_bit (int): Bit to start checking at

        Returns:
            bool: If the pattern matches the expected bit pattern
        """
        for base, bits in BIT_RULES:
            for i, expected in enumerate(bits):
                bit_idx = start_bit + base + i
                actual = self._bit_from_bytes(buf, bit_idx)
                if actual is None or actual != expected:
                    return False
        return True

    def _packet_full_len(self, buf: bytes) -> int:
        """ Checks the length of the packet using the CCSDS length value and
            ensures the buffer has enough bytes for the full packet.

        Args:
            buf (bytes): a buffer of bytes starting with a CCSDS packet

        Returns:
            int: Length of the full packet if enough bytes are present,
                 0 if not enough bytes are present,
                 -1 if the length is beyond the maximum allowed length
        """
        # Build the length based off the bytes (length is at bytes 5 and 6)
        if len(buf) < 6:
            # If there are not enough bytes, return 0
            return 0
        # CCSDS "length" = total_length - 6
        size = int.from_bytes(buf[4:6], "big", signed=False)
        full_length = size + 7
        if size <= 0 or full_length > self.max_length:
            # If there are too many bytes, we aren't reading it correctly
            return -1
        if len(buf) < full_length:
            # Check that the length of the buffer is large enough for the telem
            # Note: CCSDS Size does not include 6 primary header bytes
            return 0

        return full_length

    def read_data(self, data, extra=None):
        """ Reads in the data of bytes passed from the WarpLink system. Overrides openC3 protocol method

        Args:
            data (bytes): Data bytes passed from WarpLink. If 0 length, there are no new packets
            extra (_type_, optional): Used to pass extra information and not used here. Defaults to None.

        Returns:
            bytes, extra: Packet of bytes if a full packet is found, otherwise "STOP"
        """
        # Mirror base behavior for empty data
        if data is None or (hasattr(data, "__len__") and len(data) == 0 and len(self._buffer) == 0):
            return super().read_data(data, extra)

        if isinstance(data, (bytearray, bytes)):
            data = bytes(data)
        else:
            return ("STOP", extra)

        self._buffer.extend(data)
        total_bits = len(self._buffer) * 8

        # Search possible bit start positions where pattern fits
        # Need at least up to bit 127 from start, so stop earlier if not enough bits
        pattern_length = max(base + len(bits) for base, bits in BIT_RULES)  # e.g., 112 for the rules above
        if total_bits < pattern_length:
            return ("STOP", extra)

        # Scan bit-by-bit for the sync
        for start_bit in range(0, total_bits - pattern_length + 1):
            # Only parse a CCSDS header if this pattern begins on a byte boundary.
            if self._pattern_matches(self._buffer, start_bit):
                # Build the output buffer
                start_byte = start_bit // 8
                view = bytes(self._buffer[start_byte:])

                # Check the length value
                full_length = self._packet_full_len(view)
                if full_length < 0:
                    # Length is beyond expected maximum, continue the scanning
                    continue
                if full_length == 0:
                    # Not enough bytes yet for the length described
                    return ("STOP", extra)


                # We have a whole packet
                out = view[:full_length]
                # Consume used data up to end of the packet
                del self._buffer[: start_byte + full_length]
                return (out, extra)

        # Keep only the overlap necessary for a future match. Only hit if we didn't find any packets
        keep = (pattern_length + 8) // 8 + 6
        if len(self._buffer) > keep:
            del self._buffer[:-keep]
        return ("STOP", extra)

    # Pass-throughs
    def read_packet(self, packet): return packet
    def write_packet(self, packet): return packet
    def write_data(self, data): return data
    def post_write_interface(self, packet, data): return None
    def protocol_cmd(self, cmd_name, *args): return False
