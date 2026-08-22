## OpenC3 COSMOS Calendar Tool

Calendar view of timelines, activities, notes and metadata, with month, week,
day, gantt and list views.

### Timelines and activities

A **timeline** is a named, colored track on the calendar. It holds
**activities**, and each activity is one of three kinds:

- `command` — sends a command at its scheduled time
- `script` — runs a script at its scheduled time
- `reserve` — occupies time on the calendar without executing anything

Every timeline is backed by its own `timeline_microservice`, which runs the
`command` and `script` activities at their scheduled time and records the
outcome back onto the activity. A `reserve` activity never executes; it is
simply marked complete when its start time passes.

### Satellite passes

A satellite pass window (the interval when a spacecraft is visible from a
ground station) is represented as a `reserve` activity: it marks when the
spacecraft is reachable so that commands and scripts can be scheduled inside
it. Publish pass windows onto a timeline with `create_pass_activities` from the
COSMOS script API (Ruby and Python).

Each pass is a hash/dict that must contain a `start` and a `stop`. Times may be
a `Time`/`datetime`, an ISO 8601 string, or epoch seconds. **Any other keys are
stored on the activity and shown in the calendar** — `satellite`,
`ground_station` and `max_elevation` get a formatted label (e.g.
`ISS → Wallops · 32° el`); any other keys are shown as `key: value`.

Ruby:

```ruby
passes = [
  { 'satellite' => 'ISS', 'ground_station' => 'Wallops', 'max_elevation' => 32.4,
    'start' => '2026-08-22T18:04:11Z', 'stop' => '2026-08-22T18:13:47Z' },
  { 'satellite' => 'ISS', 'ground_station' => 'Wallops', 'max_elevation' => 9.1,
    'start' => '2026-08-22T19:41:02Z', 'stop' => '2026-08-22T19:47:20Z' },
]
result = create_pass_activities(passes)
puts result # => {"created"=>2, "deleted"=>0, "skipped"=>[]}
```

Python:

```python
passes = [
    {"satellite": "ISS", "ground_station": "Wallops", "max_elevation": 32.4,
     "start": "2026-08-22T18:04:11Z", "stop": "2026-08-22T18:13:47Z"},
    {"satellite": "ISS", "ground_station": "Wallops", "max_elevation": 9.1,
     "start": "2026-08-22T19:41:02Z", "stop": "2026-08-22T19:47:20Z"},
]
result = create_pass_activities(passes)
print(result)  # {'created': 2, 'deleted': 0, 'skipped': []}
```

Options (keyword arguments):

| Option     | Default     | Meaning                                                                 |
| ---------- | ----------- | ----------------------------------------------------------------------- |
| `timeline` | `"PASSES"`  | Timeline to publish onto. Created automatically if it does not exist.   |
| `color`    | `"#8E24AA"` | Color used only when the timeline has to be created.                    |
| `replace`  | `true`      | Before adding, delete existing `reserve` activities in the range being published, so re-running against updated propagation replaces passes instead of duplicating them. Commands and scripts scheduled inside a pass are never touched. |

The return value is a hash/dict with `created` and `deleted` counts and a
`skipped` list. Activities cannot be created in the past, so any pass whose
`start` has already elapsed is reported in `skipped` (reason `already started`)
rather than raising and abandoning the rest of the set.

### Importing passes from the UI

You don't have to script it. **File → Import Passes…** opens a file picker;
choose a `passes.json` file and its passes are added to the `PASSES` timeline
(created if needed). Re-importing replaces the existing pass windows in the same
time range, so an updated file doesn't stack duplicates — and any commands or
scripts you've scheduled inside a pass are left untouched. Passes whose start is
already in the past are skipped and reported in the confirmation.

A `passes.json` file is a JSON array; each pass needs ISO 8601 UTC `start` and
`stop` and may carry any metadata to display (`satellite`, `ground_station`,
`max_elevation`, ...):

```json
[
  {"satellite": "DEMOSAT", "ground_station": "WALLOPS",
   "start": "2026-08-22T18:04:11+00:00", "stop": "2026-08-22T18:13:47+00:00",
   "max_elevation": 42.7}
]
```

This is the same shape `create_pass_activities` accepts, and the same file
WarpTwin's `groundstation_passes` example writes — so the sim can hand a file
straight to the calendar with no script or COSMOS credentials involved.

### Viewing passes

Once published, passes appear on the timeline you chose (default `PASSES`),
which is selected automatically in the sidebar. Because they are `reserve`
activities they render as a lighter backdrop behind any commands or scripts
scheduled inside them, in every view:

- **Month / week / day / gantt** — each block is labeled with the pass summary,
  and hovering a gantt bar shows the same detail in a tooltip.
- **List** — one row per pass with its start, stop, timeline and detail.

Click any pass to open the event dialog, where the full stored metadata is
shown in the Data column.

A typical operations workflow: run your orbit propagation, call
`create_pass_activities` with the resulting windows (re-run it whenever the
propagation updates — `replace` keeps it idempotent), then open the Calendar
tool and schedule your contacts inside the pass windows.
