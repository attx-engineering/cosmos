<!--
# Copyright 2022 Ball Aerospace & Technologies Corp.
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

# Modified by OpenC3, Inc.
# All changes Copyright 2025, OpenC3, Inc.
# All Rights Reserved
#
# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.
#
# Modified by ATTX, Inc.
# All changes Copyright 2026, ATTX, Inc.
# All Rights Reserved
-->

<!--
# Copyright 2026, OpenC3, Inc.
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
-->

<template>
  <div>
    <top-bar :title="title" />
    <v-card>
      <v-card-title> Set Simulation Value </v-card-title>
      <v-card-subtitle>
        Sends an address / value pair as JSON to the simulation on its own port
      </v-card-subtitle>
      <v-card-text>
        <v-alert
          v-if="setupError"
          type="error"
          density="compact"
          class="mb-4"
          data-test="setup-error"
        >
          {{ setupError }}
        </v-alert>
        <!--
          The run Sim Control sets, as the WarpWare app tells it in the
          SIM_CONTROL target's run.json: the run and when it started, or no run
          once it ends. No line at all where nothing has ever told it, as with
          a WarpWare app that writes none.
        -->
        <v-alert
          v-if="runShown"
          :type="runShown.running ? 'info' : 'warning'"
          variant="tonal"
          density="compact"
          class="mb-4"
          data-test="sim-run"
        >
          {{ runShown.text }}
        </v-alert>
        <!--
          The running simulation's graph_tree.json comes from the WarpWare app,
          which puts each connected run's in COSMOS as the SIM_CONTROL target's: it is
          used first, and asked for again when this window is come back to. A
          file picked here serves this session, and is cached in localStorage
          for when no run has given a tree.
        -->
        <v-row dense class="mb-1">
          <v-col cols="12" md="8">
            <v-file-input
              label="Graph tree file (graph_tree.json)"
              accept=".json,application/json"
              variant="outlined"
              density="compact"
              prepend-icon="mdi-file-tree"
              hide-details="auto"
              clearable
              data-test="sim-tree-file"
              @update:model-value="onTreeFile"
              @click:clear="clearTree"
            />
          </v-col>
          <v-col cols="12" md="4" class="d-flex align-center">
            <span class="text-caption" data-test="sim-tree-status">
              {{ treeLoadedLabel }}
            </span>
          </v-col>
        </v-row>
        <v-row dense>
          <v-col cols="12" md="8">
            <!--
              Plain text field (so the address updates live on every keystroke)
              with a manually controlled suggestion menu driven by the loaded
              graph tree. Free text always works, so an address can be entered
              even if the tree file is missing or stale. addressSuggestions
              returns the next segment of the address for what's typed, to the
              next '.', by name, case aside; the arrow keys choose one, and Tab,
              Enter or '.' takes it.
            -->
            <v-menu
              v-model="showSuggestions"
              location="bottom start"
              offset="4"
              :open-on-click="false"
              :close-on-content-click="false"
            >
              <template #activator="{ props }">
                <v-text-field
                  v-bind="props"
                  v-model="address"
                  label="Simulation Address"
                  placeholder=".exc.spacecraft.params.mass"
                  persistent-placeholder
                  variant="outlined"
                  density="compact"
                  :hint="treeHint"
                  persistent-hint
                  autofocus
                  :disabled="!!setupError"
                  data-test="sim-address"
                  @update:model-value="openSuggestions"
                  @focus="openSuggestions"
                  @keydown="onAddressKey"
                />
              </template>
              <v-list
                v-if="addressSuggestions.length"
                density="compact"
                max-height="400"
                data-test="sim-address-suggestions"
              >
                <v-list-item
                  v-for="(s, i) in addressSuggestions"
                  :key="s.address"
                  :title="s.branch ? `${s.name} ›` : s.name"
                  :subtitle="s.detail"
                  :active="i === suggestionIndex"
                  @click="pickSuggestion(s)"
                />
              </v-list>
            </v-menu>
          </v-col>
          <v-col cols="12" md="4">
            <v-text-field
              v-model="value"
              label="Value"
              placeholder="5"
              persistent-placeholder
              variant="outlined"
              density="compact"
              :hint="valueHint"
              persistent-hint
              :disabled="!!setupError"
              data-test="sim-value"
              @focus="selectCurrentValue"
              @keydown.enter="send"
            />
          </v-col>
        </v-row>
        <!--
          A vector, matrix or quaternion's value as a grid of number fields,
          shaped from the value WarpTwin wrote, each cell written back into the
          Value field above in the form the simulation takes.
        -->
        <v-row v-if="gridCells" dense class="mt-1" data-test="sim-grid">
          <v-col cols="12">
            <span class="text-caption">
              {{ gridCells.length }}×{{ gridCells[0].length }}, as WarpTwin
              wrote it: each cell a number
            </span>
            <div class="grid-scroll">
              <table class="grid">
                <tr v-for="(row, r) in gridCells" :key="r">
                  <td v-for="(cell, c) in row" :key="c">
                    <v-text-field
                      :model-value="cell"
                      variant="outlined"
                      density="compact"
                      hide-details
                      :error="cellBad(r, c)"
                      :disabled="!!setupError"
                      :data-test="`sim-grid-${r}-${c}`"
                      @update:model-value="setCell(r, c, $event)"
                      @keydown.enter="send"
                    />
                  </td>
                </tr>
              </table>
            </div>
          </v-col>
        </v-row>
        <v-row dense class="mt-1">
          <v-col cols="12">
            <span class="text-caption mr-2">Examples (click to use):</span>
            <v-chip
              v-for="ex in valueExamples"
              :key="ex.label"
              size="small"
              variant="outlined"
              class="mr-1 mb-1"
              :disabled="!!setupError"
              :data-test="`sim-example-${ex.label}`"
              :title="ex.title"
              @click="value = ex.value"
            >
              {{ ex.label }}:&nbsp;<code>{{ ex.value }}</code>
            </v-chip>
          </v-col>
        </v-row>
        <v-row dense class="align-center mt-2">
          <v-col cols="12" md="8">
            <span class="text-caption mr-2">Will send:</span>
            <code class="preview" data-test="sim-preview">{{ preview }}</code>
          </v-col>
          <v-col cols="12" md="4" class="text-md-right">
            <v-btn
              color="primary"
              :disabled="sendDisabled"
              data-test="sim-send"
              @click="send"
            >
              Send
            </v-btn>
          </v-col>
        </v-row>
        <v-row v-if="status" dense>
          <v-col>
            <span
              class="text-caption"
              :class="statusError ? 'text-error' : ''"
              data-test="sim-status"
            >
              {{ status }}
            </span>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <v-card v-if="history.length" class="mt-3">
      <v-card-title class="d-flex align-center">
        Recent
        <v-spacer />
        <v-btn variant="text" size="small" data-test="clear" @click="clear">
          Clear
        </v-btn>
      </v-card-title>
      <v-card-text>
        <v-table density="compact" data-test="history">
          <thead>
            <tr>
              <th>Time</th>
              <th>Address</th>
              <th>Value</th>
              <th>Result</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(entry, index) in history" :key="index">
              <td>{{ entry.time }}</td>
              <td>{{ entry.address }}</td>
              <td>
                <code>{{ entry.value }}</code>
              </td>
              <td :class="resultClass(entry)" data-test="sim-result">
                {{ resultText(entry) }}
              </td>
              <td class="text-right">
                <v-btn
                  variant="text"
                  size="small"
                  :disabled="!!setupError"
                  @click="resend(entry)"
                >
                  Resend
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card-text>
    </v-card>
  </div>
