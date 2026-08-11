## OpenC3 COSMOS Sim Control Plugin

[Documentation](https://openc3.com)

Sets a single simulation input to a value. You type a simulation address such
as `.exc.spacecraft.params.mass` and a value such as `5`, press Send, and the
tool sends this JSON out the simulation's own port:

```json
{ "address": ".exc.spacecraft.params.mass", "value": 5 }
```

The value is sent as its natural JSON type: `5` is a number, `5.5` is a number,
`true` is a boolean, and anything that is not valid JSON is sent as a string.

The send goes through the normal COSMOS command path (`SIM SET_VALUE`), so
every value you set is logged and visible in Command Sender and the command
logs like any other command.

## Getting Started

1. At the OpenC3 Admin - Plugins, upload the openc3-cosmos-tool-simcontrol.gem file
2. Install a plugin that defines the `SIM` target with a `SET_VALUE` command
   mapped to an interface on the simulation port. The WarpLink plugin
   (`openc3-cosmos-warplink`) ships one; the port is the `sim_write_port`
   plugin variable.

Sim Control shows an error in the tool if the target or command is missing, so
you can tell a missing plugin apart from a failed send.

## Contributing

We encourage you to contribute to OpenC3 COSMOS!

Contributing is easy.

1. Fork the project
2. Create a feature branch
3. Make your changes
4. Submit a pull request

Before any contributions can be incorporated we do require all contributors to agree to a Contributor License Agreement

This protects both you and us and you retain full rights to any code you write.

## License

This OpenC3 COSMOS plugin is released under the AGPLv3.0 with a few addendums. See [LICENSE.txt](LICENSE.txt)
