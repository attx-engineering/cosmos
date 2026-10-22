# Copyright 2026 ATTX, Inc.
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


# test/test_cfdp_core.py
#
# Unit tests for microservices/CFDP_SERVICE/cfdp_core.py: the received-segment
# map, the file checksum and PDU CRC (checked against WarpOS's own code), file
# names from a remote sender, PDU parsing, and whole transfers end to end.

import json
import random
import tempfile
import unittest
from pathlib import Path

from cfdp_core import (
    EOF_FD,
    MAX_CFDP_HEADER_SIZE,
    METADATA_FD,
    CfdpBuildError,
    CfdpParseError,
    CfdpReceiver,
    CfdpSender,
    _merge_rx_segment,
    build_cfdp_pdu,
    crc16_modbus,
    modular_checksum_update,
    parse_cfdp_pdu,
    parse_int_be,
    parse_lv_string,
    safe_filename,
)

DEFAULT_NAME = "unnamed_cfdp_file.bin"


def pattern(n, seed):
    """Test data, made the same way by the harness that computed the WarpOS vectors."""
    return bytes((i * 167 + (i >> 5) * 29 + seed) & 0xFF for i in range(n))


# Vectors computed by WarpOS's own code (WarpOS commit 21d8686a), compiled into
# a C++ harness outside this repository:
#   WARPOS_CRC16       computeCRC16() in src/warpos/utils/spacepacketutils.cpp,
#                      seeded 0xFFFF as StorageManager::_packPdu() and
#                      StorageManager::_parseCfdpPdu() seed it for the CRC that
#                      ends every CFDP PDU (and once seeded 0).
#   WARPOS_SUM_*       the modular checksum StorageManager::_parseFileDataPdu()
#                      (src/apps/StorageManager/StorageManager.cpp) accumulates
#                      into TransactionData::_file_checksum, one File Data PDU
#                      per piece, in the order given, through one transaction.
#   WARPOS_TRANSFERS   whole transfers as StorageManager sends them:
#                      _packMetaDataPdu(), _packFileDataPdu() for each chunk
#                      (committed as _sendOutputData() commits them), then
#                      _packEofPdu(), with the payload limit StorageManager::start()
#                      derives from a max_pdu_bytes packet.

# (data, seed, crc)
WARPOS_CRC16 = [
    (b"123456789", 0xFFFF, 0x4B37),
    (b"123456789", 0x0000, 0xBB3D),
    (b"\x00", 0xFFFF, 0x40BF),
    (b"\xff" * 7, 0xFFFF, 0x8015),
    (pattern(1, 0), 0xFFFF, 0x40BF),
    (pattern(1, 77), 0xFFFF, 0x757F),
    (pattern(2, 0), 0xFFFF, 0x0A40),
    (pattern(2, 77), 0xFFFF, 0x6735),
    (pattern(3, 0), 0xFFFF, 0xC48B),
    (pattern(3, 77), 0xFFFF, 0xBCE6),
    (pattern(10, 0), 0xFFFF, 0x7DE1),
    (pattern(10, 77), 0xFFFF, 0xD124),
    (pattern(64, 0), 0xFFFF, 0x9098),
    (pattern(64, 77), 0xFFFF, 0xA05A),
    (pattern(255, 0), 0xFFFF, 0x59C9),
    (pattern(255, 77), 0xFFFF, 0x0A64),
    (pattern(300, 0), 0xFFFF, 0x3276),
    (pattern(300, 77), 0xFFFF, 0x59B1),
]

# offset: the checksum of pattern(n, 12) at that offset, from 0, for each n in WARPOS_SUM_LENGTHS
WARPOS_SUM_LENGTHS = (0, 1, 3, 4, 5, 9, 64, 230)
WARPOS_SUM_AT_OFFSET = {
    0: (0x00000000, 0x0C000000, 0x0CB35A00, 0x0CB35A01, 0xB4B35A01, 0xF903509E, 0xD140AF18, 0xC197899C),
    1: (0x00000000, 0x000C0000, 0x000CB35A, 0x010CB35A, 0x01B4B35A, 0x9EF90350, 0x1ED140A8, 0xB5C1976D),
    2: (0x00000000, 0x00000C00, 0x5A000CB3, 0x5A010CB3, 0x5A01B4B3, 0x509EF902, 0xAF1ED138, 0x89B5C178),
    3: (0x00000000, 0x0000000C, 0xB35A000C, 0xB35A010C, 0xB35A01B4, 0x03509EF8, 0x40AF1EC8, 0x9789B5A2),
    5: (0x00000000, 0x000C0000, 0x000CB35A, 0x010CB35A, 0x01B4B35A, 0x9EF90350, 0x1ED140A8, 0xB5C1976D),
    6: (0x00000000, 0x00000C00, 0x5A000CB3, 0x5A010CB3, 0x5A01B4B3, 0x509EF902, 0xAF1ED138, 0x89B5C178),
    7: (0x00000000, 0x0000000C, 0xB35A000C, 0xB35A010C, 0xB35A01B4, 0x03509EF8, 0x40AF1EC8, 0x9789B5A2),
    1002: (0x00000000, 0x00000C00, 0x5A000CB3, 0x5A010CB3, 0x5A01B4B3, 0x509EF902, 0xAF1ED138, 0x89B5C178),
    0xFFFFFE13: (0x00000000, 0x0000000C, 0xB35A000C, 0xB35A010C, 0xB35A01B4, 0x03509EF8, 0x40AF1EC8, 0x9789B5A2),
}
# (n, seed, offset, checksum before, checksum after)
WARPOS_SUM_FROM = [
    (57, 200, 3, 0xFFFFFFFF, 0x3A5D7F7E),
    (40, 5, 2, 0x89ABCDEF, 0x7319AB4D),
]
# 1003 bytes of 0xFF at offset 2, in PDUs of 200 bytes: the sum wraps many times
WARPOS_SUM_FF_1003_AT_2 = 0xFF00FF05
# (n, seed, offset of the first byte, where the PDUs split the data, checksum)
WARPOS_SUM_SPLIT = [
    (100, 3, 0, (1, 2, 3, 7, 50, 99), 0x3786D517),
    (100, 3, 1, (33, 66), 0x223786C8),
    (257, 9, 0, (35, 70, 105, 140, 175, 210, 245), 0x3303C160),
    (64, 1, 6, (5, 6, 11, 13), 0x006F2088),
]
# (n, seed, [start, end) ranges in the order received, checksum)
WARPOS_SUM_OVERLAP = (90, 42, [(40, 70), (0, 10), (5, 45), (40, 70), (60, 90), (0, 90), (33, 34)], 0x7A7B62B2)

