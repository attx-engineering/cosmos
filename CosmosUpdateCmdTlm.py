#!/usr/bin/env python3
###############################################################################
# Copyright (c) ATTX LLC 2024. All Rights Reserved.
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
"""
Generate OpenC3/COSMOS cmd.txt and tlm.txt from a WarpOS warplink cmd_tlm.json.

Reads the schema_version 2 JSON produced by utils/buildWarpLinkCmdTlmJson.py
and emits one command definition file and one telemetry definition file for
the OpenC3/COSMOS plugin.

COSMOS target name and output paths are derived from the JSON's cosmos_target
field so that each build gets its own COSMOS target (e.g., SIMPLE_PI_BLINKER),
allowing multiple builds to coexist in one COSMOS instance.  A matching
TARGET + INTERFACE block, modelled on WARP_CUBE's and given its own UDP ports,
is added to plugin.txt when the target is new.

Telemetry rule : only packets with at least one registration entry are emitted.
Command rule   : all commands from all apps in the build are emitted.

Usage:
    python3 CosmosUpdateCmdTlm.py --cmd-tlm-json build/cmd_tlm.json
    python3 CosmosUpdateCmdTlm.py \\
        --cmd-tlm-json  build/cmd_tlm.json \\
        --tlm-template  templates/telemetry.txt \\
        --cmd-template  templates/command.txt \\
        --target-dir    openc3-cosmos-warplink/targets
"""
import argparse
import json
import os
import re
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# CCSDS APID flag masks
# ---------------------------------------------------------------------------
_TLM_APID_MASK = 0x0800   # telemetry flag
_CMD_APID_MASK = 0x1800   # command + secondary-header-present flags

# ---------------------------------------------------------------------------
# plugin.txt generation
# ---------------------------------------------------------------------------
# Host a generated TARGET block points at.  host.docker.internal routes out of
# the COSMOS container to the machine running it, which is right for a bridge
# or a simulator; a board on the network needs its own address instead.
DEFAULT_PLUGIN_HOST = "host.docker.internal"

# First UDP port used when plugin.txt declares no ports at all.
_DEFAULT_BASE_PORT = 5005

# ---------------------------------------------------------------------------
# Telemetry packet naming
# ---------------------------------------------------------------------------
# False: only suffix packet names with _<instance> when an app registers the
#        packet on more than one instance, so single-instance names stay short.
# True:  always suffix, which keeps names stable if an app later gains a
#        second instance (at the cost of renaming everything once, now).
ALWAYS_SUFFIX_INSTANCE = False

# ---------------------------------------------------------------------------
# Type mapping: WarpOS type → (COSMOS type keyword, bit width per element)
# ---------------------------------------------------------------------------
_TYPE_MAP: dict[str, tuple[str, int]] = {
    "uint8":   ("UINT",   8),
    "uint16":  ("UINT",  16),
    "uint32":  ("UINT",  32),
    "int8":    ("INT",    8),
    "int16":   ("INT",   16),
    "int32":   ("INT",   32),
    "float32": ("FLOAT", 32),
    "float":   ("FLOAT", 32),
    "double":  ("FLOAT", 64),
    "float16": ("UINT",  16),   # raw UINT16; TLM gets READ_CONVERSION
    "bool":    ("UINT",   8),   # with STATE FALSE 0 / STATE TRUE 1
    "char":    ("STRING", 8),   # multiply by array_length for total bits
}

# ---------------------------------------------------------------------------
# Units: abbreviation → (full name, abbreviation) for COSMOS UNITS keyword
# ---------------------------------------------------------------------------
_UNITS_FULL: dict[str, tuple[str, str]] = {
    "s":        ("seconds",          "s"),
    "ns":       ("nanoseconds",      "ns"),
    "ms":       ("milliseconds",     "ms"),
    "Hz":       ("Hertz",            "Hz"),
    "rad":      ("radians",          "rad"),
    "rad/s":    ("radians/second",   "rad/s"),
    "deg":      ("degrees",          "deg"),
    "deg/s":    ("degrees/second",   "deg/s"),
    "N":        ("Newtons",          "N"),
    "N*m":      ("Newton-meters",    "N*m"),
    "m":        ("meters",           "m"),
    "m/s":      ("meters/second",    "m/s"),
    "m/s^2":    ("meters/second^2",  "m/s^2"),
    "K":        ("Kelvin",           "K"),
    "V":        ("Volts",            "V"),
    "A":        ("Amperes",          "A"),
    "W":        ("Watts",            "W"),
    "%":        ("percent",          "%"),
    "Bytes":    ("Bytes",            "Bytes"),
}


