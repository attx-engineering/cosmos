# openc3-cosmos-warplink

WarpLink plugin for WarpOS flight software, deployed to OpenC3 COSMOS.

## Targets

- `FLIGHT_BOARD` - WarpOS build target, CCSDS over UDP with CRC.
  WarpLink's generator (`CosmosUpdateCmdTlm.py`, in the `warplink` repository)
  adds a block like it to `plugin.txt` for every other build target it generates. Generated `targets/<TARGET>/` folders are not
  committed; only `common/` and `SIM_CONTROL` are.
- `SIM_CONTROL` - simulation value injection, over UDP to `sim_control_write_port` (default
  5009), separate from the flight software ports. Its command, `SET_VALUE`,
  sends raw JSON with no header or CRC:

  ```json
  { "address": ".exc.spacecraft.params.mass", "value": 5, "sequence": 7 }
  ```

  The simulation replies to each value at the port it came from,
  `sim_control_reply_port` (default 5010), which the interface reads too, as the `REPLY`
  packet: whether it set the value, why not, and the value's `sequence`. The
  Sim Control tool in the sidebar is the front end for it.

## Building

```bash
../openc3.sh cli rake build VERSION=1.0.0
```

This produces `openc3-cosmos-warplink-1.0.0.gem`, which you can install through
the COSMOS Admin > Plugins page or with `../openc3.sh cli load <gem>`.