WARPOS_TRANSFERS = [
    {
        "max_pdu_bytes": 63,
        "n": 100,
        "seed": 21,
        "local": "log.bin",
        "remote": "dl/log.bin",
        "source": 2571,
        "seq": 3085,
        "dest": 3599,
        "checksum": 0xFA4793D9,
        "pdus": [
            "26001b110a0b0c0d0e0f070000000064076c6f672e62696e0a646c2f6c6f672e62696eb7ba",
            (
                "360029110a0b0c0d0e0f0000000015bc630ab158ffa64df49b42e99037de852cd37a21c86f16bd640bb25900a74e12b9"
                "605d5c"
            ),
            (
                "360029110a0b0c0d0e0f0000002307ae55fca34af1983fe68d34db8229d0771ec56c13ba6108af56fda44b0fb65d04ab"
                "52eb5b"
            ),
            "360024110a0b0c0d0e0f00000046f9a047ee953ce38a31d87f26cd741bc26910b75e05ac53faa1480cb35a010889",
            "26000c110a0b0c0d0e0f0400fa4793d9000000648f47",
        ],
    },
    {
        "max_pdu_bytes": 63,
        "n": 0,
        "seed": 0,
        "local": "empty.bin",
        "remote": "empty.bin",
        "source": 1,
        "seq": 7,
        "dest": 2,
        "checksum": 0x00000000,
        "pdus": [
            "26001c1100010007000207000000000009656d7074792e62696e09656d7074792e62696ea48a",
            "26000c11000100070002040000000000000000003634",
        ],
    },
    {
        "max_pdu_bytes": 280,
        "n": 600,
        "seed": 5,
        "local": "img.raw",
        "remote": "img.raw",
        "source": 1,
        "seq": 65535,
        "dest": 2,
        "checksum": 0xE2BC9524,
        "pdus": [
            "260018110001ffff000207000000025807696d672e72617707696d672e7261772f7a",
            (
                "360102110001ffff00020000000005ac53faa148ef963de48b32d98027ce751cc36a11b85f06ad54fba249f0973e02a9"
                "50f79e45ec933ae1882fd67d24cb7219c0670eb55c03aa51f89f46ed943bffa64df49b42e99037de852cd37a21c86f16"
                "bd640bb25900a74ef59c43ea9138fca34af1983fe68d34db8229d0771ec56c13ba6108af56fda44bf29940e78e35f9a0"
                "47ee953ce38a31d87f26cd741bc26910b75e05ac53faa148ef963de48b32f69d44eb9239e0872ed57c23ca7118bf660d"
                "b45b02a950f79e45ec933ae1882ff39a41e88f36dd842bd27920c76e15bc630ab158ffa64df49b42e99037de852cf097"
                "3ee58c33da8128cf761dc46b12b96007ae55fca34af1983fe68d0a48"
            ),
            (
                "360102110001ffff0002000000fc34db8229ed943be28930d77e25cc731ac1680fb65d04ab52f9a047ee953ce38a31d8"
                "7f26ea9138df862dd47b22c97017be650cb35a01a84ff69d44eb9239e0872ed57c23e78e35dc832ad1781fc66d14bb62"
                "09b057fea54cf39a41e88f36dd842bd27920e48b32d98027ce751cc36a11b85f06ad54fba249f0973ee58c33da8128cf"
                "761de1882fd67d24cb7219c0670eb55c03aa51f89f46ed943be28930d77e25cc731ade852cd37a21c86f16bd640bb259"
                "00a74ef59c43ea9138df862dd47b22c97017db8229d0771ec56c13ba6108af56fda44bf29940e78e35dc832ad1781fc6"
                "6d14d87f26cd741bc26910b75e05ac53faa148ef963de48b32d928d2"
            ),
            (
                "360066110001ffff0002000001f88027ce751cc36a11d57c23ca7118bf660db45b02a950f79e45ec933ae1882fd67d24"
                "cb7219c0670ed27920c76e15bc630ab158ffa64df49b42e99037de852cd37a21c86f16bd640bcf761dc46b12b96007ae"
                "55fca34af1983fe68d34db8229d0e9dd"
            ),
            "26000c110001ffff00020400e2bc952400000258b20b",
        ],
    },
]