def _units_line(abbr: str) -> str:
    """Return a COSMOS UNITS line for the given unit abbreviation."""
    full, short = _UNITS_FULL.get(abbr, (abbr, abbr))
    return f"    UNITS {full} {short}\n"


def _sub_aligned(text: str, token: str, value: str) -> str:
    """
    Replace a column-aligned token, preserving the width it occupied.

    Used for the numeric tokens that sit in a fixed column (<<APID>>,
    <<INSTANCE>>, <<SIZE>>).  The token plus its trailing spaces defines the
    column width; the substituted value is padded to the same width so the
    generated files stay readable.  Values wider than the column push the
    rest of the line right, as they would anyway.
    """
    def repl(match: re.Match) -> str:
        width = len(token) + len(match.group(1))
        return f"{value:<{width}}" if len(value) < width else f"{value} "

    return re.sub(re.escape(token) + r"( *)", repl, text)


def _resolve_type(field: dict) -> tuple[str, int]:
    """
    Return (COSMOS_TYPE, total_bits) for a field.

    For STRING (char) arrays, total_bits = array_length * 8.
    For all other arrays, the bits are per-element; the caller must
    expand them into indexed items.
    """
    warpos_type = field["type"].lower()
    cosmos_type, bits_per = _TYPE_MAP.get(warpos_type, ("UINT", 8))
    array_length = field.get("array_length", 0) or 0

    if cosmos_type == "STRING":
        # char[] → single STRING item with total bit width
        total_bits = bits_per * (array_length if array_length > 0 else 1)
        return cosmos_type, total_bits

    return cosmos_type, bits_per


# ---------------------------------------------------------------------------
# App section comment block
# ---------------------------------------------------------------------------

