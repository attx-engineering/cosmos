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

// Sim Control's address and value, made friendlier: a vector, matrix or quaternion shows as a grid of input values,
// and the address being typed is suggested to its next '.'.
//
// A value's grid takes its shape from the value WarpTwin wrote in the run's graph_tree.json, in WarpOS's own text form:
// [[a][b][c]] a column, as a quaternion is, scalar first; [[a,b,c][d,e,f]] a matrix, row by row; a,b,c a list. The grid
// writes its cells back in that same form, which is what the simulation takes.

// The leaf types whose value is a grid, as WarpTwin names WarpOS's: Matrix, CartesianVector and Quaternion are matrix;
// std::vector is vector; std::array is array.
export const GRID_TYPES = ['matrix', 'vector', 'array']

const numeric = (text) => text.trim() !== '' && Number.isFinite(Number(text))

// A value's shape and cells, or null when it is none this grid shows: empty, ragged, or holding what is no number.
export function shapeOf(type, text) {
  if (!GRID_TYPES.includes(type) || typeof text !== 'string') return null
  const value = text.trim()
  if (value === '') return null
  let shape
  if (value.startsWith('[[') && value.endsWith(']]')) {
    const rows = value
      .slice(2, -2)
      .split('][')
      .map((row) => row.split(','))
    const cols = rows[0].length
    if (rows.some((row) => row.length !== cols)) return null
    shape = {
      form: 'rows',
      rows: rows.length,
      cols,
      cells: rows.map((row) => row.map((c) => c.trim())),
    }
  } else if (!/[[\]]/.test(value)) {
    const cells = value.split(',').map((c) => c.trim())
    shape = { form: 'list', rows: 1, cols: cells.length, cells: [cells] }
  } else {
    return null
  }
  return shape.cells.every((row) => row.every(numeric)) ? shape : null
}

// The cells written back in the shape's own form.
export function valueOf(shape, cells) {
  if (shape.form === 'list') return cells[0].map((c) => c.trim()).join(',')
  return `[[${cells.map((row) => row.map((c) => c.trim()).join(',')).join('][')}]]`
}

// Each cell that is no number, as [row, col], for the grid to mark and Send to wait on.
export function badCells(cells) {
  const bad = []
  cells.forEach((row, r) =>
    row.forEach((c, k) => {
      if (!numeric(c)) bad.push([r, k])
    }),
  )
  return bad
}

// What a grid says of a leaf that has none: why it is the text field instead.
export const NO_GRID =
  "WarpTwin wrote no current value for it, so it can't be shown as a grid: enter it as text, [[a,b,…][…]]"

// The node at a dotted address in the tree, or null.
export function nodeAt(tree, address) {
  if (!tree) return null
  const stack = [tree]
  while (stack.length) {
    const node = stack.pop()
    if (node.address === address) return node
    if (node.children) stack.push(...node.children)
  }
  return null
}

// What a leaf's suggestion says beside its name: its type, a grid's shape, and its value, cut short.
function detailOf(node) {
  if (node.children) return ''
  const shape = shapeOf(node.type, node.value)
  const size = shape === null ? '' : ` ${shape.rows}×${shape.cols}`
  const value =
    typeof node.value === 'string' && node.value !== ''
      ? `  ${node.value.length > 32 ? `${node.value.slice(0, 31)}…` : node.value}`
      : ''
  return `${node.type ?? ''}${size}${value}`
}

// The suggestions for what is typed: the next segment of the address, to the next '.'. The text up to the last '.' is
// the path chosen so far; the text after it picks among that node's children by name, ignoring case, those starting
// with it before those holding it. Each says whether it is a branch, to go on into, or a leaf.
export function nextSegments(tree, typed, limit = 100) {
  if (!tree) return []
  const raw = typed || ''
  const lastDot = raw.lastIndexOf('.')
  const base = lastDot >= 0 ? raw.slice(0, lastDot) : ''
  const partial = (lastDot >= 0 ? raw.slice(lastDot + 1) : raw).toLowerCase()
  const level = base === '' ? [tree] : (nodeAt(tree, base)?.children ?? [])
  const starting = level.filter((n) => n.name.toLowerCase().startsWith(partial))
  const holding = level.filter(
    (n) =>
      !n.name.toLowerCase().startsWith(partial) &&
      n.name.toLowerCase().includes(partial),
  )
  return [...starting, ...holding].slice(0, limit).map((n) => ({
    name: n.name,
    address: n.address,
    branch: !!n.children,
    detail: detailOf(n),
  }))
}

// The address a suggestion leaves in the field: a branch's with its '.', ready for the next segment; a leaf's as it is.
export function accepted(suggestion) {
  return suggestion.branch ? `${suggestion.address}.` : suggestion.address
}
