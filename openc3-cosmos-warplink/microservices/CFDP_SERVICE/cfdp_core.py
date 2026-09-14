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


# microservices/CFDP_SERVICE/cfdp_core.py
#
# CFDP core logic for the OpenC3 CFDP microservice.
#
# This file intentionally contains no OpenC3 API calls. It only knows how to:
#   1. Parse inbound CFDP PDUs and reconstruct received files.
#   2. Build outbound CFDP PDUs from a local file.
#
# Keeping protocol logic here makes it easy to unit test outside OpenC3.

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple


CRC16_LEN_BYTES = 2

# Matches MAX_CFDP_HEADER_SIZE in StorageManager.h -- the flight side reserves
# this much header room (a theoretical max, not the actual 10-byte header this
# sender currently builds) when computing its own max payload size, and rejects
# any inbound PDU whose data_length assumes a smaller reservation. The outbound
# chunk size here must reserve the same amount or File Data PDUs get dropped.
MAX_CFDP_HEADER_SIZE = 22

# CFDP File Directive codes used by this minimal implementation.
EOF_FD = 0x04
METADATA_FD = 0x07


class CfdpParseError(Exception):
    """Raised when a received CFDP PDU is malformed or invalid for current state."""


class CfdpBuildError(Exception):
    """Raised when an outbound CFDP PDU cannot be built."""


@dataclass(frozen=True)
class TransactionKey:
    """The CFDP transaction identifier: source entity ID + sequence number."""
    source_id: int
    seq_num: int


@dataclass
class ParsedPdu:
    """Decoded CFDP PDU header plus data field."""
    version: int
    pdu_type: int
    direction: int
    trans_mode: int
    crc_flag: int
    large_file: int
    data_length: int

    entity_id_len: int
    seq_num_len: int

    source_id: int
    seq_num: int
    dest_id: int

    data_no_crc: bytes
    expected_crc: Optional[int]
    raw_pdu: bytes


@dataclass
class CfdpTransaction:
    """Receiver-side transaction state."""
    key: TransactionKey
    source_file_name: str = ""
    dest_file_name: str = ""
    expected_file_size: Optional[int] = None
    expected_checksum: Optional[int] = None
    condition_code: Optional[int] = None
    bytes_written: int = 0
    file_path: Optional[Path] = None
    complete: bool = False
    checksum_accum: int = 0
    # Sorted, non-overlapping (start, end) byte ranges received so far. Lets
    # File Data PDUs arrive in any order -- see _merge_rx_segment().
    rx_segments: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class OutboundPdu:
    """
    One outbound CFDP PDU.

    raw_pdu is the inner CFDP PDU only. The OpenC3 command wrapper / outer CCSDS
    header / outer CRC should be handled by your normal OpenC3 command definition
    and WRITE protocols.
    """
    kind: str
    seq_num: int
    offset: Optional[int]
    raw_pdu: bytes


def parse_int_be(buf: bytes) -> int:
    """Parse an unsigned big-endian integer from an arbitrary number of bytes."""
    value = 0
    for b in buf:
        value = (value << 8) | b
    return value


def int_to_be(value: int, length: int) -> bytes:
    """Encode an unsigned integer as big-endian bytes."""
    if value < 0:
        raise ValueError("Cannot encode negative integer")
    return int(value).to_bytes(length, byteorder="big", signed=False)


def safe_filename(name: str) -> str:
    """
    Prevent path traversal from CFDP metadata.

    CFDP metadata can contain arbitrary path strings. For this receiver, only the
    basename is honored so a remote sender cannot write outside output_dir.
    """
    name = os.path.basename(name.replace("\\", "/"))
    return name if name else "unnamed_cfdp_file.bin"


def parse_lv_string(data: bytes, idx: int) -> Tuple[str, int]:
    """
    Parse a CFDP LV string.

    LV format:
      [ length: 1 byte ][ bytes: length bytes ]
    """
    if idx >= len(data):
        raise CfdpParseError("Missing LV length")

    length = data[idx]
    idx += 1

    if idx + length > len(data):
        raise CfdpParseError("LV string exceeds data length")

    raw = data[idx : idx + length]
    idx += length

    try:
        return raw.decode("utf-8"), idx
    except UnicodeDecodeError:
        # Fall back to hex so the caller still has a stable, printable value.
        return raw.hex(), idx


