# OpenC3 COSMOS - WarpLink Interface

This repo is [OpenC3 COSMOS](https://docs.openc3.com/docs) configured as the
ground system for WarpOS flight software. It provides telemetry display and
graphing, command sending, scripting, logging, CFDP file transfer, and
simulation control for one or more WarpOS build targets over UDP, serial/USB,
or TCP/IP.

## Repository layout

| Path | What it is |
| --- | --- |
| `openc3-cosmos-warplink/` | The COSMOS plugin: `plugin.txt`, per-target `cmd_tlm/`, and the built `.gem` files |
| `openc3-cosmos-warplink/targets/common/` | `target.txt` and `lib/` (CFDP-aware CRC, `check_pattern.py`, half-float conversion), which WarpLink's generator copies into every target it makes |
| `openc3-cosmos-warplink/microservices/CFDP_SERVICE/` | CFDP file transfer microservice |
| `openc3-cosmos-init/plugins/packages/openc3-cosmos-tool-simcontrol/` | The Sim Control tool |
| `openc3-cosmos-init/plugins/packages/openc3-cosmos-tool-cfdpuplink/` | The CFDP Uplink tool |
| `openc3-cosmos-init/plugins/packages/openc3-cosmos-tool-calendar/` | The Calendar tool |
| `openc3-keycloak/` | Keycloak realm and access control setup |
| `compose.yaml` | Container configuration, including the telemetry ports published into COSMOS |
| `bridge.txt` | Windows serial/USB bridge configuration, run with `openc3cli bridge bridge.txt` |
| `cfdp/` | Host directory for CFDP transfers (ships empty; contents git-ignored, bind mounted into the containers) |
| `openc3.sh` | Container control and CLI wrapper |

Everything else is upstream OpenC3 COSMOS. WarpLink's generator, which makes a
target from each WarpOS build, is WarpLink's own, in the `warplink` repository.


## Upstream

This is built on OpenC3 COSMOS, originally created by Ryan Melton
(ryanmelt) and Jason Thomas (jmthomas) and maintained by OpenC3, Inc. Upstream
documentation is at <https://docs.openc3.com/docs>; the tool reference there
(Command Sender, Telemetry Viewer, Script Runner, Data Extractor, and the rest)
applies unchanged. This repository is set up as an easy way for WarpWare to interface with OpenC3.

## License

OpenC3 COSMOS is released under the AGPL v3 with a few addendums. See
[LICENSE.txt](LICENSE.txt). Contributions are governed by
[CONTRIBUTING.txt](CONTRIBUTING.txt).
