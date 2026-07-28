# openc3-cosmos-warplink

WarpLink plugin for WarpOS flight software, deployed to OpenC3 COSMOS.

## Building

```bash
../openc3.sh cli rake build VERSION=1.0.0
```

This produces `openc3-cosmos-warplink-1.0.0.gem`, which you can install through
the COSMOS Admin > Plugins page or with `../openc3.sh cli load <gem>`.
