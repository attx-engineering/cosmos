# openc3-cosmos-warplink

WarpLink plugin for WarpOS flight software, deployed to OpenC3 COSMOS.

## Targets

- `BF2_FLIGHT_BOARD` - WarpOS build target, CCSDS over UDP with CRC.
  `CosmosUpdateCmdTlm.py` adds a block like it to `plugin.txt` for every other
  build target it generates. Generated `targets/<TARGET>/` folders are not
  committed; only `common/` and `SIM` are.
- `SIM` - simulation value injection. Write only UDP on `sim_write_port`
  (default 5009), separate from the flight software ports. Its one command,
  `SET_VALUE`, sends raw JSON with no header or CRC:

  ```json
  { "address": ".exc.spacecraft.params.mass", "value": 5 }
  ```

  The Sim Control tool in the sidebar is the front end for it.

## Building

```bash
../openc3.sh cli rake build VERSION=1.0.0
```

This produces `openc3-cosmos-warplink-1.0.0.gem`, which you can install through
the COSMOS Admin > Plugins page or with `../openc3.sh cli load <gem>`.
