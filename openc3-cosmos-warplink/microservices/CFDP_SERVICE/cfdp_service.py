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


# microservices/CFDP_SERVICE/cfdp_service.py
#
# OpenC3 wrapper for CFDP receive and send.
#
# Inbound:
#   subscribe to a telemetry packet item containing a raw/padded CFDP_PDU BLOCK
#   trim the padded block
#   pass the real CFDP PDU to CfdpReceiver
#
# Outbound:
#   poll OPENC3_TOOLS_BUCKET's cfdp/outgoing/queue/ prefix for JSON requests
#   (see the CFDP Uplink tool)
#   build Metadata/FileData/EOF inner CFDP PDUs
#   send each PDU through an OpenC3 command whose CFDP_PDU parameter is a BLOCK

from __future__ import annotations

import contextlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from openc3.api import *
from openc3.environment import OPENC3_TOOLS_BUCKET
from openc3.microservices.microservice import Microservice
from openc3.utilities.bucket import Bucket
from openc3.utilities.sleeper import Sleeper

from cfdp_core import (
    CfdpBuildError,
    CfdpReceiver,
    CfdpSender,
    CfdpParseError,
)

# Outbound transfer requests are queued as JSON objects in this bucket/prefix
# by the CFDP Uplink tool (see
# openc3-cosmos-init/plugins/packages/openc3-cosmos-tool-cfdpuplink), rather
# than dropped as local files -- the tool runs in the browser and can only
# reach OpenC3's bucket storage (Minio), not this microservice's own
# filesystem. UPLOAD_BUCKET must be the resolved bucket name (e.g. "tools"),
# not the env var name -- the Rails upload route resolves that translation
# server-side (ENV[params[:bucket]]), so the Python side has to do the same
# via openc3.environment rather than hardcoding the env var name string.
# Keep QUEUE_PREFIX in sync with CfdpUplink.vue.
UPLOAD_BUCKET = OPENC3_TOOLS_BUCKET
QUEUE_PREFIX = "cfdp/outgoing/queue/"
SENT_PREFIX = "cfdp/outgoing/sent/"
FAILED_PREFIX = "cfdp/outgoing/failed/"


def packet_item_to_bytes(value: Any) -> bytes:
    """
    Convert an OpenC3 telemetry item value into bytes.

    OpenC3 BLOCK items may arrive in different shapes depending on API/version
    and packet configuration. This handles:
    - bytes / bytearray / memoryview
    - list[int] / tuple[int]
    - hex strings
    - normal strings
    - dictionaries containing raw/value/formatted/bytes/data/buffer fields
    """
    if value is None:
        raise ValueError("CFDP item value is None")

    if isinstance(value, bytes):
        return value

    if isinstance(value, bytearray):
        return bytes(value)

    if isinstance(value, memoryview):
        return value.tobytes()

    if isinstance(value, list):
        return bytes(int(x) & 0xFF for x in value)

    if isinstance(value, tuple):
        return bytes(int(x) & 0xFF for x in value)

    if isinstance(value, str):
        text = value.strip()

        cleaned = (
            text.replace("0x", "")
            .replace("0X", "")
            .replace(",", " ")
            .replace("_", " ")
        )

        pieces = cleaned.split()
        if len(pieces) > 1:
            try:
                return bytes(int(p, 16) & 0xFF for p in pieces)
            except ValueError:
                pass

        compact = cleaned.replace(" ", "").replace("\n", "").replace("\t", "")
        if (
            len(compact) > 0
            and len(compact) % 2 == 0
            and all(c in "0123456789abcdefABCDEF" for c in compact)
        ):
            try:
                return bytes.fromhex(compact)
            except ValueError:
                pass

        return text.encode("utf-8")

    if isinstance(value, dict):
        # Prefer raw/value-like fields first. Different OpenC3 API paths may use
        # different names for the actual item value.
        for key in (
            "raw",
            "RAW",
            "value",
            "VALUE",
            "values",
            "VALUES",
            "bytes",
            "BYTES",
            "data",
            "DATA",
            "buffer",
            "BUFFER",
            "formatted",
            "FORMATTED",
        ):
            if key in value:
                return packet_item_to_bytes(value[key])

        raise TypeError(
            "Unsupported CFDP item dict shape. "
            f"keys={list(value.keys())}, value={repr(value)[:300]}"
        )

    raise TypeError(f"Unsupported CFDP item type: {type(value)}")