def crc16_modbus(data: bytes, init: int = 0xFFFF) -> int:
    """
    CRC-16 used by the flight-side CFDP packer observed in testing.

    This is the reflected 0x8005 polynomial form, also commonly represented
    with reversed polynomial 0xA001 and initial value 0xFFFF. It matches the
    inner CFDP CRCs observed from your StorageManager packets.
    """
    crc = init & 0xFFFF

    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
            crc &= 0xFFFF

    return crc & 0xFFFF


def modular_checksum_update(checksum: int, data: bytes, offset: int = 0) -> int:
    """
    Update the CFDP modular checksum.

    The flight implementation accumulates each file byte into one of four
    big-endian lanes based on absolute file offset modulo 4.
    """
    checksum &= 0xFFFFFFFF

    for i, byte in enumerate(data):
        abs_pos = offset + i
        lane = abs_pos % 4
        shift = 8 * (3 - lane)
        checksum = (checksum + ((byte & 0xFF) << shift)) & 0xFFFFFFFF

    return checksum


def _merge_rx_segment(
    segments: List[Tuple[int, int]], start: int, end: int
) -> List[Tuple[int, int]]:
    """
    Merge a newly-received [start, end) range into a sorted list of
    non-overlapping (start, end) tuples, coalescing with anything in
    `segments` that overlaps or touches it.
    """
    merged_start, merged_end = start, end
    result: List[Tuple[int, int]] = []
    inserted = False

    for seg_start, seg_end in sorted(segments):
        if seg_end < merged_start:
            result.append((seg_start, seg_end))
        elif seg_start > merged_end:
            if not inserted:
                result.append((merged_start, merged_end))
                inserted = True
            result.append((seg_start, seg_end))
        else:
            # Overlaps or touches -- absorb into the merged range.
            merged_start = min(merged_start, seg_start)
            merged_end = max(merged_end, seg_end)

    if not inserted:
        result.append((merged_start, merged_end))

    return result


def build_cfdp_pdu(
    *,
    pdu_type: int,
    source_id: int,
    seq_num: int,
    dest_id: int,
    data_without_crc: bytes,
    entity_id_len: int = 2,
    seq_num_len: int = 2,
    trans_mode: int = 1,
    direction: int = 0,
    crc_flag: int = 1,
    large_file: int = 0,
) -> bytes:
    """
    Build an inner CFDP PDU.

    The returned bytes start with the CFDP header octet, not with CCSDS wrapper
    bytes. OpenC3 should wrap this into your command packet.
    """
    if entity_id_len < 1 or entity_id_len > 8:
        raise CfdpBuildError(f"Invalid entity_id_len={entity_id_len}")
    if seq_num_len < 1 or seq_num_len > 8:
        raise CfdpBuildError(f"Invalid seq_num_len={seq_num_len}")

    # Octet 1:
    #   bits 7..5 version
    #   bit  4    pdu_type, 0=file directive, 1=file data
    #   bit  3    direction
    #   bit  2    transmission mode
    #   bit  1    CRC flag
    #   bit  0    large-file flag
    octet1 = (
        (1 << 5)
        | ((pdu_type & 0x01) << 4)
        | ((direction & 0x01) << 3)
        | ((trans_mode & 0x01) << 2)
        | ((crc_flag & 0x01) << 1)
        | (large_file & 0x01)
    )

    # Octet 4 encodes entity/sequence lengths as "length minus 1".
    id_len_encoded = entity_id_len - 1
    seq_len_encoded = seq_num_len - 1
    octet4 = ((id_len_encoded & 0x07) << 4) | (seq_len_encoded & 0x07)

    variable_header = (
        int_to_be(source_id, entity_id_len)
        + int_to_be(seq_num, seq_num_len)
        + int_to_be(dest_id, entity_id_len)
    )

    # The CFDP data length includes the optional inner CFDP CRC.
    data_length = len(data_without_crc) + (CRC16_LEN_BYTES if crc_flag else 0)
    if data_length > 0xFFFF:
        raise CfdpBuildError(f"CFDP data field too large: {data_length}")

    fixed_header = bytes([octet1]) + int_to_be(data_length, 2) + bytes([octet4])
    pdu_without_crc = fixed_header + variable_header + data_without_crc

    if not crc_flag:
        return pdu_without_crc

    crc = crc16_modbus(pdu_without_crc)
    return pdu_without_crc + int_to_be(crc, 2)


