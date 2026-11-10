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

// Sim Control's grid and suggestions: node --test, nothing to install.

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { accepted, badCells, nextSegments, nodeAt, shapeOf, valueOf } from './simControlValue.js'

// As WarpTwin writes them in a run's graph_tree.json: a quaternion and an inertia, matrix, each value in WarpOS's own form.
const QUAT = '[[1.000000][0.000000][0.000000][0.000000]]'
const INERTIA = '[[1.000000,0.000000,0.000000][0.000000,1.000000,0.000000][0.000000,0.000000,1.000000]]'

test('a grid shaped from the value WarpTwin wrote: a column, a matrix row by row, a list', () => {
  assert.deepEqual(shapeOf('matrix', QUAT), {
    form: 'rows', rows: 4, cols: 1, cells: [['1.000000'], ['0.000000'], ['0.000000'], ['0.000000']],
  })
  const inertia = shapeOf('matrix', INERTIA)
  assert.deepEqual([inertia.rows, inertia.cols, inertia.cells[1][1]], [3, 3, '1.000000'])
  assert.deepEqual(shapeOf('array', '1,2, 3'), { form: 'list', rows: 1, cols: 3, cells: [['1', '2', '3']] })
  assert.deepEqual(shapeOf('vector', '[[1,2,3]]').cells, [['1', '2', '3']], 'a row')
  assert.equal(shapeOf('vector', '-2.5e-03,4').cols, 2)
})

test('no grid: a scalar, no value, an empty vector, a ragged matrix, what is no number', () => {
  for (const [type, text] of [['float', '1.0'], ['matrix', undefined], ['matrix', ''], ['vector', ''], ['matrix', '[[1,2][3]]'],
    ['matrix', '[[1][nan]]'], ['array', '1,,2'], ['matrix', '[1,2]'], ['string', 'NADIR']]) {
    assert.equal(shapeOf(type, text), null, `${type} ${text}`)
  }
})

test('the cells written back in their own form, which the simulation takes', () => {
  const quat = shapeOf('matrix', QUAT)
  assert.equal(valueOf(quat, [['0'], ['0'], ['0'], ['1']]), '[[0][0][0][1]]')
  const inertia = shapeOf('matrix', INERTIA)
  assert.equal(valueOf(inertia, [['2', '0', '0'], ['0', '3', '0'], ['0', '0', ' 4 ']]), '[[2,0,0][0,3,0][0,0,4]]')
  assert.equal(valueOf(shapeOf('array', '1,2,3'), [['4', '5', '6']]), '4,5,6')
  // Read back, the same shape.
  assert.deepEqual(shapeOf('matrix', valueOf(inertia, inertia.cells)).cells, inertia.cells)
})

// A square matrix as WarpTwin writes one, each cell given by cell(r, c), in %f.
const square = (n, cell) =>
  `[[${Array.from({ length: n }, (_, r) => Array.from({ length: n }, (_, c) => cell(r, c).toFixed(6)).join(',')).join('][')}]]`

test("a filter's covariances: a 6×6 and a 10×10 at zero, and a 10×10 around 1e6, each round trip exact", () => {
  for (const [n, cell, length] of [[6, () => 0, 332], [10, () => 0, 912], [10, (r, c) => 1e6 + r * 10 + c, 1512]]) {
    const text = square(n, cell)
    assert.equal(text.length, length, 'the length WarpTwin writes')
    const shape = shapeOf('matrix', text)
    assert.deepEqual([shape.rows, shape.cols], [n, n])
    assert.equal(valueOf(shape, shape.cells), text)
  }
  assert.equal(shapeOf('matrix', square(10, (r, c) => 1e6 + r * 10 + c)).cells[9][9], '1000099.000000')
})

test('a cell that is no number is marked, and Send waits', () => {
  assert.deepEqual(badCells([['1', ''], ['x', '2e3']]), [[0, 1], [1, 0]])
  assert.deepEqual(badCells([['1', '-0.5']]), [])
})

const TREE = {
  name: 'exc', address: '.exc', children: [
    { name: 'PointingControl', address: '.exc.PointingControl', children: [
      { name: 'inputs', address: '.exc.PointingControl.inputs', children: [
        { name: 'target_quat', address: '.exc.PointingControl.inputs.target_quat', type: 'matrix', settable: true, value: QUAT },
        { name: 'gain', address: '.exc.PointingControl.inputs.gain', type: 'float', settable: true, value: '0.5' },
      ] },
    ] },
    { name: 'sc', address: '.exc.sc', children: [] },
    { name: 'control_monitor', address: '.exc.control_monitor', children: [] },
  ],
}

test('suggestions to the next .: the root, then each level, starting with what is typed first, then holding it, case aside', () => {
  assert.deepEqual(nextSegments(TREE, '').map((s) => s.address), ['.exc'])
  assert.deepEqual(nextSegments(TREE, '.exc.').map((s) => s.name), ['PointingControl', 'sc', 'control_monitor'])
  assert.deepEqual(nextSegments(TREE, '.exc.con').map((s) => s.name), ['control_monitor', 'PointingControl'], 'starting before holding')
  assert.deepEqual(nextSegments(TREE, '.exc.POINT').map((s) => s.name), ['PointingControl'], 'case aside')
  assert.deepEqual(nextSegments(TREE, '.exc.nothing'), [])
  assert.deepEqual(nextSegments(null, '.exc.'), [])
  assert.deepEqual(nextSegments(TREE, '.exc.PointingControl.inputs.'), [
    { name: 'target_quat', address: '.exc.PointingControl.inputs.target_quat', branch: false, detail: `matrix 4×1  ${QUAT.slice(0, 31)}…` },
    { name: 'gain', address: '.exc.PointingControl.inputs.gain', branch: false, detail: 'float  0.5' },
  ])
  assert.equal(nextSegments(TREE, '.exc.', 2).length, 2, 'at most the limit')
})

test('a suggestion taken: a branch with its ., ready for the next segment; a leaf as it is', () => {
  const [branch] = nextSegments(TREE, '.exc.Po')
  assert.equal(accepted(branch), '.exc.PointingControl.')
  const [leaf] = nextSegments(TREE, '.exc.PointingControl.inputs.tar')
  assert.equal(accepted(leaf), '.exc.PointingControl.inputs.target_quat')
  assert.equal(nodeAt(TREE, '.exc.PointingControl.inputs.gain').value, '0.5')
  assert.equal(nodeAt(TREE, '.exc.missing'), null)
})
