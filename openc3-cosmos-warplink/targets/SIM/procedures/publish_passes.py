###############################################################################
# Copyright (c) ATTX, Inc. 2026. All Rights Reserved.
#
# This software and associated documentation (the "Software") are the
# proprietary and confidential information of ATTX, Inc. The Software is
# furnished under a license agreement between ATTX and the user organization
# and may be used or copied only in accordance with the terms of the agreement.
# Refer to 'license/attx_license.adoc' for standard license terms.
#
# EXPORT CONTROL NOTICE: THIS SOFTWARE MAY INCLUDE CONTENT CONTROLLED UNDER THE
# INTERNATIONAL TRAFFIC IN ARMS REGULATIONS (ITAR) OR THE EXPORT ADMINISTRATION
# REGULATIONS (EAR99). No part of the Software may be used, reproduced, or
# transmitted in any form or by any means, for any purpose, without the express
# written permission of ATTX, Inc.
###############################################################################
"""Publish WarpTwin satellite passes onto the COSMOS calendar.

This is the COSMOS-side, file-hand-off half of the WarpTwin -> calendar bridge.
WarpTwin's ``groundstation_passes`` example writes a ``passes.json`` file (via
``warptwinutils.passes.writePassesFile``); this procedure reads that file and
publishes the passes as 'reserve' activities on the calendar. Running it here in
Script Runner means the WarpTwin machine never needs COSMOS credentials or
network access - only this JSON file crosses the boundary.

The file is a JSON list of pass objects, each with ISO 8601 UTC ``start`` and
``stop`` times plus any metadata (``satellite``, ``ground_station``,
``max_elevation``, ...) - exactly the shape ``create_pass_activities`` accepts:

    [
      {"satellite": "DEMOSAT", "ground_station": "WALLOPS",
       "start": "2026-08-22T18:04:11+00:00", "stop": "2026-08-22T18:13:47+00:00",
       "max_elevation": 42.7}
    ]

Getting the file here: upload it into this target's file storage from the COSMOS
UI (or with put_target_file), so ``PASSES_FILE`` below resolves it, then run this
procedure. ``replace=True`` makes re-running idempotent - existing pass windows
in the published range are cleared before the new set is added, while any
commands or scripts scheduled inside a pass are left untouched.
"""

import json

from openc3.script import create_pass_activities, get_target_file

# Target-file path of the passes JSON produced by WarpTwin. Change the target
# name/filename to match wherever you uploaded it.
PASSES_FILE = "SIM/passes.json"

# Calendar timeline to publish onto; created automatically if it does not exist.
TIMELINE = "PASSES"


def load_passes(path):
    """Read the passes JSON from this target's file storage."""
    handle = get_target_file(path)
    if handle is None:
        raise RuntimeError(
            f"Could not find {path}. Upload the passes.json produced by WarpTwin "
            "into this target's files, or update PASSES_FILE."
        )
    try:
        return json.load(handle)
    finally:
        handle.close()


passes = load_passes(PASSES_FILE)
print(f"Loaded {len(passes)} pass(es) from {PASSES_FILE}")

result = create_pass_activities(passes, timeline=TIMELINE, replace=True)
print(
    f"Published to '{TIMELINE}': created {result['created']}, "
    f"deleted {result['deleted']}, skipped {len(result['skipped'])}"
)
for skipped in result["skipped"]:
    print(f"  skipped {skipped['start']} -> {skipped['stop']}: {skipped['reason']}")