</template>

<script>
import { Api, OpenC3Api } from '@openc3/js-common/services'
import { TopBar } from '@openc3/vue-common/components'
import { runLine, runOf } from './simControlRun.js'
import { accepted, badCells, GRID_TYPES, nextSegments, NO_GRID, nodeAt, shapeOf, valueOf } from './simControlValue.js'

// The SIM_CONTROL target and its SET_VALUE command come from a plugin (openc3-cosmos-warplink
// ships one). The interface mapped to the target owns the simulation port.
const TARGET_NAME = 'SIM_CONTROL'
const COMMAND_NAME = 'SET_VALUE'
// The simulation's reply to each value, read by the SIM_CONTROL target's interface; a target without it reads none.
const REPLY_PACKET = 'REPLY'
// How long a value waits for its reply before it is said to have had none.
const REPLY_WAIT_MS = 5000
// How often the reply is looked for while a value waits for one.
const REPLY_LOOK_MS = 250
// The run's tree is asked for again on focus at most this often.
const TREE_LOOK_MS = 5000
// How often the run that holds WarpLink is looked for.
const RUN_LOOK_MS = 2000
const MAX_HISTORY = 20
// Where the last-loaded graph tree is cached so it survives page reloads.
const TREE_STORAGE_KEY = 'simcontrol_graph_tree'
// The graph_tree.json this tool reads: WarpTwin writes {"schemaVersion": 1, "root": <the tree>}.
const TREE_SCHEMA_VERSION = 1

