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

## What the simulation accepts

The port is **write-only**: the datagram is fire-and-forget and the simulation
never replies. A "Sent" status here means the JSON left COSMOS, **not** that the
simulation accepted it. If an address or value is rejected, the simulation logs
a warning on its own side and drops the datagram — nothing comes back to COSMOS.

**Value types.** Send a scalar JSON value; the simulation maps it onto the
addressed signal's type:

- **number** — `5`, `-3`, `5.5`. Applied to any numeric signal (integer or
  floating point). A fractional value onto an integer field is coerced.
- **boolean** — `true` / `false`. Applied to a boolean signal.
- **string** — any non-JSON text (e.g. `NADIR`). Applied verbatim to a string
  signal. A string is also how you set a **vector or matrix** signal: send the
  value's text form as a string, e.g. `"value": "[[1,2][3,4]]"`.

The value must be parseable for the target signal's type — a non-numeric string
sent to a numeric field is dropped. JSON **arrays, objects, and null are not
accepted** (a `[1,2,3]` array is dropped; send a vector as a string instead).

**Addresses.** The address must resolve to a single **signal**, e.g.
`.exc.spacecraft.params.mass`. Grouping nodes are not settable — you cannot
target a model (`.exc.spacecraft`) or a signal group (`.exc.spacecraft.params`),
only the signal beneath them. A model's `params` (configuration), `inputs`, and
`outputs` are all addressable, but most models recompute their `outputs` every
step, so a value injected onto an output does not persist — set `params` and
`inputs` for changes that stick.

## Address autocomplete

Typing an address by hand means knowing the tree. To make it discoverable, the
tool can load a dump of the simulation's graph tree and suggest addresses as you
type, cascading one level at a time — type `.exc.` and it lists everything
directly under `exc`; pick `.exc.spacecraft` and it offers `params`, `inputs`,
`outputs`; and so on down to the leaf signals, much like member access in C++.
Leaf entries also carry their type, so you know whether a signal wants a number,
a string, or a bracketed vector/matrix. When an address resolves to a settable
signal, the Value field shows the **expected type** and auto-fills a template of
the right type and shape (using the signal's current value from the dump), ready
to edit — it never overwrites a value you've typed yourself.

To enable it:

1. Run the simulation. On the first step it writes `graph_tree.json` into its
   output directory (alongside `sim_data.json`) whenever `write-data-json` is
   on, which is the default.
2. In the tool, use **Graph tree file** to pick that `graph_tree.json`. It loads
   immediately and is cached in the browser, so it survives reloads until you
   load a newer one. Because the tree changes as the sim's models change, this
   is the intended workflow: re-dump, re-pick, done — no plugin rebuild or
   upload. Use the field's clear button to forget it.

Optionally, you can instead bake a `graph_tree.json` into the `SIM` target
(e.g. `openc3-cosmos-warplink/targets/SIM/graph_tree.json`) and (re)install the
plugin; the tool falls back to that packaged copy when nothing has been loaded
in the browser. Either way, if no tree is available the address field still
works as free text — autocomplete is simply off, and the field hint says so.

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