def trim_cfdp_pdu(raw: bytes) -> bytes:
    """
    Trim a fixed-size/padded OpenC3 BLOCK down to the actual CFDP PDU length.

    The telemetry item carries a fixed-size CFDP_PDU block. The hardware pads
    unused bytes with zeroes, so the parser should only receive the actual PDU
    described by the CFDP header.
    """
    if len(raw) < 4:
        raise ValueError(f"CFDP PDU too short: len={len(raw)}")

    data_length = int.from_bytes(raw[1:3], byteorder="big", signed=False)
    length_octet = raw[3]

    entity_id_len = ((length_octet >> 4) & 0x07) + 1
    seq_len = (length_octet & 0x07) + 1

    header_len = 4 + entity_id_len + seq_len + entity_id_len
    total_len = header_len + data_length

    if total_len > len(raw):
        raise ValueError(
            f"CFDP PDU header says total_len={total_len}, "
            f"but BLOCK item only has len={len(raw)}"
        )

    return raw[:total_len]


def packet_sort_time(packet: dict) -> int:
    """Best-effort sort key for OpenC3 packet dictionaries."""
    for key in ("time", "received_time", "received_time_nsec"):
        value = packet.get(key)
        if value is None:
            continue

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                continue

        if isinstance(value, dict):
            for nested_key in ("raw", "value", "formatted"):
                nested = value.get(nested_key)
                if nested is None:
                    continue
                try:
                    return int(nested)
                except (TypeError, ValueError):
                    continue

    return 0


