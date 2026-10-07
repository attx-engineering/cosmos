## OpenC3 COSMOS CFDP Uplink Plugin

[Documentation](https://openc3.com)

Front end for the `CFDP_SERVICE` microservice in the WarpLink plugin
(`openc3-cosmos-warplink`). It has three tabs:

- **Upload** — pick a file from your own computer. The tool uploads it to the
  tools bucket under `cfdp/outgoing/files/`, then queues a request JSON under
  `cfdp/outgoing/queue/`. `CFDP_SERVICE` polls that queue, sends the file as
  Metadata / File Data / EOF PDUs through `STORAGE_MANAGER_CFDP`, and moves
  the request to `cfdp/outgoing/sent/` or `cfdp/outgoing/failed/`.
- **Request File** — sends `STORAGE_MANAGER_FILE_GET` to a target so WarpOS
  downlinks a file over CFDP.
- **Downloads** — lists and downloads every file `CFDP_SERVICE` has received
  in the `OPENC3_CFDP_VOLUME`, complete or not, labelled:
  - **Complete** — fully received and checksum-verified (`incoming/complete/`)
  - **Receiving** — in `incoming/in_progress/` with data in the last 30 s
  - **Incomplete** — in `incoming/in_progress/` but no recent data (stalled)
  - **Failed** — the transfer ended without a good file (`incoming/failed/`),
    with the reason

  Partial files show how many bytes arrived and how many ranges are missing;
  missing bytes are zero-filled in the downloaded file.

Uploading to the tools bucket requires the admin role.

## Requirements

- The WarpLink plugin installed with `cfdp_enable` set to `true`.
- `OPENC3_CFDP_VOLUME` set in `.env`, and the `./cfdp` bind mount in
  `compose.yaml`, so the Downloads tab can read what the service writes.

## Building

1. `pnpm install` from `openc3-cosmos-init/plugins`
1. `pnpm build` in this directory
1. `rake build VERSION=X.Y.Z`

The COSMOS init container builds and installs this tool automatically; set
`OPENC3_NO_CFDPUPLINK=1` in `.env` to skip it.
