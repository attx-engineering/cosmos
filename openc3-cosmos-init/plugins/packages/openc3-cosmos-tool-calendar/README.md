## OpenC3 COSMOS Calendar Tool

Calendar view of timelines, activities, notes and metadata.

Timelines hold activities. An activity is a command, a script, or a "reserve"
block that simply occupies time on the calendar. Each timeline is backed by its
own `timeline_microservice` which runs the activities at their scheduled time
and records the outcome back onto the activity.

Reserve activities are also how satellite pass windows are represented - see
`create_pass_activities` in the COSMOS script API.