def parse_cfdp_pdu(raw: bytes) -> ParsedPdu:
    """Parse an inner CFDP PDU."""
    if len(raw) < 7:
        raise CfdpParseError(f"PDU too short: {len(raw)} bytes")

    idx = 0

    octet1 = raw[idx]
    idx += 1

    version = (octet1 >> 5) & 0x07
    pdu_type = (octet1 >> 4) & 0x01
    direction = (octet1 >> 3) & 0x01
    trans_mode = (octet1 >> 2) & 0x01
    crc_flag = (octet1 >> 1) & 0x01
    large_file = octet1 & 0x01

    if version != 1:
        raise CfdpParseError(f"Unsupported CFDP version: {version}")

    data_length = parse_int_be(raw[idx : idx + 2])
    idx += 2

    octet4 = raw[idx]
    idx += 1

    entity_id_len = ((octet4 >> 4) & 0x07) + 1
    seq_num_len = (octet4 & 0x07) + 1

    variable_header_len = entity_id_len + seq_num_len + entity_id_len
    header_len = 4 + variable_header_len
    total_len = header_len + data_length

    if len(raw) < total_len:
        raise CfdpParseError(f"Incomplete PDU: need {total_len}, got {len(raw)}")

    source_id = parse_int_be(raw[idx : idx + entity_id_len])
    idx += entity_id_len

    seq_num = parse_int_be(raw[idx : idx + seq_num_len])
    idx += seq_num_len

    dest_id = parse_int_be(raw[idx : idx + entity_id_len])
    idx += entity_id_len

    data = raw[idx : idx + data_length]

    expected_crc = None
    if crc_flag:
        if len(data) < CRC16_LEN_BYTES:
            raise CfdpParseError("CRC flag set but data field is shorter than CRC")
        expected_crc = parse_int_be(data[-CRC16_LEN_BYTES:])
        data_no_crc = data[:-CRC16_LEN_BYTES]

        computed_crc = crc16_modbus(raw[: total_len - CRC16_LEN_BYTES])
        if computed_crc != expected_crc:
            raise CfdpParseError(
                f"CFDP CRC mismatch: computed 0x{computed_crc:04X}, "
                f"received 0x{expected_crc:04X}"
            )
    else:
        data_no_crc = data

    return ParsedPdu(
        version=version,
        pdu_type=pdu_type,
        direction=direction,
        trans_mode=trans_mode,
        crc_flag=crc_flag,
        large_file=large_file,
        data_length=data_length,
        entity_id_len=entity_id_len,
        seq_num_len=seq_num_len,
        source_id=source_id,
        seq_num=seq_num,
        dest_id=dest_id,
        data_no_crc=data_no_crc,
        expected_crc=expected_crc,
        raw_pdu=raw[:total_len],
    )


