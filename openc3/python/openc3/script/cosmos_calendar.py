# Copyright 2023 OpenC3, Inc.
# All Rights Reserved.
#
# This program is free software; you can modify and/or redistribute it
# under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation; version 3 with
# attribution addendums as found in the LICENSE.txt
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.

import json
from datetime import datetime, timezone

import openc3.script
from openc3.environment import OPENC3_SCOPE


def list_timelines(scope=OPENC3_SCOPE):
    response = openc3.script.API_SERVER.request("get", "/openc3-api/timeline", scope=scope)
    return _handle_response(response, "Failed to list timelines")


def create_timeline(name, color=None, scope=OPENC3_SCOPE):
    data = {}
    data["name"] = name
    if color:
        data["color"] = color
    response = openc3.script.API_SERVER.request("post", "/openc3-api/timeline", data=data, json=True, scope=scope)
    return _handle_response(response, "Failed to create timeline")


def get_timeline(name, scope=OPENC3_SCOPE):
    response = openc3.script.API_SERVER.request("get", f"/openc3-api/timeline/{name}", scope=scope)
    return _handle_response(response, "Failed to get timeline")


def set_timeline_color(name, color, scope=OPENC3_SCOPE):
    post_data = {}
    post_data["color"] = color
    response = openc3.script.API_SERVER.request(
        "post",
        f"/openc3-api/timeline/{name}/color",
        data=post_data,
        json=True,
        scope=scope,
    )
    return _handle_response(response, "Failed to set timeline color")


def delete_timeline(name, force=False, scope=OPENC3_SCOPE):
    url = f"/openc3-api/timeline/{name}"
    if force:
        url += "?force=true"
    response = openc3.script.API_SERVER.request("delete", url, scope=scope)
    return _handle_response(response, "Failed to delete timeline")


def create_timeline_activity(name, kind, start, stop, data={}, scope=OPENC3_SCOPE):
    kind = kind.lower()
    kinds = ["command", "script", "reserve"]
    if kind not in kinds:
        raise RuntimeError(f"Unknown kind: {kind}. Must be one of {', '.join(kinds)}.")
    post_data = {}
    post_data["start"] = start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    post_data["stop"] = stop.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    post_data["kind"] = kind
    post_data["data"] = data
    response = openc3.script.API_SERVER.request(
        "post",
        f"/openc3-api/timeline/{name}/activities",
        data=post_data,
        json=True,
        scope=scope,
    )
    return _handle_response(response, "Failed to create timeline activity")


def get_timeline_activity(name, start, uuid, scope=OPENC3_SCOPE):
    response = openc3.script.API_SERVER.request("get", f"/openc3-api/timeline/{name}/activity/{start}/{uuid}", scope=scope)
    return _handle_response(response, "Failed to get timeline activity")


def get_timeline_activities(name, start=None, stop=None, limit=None, scope=OPENC3_SCOPE):
    url = f"/openc3-api/timeline/{name}/activities"
    if start and stop:
        url += f"?start={start}&stop={stop}"
    if limit:
        url += f"?limit={limit}"
    response = openc3.script.API_SERVER.request("get", url, scope=scope)
    return _handle_response(response, "Failed to get timeline activities")


def delete_timeline_activity(name, start, uuid, scope=OPENC3_SCOPE):
    response = openc3.script.API_SERVER.request(
        "delete", f"/openc3-api/timeline/{name}/activity/{start}/{uuid}", scope=scope
    )
    return _handle_response(response, "Failed to delete timeline activity")


def create_pass_activities(
    passes, timeline="PASSES", color="#8E24AA", replace=True, scope=OPENC3_SCOPE
):
    """Publish satellite pass windows onto a timeline as 'reserve' activities.

    A reserve activity occupies time on the calendar without executing
    anything, which is exactly what a pass window is: it shows when the
    spacecraft is visible so commands and scripts can be scheduled inside it.

    Parameters:
        passes: iterable of dicts, each needing a "start" and a "stop" given as
            a datetime, an ISO 8601 string, or epoch seconds. Any other keys
            (satellite, ground_station, max_elevation, ...) are stored on the
            activity and shown in the calendar.
        timeline: timeline to publish onto, created if missing
        color: color for the timeline when it has to be created
        replace: remove existing reserve activities that fall in the range
            being published before adding the new ones, so re-running against
            updated propagation replaces passes rather than duplicating them

    Returns:
        dict with counts of what happened and the skipped passes listed
    """
    normalized = []
    for entry in passes:
        entry = dict(entry)
        start = _to_datetime(entry.pop("start", None))
        stop = _to_datetime(entry.pop("stop", None))
        if start is None or stop is None:
            raise RuntimeError(f"Pass requires both a start and a stop: {entry}")
        if start >= stop:
            raise RuntimeError(f"Pass start {start} is not before stop {stop}")
        normalized.append({"start": start, "stop": stop, "data": entry})
    if not normalized:
        return {"created": 0, "deleted": 0, "skipped": []}

    # Create the timeline on first use so callers don't have to
    if not any(t["name"] == timeline for t in list_timelines(scope=scope)):
        create_timeline(timeline, color=color, scope=scope)

    normalized.sort(key=lambda entry: entry["start"])
    range_start = normalized[0]["start"]
    range_stop = normalized[-1]["stop"]

    deleted = 0
    if replace:
        existing = get_timeline_activities(
            timeline,
            start=range_start.isoformat(),
            stop=range_stop.isoformat(),
            scope=scope,
        )
        for activity in existing:
            # Only clear passes - a command or script scheduled inside a pass
            # window belongs to the operator, not to the propagation run.
            if activity["kind"] != "reserve":
                continue
            delete_timeline_activity(
                timeline, activity["start"], activity["uuid"], scope=scope
            )
            deleted += 1

    created = 0
    skipped = []
    now = datetime.now(timezone.utc)
    for entry in normalized:
        # Activities cannot be created in the past, so a pass already underway
        # is reported rather than raising and abandoning the rest of the set.
        if entry["start"] <= now:
            skipped.append(
                {
                    "start": entry["start"],
                    "stop": entry["stop"],
                    "reason": "already started",
                }
            )
            continue
        create_timeline_activity(
            timeline,
            "reserve",
            entry["start"],
            entry["stop"],
            data=entry["data"],
            scope=scope,
        )
        created += 1
    return {"created": created, "deleted": deleted, "skipped": skipped}


# Accepts the several shapes a pass time can arrive in from a propagator.
# Naive datetimes are treated as UTC, which is what propagators emit.
def _to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    raise RuntimeError(f"Cannot interpret {value!r} as a time")


# Helper method to handle the response
def _handle_response(response, error_message):
    if response is None:
        return None
    if response.status_code >= 400:
        result = json.loads(response.text)
        raise RuntimeError(f"{error_message} due to {result['message']}")
    # Not sure why the response body is empty (on delete) but check for that
    if response.text is None or len(response.text) == 0:
        return None
    else:
        return json.loads(response.text)