class QuietLogger:
    """Keeps what the receiver logs, so the tests print nothing."""

    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def warn(self, msg):
        self.messages.append(("warn", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


def runs(covered):
    """The segment list a set of covered byte offsets should give: maximal [start, end) runs."""
    result = []
    for pos in sorted(covered):
        if result and result[-1][1] == pos:
            result[-1] = (result[-1][0], pos + 1)
        else:
            result.append((pos, pos + 1))
    return result


def merge_all(ranges):
    segments = []
    for start, end in ranges:
        segments = _merge_rx_segment(segments, start, end)
    return segments


class ReceiverTestCase(unittest.TestCase):
    """A receiver writing into a temporary folder, and a way to make transfers for it."""

    LOCAL_ENTITY_ID = 1
    REMOTE_ENTITY_ID = 2

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "out"
        self.logger = QuietLogger()
        self.receiver = CfdpReceiver(str(self.out), local_entity_id=self.LOCAL_ENTITY_ID, logger=self.logger)

    def sender(self, seq=7, max_pdu_bytes=64):
        return CfdpSender(
            source_entity_id=self.REMOTE_ENTITY_ID,
            dest_entity_id=self.LOCAL_ENTITY_ID,
            seq_num=seq,
            max_pdu_bytes=max_pdu_bytes,
        )

    def transfer(self, data, remote="file.bin", seq=7, max_pdu_bytes=64):
        """Metadata, File Data and EOF PDUs, as raw bytes, for sending `data` as `remote`."""
        local = self.root / "outgoing" / f"{seq}.bin"
        local.parent.mkdir(exist_ok=True)
        local.write_bytes(data)
        return [pdu.raw_pdu for pdu in self.sender(seq, max_pdu_bytes).build_file_transfer(str(local), remote)]

    def receive(self, pdus):
        transaction = None
        for raw in pdus:
            transaction = self.receiver.handle_pdu_bytes(raw)
        return transaction

    def files(self):
        """Every file under the output folder, by its path there."""
        return {p.relative_to(self.out).as_posix(): p.read_bytes() for p in sorted(self.out.rglob("*")) if p.is_file()}

    def status(self, relative):
        return json.loads((self.out / relative).read_text())


class TestMergeRxSegment(unittest.TestCase):
    def test_disjoint_ranges_stay_separate_and_sorted(self):
        self.assertEqual(merge_all([(30, 40), (0, 10), (50, 60), (15, 20)]), [(0, 10), (15, 20), (30, 40), (50, 60)])

    def test_adjacent_ranges_coalesce(self):
        self.assertEqual(merge_all([(0, 10), (10, 20)]), [(0, 20)])
        self.assertEqual(merge_all([(10, 20), (0, 10)]), [(0, 20)])
        self.assertEqual(merge_all([(0, 10), (20, 30), (10, 20)]), [(0, 30)])

    def test_overlapping_ranges_coalesce(self):
        self.assertEqual(merge_all([(0, 10), (5, 15)]), [(0, 15)])
        self.assertEqual(merge_all([(5, 15), (0, 10)]), [(0, 15)])
        self.assertEqual(merge_all([(10, 20), (30, 40), (50, 60), (15, 55)]), [(10, 60)])
        self.assertEqual(merge_all([(10, 20), (30, 40), (0, 100)]), [(0, 100)])
        self.assertEqual(merge_all([(0, 100), (40, 60)]), [(0, 100)])

    def test_filling_one_gap_leaves_the_others(self):
        self.assertEqual(merge_all([(0, 10), (20, 30), (40, 50), (10, 20)]), [(0, 30), (40, 50)])
        self.assertEqual(merge_all([(0, 10), (20, 30), (40, 50), (12, 18)]), [(0, 10), (12, 18), (20, 30), (40, 50)])

    def test_duplicate_ranges_change_nothing(self):
        self.assertEqual(merge_all([(0, 10), (20, 30), (20, 30), (0, 10)]), [(0, 10), (20, 30)])

    def test_empty_range_adds_no_segment(self):
        # As WarpOS's StorageManager::_insertRxSegment() ignores one. A segment
        # (0, 0) would also make an empty file look incomplete at EOF.
        self.assertEqual(merge_all([(0, 0)]), [])
        self.assertEqual(merge_all([(5, 5)]), [])
        self.assertEqual(merge_all([(0, 10), (20, 20)]), [(0, 10)])
        self.assertEqual(merge_all([(0, 10), (30, 40), (20, 20)]), [(0, 10), (30, 40)])

    def test_input_is_left_unchanged(self):
        segments = [(0, 10), (20, 30)]
        _merge_rx_segment(segments, 10, 20)
        self.assertEqual(segments, [(0, 10), (20, 30)])

    def test_random_sequences_match_a_set_of_covered_offsets(self):
        rng = random.Random(20261021)
        for _ in range(3000):
            size = rng.randint(1, 120)
            segments, covered, received = [], set(), []
            for _ in range(rng.randint(1, 25)):
                if received and rng.random() < 0.2:
                    start, end = rng.choice(received)
                else:
                    start = rng.randint(0, size)
                    end = rng.randint(start, min(size, start + rng.randint(0, 40)))
                received.append((start, end))
                segments = _merge_rx_segment(segments, start, end)
                covered.update(range(start, end))
                self.assertEqual(segments, runs(covered), f"after receiving {received}")


class TestModularChecksumMatchesWarpOS(unittest.TestCase):
    def test_one_piece_at_every_lane(self):
        for offset, sums in WARPOS_SUM_AT_OFFSET.items():
            for n, expected in zip(WARPOS_SUM_LENGTHS, sums):
                with self.subTest(offset=offset, n=n):
                    self.assertEqual(modular_checksum_update(0, pattern(n, 12), offset=offset), expected)

    def test_continues_a_running_checksum(self):
        for n, seed, offset, initial, expected in WARPOS_SUM_FROM:
            with self.subTest(n=n, offset=offset, initial=initial):
                self.assertEqual(modular_checksum_update(initial, pattern(n, seed), offset=offset), expected)

    def test_wraps_at_32_bits(self):
        self.assertEqual(modular_checksum_update(0, b"\xff" * 1003, offset=2), WARPOS_SUM_FF_1003_AT_2)

    def test_split_across_calls(self):
        for n, seed, base, cuts, expected in WARPOS_SUM_SPLIT:
            data = pattern(n, seed)
            checksum, prev = 0, 0
            for cut in cuts + (n,):
                checksum = modular_checksum_update(checksum, data[prev:cut], offset=base + prev)
                prev = cut
            with self.subTest(n=n, base=base, cuts=cuts):
                self.assertEqual(checksum, expected)
                self.assertEqual(modular_checksum_update(0, data, offset=base), expected)

    def test_any_split_equals_one_call(self):
        rng = random.Random(4)
        for _ in range(500):
            data = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
            base = rng.choice([0, 1, 2, 3, rng.randrange(2**32 - len(data) + 1)])
            cuts = sorted(rng.randint(0, len(data)) for _ in range(rng.randint(0, 8)))
            checksum, prev = 0, 0
            for cut in cuts + [len(data)]:
                checksum = modular_checksum_update(checksum, data[prev:cut], offset=base + prev)
                prev = cut
            self.assertEqual(checksum, modular_checksum_update(0, data, offset=base))

    def test_sender_checksum_matches_warpos(self):
        for vector in WARPOS_TRANSFERS:
            data = pattern(vector["n"], vector["seed"])
            with self.subTest(n=vector["n"]):
                self.assertEqual(modular_checksum_update(0, data), vector["checksum"])


class TestReceiverChecksumMatchesWarpOS(ReceiverTestCase):
    def test_overlapping_and_repeated_bytes_count_once(self):
        n, seed, ranges, expected = WARPOS_SUM_OVERLAP
        data = pattern(n, seed)
        sender = self.sender()
        transaction = self.receive([sender._build_metadata(Path("local.bin"), "file.bin", n)])
        for start, end in ranges:
            self.receiver.handle_pdu_bytes(sender._build_file_data(start, data[start:end]))
        self.assertEqual(transaction.checksum_accum, expected)
        self.assertEqual(transaction.rx_segments, [(0, n)])


class TestCrc16MatchesWarpOS(unittest.TestCase):
    def test_matches_warpos(self):
        for data, seed, expected in WARPOS_CRC16:
            with self.subTest(data=data[:12], length=len(data), seed=seed):
                self.assertEqual(crc16_modbus(data, init=seed), expected)

    def test_ends_every_pdu_high_byte_first(self):
        raw = build_cfdp_pdu(pdu_type=1, source_id=2, seq_num=3, dest_id=1, data_without_crc=pattern(30, 1))
        self.assertEqual(raw[-2:], crc16_modbus(raw[:-2]).to_bytes(2, "big"))


class TestSafeFilename(unittest.TestCase):
    def test_traversal_keeps_only_the_last_component(self):
        for name in [
            "../../outside",
            "../outside",
            "..\\..\\outside",
            "..\\outside",
            "a/../../outside",
            "a\\..\\..\\outside",
            "../..\\../outside",
            "incoming/complete/../../../outside",
        ]:
            with self.subTest(name=name):
                self.assertEqual(safe_filename(name), "outside")

    def test_absolute_paths_keep_only_the_last_component(self):
        for name in [
            "/etc/outside",
            "//outside",
            "C:\\outside",
            "C:/outside",
            "\\\\server\\share\\outside",
            "\\outside",
        ]:
            with self.subTest(name=name):
                self.assertEqual(safe_filename(name), "outside")

    def test_empty_names_get_the_default(self):
        for name in ["", "/", "\\", "dir/", "dir\\", "C:\\", "/etc/"]:
            with self.subTest(name=name):
                self.assertEqual(safe_filename(name), DEFAULT_NAME)

    def test_names_of_only_dots_get_the_default(self):
        for name in [".", "..", "...", "....", "../..", "dir/..", "dir/.", "..\\..", "/.."]:
            with self.subTest(name=name):
                self.assertEqual(safe_filename(name), DEFAULT_NAME)

    def test_a_nul_ends_the_name(self):
        # As it does on the flight side, which hands the name to its OS as a C string.
        self.assertEqual(safe_filename("report.txt\x00.exe"), "report.txt")
        self.assertEqual(safe_filename("outside\x00/../../x"), "outside")
        self.assertEqual(safe_filename("../../outside\x00"), "outside")
        self.assertEqual(safe_filename("\x00"), DEFAULT_NAME)
        self.assertEqual(safe_filename("..\x00x"), DEFAULT_NAME)

    def test_ordinary_names_are_kept(self):
        for name in ["file.bin", "my file (1).txt", ".hidden", "a..b", "x.", "ünïcødé.dat", "tlm_0x1f.csv"]:
            with self.subTest(name=name):
                self.assertEqual(safe_filename(name), name)

    def test_any_name_becomes_one_plain_component(self):
        rng = random.Random(11)
        alphabet = ["a", "b", ".", ".", "/", "\\", "\x00", ":", " ", "é"]
        for _ in range(5000):
            name = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
            result = safe_filename(name)
            self.assertTrue(result, repr(name))
            self.assertNotIn("/", result, repr(name))
            self.assertNotIn("\\", result, repr(name))
            self.assertNotIn("\x00", result, repr(name))
            self.assertNotEqual(set(result), {"."}, repr(name))
            self.assertEqual(Path(result).name, result, repr(name))


class TestReceiverStaysInOutputFolder(unittest.TestCase):
    """A remote sender must never make the receiver write outside its output folder."""

    # The output folder is nested deep enough that every one of these names,
    # if honored, would land inside the temporary tree, where it is seen.
    NESTING = ("1", "2", "3", "4")

    def remote_names(self):
        names = ["../" * k + "outside" for k in range(1, 8)]
        names += ["..\\" * k + "outside" for k in range(1, 8)]
        names += [
            "{root}/outside",
            "incoming/../../../../../outside",
            "outside\x00/../../../../../../../x",
            "..",
            ".",
            "",
            "/",
        ]
        return names

    def test_no_remote_name_writes_outside_the_output_folder(self):
        for template in self.remote_names():
            with self.subTest(name=template), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                name = template.replace("{root}", str(root))
                out = root.joinpath(*self.NESTING, "out")
                receiver = CfdpReceiver(str(out), local_entity_id=1, logger=QuietLogger())
                local = root / "local.bin"
                local.write_bytes(pattern(50, 3))
                sender = CfdpSender(source_entity_id=2, dest_entity_id=1, seq_num=9, max_pdu_bytes=280)
                transaction = None
                for pdu in sender.build_file_transfer(str(local), name):
                    transaction = receiver.handle_pdu_bytes(pdu.raw_pdu)
                local.unlink()

                ancestors = {root.joinpath(*self.NESTING[: i + 1]) for i in range(len(self.NESTING))}
                outside = [p for p in root.rglob("*") if p not in ancestors and p != out and out not in p.parents]
                self.assertEqual(outside, [])
                expected = out / CfdpReceiver.COMPLETE_SUBDIR / safe_filename(name)
                self.assertTrue(transaction.complete)
                self.assertEqual(transaction.file_path, expected)
                self.assertEqual(expected.read_bytes(), pattern(50, 3))


class TestParseCfdpPdu(unittest.TestCase):
    def valid_pdus(self):
        sender = CfdpSender(source_entity_id=2, dest_entity_id=1, seq_num=300, max_pdu_bytes=64)
        return [
            sender._build_metadata(Path("src.bin"), "dst.bin", 1234),
            sender._build_file_data(70000, pattern(30, 4)),
            sender._build_eof(0xDEADBEEF, 1234),
            build_cfdp_pdu(pdu_type=1, source_id=5, seq_num=6, dest_id=7, data_without_crc=b"\x00" * 6, crc_flag=0),
            build_cfdp_pdu(
                pdu_type=0, source_id=1, seq_num=2, dest_id=3, data_without_crc=b"\x04", entity_id_len=8, seq_num_len=8
            ),
        ]

    def test_every_truncation_is_refused(self):
        for raw in self.valid_pdus():
            for cut in range(len(raw)):
                with self.subTest(pdu=raw.hex(), cut=cut):
                    with self.assertRaises(CfdpParseError):
                        parse_cfdp_pdu(raw[:cut])

    def test_every_single_bit_flip_is_refused(self):
        # Every bit but the CRC flag itself: cleared, the PDU reads as one
        # without a CRC, as WarpOS's StorageManager::_parseCfdpPdu() reads it too.
        for raw in self.valid_pdus()[:3]:
            for bit in range(len(raw) * 8):
                if bit == 6:
                    continue
                flipped = bytearray(raw)
                flipped[bit // 8] ^= 0x80 >> (bit % 8)
                with self.subTest(pdu=raw.hex(), bit=bit):
                    with self.assertRaises(CfdpParseError):
                        parse_cfdp_pdu(bytes(flipped))

    def test_wrong_crc_is_refused(self):
        raw = self.valid_pdus()[0]
        bad = raw[:-2] + ((parse_int_be(raw[-2:]) + 1) & 0xFFFF).to_bytes(2, "big")
        with self.assertRaisesRegex(CfdpParseError, "CRC mismatch"):
            parse_cfdp_pdu(bad)

    def test_wrong_version_is_refused(self):
        raw = bytearray(self.valid_pdus()[3])
        for version in (0, 2, 7):
            raw[0] = (raw[0] & 0x1F) | (version << 5)
            with self.assertRaisesRegex(CfdpParseError, "version"):
                parse_cfdp_pdu(bytes(raw))

    def test_crc_flag_with_a_data_field_shorter_than_the_crc_is_refused(self):
        for data_length in (0, 1):
            raw = bytes([0x22]) + data_length.to_bytes(2, "big") + bytes([0x11]) + bytes(6) + bytes(data_length)
            with self.subTest(data_length=data_length):
                with self.assertRaises(CfdpParseError):
                    parse_cfdp_pdu(raw)

    def test_padding_after_the_pdu_is_ignored(self):
        for raw in self.valid_pdus():
            parsed = parse_cfdp_pdu(raw + bytes(20))
            self.assertEqual(parsed.raw_pdu, raw)

    def test_random_bytes_raise_only_cfdp_parse_error(self):
        rng = random.Random(99)
        valid = self.valid_pdus()
        for i in range(20000):
            if i % 2:
                raw = bytes(rng.randrange(256) for _ in range(rng.randint(0, 40)))
                raw = bytes([0x20 | (raw[0] & 0x1F)]) + raw[1:] if raw and rng.random() < 0.8 else raw
            else:
                mutated = bytearray(rng.choice(valid))
                for _ in range(rng.randint(1, 3)):
                    mutated[rng.randrange(len(mutated))] = rng.randrange(256)
                raw = bytes(mutated[: rng.randint(0, len(mutated))]) if rng.random() < 0.3 else bytes(mutated)
            try:
                parse_cfdp_pdu(raw)
            except CfdpParseError:
                pass
            except Exception as exc:
                self.fail(f"{type(exc).__name__}: {exc} for {raw.hex()}")


class TestBuildThenParse(unittest.TestCase):
    def setUp(self):
        self.sender = CfdpSender(source_entity_id=0x0102, dest_entity_id=0x0304, seq_num=0xFEDC, max_pdu_bytes=280)

    def assert_header(self, parsed, pdu_type):
        self.assertEqual(parsed.version, 1)
        self.assertEqual(parsed.pdu_type, pdu_type)
        self.assertEqual(parsed.direction, 0)
        self.assertEqual(parsed.trans_mode, 1)
        self.assertEqual(parsed.crc_flag, 1)
        self.assertEqual(parsed.large_file, 0)
        self.assertEqual((parsed.entity_id_len, parsed.seq_num_len), (2, 2))
        self.assertEqual((parsed.source_id, parsed.seq_num, parsed.dest_id), (0x0102, 0xFEDC, 0x0304))
        self.assertEqual(parsed.data_length, len(parsed.data_no_crc) + 2)

    def test_metadata(self):
        parsed = parse_cfdp_pdu(self.sender._build_metadata(Path("/x/local name.bin"), "remote/name.bin", 123456))
        self.assert_header(parsed, 0)
        data = parsed.data_no_crc
        self.assertEqual(data[0], METADATA_FD)
        self.assertEqual(data[1], 0)
        self.assertEqual(parse_int_be(data[2:6]), 123456)
        source, idx = parse_lv_string(data, 6)
        dest, idx = parse_lv_string(data, idx)
        self.assertEqual((source, dest, idx), ("local name.bin", "remote/name.bin", len(data)))

    def test_file_data(self):
        chunk = pattern(200, 8)
        parsed = parse_cfdp_pdu(self.sender._build_file_data(0xFFFFFF00, chunk))
        self.assert_header(parsed, 1)
        self.assertEqual(parse_int_be(parsed.data_no_crc[:4]), 0xFFFFFF00)
        self.assertEqual(parsed.data_no_crc[4:], chunk)

    def test_eof(self):
        parsed = parse_cfdp_pdu(self.sender._build_eof(0x89ABCDEF, 0xFFFFFFFF))
        self.assert_header(parsed, 0)
        self.assertEqual(parsed.data_no_crc, bytes([EOF_FD, 0]) + (0x89ABCDEF).to_bytes(4, "big") + bytes([0xFF] * 4))

    def test_every_header_field_and_length(self):
        rng = random.Random(3)
        for entity_id_len in range(1, 9):
            for seq_num_len in range(1, 9):
                fields = dict(
                    pdu_type=rng.randint(0, 1),
                    source_id=rng.randrange(256**entity_id_len),
                    seq_num=256**seq_num_len - 1,
                    dest_id=rng.randrange(256**entity_id_len),
                    data_without_crc=pattern(rng.randint(0, 40), entity_id_len),
                    entity_id_len=entity_id_len,
                    seq_num_len=seq_num_len,
                    trans_mode=rng.randint(0, 1),
                    direction=rng.randint(0, 1),
                    crc_flag=rng.randint(0, 1),
                    large_file=rng.randint(0, 1),
                )
                parsed = parse_cfdp_pdu(build_cfdp_pdu(**fields))
                with self.subTest(**{k: v for k, v in fields.items() if k != "data_without_crc"}):
                    for key, value in fields.items():
                        if key != "data_without_crc":
                            self.assertEqual(getattr(parsed, key), value, key)
                    self.assertEqual(parsed.data_no_crc, fields["data_without_crc"])

    def test_bad_header_lengths_are_refused(self):
        for entity_id_len, seq_num_len in [(0, 2), (9, 2), (2, 0), (2, 9)]:
            with self.subTest(entity_id_len=entity_id_len, seq_num_len=seq_num_len):
                with self.assertRaises(CfdpBuildError):
                    build_cfdp_pdu(
                        pdu_type=0,
                        source_id=1,
                        seq_num=1,
                        dest_id=1,
                        data_without_crc=b"\x04",
                        entity_id_len=entity_id_len,
                        seq_num_len=seq_num_len,
                    )

    def test_data_field_past_16_bits_is_refused(self):
        build_cfdp_pdu(pdu_type=1, source_id=1, seq_num=1, dest_id=1, data_without_crc=bytes(0xFFFD))
        with self.assertRaises(CfdpBuildError):
            build_cfdp_pdu(pdu_type=1, source_id=1, seq_num=1, dest_id=1, data_without_crc=bytes(0xFFFE))


class TestWarpOSTransfers(ReceiverTestCase):
    """Whole transfers exactly as WarpOS's StorageManager packs them."""

    def test_sender_builds_what_warpos_builds(self):
        for vector in WARPOS_TRANSFERS:
            local = self.root / vector["local"]
            local.write_bytes(pattern(vector["n"], vector["seed"]))
            sender = CfdpSender(
                source_entity_id=vector["source"],
                dest_entity_id=vector["dest"],
                seq_num=vector["seq"],
                max_pdu_bytes=vector["max_pdu_bytes"],
            )
            built = [pdu.raw_pdu.hex() for pdu in sender.build_file_transfer(str(local), vector["remote"])]
            with self.subTest(n=vector["n"], max_pdu_bytes=vector["max_pdu_bytes"]):
                self.assertEqual(built, vector["pdus"])

    def test_receiver_reassembles_what_warpos_sends(self):
        for vector in WARPOS_TRANSFERS:
            receiver = CfdpReceiver(str(self.out), local_entity_id=vector["dest"], logger=self.logger)
            transaction = None
            for raw in vector["pdus"]:
                transaction = receiver.handle_pdu_bytes(bytes.fromhex(raw))
            name = safe_filename(vector["remote"])
            with self.subTest(n=vector["n"]):
                self.assertTrue(transaction.complete)
                self.assertEqual(transaction.checksum_accum, vector["checksum"])
                self.assertEqual(transaction.file_path, self.out / CfdpReceiver.COMPLETE_SUBDIR / name)
                self.assertEqual(transaction.file_path.read_bytes(), pattern(vector["n"], vector["seed"]))

    def test_warpos_headers_parse(self):
        for vector in WARPOS_TRANSFERS:
            for i, raw in enumerate(vector["pdus"]):
                parsed = parse_cfdp_pdu(bytes.fromhex(raw))
                with self.subTest(n=vector["n"], pdu=i):
                    self.assertEqual((parsed.version, parsed.direction, parsed.trans_mode), (1, 0, 1))
                    self.assertEqual((parsed.crc_flag, parsed.large_file), (1, 0))
                    self.assertEqual((parsed.entity_id_len, parsed.seq_num_len), (2, 2))
                    self.assertEqual(
                        (parsed.source_id, parsed.seq_num, parsed.dest_id),
                        (vector["source"], vector["seq"], vector["dest"]),
                    )
                    self.assertEqual(parsed.pdu_type, 0 if i in (0, len(vector["pdus"]) - 1) else 1)


class TestSenderFitsWarpOS(ReceiverTestCase):
    """
    WarpOS's StorageManager::_parseCfdpPdu() drops a PDU whose data field
    (CRC included) is longer than max_pdu_bytes - MAX_CFDP_HEADER_SIZE, the
    payload limit StorageManager::start() sets plus the CRC.
    """

    def test_every_pdu_fits(self):
        for max_pdu_bytes in (40, 48, 63, 128, 256, 280):
            for n in (0, 1, max_pdu_bytes - 29, max_pdu_bytes - 28, max_pdu_bytes - 27, 700):
                for raw in self.transfer(pattern(n, 1), remote="f", max_pdu_bytes=max_pdu_bytes):
                    parsed = parse_cfdp_pdu(raw)
                    with self.subTest(max_pdu_bytes=max_pdu_bytes, n=n, pdu=raw[:20].hex()):
                        self.assertLessEqual(parsed.data_length, max_pdu_bytes - MAX_CFDP_HEADER_SIZE)
                        self.assertLessEqual(len(raw), max_pdu_bytes)

    def test_metadata_too_long_for_warpos_is_refused(self):
        # 63-byte PDUs: WarpOS takes a Metadata data field of 39 bytes before the
        # CRC, 8 of them fixed, the file names' LV values the rest.
        sender = self.sender(max_pdu_bytes=63)
        local = self.root / "a.bin"
        local.write_bytes(b"data")
        list(sender.build_file_transfer(str(local), "r" * 26))
        with self.assertRaises(CfdpBuildError):
            list(sender.build_file_transfer(str(local), "r" * 27))

    def test_an_eof_too_long_for_warpos_is_refused_before_anything_is_sent(self):
        # 33-byte PDUs take an 11-byte data field: this Metadata's, never an EOF's 12.
        local = self.root / "a"
        local.write_bytes(b"data")
        transfer = self.sender(max_pdu_bytes=33).build_file_transfer(str(local), "")
        with self.assertRaisesRegex(CfdpBuildError, "EOF"):
            next(transfer)


class TestTransfers(ReceiverTestCase):
    def test_whole_transfer_lands_in_complete(self):
        sizes = (0, 1, 35, 36, 37, 100, 1003)
        for n in sizes:
            with self.subTest(n=n):
                data = pattern(n, n)
                transaction = self.receive(self.transfer(data, remote=f"file{n}.bin", seq=n))
                self.assertTrue(transaction.complete)
                self.assertEqual(self.files().get(f"incoming/complete/file{n}.bin"), data)
        self.assertEqual(sorted(self.files()), sorted(f"incoming/complete/file{n}.bin" for n in sizes))

    def test_whole_transfer_at_the_default_pdu_size(self):
        data = pattern(5000, 77)
        local = self.root / "big.bin"
        local.write_bytes(data)
        sender = CfdpSender(source_entity_id=2, dest_entity_id=1, seq_num=1)
        self.receive([pdu.raw_pdu for pdu in sender.build_file_transfer(str(local), "big.bin")])
        self.assertEqual(self.files(), {"incoming/complete/big.bin": data})

    def test_file_data_out_of_order_and_duplicated(self):
        rng = random.Random(1021)
        for trial in range(40):
            data = pattern(rng.randint(1, 600), trial)
            pdus = self.transfer(data, remote=f"t{trial}.bin", seq=trial)
            file_data = pdus[1:-1]
            shuffled = file_data + [rng.choice(file_data) for _ in range(rng.randint(0, 5))]
            rng.shuffle(shuffled)
            transaction = self.receive([pdus[0]] + shuffled + [pdus[-1]])
            with self.subTest(trial=trial):
                self.assertTrue(transaction.complete)
                self.assertEqual(self.files()[f"incoming/complete/t{trial}.bin"], data)

    def test_overlapping_resends_with_other_chunk_sizes(self):
        data = pattern(777, 5)
        first = self.transfer(data, seq=3, max_pdu_bytes=48)
        second = self.transfer(data, seq=3, max_pdu_bytes=64)
        mixed = first[1:-1] + second[1:-1]
        random.Random(6).shuffle(mixed)
        transaction = self.receive([first[0]] + mixed + [second[-1]])
        self.assertTrue(transaction.complete)
        self.assertEqual(self.files(), {"incoming/complete/file.bin": data})

    def test_a_missing_segment_leaves_an_incomplete_file_naming_it(self):
        data = pattern(100, 9)
        # The first, the middle and the last of three File Data PDUs: [0, 36) [36, 72) [72, 100)
        for lost in (1, 2, 3):
            with self.subTest(lost=lost):
                name = f"file{lost}.bin"
                pdus = self.transfer(data, remote=name, seq=lost)
                parsed = parse_cfdp_pdu(pdus[lost])
                lost_start = parse_int_be(parsed.data_no_crc[:4])
                lost_end = lost_start + len(parsed.data_no_crc) - 4
                self.receive(pdus[:lost] + pdus[lost + 1 : -1])

                staged = self.status(f"incoming/in_progress/{name}.cfdp-status.json")
                self.assertEqual(staged["state"], "receiving")
                self.assertEqual(staged["missing_ranges"], [[lost_start, lost_end]])
                self.assertEqual(staged["bytes_received"], 100 - (lost_end - lost_start))
                self.assertEqual(staged["expected_file_size"], 100)
                self.assertEqual((staged["source_file_name"], staged["dest_file_name"]), (f"{lost}.bin", name))

                with self.assertRaises(CfdpParseError):
                    self.receiver.handle_pdu_bytes(pdus[-1])
                files = {path: content for path, content in self.files().items() if name in path}
                self.assertEqual(sorted(files), [f"incoming/failed/{name}", f"incoming/failed/{name}.cfdp-status.json"])
                # A gap is zero-filled; a missing tail is simply not there.
                expected = data[:lost_start]
                if lost_end < 100:
                    expected += bytes(lost_end - lost_start) + data[lost_end:]
                self.assertEqual(files[f"incoming/failed/{name}"], expected)
                failed = self.status(f"incoming/failed/{name}.cfdp-status.json")
                self.assertEqual(failed["state"], "failed")
                self.assertEqual(failed["missing_ranges"], [[lost_start, lost_end]])
                self.assertEqual(failed["bytes_received"], 100 - (lost_end - lost_start))
                self.assertIn("before every byte", failed["reason"])

    def test_several_missing_segments_are_all_named(self):
        data = pattern(200, 2)
        pdus = self.transfer(data)
        # 36-byte chunks: [0, 36) [36, 72) [72, 108) [108, 144) [144, 180) [180, 200)
        kept = [pdus[0], pdus[2], pdus[4], pdus[-1]]
        with self.assertRaises(CfdpParseError):
            self.receive(kept)
        failed = self.status("incoming/failed/file.bin.cfdp-status.json")
        self.assertEqual(failed["missing_ranges"], [[0, 36], [72, 108], [144, 200]])
        self.assertEqual(failed["bytes_received"], 72)

    def test_wrong_checksum_in_eof_goes_to_failed(self):
        data = pattern(100, 9)
        pdus = self.transfer(data)
        wrong = self.sender()._build_eof(modular_checksum_update(0, data) ^ 1, len(data))
        with self.assertRaisesRegex(CfdpParseError, "checksum"):
            self.receive(pdus[:-1] + [wrong])
        files = self.files()
        self.assertEqual(sorted(files), ["incoming/failed/file.bin", "incoming/failed/file.bin.cfdp-status.json"])
        self.assertEqual(files["incoming/failed/file.bin"], data)
        failed = self.status("incoming/failed/file.bin.cfdp-status.json")
        self.assertEqual((failed["state"], failed["missing_ranges"]), ("failed", []))
        self.assertIn("checksum", failed["reason"])

    def test_wrong_size_in_eof_goes_to_failed(self):
        data = pattern(100, 9)
        pdus = self.transfer(data)
        for size in (99, 101):
            with self.subTest(size=size):
                receiver = CfdpReceiver(str(self.out / str(size)), local_entity_id=1, logger=self.logger)
                for raw in pdus[:-1]:
                    receiver.handle_pdu_bytes(raw)
                with self.assertRaises(CfdpParseError):
                    receiver.handle_pdu_bytes(self.sender()._build_eof(modular_checksum_update(0, data), size))
                self.assertTrue((self.out / str(size) / CfdpReceiver.FAILED_SUBDIR / "file.bin").exists())
                self.assertFalse((self.out / str(size) / CfdpReceiver.COMPLETE_SUBDIR / "file.bin").exists())

    def test_eof_cancelling_the_transfer_goes_to_failed(self):
        pdus = self.transfer(pattern(100, 9))
        cancel = bytearray(parse_cfdp_pdu(pdus[-1]).data_no_crc)
        cancel[1] = 0x40
        raw = build_cfdp_pdu(pdu_type=0, source_id=2, seq_num=7, dest_id=1, data_without_crc=bytes(cancel))
        transaction = self.receive(pdus[:-1] + [raw])
        self.assertTrue(transaction.complete)
        self.assertEqual(transaction.condition_code, 4)
        failed = self.status("incoming/failed/file.bin.cfdp-status.json")
        self.assertIn("condition code 4", failed["reason"])
        self.assertNotIn("incoming/complete/file.bin", self.files())

    def test_late_file_data_after_completion_changes_nothing(self):
        data = pattern(100, 9)
        pdus = self.transfer(data)
        self.receive(pdus)
        before = self.files()
        result = self.receiver.handle_pdu_bytes(pdus[2])
        self.assertIsNone(result)
        self.assertEqual(self.files(), before)
        self.assertEqual(before, {"incoming/complete/file.bin": data})

    def test_late_file_data_after_failure_leaves_it_failed(self):
        pdus = self.transfer(pattern(100, 9))
        with self.assertRaises(CfdpParseError):
            self.receive(pdus[:2] + pdus[3:])
        before = self.files()
        self.assertIsNone(self.receiver.handle_pdu_bytes(pdus[2]))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.status("incoming/failed/file.bin.cfdp-status.json")["state"], "failed")

    def test_repeated_eof_after_failure_keeps_the_status(self):
        pdus = self.transfer(pattern(100, 9))
        with self.assertRaises(CfdpParseError):
            self.receive(pdus[:2] + pdus[3:])
        before = self.files()
        try:
            self.receiver.handle_pdu_bytes(pdus[-1])
        except CfdpParseError:
            pass
        self.assertEqual(sorted(self.files()), sorted(before))
        self.assertEqual(self.status("incoming/failed/file.bin.cfdp-status.json")["state"], "failed")

    def test_a_failed_transfer_leaves_an_earlier_complete_file_alone(self):
        first = pattern(100, 1)
        self.receive(self.transfer(first, seq=1))
        second = self.transfer(pattern(100, 2), seq=2)
        with self.assertRaises(CfdpParseError):
            self.receive(second[:2] + second[3:])
        self.assertEqual(self.files()["incoming/complete/file.bin"], first)

    def test_two_transfers_to_one_name_never_make_a_corrupt_file(self):
        # Two files of one name in different folders, at once. The second
        # transfer's Metadata empties the staged file the first is writing; the
        # first must not then be published.
        a, b = pattern(100, 1), pattern(100, 2)
        first = self.transfer(a, remote="/sd/run1/tlm.csv", seq=1)
        second = self.transfer(b, remote="/sd/run2/tlm.csv", seq=2)
        self.receive(first[:3] + second[:3])
        for raw in first[3:] + second[3:]:
            try:
                self.receiver.handle_pdu_bytes(raw)
            except CfdpParseError:
                pass
        self.assertEqual(self.files(), {"incoming/complete/tlm.csv": b})
        errors = [msg for level, msg in self.logger.messages if level == "error"]
        self.assertTrue(any("abandoned" in msg for msg in errors), errors)

    def test_interleaved_transactions_both_complete(self):
        a, b = pattern(300, 1), pattern(250, 2)
        first, second = self.transfer(a, remote="a.bin", seq=1), self.transfer(b, remote="b.bin", seq=2)
        mixed = [raw for pair in zip(first, second) for raw in pair] + first[len(second) :] + second[len(first) :]
        eofs = [first[-1], second[-1]]
        self.receive([raw for raw in mixed if raw not in eofs] + eofs)
        self.assertEqual(self.files(), {"incoming/complete/a.bin": a, "incoming/complete/b.bin": b})

    def test_file_data_past_the_expected_size_is_refused(self):
        pdus = self.transfer(pattern(30, 1))
        self.receive(pdus[:1])
        with self.assertRaisesRegex(CfdpParseError, "exceeds expected size"):
            self.receiver.handle_pdu_bytes(self.sender()._build_file_data(20, pattern(11, 1)))
        self.assertEqual(self.files()["incoming/in_progress/file.bin"], b"")

    def test_pdus_for_another_entity_are_ignored(self):
        local = self.root / "x.bin"
        local.write_bytes(pattern(50, 1))
        sender = CfdpSender(source_entity_id=2, dest_entity_id=99, seq_num=1, max_pdu_bytes=48)
        for pdu in sender.build_file_transfer(str(local), "x.bin"):
            self.assertIsNone(self.receiver.handle_pdu_bytes(pdu.raw_pdu))
        self.assertEqual(self.files(), {})


class TestReceiverRefusesMalformedPdus(ReceiverTestCase):
    def directive(self, data, large_file=0, seq=7):
        return build_cfdp_pdu(
            pdu_type=0, source_id=2, seq_num=seq, dest_id=1, data_without_crc=data, large_file=large_file
        )

    def test_short_or_malformed_directives_are_refused(self):
        # Metadata first, so that each EOF below is refused for its own fault.
        metadata_pdu = self.transfer(b"abc")[0]
        self.receiver.handle_pdu_bytes(metadata_pdu)
        metadata = parse_cfdp_pdu(metadata_pdu).data_no_crc
        cases = {
            "empty directive": self.directive(b""),
            "metadata, directive alone": self.directive(bytes([METADATA_FD])),
            "metadata, no file size": self.directive(metadata[:5]),
            "metadata, large file size cut short": self.directive(metadata[:9], large_file=1),
            "metadata, no source name": self.directive(metadata[:6]),
            "metadata, source name cut short": self.directive(metadata[:9]),
            "metadata, no destination name": self.directive(metadata[:12]),
            "metadata, destination name cut short": self.directive(metadata[:-1]),
            "eof, nine bytes": self.directive(bytes([EOF_FD]) + bytes(8)),
            "eof, large file size cut short": self.directive(bytes([EOF_FD]) + bytes(9), large_file=1),
        }
        for label, raw in cases.items():
            with self.subTest(label):
                with self.assertRaises(CfdpParseError):
                    self.receiver.handle_pdu_bytes(raw)
        staged = ["incoming/in_progress/file.bin", "incoming/in_progress/file.bin.cfdp-status.json"]
        self.assertEqual(sorted(self.files()), staged)

    def test_file_data_without_an_offset_is_refused(self):
        self.receive(self.transfer(pattern(30, 1))[:1])
        raw = build_cfdp_pdu(pdu_type=1, source_id=2, seq_num=7, dest_id=1, data_without_crc=b"\x00\x00\x00")
        with self.assertRaisesRegex(CfdpParseError, "offset"):
            self.receiver.handle_pdu_bytes(raw)

    def test_file_data_before_metadata_is_refused(self):
        with self.assertRaisesRegex(CfdpParseError, "before Metadata"):
            self.receiver.handle_pdu_bytes(self.transfer(pattern(30, 1))[1])

    def test_eof_before_metadata_is_refused(self):
        for data in (b"", pattern(30, 1)):
            with self.subTest(size=len(data)):
                with self.assertRaises(CfdpParseError):
                    self.receiver.handle_pdu_bytes(self.transfer(data, seq=len(data))[-1])
        self.assertEqual(self.files(), {})

    def test_a_name_too_long_to_stage_with_its_status_is_refused(self):
        # The status sidecar adds STATUS_SUFFIX to the name, and both must fit in 255 bytes.
        longest = 255 - len(CfdpReceiver.STATUS_SUFFIX)
        self.receive(self.transfer(pattern(50, 1), remote="a" * longest, seq=1, max_pdu_bytes=280))
        self.assertEqual(self.files(), {"incoming/complete/" + "a" * longest: pattern(50, 1)})
        for seq, name in enumerate(["b" * (longest + 1), "é" * 120], start=2):
            with self.subTest(length=len(name.encode("utf-8"))):
                pdus = self.transfer(pattern(50, 1), remote=name, seq=seq, max_pdu_bytes=280)
                with self.assertRaisesRegex(CfdpParseError, "too long"):
                    self.receiver.handle_pdu_bytes(pdus[0])
        self.assertEqual(len(self.files()), 1)

    def test_a_name_not_utf8_is_kept_as_hex(self):
        for seq, raw_name, fits in [(1, b"\xff" * 100, True), (2, b"\xfe" * 120, False)]:
            data = bytes([METADATA_FD, 0]) + (3).to_bytes(4, "big") + b"\x01x" + bytes([len(raw_name)]) + raw_name
            sender = self.sender(seq)
            pdus = [self.directive(data, seq=seq), sender._build_file_data(0, b"abc"), sender._build_eof(0x61626300, 3)]
            with self.subTest(length=len(raw_name)):
                if fits:
                    self.receive(pdus)
                    self.assertEqual(self.files()["incoming/complete/" + raw_name.hex()], b"abc")
                else:
                    with self.assertRaisesRegex(CfdpParseError, "too long"):
                        self.receive(pdus)

    def test_random_pdus_raise_only_cfdp_parse_error(self):
        rng = random.Random(2026)
        for _ in range(4000):
            large_file = int(rng.random() < 0.2)
            size_len = 8 if large_file else 4
            kind = rng.choice(["metadata", "eof", "file_data", "other"])
            if kind == "metadata":
                names = [bytes(rng.randrange(256) for _ in range(rng.randint(0, 200))) for _ in range(2)]
                data = bytes([METADATA_FD, rng.randrange(256)]) + rng.randrange(400).to_bytes(size_len, "big")
                for name in names:
                    data += bytes([max(0, min(255, len(name) + rng.choice([0, 0, 0, 1, -1])))]) + name
                data = data[: rng.randint(0, len(data))] if rng.random() < 0.3 else data
            elif kind == "eof":
                data = bytes([EOF_FD, rng.choice([0, 0, 0x10, 0xF0])]) + bytes(rng.randrange(256) for _ in range(4))
                data += rng.randrange(400).to_bytes(size_len, "big")
                data = data[: rng.randint(0, len(data))] if rng.random() < 0.3 else data
            elif kind == "file_data":
                data = rng.randrange(450).to_bytes(size_len, "big") + bytes(rng.randint(0, 60))
                data = data[: rng.randint(0, len(data))] if rng.random() < 0.2 else data
            else:
                data = bytes(rng.randrange(256) for _ in range(rng.randint(0, 20)))
            raw = build_cfdp_pdu(
                pdu_type=int(kind == "file_data"),
                source_id=2,
                seq_num=rng.randint(0, 5),
                dest_id=1,
                data_without_crc=data,
                large_file=large_file,
            )
            try:
                self.receiver.handle_pdu_bytes(raw)
            except CfdpParseError:
                pass
            except Exception as exc:
                self.fail(f"{type(exc).__name__}: {exc} for {raw.hex()}")
        outside = [p for p in self.root.rglob("*") if p != self.out and self.out not in p.parents]
        self.assertEqual(outside, [])


if __name__ == "__main__":
    unittest.main()
