# WarpLink

WarpLink is [OpenC3 COSMOS](https://docs.openc3.com/docs) configured as the
ground system for WarpOS flight software. It provides telemetry display and
graphing, command sending, scripting, and logging for one or more WarpOS build
targets over UDP, serial/USB, or TCP/IP.

## Repository layout

| Path | What it is |
| --- | --- |
| `CosmosUpdateCmdTlm.py` | Generates COSMOS command/telemetry definitions from a WarpOS `cmd_tlm.json` |
| `templates/` | CCSDS header templates (`command.txt`, `telemetry.txt`) the generator fills in |
| `openc3-cosmos-warplink/` | The COSMOS plugin: `plugin.txt`, per-target `cmd_tlm/`, and the built `.gem` files |
| `openc3-cosmos-warplink/targets/common/` | `target.txt` and `lib/` (CRC, `check_pattern.py`, half-float conversion) copied into every generated target |
| `openc3-cosmos-init/plugins/packages/openc3-cosmos-tool-simcontrol/` | The Sim Control tool |
| `openc3.sh` | Container control and CLI wrapper |

Everything else is upstream OpenC3 COSMOS.

## Setup

1. Clone WarpLink from the GitHub distribution:
   <https://github.com/warpware-distribution/warplink>

2. **Generate the cmd/tlm files.** From within WarpOS, go to the `build`
   directory and run `cmake ..`

   1. This creates `cmd_tlm.json` in the build directory.
   2. Copy that file into the base directory of WarpLink.
   3. From the base directory, run `python3 CosmosUpdateCmdTlm.py`

   The generator reads the `cosmos_target` field in the JSON and writes
   everything that target needs:

   - `openc3-cosmos-warplink/targets/<TARGET>/cmd_tlm/cmd.txt` and `tlm.txt`
   - `target.txt` and `lib/` copied from `targets/common/`
   - a `TARGET` + `INTERFACE` block in `openc3-cosmos-warplink/plugin.txt`, on
     the next free pair of UDP ports, if that target is not declared yet

   Each WarpOS build gets its own COSMOS target, so several builds can coexist
   in one instance. Blocks that already exist in `plugin.txt` are never
   rewritten — ports and hosts you tune there survive regeneration. Run
   `python3 CosmosUpdateCmdTlm.py --help` for the available paths and flags.

3. **Start the containers.**

   ```bash
   ./openc3.sh start   # first time: builds the containers, then runs them
   ./openc3.sh run     # afterwards: runs the already-built containers
   ```

4. **Build the plugin** that ingests the commands and telemetry:

   ```bash
   cd openc3-cosmos-warplink/ && ../openc3.sh cli rake build VERSION=1.0.0
   ```

   1. Increment the version (MAJOR.MINOR.PATCH) on every build — COSMOS keys
      plugins by version, so reinstalling requires a new number. 
   2. This creates `openc3-cosmos-warplink-#.#.#.gem` in that directory, used
      in the next steps.

5. In a web browser, open <http://localhost:2900/> — this is the WarpLink GUI.

6. **Install the plugin.** From the Admin Console, select "Install from file"
   and choose the `.gem` you just built. The install dialog lists every
   `VARIABLE` in `plugin.txt` (each target's enable flag, host, and ports), so
   connection settings can be changed here without editing the file.

7. Depending on your setup, follow the UDP, Linux Serial/USB, or Windows
   Serial/USB instructions below for connecting to the telemetry stream.

### Rebuilding after a change

Any change to `plugin.txt`, `cmd.txt`, `tlm.txt`, or the target `lib/` needs a
new gem: rebuild with an incremented `VERSION` and reinstall it through the
Admin Console. Regenerating from a new `cmd_tlm.json` (step 2) counts.

## Targets and ports

Each target needs its own UDP ports. COSMOS scopes packet identification to the
targets mapped to the receiving interface, and the WarpOS builds reuse the same
STREAM_IDs, so two targets sharing an interface — or two interfaces sharing a
read port — cannot be told apart. `CosmosUpdateCmdTlm.py` allocates above the
highest port already declared to keep new targets clear of existing ones.

| Target | Host | Write (command) | Read (telemetry) |
| --- | --- | --- | --- |
| `EXAMPLE` | `172.20.10.4` | 5006 | 5005 |
| `SIM` | `host.docker.internal` | 5009 | — (send only) |

Set `<target>_enable` to `false`, in the file or in the install dialog, to skip
a target you are not flying.

## Windows Serial/USB Command/Telemetry Interface

To run WarpLink over serial/USB on Windows, a "Bridge" is needed to connect the
data arriving on the host machine's COM port to the Docker instance running
under the hood.

Downloads needed:

- Download Ruby (v3.2+) from the official Ruby website.
- From PowerShell, run `gem install openc3`
  - Ensure the Ruby gem executable path is in your `PATH` environment variable.

Configuration:

- `bridge.txt` is not checked into this repo. Generate a default in the base
  directory with `openc3cli bridgesetup bridge.txt`, then edit:
  - UART configuration (baud rate, parity, data bits, flow control, etc.)
  - COM port name — the port you read and write depends on what your computer
    assigned the USB connection
  - Router port — used to route serial telemetry to an internal TCP connection
- In `openc3-cosmos-warplink/plugin.txt`, each target block has a commented
  `INTERFACE` line for a TCP connection to `host.docker.internal`. Uncomment
  that line for your target and comment out its other `INTERFACE` lines (serial
  and UDP).
  - Changing `plugin.txt` means rebuilding the `.gem` and reinstalling it
    through the UI, per the instructions above.

Once the new gem is uploaded and the routing device is plugged in, run the
bridge:

- From PowerShell: `openc3cli bridge bridge.txt`
- Expect a couple of outputs in the terminal. You will know it succeeded on
  `SERIAL_ROUTER: Tcpip server accepted from host.docker.internal(...)`

## Linux Serial/USB Connection

To connect to a serial/USB device on Linux, configure `plugin.txt`. Each target
block has a commented line for `openc3/interfaces/serial_interface.py`. Uncomment
it and comment out that target's other `INTERFACE` lines. Its options are, in
order:

- Write port
- Read port
- Baud rate
- Parity
- Stop bits
- Write timeout
- Read timeout

Ensure the serial configuration matches your hardware, and that the read/write
ports (default `/dev/ttyUSB0`) match the USB/serial device you have plugged in.

- Changing `plugin.txt` means rebuilding the `.gem` and reinstalling it through
  the UI, per the instructions above.

## Using a Raspberry Pi for command/telemetry

The simplest way to receive telemetry is over WiFi using a RasPi. You can
either:

1. Use the Raspberry Pi as a passthrough for telemetry.
   1. Connect the telemetry UART from the hardware to the Pi.
   2. Upload `cmd-tlm-interface.py` to the Pi and update its configuration —
      specifically the arguments at the beginning of `main` for which USB
      device, which IP, and the UART rate.
   3. Run `cmd-tlm-interface.py`, with either the correct defaults described
      above or the correct option flags. Telemetry should start passing through.
2. Use the Raspberry Pi as the hardware platform, configured to take telemetry
   and send it over a socket.

**Notes:**

1. `cmd-tlm-interface.py` ships with the WarpLink distribution, not with this
   repository — get it from the distribution clone in step 1.
2. The Pi must send to the read port and listen on the write port of the target
   it is feeding (5005/5006 for `WARP_CUBE`; see the table above).
3. In `openc3-cosmos-warplink/plugin.txt`, ensure the IP in that target's
   `<target>_host` variable is the IP of the Pi you are running — or set it in
   the plugin install dialog, which needs no rebuild.

### RasPi configuration for Serial-UDP

> **Note:** the Raspberry Pi option is only used if you are routing commands and
> telemetry through a Pi so your ground station can send and receive over UDP.

If the RasPi hasn't been flashed yet:

1. Download the RPi Imager.
2. Plug the SD card into your computer.
3. Configure:
   1. Operating System: RPi OS 64-bit
   2. Storage: internal SD card reader (or whatever your SD card interface is)
   3. Settings (gear icon):
      1. Set the hostname to your liking
      2. Check "enable SSH" and "Use password authentication"
      3. Choose a username
      4. Configure wireless LAN for your network, and check the password
   4. Click "Write", then "Yes"
4. Once the write completes and the dialog says it is safe, unplug the SD card
   and transfer it to the RasPi.
5. Plug in the USB-C power supply.
6. Wait for the onboard LED to blink green.
7. From a separate computer on the same network: `ssh <hostname>.local`
   1. If the connection does not work, try pinging the Pi.
   2. On first boot the RasPi may need to connect to WiFi, so allow ~10 minutes
      before troubleshooting.
8. Set up the UDP connection on the RasPi:
   1. In `cmd-tlm-interface.py`, change the IP address and name in lines 40-41.
   2. Transfer the file to the RasPi (VSCode remote-ssh extension, SFTP, or
      another method).
9. On the RasPi CLI: `sudo python3 cmd-tlm-interface.py`
   1. You should start to see `[UART RX]` data streaming on stdout, if the
      serial input is sending telemetry.

## Simulation control

The `SIM` target is not a WarpOS build. It is a send-only JSON channel on its
own port (5009 by default) so it never mixes with flight software command
traffic. Its one command, `SET_VALUE`, sends raw JSON with no CCSDS header and
no CRC:

```json
{ "address": ".exc.spacecraft.params.mass", "value": 5 }
```

The Sim Control tool in the sidebar is the front end for it.

## Troubleshooting

Most of the time, disconnecting and reconnecting (via the "Action" column on the
CmdTlmServer tab) or rebuilding and reinstalling the plugin is enough.

1. If no data appears in the GUI and there are no recurring messages on the
   CmdTlmServer page:
   1. Check that the Raspberry Pi is actually sending UDP data — verify the IP
      address, baud rate, and serial port on the Pi.
   2. Ensure the IP addresses and ports are correct in
      `openc3-cosmos-warplink/plugin.txt`, or in the plugin install dialog.
   3. Check that the target's `<target>_enable` variable is `true`.
2. If many "unknown" packets are arriving, the definitions no longer match the
   flight software. Reload `cmd_tlm.json` from WarpOS, copy it into WarpLink,
   rerun `CosmosUpdateCmdTlm.py`, and rebuild and reinstall the `.gem`.
3. If a target loads but never identifies packets while another target works,
   check that the two are not sharing a read port — see
   [Targets and ports](#targets-and-ports).

## Upstream

WarpLink is built on OpenC3 COSMOS, originally created by Ryan Melton
(ryanmelt) and Jason Thomas (jmthomas) and maintained by OpenC3, Inc. Upstream
documentation is at <https://docs.openc3.com/docs>; the tool reference there
(Command Sender, Telemetry Viewer, Script Runner, Data Extractor, and the rest)
applies unchanged.

## License

OpenC3 COSMOS is released under the AGPL v3 with a few addendums. See
[LICENSE.txt](LICENSE.txt). Contributions are governed by
[CONTRIBUTING.txt](CONTRIBUTING.txt).