def _app_comment(app: dict) -> str:
    sep  = "#" * 78
    name = f"{app['name']} ({app['short_name']})"
    desc = app.get("description", "")
    n_inst = len(app["instances"])
    inst_str = f"{'Instance' if n_inst == 1 else f'{n_inst} Instances'}"
    base_hex = f"0x{app['apid_base']:03X}"
    lines = [
        f"# {sep}\n",
        f"# {name}\n",
    ]
    if desc:
        lines.append(f"# {desc}\n")
    lines.append(f"# Base APID: {base_hex}  |  {inst_str}\n")
    lines.append(f"# {sep}\n")
    lines.append("\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Telemetry formatter
# ---------------------------------------------------------------------------

def _format_tlm_item(field: dict, append_key: str = "APPEND_ITEM") -> str:
    """Format one telemetry item (scalar or array element)."""
    cosmos_type, bits_per = _resolve_type(field)
    warpos_type  = field["type"].lower()
    array_length = field.get("array_length", 0) or 0
    description  = field.get("description", "")
    units        = field.get("units")

    lines = []

    if cosmos_type == "STRING":
        # Single STRING item for char[]
        total_bits = bits_per  # already total from _resolve_type
        line = f"  {append_key:<18}{field['id']:<30}{total_bits:<10}{cosmos_type:<10}\"{description}\"\n"
        lines.append(line)
    elif array_length > 0:
        for i in range(array_length):
            item_name = f"{field['id']}_{i}"
            line = (
                f"  {append_key:<18}{item_name:<30}{bits_per:<10}"
                f"{cosmos_type:<10}\"{description}\"\n"
            )
            lines.append(line)
            if warpos_type == "float16":
                lines.append("    READ_CONVERSION half_float_conversion.py\n")
            if units:
                lines.append(_units_line(units))
    else:
        line = (
            f"  {append_key:<18}{field['id']:<30}{bits_per:<10}"
            f"{cosmos_type:<10}\"{description}\"\n"
        )
        lines.append(line)
        if warpos_type == "float16":
            lines.append("    READ_CONVERSION half_float_conversion.py\n")
        if warpos_type == "bool":
            lines.append("    STATE FALSE 0\n")
            lines.append("    STATE TRUE 1\n")
        if units:
            lines.append(_units_line(units))

    return "".join(lines)


def _format_tlm_packets(template: str, target: str, pkt: dict, short_name: str) -> str:
    """
    Render one TELEMETRY block per registration.

    Every app instance that registers the packet for downlink gets its own
    COSMOS definition.  The blocks are identical apart from the INSTANCE
    ID value, which lets COSMOS identify packets on (STREAM_ID, INSTANCE)
    rather than STREAM_ID alone.
    """
    apid_cosmos = pkt["apid"] | _TLM_APID_MASK
    base_name   = f"{short_name}_{pkt['name']}"
    regs        = pkt["registrations"]
    suffixed    = ALWAYS_SUFFIX_INSTANCE or len(regs) > 1

    # The payload is identical for every instance, so build it once.
    fields_str = "".join(_format_tlm_item(f) for f in pkt["fields"])
    fields_str += "  APPEND_ITEM      CRC                           16        UINT      \"CRC16 checksum\"\n"

    blocks = []
    for reg in regs:
        instance = reg.get("instance", 0)
        name     = f"{base_name}_{instance}" if suffixed else base_name
        description = pkt.get("description", "")
        if suffixed and description:
            description = f"{description} (instance {instance})"
        reg_line = (
            f"  # Downlink: {reg['rate_sec']} s  priority={reg['priority']}"
            f"  instance={instance}\n"
        )

        pkt_str = template
        pkt_str = pkt_str.replace("<<TARGET>>",            target)
        pkt_str = pkt_str.replace("<<PACKET_NAME>>",       name)
        pkt_str = pkt_str.replace("<<ENDIANNESS>>",        "BIG_ENDIAN")
        pkt_str = pkt_str.replace("<<DESCRIPTION>>",       description)
        pkt_str = _sub_aligned(pkt_str, "<<APID>>",        str(apid_cosmos))
        pkt_str = _sub_aligned(pkt_str, "<<INSTANCE>>",    str(instance))
        pkt_str = pkt_str.replace("<<ADDITIONAL_FIELDS>>", reg_line + fields_str)
        blocks.append(pkt_str)

    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Command formatter
# ---------------------------------------------------------------------------

def _format_cmd_parameter(field: dict, append_key: str = "APPEND_PARAMETER") -> str:
    """Format one command parameter (scalar or array element)."""
    cosmos_type, bits_per = _resolve_type(field)
    warpos_type  = field["type"].lower()
    array_length = field.get("array_length", 0) or 0
    description  = field.get("description", "")
    units        = field.get("units")

    lines = []

    if cosmos_type == "STRING":
        total_bits = bits_per  # already total from _resolve_type
        line = (
            f"  {append_key:<18}{field['id']:<30}{total_bits:<10}"
            f"{cosmos_type:<10}{'':<10}{'':<10}{''!r:<10}\"{description}\"\n"
        )
        # STRING parameters: no min/max; default is empty string
        line = (
            f"  {append_key:<18}{field['id']:<30}{total_bits:<10}"
            f"STRING    \"\"        \"{description}\"\n"
        )
        lines.append(line)
    elif array_length > 0:
        for i in range(array_length):
            item_name = f"{field['id']}_{i}"
            line = (
                f"  {append_key:<18}{item_name:<30}{bits_per:<10}"
                f"{cosmos_type:<10}{'MIN':<10}{'MAX':<10}{'0':<10}\"{description}\"\n"
            )
            lines.append(line)
            if units:
                lines.append(_units_line(units))
    else:
        default = "0"
        line = (
            f"  {append_key:<18}{field['id']:<30}{bits_per:<10}"
            f"{cosmos_type:<10}{'MIN':<10}{'MAX':<10}{default:<10}\"{description}\"\n"
        )
        lines.append(line)
        if warpos_type == "bool":
            lines.append("    STATE FALSE 0\n")
            lines.append("    STATE TRUE 1\n")
        if units:
            lines.append(_units_line(units))

    return "".join(lines)


def _format_cmd_packet(template: str, target: str, pkt: dict, short_name: str) -> str:
    """Render one COMMAND packet block from template + packet dict."""
    apid_cosmos = pkt["apid"] | _CMD_APID_MASK
    cosmos_name = f"{short_name}_{pkt['name']}"
    pkt_len     = pkt["size"] + 10   # payload + secondary header (8 B) + CRC (2 B)

    fields_str = "".join(_format_cmd_parameter(f) for f in pkt["fields"])
    fields_str += (
        "  APPEND_PARAMETER CRC                           16        UINT      "
        "MIN       MAX       0         \"CRC16 Checksum\"\n"
    )

    pkt_str = template
    pkt_str = pkt_str.replace("<<TARGET>>",            target)
    pkt_str = pkt_str.replace("<<PACKET_NAME>>",       cosmos_name)
    pkt_str = pkt_str.replace("<<ENDIANNESS>>",        "BIG_ENDIAN")
    pkt_str = pkt_str.replace("<<DESCRIPTION>>",       pkt.get("description", ""))
    pkt_str = _sub_aligned(pkt_str, "<<APID>>",        str(apid_cosmos))
    pkt_str = _sub_aligned(pkt_str, "<<SIZE>>",        str(pkt_len))
    pkt_str = pkt_str.replace("<<ADDITIONAL_FIELDS>>", fields_str)
    return pkt_str


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------

class CosmosUpdateCmdTlm:
    """
    Generate COSMOS cmd.txt and tlm.txt from a warplink cmd_tlm.json.

    Also sets up the full target directory by copying target.txt and lib/
    from targets/common/ into targets/<cosmos_target>/, and adds a
    TARGET + INTERFACE block for the generated target to plugin.txt if it
    does not already declare one.

    Parameters
    ----------
    cmd_tlm_json : str | Path
        Schema-version-2 JSON produced by buildWarpLinkCmdTlmJson.py.
    tlm_template : str | Path
        Path to templates/telemetry.txt (CCSDS header template).
    cmd_template : str | Path
        Path to templates/command.txt (CCSDS header template).
    target_dir : str | Path
        Root of the targets/ folder in the COSMOS plugin.  Output is written
        to <target_dir>/<cosmos_target>/.
    common_dir : str | Path | None
        Path to the targets/common/ folder containing the shared target.txt
        and lib/.  Defaults to <target_dir>/common.  Skipped if absent.
    plugin_txt : str | Path | None
        Path to plugin.txt.  Gains a TARGET block for the cosmos_target value
        if it has none.  Defaults to <target_dir>/../plugin.txt.
    plugin_host : str
        Host the generated INTERFACE line points at.  Only used when a new
        block is written; existing blocks are never rewritten.
    update_plugin : bool
        False only warns about a missing TARGET block instead of adding one.
    """

    def __init__(
        self,
        cmd_tlm_json,
        tlm_template,
        cmd_template,
        target_dir,
        common_dir=None,
        plugin_txt=None,
        plugin_host=DEFAULT_PLUGIN_HOST,
        update_plugin=True,
    ):
        with open(cmd_tlm_json) as f:
            self._data = json.load(f)

        schema = self._data.get("schema_version", 1)
        if schema != 2:
            raise ValueError(
                f"Unsupported cmd_tlm.json schema_version {schema}. "
                "Expected 2 (produced by buildWarpLinkCmdTlmJson.py)."
            )

        self._target = self._data["cosmos_target"]

        with open(tlm_template) as f:
            self._tlm_template = f.read()
        with open(cmd_template) as f:
            self._cmd_template = f.read()

        target_dir          = Path(target_dir)
        self._out_dir       = target_dir / self._target / "cmd_tlm"
        self._target_root   = target_dir / self._target
        self._common_dir    = Path(common_dir) if common_dir else target_dir / "common"
        self._plugin_txt    = Path(plugin_txt) if plugin_txt else target_dir.parent / "plugin.txt"
        self._plugin_host   = plugin_host
        self._update_plugin = update_plugin

    # ------------------------------------------------------------------
    # Target directory setup helpers
    # ------------------------------------------------------------------

    def _setup_target_dir(self) -> None:
        """
        Copy target.txt and lib/ from common/ into the target directory.

        Silently skips any source that doesn't exist so the script still
        works if the user hasn't created the common folder yet.
        """
        if not self._common_dir.exists():
            return

        # Copy target.txt
        src_target_txt = self._common_dir / "target.txt"
        if src_target_txt.exists():
            dst = self._target_root / "target.txt"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_target_txt, dst)
            print(f"Copied       : {dst}")

        # Copy lib/ — overwrite existing files so protocol updates propagate
        src_lib = self._common_dir / "lib"
        if src_lib.exists():
            dst_lib = self._target_root / "lib"
            shutil.copytree(src_lib, dst_lib, dirs_exist_ok=True)
            print(f"Copied       : {dst_lib}/")

    def _next_free_ports(self, text: str) -> tuple[int, int]:
        """
        Return (read_port, write_port) that no VARIABLE in plugin.txt uses.

        COSMOS scopes packet identification to the targets mapped to the
        receiving interface, and every WarpOS build reuses the same STREAM_IDs,
        so two targets must never share a port.  Taking one above the highest
        port already declared keeps new targets clear of every existing one
        without having to reason about which are currently enabled.
        """
        ports = [
            int(m)
            for m in re.findall(
                r'^\s*VARIABLE\s+\w*_port\s+(\d+)\s*$', text, flags=re.MULTILINE
            )
        ]
        read_port = max(ports) + 1 if ports else _DEFAULT_BASE_PORT
        return read_port, read_port + 1

    def _plugin_block(self, read_port: int, write_port: int) -> tuple[str, str]:
        """
        Build the (VARIABLE block, TARGET block) pair for this target.

        Mirrors the WARP_CUBE blocks: same UDP interface, same CRC and
        check_pattern protocols, with the target name, interface name and
        ports swapped in.  The commented serial and TCP/IP lines come along
        so the connection can be switched by uncommenting, as for WARP_CUBE.
        """
        target = self._target
        prefix = target.lower()
        rule   = "# " + "-" * 75

        names = [f"{prefix}_{s}" for s in ("enable", "host", "write_port", "read_port")]
        width = max(len(n) for n in names) + 2
        values = ["true", self._plugin_host, str(write_port), str(read_port)]

        var_block = "\n".join(
            [rule, f"# {target}", rule]
            + [f"VARIABLE {n:<{width}}{v}" for n, v in zip(names, values)]
        ) + "\n"

        interface = f"{target}_INT"
        target_block = f"""
<% if {prefix}_enable.to_s.strip.downcase == "true" %>
TARGET {target} {target}

# Uncomment the line that matches your hardware connection
#INTERFACE {interface} openc3/interfaces/serial_interface.py /dev/ttyUSB0 /dev/ttyUSB0 115200 NONE 1 10.0 None # Serial to Linux
#INTERFACE {interface} openc3/interfaces/tcpip_client_interface.py host.docker.internal <%= {prefix}_write_port %> <%= {prefix}_read_port %> 10.0 None # Docker routing to Windows bridge
INTERFACE {interface} openc3/interfaces/udp_interface.py <%= {prefix}_host %> <%= {prefix}_write_port %> <%= {prefix}_read_port %> None None 128 10.0 None # RasPi UDP
  PROTOCOL WRITE openc3/interfaces/protocols/crc_protocol.py CRC False ERROR -16 16 BIG_ENDIAN 0x8005 0xFFFF False True
  PROTOCOL READ check_pattern.py
  PROTOCOL READ openc3/interfaces/protocols/crc_protocol.py CRC False ERROR -16 16 BIG_ENDIAN 0x8005 0xFFFF False True
  MAP_TARGET {target}
<% end %>
"""
        return var_block, target_block

    def _update_plugin_txt(self) -> None:
        """
        Add a TARGET + INTERFACE block for the generated target to plugin.txt.

        plugin.txt declares one such block per build target, each on its own
        ports.  Generating a target the plugin never declares would ship
        cmd/tlm definitions that COSMOS silently ignores, so write the block
        rather than leaving it as a manual step.

        Already-declared targets are left exactly as they are: the ports, host
        and interface type in an existing block are deployment choices, and
        rewriting them on every build would undo whatever was tuned by hand.
        """
        if not self._plugin_txt.exists():
            print(f"WARNING      : {self._plugin_txt} not found, no TARGET block written")
            return

        text = self._plugin_txt.read_text()

        if re.search(
            rf'^\s*TARGET\s+{re.escape(self._target)}\s', text, flags=re.MULTILINE
        ):
            print(f"Declared     : TARGET {self._target} already in {self._plugin_txt}")
            return

        if not self._update_plugin:
            print(
                f"WARNING      : no 'TARGET {self._target}' block in {self._plugin_txt}.\n"
                f"               Re-run without --no-plugin-txt to add one, or copy an\n"
                f"               existing block and change the target name, interface\n"
                f"               name, and ports, or the target will not load."
            )
            return

        read_port, write_port = self._next_free_ports(text)
        var_block, target_block = self._plugin_block(read_port, write_port)

        # VARIABLEs go with the others, above the first ERB block that uses
        # them; the TARGET block goes at the end, where appending cannot break
        # an existing <% if %> ... <% end %> pair.
        erb = re.search(r'^<%', text, flags=re.MULTILINE)
        if erb:
            text = text[: erb.start()] + var_block + "\n" + text[erb.start() :]
        else:
            text = text.rstrip("\n") + "\n\n" + var_block

        text = text.rstrip("\n") + "\n" + target_block
        self._plugin_txt.write_text(text)

        print(
            f"Declared     : TARGET {self._target} added to {self._plugin_txt}\n"
            f"               host={self._plugin_host} "
            f"write_port={write_port} read_port={read_port}"
        )

    # ------------------------------------------------------------------

    def __call__(self) -> None:
        """Generate cmd.txt and tlm.txt and write them to the output directory."""
        tlm_str = ""
        cmd_str = ""

        for app in self._data["apps"]:
            comment     = _app_comment(app)
            short_name  = app["short_name"]

            # -- Registered telemetry --
            app_tlm_written = False
            for pkt in app["telemetry"]:
                if not pkt["registrations"]:
                    continue
                if not app_tlm_written:
                    tlm_str += comment
                    app_tlm_written = True
                tlm_str += _format_tlm_packets(self._tlm_template, self._target, pkt, short_name)
                tlm_str += "\n"

            # -- All commands --
            if not app["commands"]:
                continue
            app_cmd_written = False
            for pkt in app["commands"]:
                if not app_cmd_written:
                    cmd_str += comment
                    app_cmd_written = True
                cmd_str += _format_cmd_packet(self._cmd_template, self._target, pkt, short_name)
                cmd_str += "\n"

        self._setup_target_dir()
        self._out_dir.mkdir(parents=True, exist_ok=True)
        (self._out_dir / "tlm.txt").write_text(tlm_str)
        (self._out_dir / "cmd.txt").write_text(cmd_str)
        self._update_plugin_txt()

        print(f"COSMOS target : {self._target}")
        print(f"Written       : {self._out_dir / 'tlm.txt'}")
        print(f"Written       : {self._out_dir / 'cmd.txt'}")

    @property
    def target(self) -> str:
        return self._target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate COSMOS cmd/tlm definitions from a warplink cmd_tlm.json."
    )
    parser.add_argument(
        "--cmd-tlm-json",
        default="./cmd_tlm.json",
        help="Path to cmd_tlm.json (schema v2) from buildWarpLinkCmdTlmJson.py",
    )
    parser.add_argument(
        "--tlm-template",
        default="templates/telemetry.txt",
        help="Path to the CCSDS telemetry header template",
    )
    parser.add_argument(
        "--cmd-template",
        default="templates/command.txt",
        help="Path to the CCSDS command header template",
    )
    parser.add_argument(
        "--target-dir",
        default="./openc3-cosmos-warplink/targets",
        help="Root of the COSMOS plugin targets/ directory "
             "(output goes to <target-dir>/<cosmos_target>/)",
    )
    parser.add_argument(
        "--common-dir",
        default=None,
        help="Path to the common/ folder with shared target.txt and lib/. "
             "Defaults to <target-dir>/common",
    )
    parser.add_argument(
        "--plugin-txt",
        default=None,
        help="Path to plugin.txt to update. "
             "Defaults to <target-dir>/../plugin.txt",
    )
    parser.add_argument(
        "--plugin-host",
        default=DEFAULT_PLUGIN_HOST,
        help="Host the generated INTERFACE line connects to "
             f"(default: {DEFAULT_PLUGIN_HOST}). Only used when adding a new "
             "TARGET block; existing blocks are left alone",
    )
    parser.add_argument(
        "--no-plugin-txt",
        dest="update_plugin",
        action="store_false",
        help="Only warn about a missing TARGET block instead of adding one",
    )
    args = parser.parse_args()

    gen = CosmosUpdateCmdTlm(
        args.cmd_tlm_json,
        args.tlm_template,
        args.cmd_template,
        args.target_dir,
        common_dir=args.common_dir,
        plugin_txt=args.plugin_txt,
        plugin_host=args.plugin_host,
        update_plugin=args.update_plugin,
    )
    gen()