class CFDPService(Microservice):
    def __init__(self, name):
        super().__init__(name)

        # Inbound telemetry subscription options.
        self.target = None
        self.packet = None
        self.item = None

        # File/output configuration.
        self.output_dir = "/openc3/tmp/cfdp"
        self.local_entity_id = 0

        # Outbound command options.
        self.command_target = None
        self.command_packet = "CFDP_PDU"
        self.command_item = "CFDP_PDU"
        self.cfdp_block_size = 280

        # Outbound queue: next_sequence.txt still lives on local disk (it's a
        # small durable counter on an already-mounted volume); the request
        # queue itself lives in a bucket -- see UPLOAD_BUCKET/QUEUE_PREFIX.
        self.outgoing_dir = None

        # Poll interval for outbound requests.
        self.outgoing_poll_seconds = 1.0

        for option in self.config["options"]:
            key = option[0].upper()

            if key == "TARGET":
                self.target = option[1]
            elif key == "PACKET":
                self.packet = option[1]
            elif key == "ITEM":
                self.item = option[1]
            elif key == "OUTPUT_DIR":
                self.output_dir = option[1]
            elif key == "LOCAL_ENTITY_ID":
                self.local_entity_id = int(option[1], 0)
            elif key == "COMMAND_TARGET":
                self.command_target = option[1]
            elif key == "COMMAND_PACKET":
                self.command_packet = option[1]
            elif key == "COMMAND_ITEM":
                self.command_item = option[1]
            elif key == "CFDP_BLOCK_SIZE":
                self.cfdp_block_size = int(option[1], 0)
            elif key == "OUTGOING_DIR":
                self.outgoing_dir = option[1]
            elif key == "OUTGOING_POLL_SECONDS":
                self.outgoing_poll_seconds = float(option[1])
            else:
                self.logger.warning(f"Unknown CFDP_SERVICE option: {option}")

        missing = [
            option_name
            for option_name, value in [
                ("TARGET", self.target),
                ("PACKET", self.packet),
                ("ITEM", self.item),
            ]
            if value is None
        ]
        if missing:
            raise RuntimeError(f"Missing required CFDP_SERVICE options: {missing}")

        if self.command_target is None:
            self.command_target = self.target

        if self.outgoing_dir is None:
            self.outgoing_dir = str(Path(self.output_dir) / "outgoing")

        self.outgoing_dir = Path(self.outgoing_dir)
        self.outgoing_dir.mkdir(parents=True, exist_ok=True)

        self.bucket = Bucket.getClient()

        self.sleeper = Sleeper()
        self.receiver = CfdpReceiver(
            output_dir=self.output_dir,
            local_entity_id=self.local_entity_id,
            logger=self.logger,
        )

        self.subscription_id = None
        self.last_outgoing_scan = 0.0

    def run(self):
        self.logger.info(
            f"Starting CFDPService target={self.target} packet={self.packet} "
            f"item={self.item} output_dir={self.output_dir} "
            f"local_entity_id={self.local_entity_id}"
        )

        self.logger.info(
            f"Outbound CFDP config: command={self.command_target} {self.command_packet} "
            f"item={self.command_item} queue_bucket={UPLOAD_BUCKET} "
            f"queue_prefix={QUEUE_PREFIX} block_size={self.cfdp_block_size}"
        )

        self.subscription_id = subscribe_packets([[self.target, self.packet]])
        self.logger.info(f"CFDP subscription id: {self.subscription_id}")

        while True:
            if self.cancel_thread:
                break

            try:
                self.subscription_id, packets = get_packets(self.subscription_id)

                if packets:
                    packets.sort(key=packet_sort_time)
                    self.logger.info(f"CFDPService received {len(packets)} packet(s)")

                    for packet in packets:
                        self.handle_packet(packet)

                self.process_outgoing_queue_if_due()

                if not packets:
                    time.sleep(0.1)

            except Exception as exc:
                self.logger.error(f"CFDPService loop error: {exc}")

                # Avoid a hot error loop.
                if self.sleeper.sleep(1.0):
                    break

    # ---------------------------------------------------------------------
    # Inbound handling
    # ---------------------------------------------------------------------

    def handle_packet(self, packet: dict):
        """Handle one subscribed telemetry packet containing an inbound CFDP_PDU."""
        if self.item not in packet:
            self.logger.warning(
                f"Packet {packet.get('target_name')} {packet.get('packet_name')} "
                f"does not contain item {self.item}. "
                f"Packet keys={list(packet.keys())}"
            )
            return

        try:
            value = packet.get(self.item)

            raw_block = packet_item_to_bytes(value)
            raw_pdu = trim_cfdp_pdu(raw_block)

            self.logger.info(
                f"CFDP RX PDU len={len(raw_pdu)} first32={raw_pdu[:32].hex()}"
            )

            transaction = self.receiver.handle_pdu_bytes(raw_pdu)

            if transaction is not None and transaction.complete:
                self.on_transaction_complete(transaction)

        except CfdpParseError as exc:
            self.logger.error(f"CFDP parse error: {exc}")
        except Exception as exc:
            self.logger.error(f"CFDP packet handling error: {exc}")

    def on_transaction_complete(self, transaction):
        """Called when an inbound transaction successfully completes."""
        self.logger.info(
            f"CFDP transaction complete: source={transaction.key.source_id} "
            f"seq={transaction.key.seq_num} file={transaction.file_path}"
        )

    # ---------------------------------------------------------------------
    # Outbound queue handling
    # ---------------------------------------------------------------------

    def process_outgoing_queue_if_due(self):
        """Poll the outgoing queue periodically."""
        now = time.monotonic()
        if now - self.last_outgoing_scan < self.outgoing_poll_seconds:
            return

        self.last_outgoing_scan = now
        self.process_outgoing_queue()

    def process_outgoing_queue(self):
        """
        Process request JSON objects under the outbound queue bucket prefix.

        Objects are uploaded by the CFDP Uplink tool (or anything else
        writing to this prefix). Exactly one of 'local_path' (a path
        CFDP_SERVICE can already read) or 'source_key' (a bucket object
        holding an uploaded file's bytes, under cfdp/outgoing/files/) must be
        present. Request examples:
          {
            "local_path": "/openc3/user/cfdp/outgoing/queue/test.txt",
            "remote_name": "test.txt",
            "destination_entity_id": 0
          }
          {
            "source_key": "cfdp/outgoing/files/1786047344384_test.txt",
            "remote_name": "test.txt",
            "destination_entity_id": 0
          }
        """
        try:
            objects = self.bucket.list_objects(bucket=UPLOAD_BUCKET, prefix=QUEUE_PREFIX)
        except Bucket.NotFound:
            return

        keys = sorted(
            obj["Key"]
            for obj in objects
            if obj["Key"].endswith(".json") and obj["Key"] != QUEUE_PREFIX
        )
        if not keys:
            return

        # Process one request per scan so a large transfer does not starve RX
        # handling for too long.
        self.process_outgoing_request(keys[0])

    def process_outgoing_request(self, key: str):
        """Build and send one outbound CFDP file transfer request."""
        source_key = None
        try:
            response = self.bucket.get_object(bucket=UPLOAD_BUCKET, key=key)
            if response is None:
                self.logger.warning(f"CFDP TX request disappeared before processing: {key}")
                return
            body = response["Body"].read()
            request = json.loads(body)

            if not request.get("remote_name"):
                raise ValueError("CFDP TX request missing required 'remote_name'")
            remote_name = str(request["remote_name"])
            if "destination_entity_id" not in request:
                raise ValueError("CFDP TX request missing required 'destination_entity_id'")
            destination_entity_id = int(request["destination_entity_id"])

            local_path_value = request.get("local_path")
            source_key = request.get("source_key")
            if bool(local_path_value) == bool(source_key):
                raise ValueError(
                    "CFDP TX request must have exactly one of 'local_path' "
                    "(a path CFDP_SERVICE can already read) or 'source_key' "
                    "(a bucket object uploaded by the CFDP Uplink tool)"
                )
            source_filename = request.get("source_filename")

            seq_num = int(request.get("sequence_number", self.next_sequence_number()))

            with self._resolve_local_path(local_path_value, source_key, source_filename) as local_path:
                self.logger.info(
                    f"CFDP TX request={key} local_path={local_path} "
                    f"remote_name={remote_name} dest_entity={destination_entity_id} seq={seq_num}"
                )

                sender = CfdpSender(
                    source_entity_id=self.local_entity_id,
                    dest_entity_id=destination_entity_id,
                    seq_num=seq_num,
                    max_pdu_bytes=self.cfdp_block_size,
                    logger=self.logger,
                )

                pdu_count = 0
                for outbound in sender.build_file_transfer(
                    local_path=str(local_path),
                    remote_name=remote_name,
                ):
                    self.send_cfdp_pdu(outbound.raw_pdu)
                    pdu_count += 1

                    self.logger.info(
                        f"CFDP TX sent {outbound.kind} seq={outbound.seq_num} "
                        f"offset={outbound.offset} len={len(outbound.raw_pdu)} "
                        f"first32={outbound.raw_pdu[:32].hex()}"
                    )

                    # Small delay to avoid hammering the command path.
                    MIN_PDU_DELAY_SECONDS = 0.1

                    requested_delay = float(request.get("pdu_delay_seconds", MIN_PDU_DELAY_SECONDS))
                    delay = max(MIN_PDU_DELAY_SECONDS, requested_delay)

                    if requested_delay < MIN_PDU_DELAY_SECONDS:
                        self.logger.warning(
                            "CFDP TX pdu_delay_seconds %.3f is below minimum %.3f; clamping",
                            requested_delay,
                            MIN_PDU_DELAY_SECONDS)
                    time.sleep(delay)

            self.logger.info(
                f"CFDP TX complete request={key} pdu_count={pdu_count}"
            )
            self.move_request(key, SENT_PREFIX, body)

        except Exception as exc:
            self.logger.error(f"CFDP TX request failed {key}: {exc}")
            self.move_request(key, FAILED_PREFIX)
        finally:
            # The uploaded file itself isn't archived like the (small) request
            # JSON -- the source still exists on the uploader's machine, so
            # there's no need to keep a duplicate copy of potentially large
            # file bytes around in the bucket after processing.
            if source_key:
                self.bucket.delete_object(bucket=UPLOAD_BUCKET, key=source_key)

    @contextlib.contextmanager
    def _resolve_local_path(
        self,
        local_path_value: Optional[str],
        source_key: Optional[str],
        source_filename: Optional[str],
    ):
        """
        Yield a real local filesystem path for the transfer's source file.

        For 'source_key' requests (uploaded via the CFDP Uplink tool), the
        bucket object is downloaded to a temp file so build_file_transfer()
        -- which just opens and reads a path -- doesn't need to know or care
        that the file didn't already exist on this filesystem.

        The temp file is named from 'source_filename' (the real original
        name from the uploader's machine), not from source_key's own name
        (which is timestamp-prefixed for bucket-key uniqueness) --
        _build_metadata() reads local_path.name as the CFDP PDU's source
        filename field, so using the timestamped key name here would leak
        into the actual wire protocol.
        """
        if source_key:
            with tempfile.TemporaryDirectory() as tmp_dir:
                local_path = Path(tmp_dir) / (source_filename or Path(source_key).name)
                response = self.bucket.get_object(bucket=UPLOAD_BUCKET, key=source_key, path=str(local_path))
                if response is None:
                    raise ValueError(f"Uploaded file object not found: {source_key}")
                yield local_path
        else:
            yield Path(str(local_path_value))

    def next_sequence_number(self) -> int:
        """
        Allocate the next local CFDP sequence number.

        Stored on disk so the counter survives microservice restarts.
        """
        sequence_file = self.outgoing_dir / "next_sequence.txt"

        try:
            current = int(sequence_file.read_text(encoding="utf-8").strip(), 0)
        except Exception:
            current = 1

        seq = current & 0xFFFF
        next_value = (seq + 1) & 0xFFFF
        if next_value == 0:
            next_value = 1

        sequence_file.write_text(str(next_value), encoding="utf-8")
        return seq

    def move_request(self, key: str, destination_prefix: str, body: Optional[bytes] = None):
        """
        Move a processed request from queue/ to sent/ or failed/.

        Buckets have no atomic move, so this copies the object under the
        destination prefix (timestamped so repeated request names don't
        collide) then deletes the original. If the caller doesn't already
        have the body (e.g. the failure happened before it could be read),
        it's re-fetched here.
        """
        if body is None:
            response = self.bucket.get_object(bucket=UPLOAD_BUCKET, key=key)
            if response is None:
                return
            body = response["Body"].read()

        stamped_key = f"{destination_prefix}{int(time.time())}_{key.rsplit('/', 1)[-1]}"
        self.bucket.put_object(bucket=UPLOAD_BUCKET, key=stamped_key, body=body)
        self.bucket.delete_object(bucket=UPLOAD_BUCKET, key=key)

    # ---------------------------------------------------------------------
    # OpenC3 command sending
    # ---------------------------------------------------------------------

    def send_cfdp_pdu(self, raw_pdu: bytes):
        """
        Send one inner CFDP PDU through the OpenC3 command path.

        For OpenC3 BLOCK/variable-length STRING parameters, do NOT pass a hex
        string. A hex string like "260030..." is interpreted as ASCII text and
        becomes twice as many bytes.

        Sent unpadded: the command's data_buffer parameter is a variable-length
        field (see StorageManager.json's "variable_length": true), so COSMOS
        writes exactly these bytes with no trailing padding. Padding to
        cfdp_block_size used to be required when data_buffer was a fixed-size
        field, but padding every command out to a fixed size left unconsumed
        zero bytes piling up in CommandManager's input buffer on the flight
        side after every single command.
        """
        self.logger.info(
            f"Sending OpenC3 command: {self.command_target} {self.command_packet} "
            f"{self.command_item}_len={len(raw_pdu)} first16={raw_pdu[:16].hex()}"
        )

        cmd(
            self.command_target,
            self.command_packet,
            {
                self.command_item: raw_pdu
            }
        )

    def shutdown(self):
        self.sleeper.cancel()
        super().shutdown()


if __name__ == "__main__":
    CFDPService.class_run()