// The tree a graph_tree.json holds, or an Error saying why it holds none this tool reads. A versioned document of
// another version is refused, rather than read as what it may not be; one with no version, as WarpTwin wrote before
// it versioned the file, is the tree itself.
function treeOf(contents) {
  if (contents === null || typeof contents !== 'object' || Array.isArray(contents)) {
    return new Error('it is not a graph_tree.json: no tree in it')
  }
  if ('schemaVersion' in contents) {
    if (contents.schemaVersion !== TREE_SCHEMA_VERSION) {
      return new Error(
        `its schemaVersion is ${JSON.stringify(contents.schemaVersion)}, and Sim Control reads version ` +
          `${TREE_SCHEMA_VERSION}: a newer Sim Control reads it`,
      )
    }
    contents = contents.root
  }
  if (
    contents === null ||
    typeof contents !== 'object' ||
    typeof contents.address !== 'string'
  ) {
    return new Error('it is not a graph_tree.json: its tree names no address')
  }
  return contents
}

export default {
  components: {
    TopBar,
  },
  data() {
    return {
      title: 'Sim Control',
      api: null,
      address: '',
      value: '',
      status: '',
      statusError: false,
      setupError: null,
      sending: false,
      history: [],
      // The sim's graph-tree dump (graph_tree.json), copied into the SIM_CONTROL
      // target directory. Drives address autocompletion; null until loaded (or
      // if absent, in which case the address field is just free text).
      tree: null,
      treeStatus: '',
      treeSource: '',
      // The run's tree as last read from the SIM_CONTROL target, so a read finding the same one changes nothing.
      treeText: '',
      treeLookedAt: 0,
      // The run the WarpWare app last said holds WarpLink (run.json): undefined while none has ever been said, null when
      // what it said is not read; when it started, so a new run's tree is taken at once; and when it was last looked at.
      run: undefined,
      runStarted: '',
      runLookedAt: 0,
      runTimer: null,
      // Whether the SIM_CONTROL target reads the simulation's replies (its REPLY packet), and each value's own number, which
      // the reply echoes; it starts anywhere, so a reply to another session's value is never taken for one of these.
      replies: false,
      sequence: Math.floor(Math.random() * 1000000),
      replyTimer: null,
      showSuggestions: false,
      // The suggestion the arrow keys have chosen.
      suggestionIndex: 0,
      // The grid of the value's cells, and its form, while the value is a vector, matrix or quaternion WarpTwin wrote one
      // for: its own cells, so a cell cleared while typed into keeps the grid. Set from the grid, the value is not read back.
      gridCells: null,
      gridShape: null,
      fromGrid: false,
      // The last value we auto-filled from a signal's template, so we can
      // replace it when the address changes without clobbering a value the
      // user typed themselves.
      autofilled: '',
      // One example per value type. Scalars (number/decimal/boolean) parse as
      // their JSON type; text and the vector/quaternion/matrix/array forms are
      // not valid JSON, so they fall through to being sent as a string -- which
      // is exactly what the simulation expects for those (a JSON array like
      // [1,2,3] would be rejected). The bracket forms match WarpOS's own
      // string format: a column vector/quaternion is [[a][b]...], a matrix is
      // [[row][row]...] with commas inside each row, and a plain array is a bare
      // comma-separated list. WarpOS's quaternions are scalar first, so the
      // quaternion example is the identity, [[w][x][y][z]] = [[1][0][0][0]].
      valueExamples: [
        { label: 'number', value: '5' },
        { label: 'decimal', value: '5.5' },
        { label: 'boolean', value: 'true' },
        { label: 'string', value: 'NADIR' },
        { label: 'vector', value: '[[1][2][3]]' },
        {
          label: 'quaternion',
          value: '[[1][0][0][0]]',
          title:
            'The identity. WarpOS orders a quaternion scalar first: [[w][x][y][z]]',
        },
        { label: 'matrix', value: '[[1,2,3][4,5,6][7,8,9]]' },
        { label: 'array', value: '1,2,3' },
      ],
    }
  },
  computed: {
    // What is said of the run that holds WarpLink: none while nothing has told Sim Control of one.
    runShown() {
      if (this.run === undefined) return null
      return runLine(this.run, new Date(this.runLookedAt))
    },
    // The value is sent as whatever JSON type it parses as, so 5 is a number,
    // true is a boolean, and NADIR is a string
    parsedValue() {
      const trimmed = this.value.trim()
      try {
        return JSON.parse(trimmed)
      } catch {
        return trimmed
      }
    },
    preview() {
      return JSON.stringify({
        address: (this.address || '').trim(),
        value: this.parsedValue,
      })
    },
    sendDisabled() {
      return (
        this.sending ||
        !!this.setupError ||
        (this.address || '').trim() === '' ||
        this.value.trim() === '' ||
        this.gridBad.length > 0
      )
    },
    // Each grid cell that is no number: marked, and Send waits.
    gridBad() {
      return this.gridCells ? badCells(this.gridCells) : []
    },
    // The next segment of the address for what's typed, to the next '.': the children of the path
    // chosen so far, by name, case aside, those starting with what's typed before those holding it (simControlValue.js).
    addressSuggestions() {
      return nextSegments(this.tree, this.address)
    },
    treeHint() {
      if (this.tree) return 'autocomplete from graph_tree.json'
      return this.treeStatus
    },
    treeLoadedLabel() {
      if (this.tree) {
        const n = this.tree.children?.length ?? 0
        return `Loaded${this.treeSource ? ` (${this.treeSource})` : ''} — ${n} top-level nodes`
      }
      return 'No graph tree loaded'
    },
    // The leaf signal the current address resolves to exactly, if any. Only
    // leaves (nodes with no children) carry a type and are settable.
    resolvedLeaf() {
      if (!this.tree) return null
      const node = this.findNodeByAddress((this.address || '').trim())
      if (node && !node.children && node.type) return node
      return null
    },
    // Hint under the Value field: the expected type for the resolved signal
    // when we know it, otherwise the general guidance. While the field holds
    // the filled-in value untouched, it says that is the current value.
    valueHint() {
      const leaf = this.resolvedLeaf
      if (leaf) {
        if (!leaf.settable) return `${leaf.type} — read-only, cannot be set`
        if (GRID_TYPES.includes(leaf.type) && shapeOf(leaf.type, leaf.value) === null) return NO_GRID
        return this.value !== '' && this.value === this.autofilled
          ? `expected type: ${leaf.type} — its current value`
          : `expected type: ${leaf.type}`
      }
      return 'number, true/false, or text; arrays/matrices as a string'
    },
  },
  watch: {
    // When the address resolves to a settable signal, prefill the Value field
    // with a template matching that signal's type. Never overwrite something
    // the user typed -- only fill when the field is empty or still holds our
    // last auto-filled template.
    resolvedLeaf(leaf) {
      if (leaf && leaf.settable && (this.value === '' || this.value === this.autofilled)) {
        const template = this.templateForLeaf(leaf)
        this.value = template
        this.autofilled = template
      }
      this.gridFrom(leaf)
    },
    // The value changed in its own field, not from the grid: the grid follows it while it reads as the leaf's shape.
    value() {
      if (this.fromGrid) {
        this.fromGrid = false
        return
      }
      this.gridFrom(this.resolvedLeaf)
    },
    address() {
      this.suggestionIndex = 0
    },
  },
  created() {
    this.api = new OpenC3Api()
  },
  mounted() {
    // Tell the user the target is missing rather than failing on the first send
    this.api
      .get_target_names()
      .then((names) => {
        if (!names.includes(TARGET_NAME)) {
          this.setupError =
            `The ${TARGET_NAME} target is not installed. Install a plugin ` +
            `defining ${TARGET_NAME} with a ${COMMAND_NAME} command mapped ` +
            `to the simulation port.`
        }
      })
      .catch((error) => {
        this.setupError = `Unable to look up targets: ${error.message}`
      })
    // Whether the SIM_CONTROL target reads the simulation's replies: a target without its REPLY packet sends values alone.
    this.api
      .get_all_tlm_names(TARGET_NAME)
      .then((names) => {
        this.replies = names.includes(REPLY_PACKET)
      })
      .catch(() => {
        this.replies = false
      })
    // The running simulation's tree, which the WarpWare app puts in COSMOS as the SIM_CONTROL target's, comes first; else
    // the tree loaded here before, cached in this browser.
    this.loadGraphTree().then((loaded) => {
      if (!loaded) this.loadStoredTree()
    })
    // A run started since this opened has put its tree there: asked for again when this window is come back to,
    // unless a file was picked here for this session.
    this.onFocus = () => {
      if (this.treeSource === 'file' || Date.now() - this.treeLookedAt < TREE_LOOK_MS) return
      this.loadGraphTree()
    }
    window.addEventListener('focus', this.onFocus)
    // The run that holds WarpLink, looked for every few seconds.
    this.loadRun()
    this.runTimer = setInterval(this.loadRun, RUN_LOOK_MS)
  },
  beforeUnmount() {
    window.removeEventListener('focus', this.onFocus)
    clearInterval(this.replyTimer)
    clearInterval(this.runTimer)
  },
  methods: {
    // Restore the last-loaded tree from localStorage. Returns whether one was
    // found, so mounted() knows whether to try the SIM_CONTROL target fallback.
    loadStoredTree() {
      try {
        const raw = localStorage.getItem(TREE_STORAGE_KEY)
        if (raw) {
          const tree = treeOf(JSON.parse(raw))
          if (tree instanceof Error) {
            localStorage.removeItem(TREE_STORAGE_KEY)
            return false
          }
          this.tree = tree
          this.treeSource = 'cached'
          this.treeStatus = ''
          return true
        }
      } catch {
        // Corrupt/oversized cache -- ignore and fall back.
      }
      return false
    },
    // Read a graph_tree.json the user picked, parse it, drive autocomplete, and
    // cache it so it persists across reloads. No plugin rebuild or upload
    // needed -- this is the fast path for a frequently-changing tree.
    onTreeFile(file) {
      const chosen = Array.isArray(file) ? file[0] : file
      if (!chosen) return
      const reader = new FileReader()
      reader.onload = () => {
        let tree
        try {
          tree = treeOf(JSON.parse(reader.result))
        } catch (error) {
          tree = new Error(`it is not JSON: ${error.message}`)
        }
        if (tree instanceof Error) {
          this.tree = null
          this.treeSource = ''
          this.treeStatus = `Could not use ${chosen.name}: ${tree.message}`
          this.$notify.caution({ title: 'Graph tree not loaded', body: this.treeStatus })
          return
        }
        this.tree = tree
        this.treeSource = 'file'
        this.treeStatus = ''
        try {
          localStorage.setItem(TREE_STORAGE_KEY, reader.result)
        } catch {
          // Over quota -- the tree still works this session, just not cached.
        }
      }
      reader.readAsText(chosen)
    },
    // Forget the loaded tree (and the cached copy); autocomplete goes back off.
    clearTree() {
      this.tree = null
      this.treeSource = ''
      this.showSuggestions = false
      try {
        localStorage.removeItem(TREE_STORAGE_KEY)
      } catch {
        // Nothing to do if storage is unavailable.
      }
      this.treeStatus = 'Load a graph_tree.json to enable address autocomplete.'
    },
    // Fetch the running simulation's tree from the SIM_CONTROL target's folder, where the WarpWare app puts each connected
    // run's: a plain target file, read via the storage download endpoint, trying targets_modified (where the
    // WarpWare app, and an edit made in COSMOS, put it) before the packaged targets copy. Resolves to whether a
    // tree is in use from there.
    async loadGraphTree() {
      this.treeLookedAt = Date.now()
      const scope = window.openc3Scope || 'DEFAULT'
      const relativePath = `${TARGET_NAME}/graph_tree.json`
      for (const area of ['targets_modified', 'targets']) {
        try {
          const objectPath = `${scope}/${area}/${relativePath}`
          const response = await Api.get(
            `/openc3-api/storage/download_file/${encodeURIComponent(objectPath)}`,
            {
              params: { bucket: 'OPENC3_CONFIG_BUCKET' },
              headers: { 'Ignore-Errors': '404,500' },
            },
          )
          if (response?.data?.contents) {
            const text = atob(response.data.contents)
            if (text === this.treeText && this.tree) return true
            const tree = treeOf(JSON.parse(text))
            if (tree instanceof Error) {
              this.treeStatus = `The run's graph_tree.json was not used: ${tree.message}`
              return false
            }
            this.tree = tree
            this.treeText = text
            this.treeSource = "the run's"
            this.treeStatus = ''
            return true
          }
        } catch {
          // Not in this area; fall through and try the next one.
        }
      }
      if (!this.tree) {
        this.treeStatus =
          'Load a graph_tree.json above to enable address autocomplete.'
      }
      return false
    },
    // The run that holds WarpLink, as the WarpWare app last said in the SIM_CONTROL target's run.json. A run newly
    // started has put its tree beside it: taken at once, unless a file was picked here for this session. Once said, a
    // run.json gone is no run.
    async loadRun() {
      const scope = window.openc3Scope || 'DEFAULT'
      const objectPath = `${scope}/targets_modified/${TARGET_NAME}/run.json`
      let text
      try {
        const response = await Api.get(`/openc3-api/storage/download_file/${encodeURIComponent(objectPath)}`, {
          params: { bucket: 'OPENC3_CONFIG_BUCKET' },
          headers: { 'Ignore-Errors': '404,500' },
        })
        text = response?.data?.contents ? atob(response.data.contents) : undefined
      } catch {
        text = undefined
      }
      this.runLookedAt = Date.now()
      if (text === undefined) {
        if (this.run !== undefined) this.run = null
        return
      }
      const run = runOf(text)
      if (run !== null && run.state === 'running' && run.started !== this.runStarted && this.treeSource !== 'file') {
        this.loadGraphTree()
      }
      this.runStarted = run?.started ?? ''
      this.run = run
    },
    // Entering the Value field while it holds the filled-in value untouched
    // selects all of it, so typing replaces it and an arrow key edits it:
    // typed after it, the value would be nonsense the simulation refuses.
    selectCurrentValue(event) {
      if (this.value === '' || this.value !== this.autofilled) return
      event.target?.select?.()
    },
    // Show the suggestion menu when the tree is loaded and there is at least
    // one candidate for what's currently typed.
    openSuggestions() {
      this.showSuggestions = !!this.tree && this.addressSuggestions.length > 0
    },
    // Fill the field with a chosen address. If that node has children, append a
    // trailing '.' so the next suggestions are its children (drilling deeper);
    // if it's a leaf, leave it as-is and close the menu.
    pickSuggestion(suggestion) {
      this.address = accepted(suggestion)
      this.suggestionIndex = 0
      this.$nextTick(() => {
        this.showSuggestions = suggestion.branch && this.addressSuggestions.length > 0
      })
    },
    // The address field's keys while suggestions show: the arrows choose one; Tab, Enter, or the arrow right at the
    // field's end take it; '.' takes a branch, going on into it. Enter sends once the address is taken, and with no
    // suggestion showing; Escape closes them.
    onAddressKey(event) {
      const list = this.addressSuggestions
      const open = this.showSuggestions && list.length > 0
      const chosen = open ? list[Math.min(this.suggestionIndex, list.length - 1)] : undefined
      const atEnd = event.target?.selectionStart === (this.address || '').length
      if (open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
        event.preventDefault()
        const step = event.key === 'ArrowDown' ? 1 : list.length - 1
        this.suggestionIndex = (this.suggestionIndex + step) % list.length
        return
      }
      if (chosen && accepted(chosen) !== this.address &&
        (event.key === 'Tab' || event.key === 'Enter' || (event.key === 'ArrowRight' && atEnd) || (event.key === '.' && chosen.branch))) {
        event.preventDefault()
        this.pickSuggestion(chosen)
        return
      }
      if (event.key === 'Escape') {
        this.showSuggestions = false
        return
      }
      if (event.key === 'Enter') this.send()
    },
    // The grid for a leaf: shaped from the value WarpTwin wrote for it, and filled from the Value field while that reads
    // as the same shape; none for a leaf with no such value, as WarpTwin writes none it could not, nor while the field
    // reads as another shape.
    gridFrom(leaf) {
      const shape = leaf && leaf.settable && GRID_TYPES.includes(leaf.type) ? shapeOf(leaf.type, leaf.value) : null
      const now = shape ? shapeOf(leaf.type, this.value) : null
      const same = now && now.form === shape.form && now.rows === shape.rows && now.cols === shape.cols
      this.gridShape = shape
      this.gridCells = same ? now.cells.map((row) => [...row]) : null
    },
    // Whether a grid cell is no number.
    cellBad(r, c) {
      return this.gridBad.some(([br, bc]) => br === r && bc === c)
    },
    // A cell typed into: the grid's cells kept, the Value field written from them in the form the simulation takes.
    setCell(r, c, text) {
      const cells = this.gridCells.map((row) => [...row])
      cells[r][c] = text ?? ''
      this.gridCells = cells
      const next = valueOf(this.gridShape, cells)
      if (next !== this.value) {
        this.fromGrid = true
        this.value = next
      }
    },
    // A ready-to-edit value for a signal. The dump's current value is the best
    // template -- it is already the right type and, for vectors/matrices, the
    // right dimensions -- so prefer it; otherwise fall back to a generic
    // per-type stub the user can shape.
    templateForLeaf(leaf) {
      if (leaf.value !== undefined && leaf.value !== null && leaf.value !== '') {
        return leaf.value
      }
      switch (leaf.type) {
        case 'integer':
          return '0'
        case 'float':
          return '0.0'
        case 'string':
          return ''
        case 'vector':
          return '[[0][0][0]]'
        case 'array':
          return '0,0,0'
        case 'matrix':
          return '[[0,0,0][0,0,0][0,0,0]]'
        default:
          return ''
      }
    },
    // Depth-first search for the node whose full dotted address matches.
    findNodeByAddress(address) {
      return nodeAt(this.tree, address)
    },
    send() {
      if (this.sendDisabled) return
      this.sending = true
      const address = this.address.trim()
      const value = this.parsedValue
      // Numbered, when the simulation's replies are read, so its reply is matched to this value.
      const sequence = this.replies ? (this.sequence = (this.sequence + 1) % 4294967296) : undefined
      this.api
        .cmd(
          TARGET_NAME,
          COMMAND_NAME,
          sequence === undefined ? { ADDRESS: address, VALUE: value } : { ADDRESS: address, VALUE: value, SEQUENCE: sequence },
          // Handled below, so don't let the interceptor pop its own error
          { 'Ignore-Errors': '428 500' },
        )
        .then(() => {
          this.status = `Sent ${this.preview}`
          this.statusError = false
          this.addHistory(address, value, true, null, sequence)
          // Numbered, the simulation's reply says whether it was set (lookForReplies); otherwise only that it was sent.
          if (sequence === undefined) {
            this.$notify.normal({
              title: `Sent ${address}`,
              body: `${JSON.stringify(value)}`,
              severity: 'success',
            })
          }
        })
        .catch((error) => {
          const message = error.message || error.name || 'unknown error'
          this.status = `Error sending ${address}: ${message}`
          this.statusError = true
          this.addHistory(address, value, false, message)
          this.$notify.caution({
            title: `Unable to set ${address}`,
            body: message,
          })
        })
        .finally(() => {
          this.sending = false
        })
    },
    resend(entry) {
      this.address = entry.address
      this.value = entry.value
      this.send()
    },
    addHistory(address, value, success, error = null, sequence = undefined) {
      this.history.unshift({
        time: new Date().toLocaleTimeString(),
        address,
        value: JSON.stringify(value),
        success,
        error,
        // The simulation's reply: waited for while numbered and sent; then accepted, refused, or none.
        sequence,
        sentAt: Date.now(),
        reply: success && sequence !== undefined ? 'waiting' : undefined,
        replyError: '',
      })
      this.history = this.history.slice(0, MAX_HISTORY)
      if (this.history.some((e) => e.reply === 'waiting') && !this.replyTimer) {
        this.replyTimer = setInterval(() => this.lookForReplies(), REPLY_LOOK_MS)
      }
    },
    // The latest reply, matched to the value waiting for it by its number; a value waiting too long had none.
    async lookForReplies() {
      const waiting = this.history.filter((e) => e.reply === 'waiting')
      if (!waiting.length) {
        clearInterval(this.replyTimer)
        this.replyTimer = null
        return
      }
      try {
        const packet = await this.api.get_tlm_packet(TARGET_NAME, REPLY_PACKET, 'CONVERTED')
        const item = Object.fromEntries((packet ?? []).map(([name, value]) => [name, value]))
        const entry = waiting.find((e) => e.sequence === item.SEQUENCE && e.address === item.ADDRESS)
        if (entry) {
          entry.reply = item.ACCEPTED === true ? 'accepted' : 'refused'
          entry.replyError = item.ERROR ?? ''
          this.notifyReply(entry)
        }
      } catch {
        // No reply read this time; the value goes on waiting.
      }
      const now = Date.now()
      for (const e of waiting) {
        if (e.reply === 'waiting' && now - e.sentAt > REPLY_WAIT_MS) {
          e.reply = 'none'
          this.notifyReply(e)
        }
      }
    },
    // What the simulation said of a value, as a notification: set, refused with its reason, or no reply.
    notifyReply(entry) {
      if (entry.reply === 'accepted') {
        this.$notify.normal({ title: `Set ${entry.address}`, body: entry.value, severity: 'success' })
      } else {
        this.$notify.caution({ title: `${entry.address} was not set`, body: this.resultText(entry) })
      }
    },
    resultText(entry) {
      if (!entry.success) return entry.error
      switch (entry.reply) {
        case 'waiting':
          return 'Sent, waiting for the simulation'
        case 'accepted':
          return 'Set'
        case 'refused':
          return `Refused: ${entry.replyError || 'the simulation gave no reason'}`
        case 'none':
          return 'No reply: the simulation is not running or not connected, or SIM_CONTROL reads no replies (its plugin.txt block names no sim_control_reply_port)'
        default:
          return 'Sent'
      }
    },
    resultClass(entry) {
      if (!entry.success || entry.reply === 'refused') return 'text-error'
      if (entry.reply === 'none') return 'text-warning'
      if (entry.reply === 'accepted') return 'text-success'
      return ''
    },
    clear() {
      this.history = []
    },
  },
}
</script>

<style scoped>
.preview {
  font-family: 'Courier New', Courier, monospace;
}
/* A filter's 10×10 is wider than the page: the grid scrolls in its own box. */
.grid-scroll {
  max-width: 100%;
  overflow-x: auto;
}
.grid {
  border-collapse: collapse;
  margin-top: 4px;
}
.grid td {
  min-width: 7rem;
  padding: 2px;
}
</style>
