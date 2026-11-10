// Copyright 2026 ATTX, Inc.
// All Rights Reserved.
//
// This program is free software; you can modify and/or redistribute it
// under the terms of the GNU Affero General Public License
// as published by the Free Software Foundation; version 3 with
// attribution addendums as found in the LICENSE.txt
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.

// Which simulation run Sim Control sets, as the WarpWare app tells it: the
// SIM_CONTROL target's run.json, beside the run's graph_tree.json, which
// `warpware run` puts while a run is connected -- running, with its script,
// pid and start, its heartbeat renewed every few seconds -- and marks ended as
// the run lets go. A heartbeat gone old is a run whose process was stopped, and
// so wrote no end: no run either.

export const RUN_FORMAT = 'warpware.sim-run/1'
// A heartbeat older than this is no run's: three of the WarpWare app's 5 s.
export const RUN_STALE_MS = 15000

// The status run.json holds, or null when it is not one this tool reads.
export function runOf(text) {
  let json
  try {
    json = JSON.parse(text)
  } catch {
    return null
  }
  if (json === null || typeof json !== 'object' || json.format !== RUN_FORMAT) return null
  if (typeof json.script !== 'string' || typeof json.started !== 'string') return null
  if (json.state === 'running' && typeof json.heartbeat === 'string') {
    return { state: 'running', script: json.script, started: json.started, heartbeat: json.heartbeat }
  }
  if (json.state === 'ended') return { state: 'ended', script: json.script, started: json.started }
  return null
}

// When a run started, as this browser's clock reads it: 10:42 today, else Nov 9, 10:42.
export function since(started, now = new Date()) {
  const at = new Date(started)
  if (Number.isNaN(at.getTime())) return started
  const two = (n) => String(n).padStart(2, '0')
  const time = `${two(at.getHours())}:${two(at.getMinutes())}`
  if (at.toDateString() === now.toDateString()) return time
  const month = at.toLocaleString('en-US', { month: 'short' })
  return `${month} ${at.getDate()}, ${time}`
}

// Whether a run holds WarpLink now, and what Sim Control says of it: the run, or no run.
export function runLine(status, now = new Date()) {
  const live =
    status !== null &&
    status.state === 'running' &&
    now.getTime() - new Date(status.heartbeat).getTime() <= RUN_STALE_MS
  if (live) return { running: true, started: status.started, text: `Run: ${status.script}, since ${since(status.started, now)}` }
  return { running: false, text: 'No run: start a simulation in the WarpWare app, and it connects here' }
}