class CfdpReceiver:
    """Minimal receiver for Metadata, FileData, EOF in unacknowledged mode."""

    # Files are written under STAGING_SUBDIR while a transfer is in
    # progress -- FileData PDUs can arrive out of order and get written at
    # arbitrary offsets (see _handle_file_data), so a still-active or
    # stalled transfer's file is indistinguishable from a finished one by
    # name/location alone. Only once _handle_eof verifies full coverage and
    # a matching checksum does the file get atomically moved into
    # COMPLETE_SUBDIR -- a file there is always complete and correct.
    #
    # Files in STAGING_SUBDIR and FAILED_SUBDIR are partial (any gaps are
    # zero-filled) and each carries a STATUS_SUFFIX sidecar describing how
    # much arrived and why it isn't complete, so the CFDP Uplink tool's
    # Downloads tab can still offer them while saying they're incomplete.
    # The sidecar is removed when a transfer completes.
    STAGING_SUBDIR = "incoming/in_progress"
    COMPLETE_SUBDIR = "incoming/complete"
    FAILED_SUBDIR = "incoming/failed"
    # Keep in sync with STATUS_SUFFIX in CfdpUplink.vue.
    STATUS_SUFFIX = ".cfdp-status.json"

    def __init__(self, output_dir: str, local_entity_id: int, logger=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for subdir in (self.STAGING_SUBDIR, self.COMPLETE_SUBDIR, self.FAILED_SUBDIR):
            (self.output_dir / subdir).mkdir(parents=True, exist_ok=True)

        self.local_entity_id = int(local_entity_id)
        self.logger = logger
        self.transactions: Dict[TransactionKey, CfdpTransaction] = {}

    def log(self, level: str, msg: str):
        if self.logger is not None:
            getattr(self.logger, level)(msg)
        else:
            print(f"[{level.upper()}] {msg}")

    def handle_pdu_bytes(self, raw: bytes) -> Optional[CfdpTransaction]:
        pdu = parse_cfdp_pdu(raw)

        if pdu.dest_id != self.local_entity_id:
            self.log(
                "warn",
                f"Ignoring CFDP PDU for dest_id={pdu.dest_id}; "
                f"local_entity_id={self.local_entity_id}",
            )
            return None

        key = TransactionKey(pdu.source_id, pdu.seq_num)

        if pdu.pdu_type == 0:
            return self._handle_directive(key, pdu)

        return self._handle_file_data(key, pdu)

    def _get_or_create_transaction(self, key: TransactionKey) -> CfdpTransaction:
        if key not in self.transactions:
            self.transactions[key] = CfdpTransaction(key=key)
        return self.transactions[key]

    def _handle_directive(self, key: TransactionKey, pdu: ParsedPdu) -> Optional[CfdpTransaction]:
        if not pdu.data_no_crc:
            raise CfdpParseError("Empty File Directive PDU")

        directive = pdu.data_no_crc[0]

        if directive == METADATA_FD:
            return self._handle_metadata(key, pdu)

        if directive == EOF_FD:
            return self._handle_eof(key, pdu)

        self.log("warn", f"Unsupported CFDP directive 0x{directive:02X}")
        return None

    def _handle_metadata(self, key: TransactionKey, pdu: ParsedPdu) -> CfdpTransaction:
        data = pdu.data_no_crc
        idx = 0

        directive = data[idx]
        idx += 1
        if directive != METADATA_FD:
            raise CfdpParseError("Expected Metadata directive")

        flags = data[idx]
        idx += 1

        checksum_type = flags & 0x0F
        if checksum_type != 0:
            self.log("warn", f"Non-modular checksum type seen: {checksum_type}")

        file_size_len = 8 if pdu.large_file else 4
        if idx + file_size_len > len(data):
            raise CfdpParseError("Metadata missing file size")

        file_size = parse_int_be(data[idx : idx + file_size_len])
        idx += file_size_len

        source_name, idx = parse_lv_string(data, idx)
        dest_name, idx = parse_lv_string(data, idx)

        transaction = self._get_or_create_transaction(key)
        transaction.source_file_name = source_name
        transaction.dest_file_name = dest_name
        transaction.expected_file_size = file_size
        transaction.bytes_written = 0
        transaction.checksum_accum = 0
        transaction.complete = False
        transaction.rx_segments = []

        safe_name = safe_filename(dest_name)
        transaction.file_path = self.output_dir / self.STAGING_SUBDIR / safe_name

        # Reset any previous partial file for this destination.
        with open(transaction.file_path, "wb"):
            pass
        self._write_status(transaction, "receiving")

        self.log(
            "info",
            f"CFDP Metadata: tx=({key.source_id},{key.seq_num}) "
            f"src='{source_name}' dst='{dest_name}' size={file_size}",
        )

        return transaction

    def _handle_file_data(self, key: TransactionKey, pdu: ParsedPdu) -> CfdpTransaction:
        transaction = self._get_or_create_transaction(key)

        if transaction.file_path is None:
            raise CfdpParseError(f"File Data before Metadata for tx={key}")

        offset_len = 8 if pdu.large_file else 4
        if len(pdu.data_no_crc) < offset_len:
            raise CfdpParseError("File Data PDU too short for offset")

        file_offset = parse_int_be(pdu.data_no_crc[:offset_len])
        file_data = pdu.data_no_crc[offset_len:]
        range_end = file_offset + len(file_data)

        # File Data may arrive in any order. Reject only if it would write
        # past the file size the Metadata PDU told us to expect.
        if transaction.expected_file_size is not None:
            if range_end > transaction.expected_file_size:
                raise CfdpParseError(
                    f"FileData exceeds expected size tx={key}: "
                    f"offset={file_offset}, bytes={len(file_data)}, "
                    f"expected_total={transaction.expected_file_size}"
                )

        # Only fold bytes we haven't already counted into the checksum --
        # otherwise a segment overlapping one we've already received (e.g. a
        # resend) would double-count. Walk the sorted rx_segments to find the
        # sub-ranges of [file_offset, range_end) that are genuinely new.
        cursor = file_offset
        for seg_start, seg_end in transaction.rx_segments:
            if cursor >= range_end:
                break
            if seg_end <= cursor:
                continue
            if seg_start >= range_end:
                break
            if seg_start > cursor:
                new_chunk = file_data[cursor - file_offset : seg_start - file_offset]
                transaction.checksum_accum = modular_checksum_update(
                    transaction.checksum_accum, new_chunk, offset=cursor
                )
            cursor = max(cursor, seg_end)
        if cursor < range_end:
            new_chunk = file_data[cursor - file_offset :]
            transaction.checksum_accum = modular_checksum_update(
                transaction.checksum_accum, new_chunk, offset=cursor
            )

        # Write at the PDU's own offset -- safe even for an overlapping
        # resend, since the source bytes for a given file offset never change
        # within one transaction. The file was created empty in
        # _handle_metadata, so seeking past its current end zero-fills the gap.
        with open(transaction.file_path, "r+b") as f:
            f.seek(file_offset)
            f.write(file_data)

        transaction.rx_segments = _merge_rx_segment(transaction.rx_segments, file_offset, range_end)
        transaction.bytes_written = sum(end - start for start, end in transaction.rx_segments)
        self._write_status(transaction, "receiving")

        self.log(
            "info",
            f"CFDP FileData: tx=({key.source_id},{key.seq_num}) "
            f"offset={file_offset} bytes={len(file_data)} total={transaction.bytes_written}",
        )

        return transaction

    def _handle_eof(self, key: TransactionKey, pdu: ParsedPdu) -> CfdpTransaction:
        data = pdu.data_no_crc
        idx = 0

        if len(data) < 10:
            raise CfdpParseError("EOF PDU too short")

        directive = data[idx]
        idx += 1
        if directive != EOF_FD:
            raise CfdpParseError("Expected EOF directive")

        condition_byte = data[idx]
        idx += 1
        condition_code = (condition_byte >> 4) & 0x0F

        file_checksum = parse_int_be(data[idx : idx + 4])
        idx += 4

        file_size_len = 8 if pdu.large_file else 4
        file_size = parse_int_be(data[idx : idx + file_size_len])
        idx += file_size_len

        transaction = self._get_or_create_transaction(key)
        transaction.expected_checksum = file_checksum
        transaction.condition_code = condition_code

        if condition_code != 0:
            self.log("error", f"CFDP EOF reported error condition={condition_code} tx={key}")
            self._move_to_failed(transaction, f"Sender cancelled the transfer (condition code {condition_code})")
            transaction.complete = True
            return transaction

        # Validate that we've received the whole file with no gaps. PDUs may
        # have arrived out of order, so this checks full coverage of
        # rx_segments rather than a simple running byte count.
        if file_size == 0:
            fully_received = not transaction.rx_segments
        else:
            fully_received = (
                len(transaction.rx_segments) == 1
                and transaction.rx_segments[0][0] == 0
                and transaction.rx_segments[0][1] == file_size
            )
        if not fully_received:
            self._move_to_failed(transaction, "EOF arrived before every byte of the file was received")
            raise CfdpParseError(
                f"EOF size mismatch tx={key}: wrote {transaction.bytes_written}, EOF says {file_size}, "
                f"segments={transaction.rx_segments}"
            )

        if transaction.checksum_accum != file_checksum:
            self._move_to_failed(transaction, "All bytes arrived but the file checksum does not match")
            raise CfdpParseError(
                f"EOF checksum mismatch tx={key}: computed 0x{transaction.checksum_accum:08X}, "
                f"EOF says 0x{file_checksum:08X}"
            )

        # Full coverage and checksum both verified -- only now is it safe to
        # publish the file where anything outside this class can see it.
        final_path = self.output_dir / self.COMPLETE_SUBDIR / transaction.file_path.name
        self._status_path(transaction.file_path).unlink(missing_ok=True)
        transaction.file_path.replace(final_path)
        transaction.file_path = final_path
        transaction.complete = True

        self.log(
            "info",
            f"CFDP COMPLETE: tx=({key.source_id},{key.seq_num}) "
            f"path={transaction.file_path} size={file_size} checksum=0x{file_checksum:08X}",
        )

        return transaction

    def _move_to_failed(self, transaction: "CfdpTransaction", reason: str):
        """Move a transaction's staged file out of in_progress/ so it never looks complete."""
        if transaction.file_path is None or not transaction.file_path.exists():
            return
        staged_status = self._status_path(transaction.file_path)
        failed_path = self.output_dir / self.FAILED_SUBDIR / transaction.file_path.name
        transaction.file_path.replace(failed_path)
        transaction.file_path = failed_path
        self._write_status(transaction, "failed", reason)
        staged_status.unlink(missing_ok=True)

    def _status_path(self, file_path: Path) -> Path:
        return file_path.with_name(file_path.name + self.STATUS_SUFFIX)

    def _write_status(self, transaction: "CfdpTransaction", state: str, reason: Optional[str] = None):
        """
        Write the sidecar describing a partial file: how much arrived, which
        byte ranges are missing (zero-filled in the file), and why it isn't
        complete. Best effort -- a failed write must never interrupt receiving.
        """
        expected = transaction.expected_file_size
        missing = []
        if expected is not None:
            cursor = 0
            for start, end in transaction.rx_segments:
                if start > cursor:
                    missing.append([cursor, start])
                cursor = max(cursor, end)
            if cursor < expected:
                missing.append([cursor, expected])

        status = {
            "state": state,
            "reason": reason,
            "source_entity_id": transaction.key.source_id,
            "sequence_number": transaction.key.seq_num,
            "source_file_name": transaction.source_file_name,
            "dest_file_name": transaction.dest_file_name,
            "expected_file_size": expected,
            "bytes_received": transaction.bytes_written,
            "missing_ranges": missing,
            "updated_at": time.time(),
        }
        try:
            self._status_path(transaction.file_path).write_text(json.dumps(status, indent=2))
        except OSError as exc:
            self.log("warn", f"Could not write CFDP status for {transaction.file_path}: {exc}")


class CfdpSender:
    """
    Minimal outbound sender for unacknowledged small-file CFDP transfers.

    It builds the inner CFDP PDUs only. The OpenC3 service is responsible for
    wrapping/sending them as commands.
    """

    def __init__(
        self,
        *,
        source_entity_id: int,
        dest_entity_id: int,
        seq_num: int,
        max_pdu_bytes: int = 280,
        entity_id_len: int = 2,
        seq_num_len: int = 2,
        logger=None,
    ):
        self.source_entity_id = int(source_entity_id)
        self.dest_entity_id = int(dest_entity_id)
        self.seq_num = int(seq_num) & 0xFFFF
        self.max_pdu_bytes = int(max_pdu_bytes)
        self.entity_id_len = int(entity_id_len)
        self.seq_num_len = int(seq_num_len)
        self.logger = logger

        self.fixed_header_len = 4 + self.entity_id_len + self.seq_num_len + self.entity_id_len

        if self.max_pdu_bytes <= self.fixed_header_len + CRC16_LEN_BYTES:
            raise CfdpBuildError(
                f"max_pdu_bytes={self.max_pdu_bytes} is too small for CFDP header"
            )

    def _build_metadata(self, local_path: Path, remote_name: str, file_size: int) -> bytes:
        source_name = local_path.name.encode("utf-8")
        dest_name = remote_name.encode("utf-8")

        if len(source_name) > 255:
            raise CfdpBuildError("Source filename too long for one-byte LV encoding")
        if len(dest_name) > 255:
            raise CfdpBuildError("Destination filename too long for one-byte LV encoding")
        if file_size > 0xFFFFFFFF:
            raise CfdpBuildError("Large-file mode is not implemented")

        # Metadata directive data:
        #   directive 0x07
        #   flags: closure not requested, checksum type 0 modular
        #   file size, 4 bytes
        #   source filename LV
        #   destination filename LV
        data = (
            bytes([METADATA_FD, 0x00])
            + int_to_be(file_size, 4)
            + bytes([len(source_name)])
            + source_name
            + bytes([len(dest_name)])
            + dest_name
        )

        return build_cfdp_pdu(
            pdu_type=0,
            source_id=self.source_entity_id,
            seq_num=self.seq_num,
            dest_id=self.dest_entity_id,
            data_without_crc=data,
            entity_id_len=self.entity_id_len,
            seq_num_len=self.seq_num_len,
        )

    def _build_file_data(self, offset: int, chunk: bytes) -> bytes:
        if offset > 0xFFFFFFFF:
            raise CfdpBuildError("Large-file offsets are not implemented")

        data = int_to_be(offset, 4) + chunk

        return build_cfdp_pdu(
            pdu_type=1,
            source_id=self.source_entity_id,
            seq_num=self.seq_num,
            dest_id=self.dest_entity_id,
            data_without_crc=data,
            entity_id_len=self.entity_id_len,
            seq_num_len=self.seq_num_len,
        )

    def _build_eof(self, checksum: int, file_size: int) -> bytes:
        if file_size > 0xFFFFFFFF:
            raise CfdpBuildError("Large-file mode is not implemented")

        # EOF directive data:
        #   directive 0x04
        #   condition code/spare, 0 means success
        #   modular checksum, 4 bytes
        #   file size, 4 bytes
        data = (
            bytes([EOF_FD, 0x00])
            + int_to_be(checksum & 0xFFFFFFFF, 4)
            + int_to_be(file_size, 4)
        )

        return build_cfdp_pdu(
            pdu_type=0,
            source_id=self.source_entity_id,
            seq_num=self.seq_num,
            dest_id=self.dest_entity_id,
            data_without_crc=data,
            entity_id_len=self.entity_id_len,
            seq_num_len=self.seq_num_len,
        )

    def build_file_transfer(self, local_path: str, remote_name: str) -> Iterator[OutboundPdu]:
        """
        Yield Metadata, FileData*, EOF PDUs for a local file.

        Empty files produce only Metadata and EOF.
        """
        path = Path(local_path)
        if not path.is_file():
            raise CfdpBuildError(f"Outbound local_path is not a file: {path}")

        file_size = path.stat().st_size
        if file_size > 0xFFFFFFFF:
            raise CfdpBuildError("Large-file mode is not implemented")

        metadata = self._build_metadata(path, remote_name, file_size)
        if len(metadata) > self.max_pdu_bytes:
            raise CfdpBuildError(
                f"Metadata PDU is {len(metadata)} bytes, max is {self.max_pdu_bytes}"
            )

        yield OutboundPdu(kind="metadata", seq_num=self.seq_num, offset=None, raw_pdu=metadata)

        # FileData max chunk size:
        #   max inner PDU bytes
        # - flight side's conservative header reservation (MAX_CFDP_HEADER_SIZE,
        #   not the smaller actual fixed_header_len -- the receiver's own max
        #   payload check is sized off the conservative reservation, so building
        #   chunks off the tighter actual header size produces PDUs the flight
        #   side rejects as oversized)
        # - 4-byte file offset
        # - 2-byte inner CFDP CRC
        max_chunk = self.max_pdu_bytes - MAX_CFDP_HEADER_SIZE - 4 - CRC16_LEN_BYTES
        if max_chunk <= 0:
            raise CfdpBuildError("Computed max file data chunk is not positive")

        checksum = 0
        offset = 0

        with open(path, "rb") as f:
            while True:
                chunk = f.read(max_chunk)
                if not chunk:
                    break

                file_data = self._build_file_data(offset, chunk)
                if len(file_data) > self.max_pdu_bytes:
                    raise CfdpBuildError(
                        f"FileData PDU is {len(file_data)} bytes, max is {self.max_pdu_bytes}"
                    )

                yield OutboundPdu(
                    kind="file_data",
                    seq_num=self.seq_num,
                    offset=offset,
                    raw_pdu=file_data,
                )

                checksum = modular_checksum_update(checksum, chunk, offset=offset)
                offset += len(chunk)

        eof = self._build_eof(checksum, file_size)
        if len(eof) > self.max_pdu_bytes:
            raise CfdpBuildError(f"EOF PDU is {len(eof)} bytes, max is {self.max_pdu_bytes}")

        yield OutboundPdu(kind="eof", seq_num=self.seq_num, offset=None, raw_pdu=eof)
