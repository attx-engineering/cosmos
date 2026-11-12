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

// Which run Sim Control sets, as run.json says: node --test, nothing to install.

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  RUN_STALE_MS,
  runLine,
  runOf,
  since,
  TREE_WAIT_MS,
  treeAwaited,
} from './simControlRun.js'

const RUNNING = {
  format: 'warpware.sim-run/1',
  state: 'running',
  script: 'scripts/demo/script.py',
  pid: 4120,
  started: new Date(2026, 10, 10, 10, 42).toISOString(),
  heartbeat: new Date(2026, 10, 10, 10, 50).toISOString(),
}

test('run.json read: running with its heartbeat, or ended; anything else none', () => {
  assert.deepEqual(runOf(JSON.stringify(RUNNING)), {
    state: 'running',
    script: RUNNING.script,
    started: RUNNING.started,
    heartbeat: RUNNING.heartbeat,
  })
  const ended = { ...RUNNING, state: 'ended', ended: RUNNING.heartbeat }
  delete ended.heartbeat
  assert.deepEqual(runOf(JSON.stringify(ended)), {
    state: 'ended',
    script: RUNNING.script,
    started: RUNNING.started,
  })
  for (const text of [
    '',
    '{',
    'null',
    '[]',
    JSON.stringify({ ...RUNNING, format: 'other' }),
    JSON.stringify({ ...RUNNING, heartbeat: undefined }),
    JSON.stringify({ ...RUNNING, state: 'paused' }),
    JSON.stringify({ ...RUNNING, script: 7 }),
  ]) {
    assert.equal(runOf(text), null, text)
  }
})

test('the run, while its heartbeat is fresh; no run once it ends, or its heartbeat goes old', () => {
  const now = new Date(2026, 10, 10, 10, 50, 5)
  const status = runOf(JSON.stringify(RUNNING))
  assert.deepEqual(runLine(status, now), {
    running: true,
    started: RUNNING.started,
    text: 'Run: scripts/demo/script.py, since 10:42',
  })
  const none = {
    running: false,
    text: 'No run: start a simulation in the WarpWare app, and it connects here',
  }
  assert.deepEqual(
    runLine(
      status,
      new Date(new Date(RUNNING.heartbeat).getTime() + RUN_STALE_MS + 1),
    ),
    none,
    'its process stopped',
  )
  assert.deepEqual(
    runLine(runOf(JSON.stringify({ ...RUNNING, state: 'ended' })), now),
    none,
  )
  assert.deepEqual(runLine(null, now), none)
})

test('when a run started: its time today, else its day too', () => {
  const now = new Date(2026, 10, 10, 15, 0)
  assert.equal(since(new Date(2026, 10, 10, 9, 5).toISOString(), now), '09:05')
  assert.equal(
    since(new Date(2026, 10, 9, 22, 41).toISOString(), now),
    'Nov 9, 22:41',
  )
  assert.equal(since('not a time', now), 'not a time')
})

test("a new run's tree, asked for at each look until it is in, or the wait is over", () => {
  const run = {
    state: 'running',
    script: 'scripts/demo/script.py',
    started: 'B',
  }
  // A run newly seen: its tree awaited, from the one in use before it.
  const first = treeAwaited(null, run, 'A', 'old tree', 1000)
  assert.deepEqual(first, { started: 'B', before: 'old tree', since: 1000 })
  assert.deepEqual(
    treeAwaited(null, run, '', '', 1000),
    { started: 'B', before: '', since: 1000 },
    'after a look that found no run',
  )
  // Still awaited while the same tree is in use, the run not yet having put its own.
  assert.equal(treeAwaited(first, run, 'B', 'old tree', 3000), first)
  // In once the tree in use is another: awaited no more.
  assert.equal(treeAwaited(first, run, 'B', 'new tree', 5000), null)
  // Over once the wait is: what COSMOS holds is the run's.
  assert.equal(
    treeAwaited(first, run, 'B', 'old tree', 1000 + TREE_WAIT_MS + 1),
    null,
  )
  // The first look: the tree COSMOS holds was asked for already, unless none was in use.
  assert.equal(treeAwaited(null, run, null, 'its tree', 1000), null)
  assert.deepEqual(treeAwaited(null, run, null, '', 1000), {
    started: 'B',
    before: '',
    since: 1000,
  })
  // No run, or one ended: nothing awaited.
  assert.equal(treeAwaited(first, null, 'B', 'old tree', 2000), null)
  assert.equal(
    treeAwaited(first, { ...run, state: 'ended' }, 'B', 'old tree', 2000),
    null,
  )
})
