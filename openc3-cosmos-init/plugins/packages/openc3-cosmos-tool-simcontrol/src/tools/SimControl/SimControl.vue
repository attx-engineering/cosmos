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
          Load the sim's graph_tree.json straight into the tool. It changes
          often, so this avoids any plugin rebuild/upload: dump the tree, pick
          it here, and autocomplete updates immediately. The parsed tree is kept
          in localStorage so it survives reloads until you load a newer one.
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
              returns exactly the next level down the tree for what's typed,
              cascading like member access in C++.
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
                  @keydown.enter="send"
                />
              </template>
              <v-list
                v-if="addressSuggestions.length"
                density="compact"
                max-height="400"
                data-test="sim-address-suggestions"
              >
                <v-list-item
                  v-for="s in addressSuggestions"
                  :key="s"
                  :title="s"
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
              @keydown.enter="send"
            />
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
              <td :class="entry.success ? '' : 'text-error'">
                {{ entry.success ? 'Sent' : entry.error }}
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

// The SIM target and its SET_VALUE command come from a plugin (openc3-cosmos-warplink
// ships one). The interface mapped to the target owns the simulation port.
const TARGET_NAME = 'SIM'
const COMMAND_NAME = 'SET_VALUE'
const MAX_HISTORY = 20
// Where the last-loaded graph tree is cached so it survives page reloads.
const TREE_STORAGE_KEY = 'simcontrol_graph_tree'

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
      // The sim's graph-tree dump (graph_tree.json), copied into the SIM
      // target directory. Drives address autocompletion; null until loaded (or
      // if absent, in which case the address field is just free text).
      tree: null,
      treeStatus: '',
      treeSource: '',
      showSuggestions: false,
      // The last value we auto-filled from a signal's template, so we can
      // replace it when the address changes without clobbering a value the
      // user typed themselves.
      autofilled: '',
      // One example per value type. Scalars (number/decimal/boolean) parse as
      // their JSON type; text and the vector/quaternion/matrix/array forms are
      // not valid JSON, so they fall through to being sent as a string -- which
      // is exactly what the simulation expects for those (a JSON array like
      // [1,2,3] would be rejected). The bracket forms match clockwerk's own
      // string format: a column vector/quaternion is [[a][b]...], a matrix is
      // [[row][row]...] with commas inside each row, and a plain array is a bare
      // comma-separated list.
      valueExamples: [
        { label: 'number', value: '5' },
        { label: 'decimal', value: '5.5' },
        { label: 'boolean', value: 'true' },
        { label: 'string', value: 'NADIR' },
        { label: 'vector', value: '[[1][2][3]]' },
        { label: 'quaternion', value: '[[0][0][0][1]]' },
        { label: 'matrix', value: '[[1,2,3][4,5,6][7,8,9]]' },
        { label: 'array', value: '1,2,3' },
      ],
    }
  },
  computed: {
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
        this.value.trim() === ''
      )
    },
    // Cascading address suggestions: given what's typed, list the nodes at the
    // next level down the tree (like member access in C++). The text up to the
    // last '.' is the committed path; the text after it filters that level's
    // children by name. Returns full dotted addresses so selecting one just
    // extends the field, ready for another '.' to go deeper.
    addressSuggestions() {
      if (!this.tree) return []
      const raw = this.address || ''
      const lastDot = raw.lastIndexOf('.')
      const base = lastDot >= 0 ? raw.slice(0, lastDot) : ''
      const partial = lastDot >= 0 ? raw.slice(lastDot + 1) : raw
      // base === '' means we're still at the root ('.exc'); otherwise list the
      // children of the node at the committed path.
      const level =
        base === ''
          ? [this.tree]
          : (this.findNodeByAddress(base)?.children ?? [])
      return level
        .filter((node) => node.name.startsWith(partial))
        .map((node) => node.address)
        .slice(0, 100)
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
    // when we know it, otherwise the general guidance.
    valueHint() {
      const leaf = this.resolvedLeaf
      if (leaf) {
        return leaf.settable
          ? `expected type: ${leaf.type}`
          : `${leaf.type} — read-only, cannot be set`
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
      if (!leaf || !leaf.settable) return
      if (this.value !== '' && this.value !== this.autofilled) return
      const template = this.templateForLeaf(leaf)
      this.value = template
      this.autofilled = template
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
    // Prefer a tree the user loaded before (cached); otherwise fall back to a
    // graph_tree.json baked into the SIM target, if one happens to be there.
    if (!this.loadStoredTree()) {
      this.loadGraphTree()
    }
  },
  methods: {
    // Restore the last-loaded tree from localStorage. Returns whether one was
    // found, so mounted() knows whether to try the SIM target fallback.
    loadStoredTree() {
      try {
        const raw = localStorage.getItem(TREE_STORAGE_KEY)
        if (raw) {
          this.tree = JSON.parse(raw)
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
        try {
          const parsed = JSON.parse(reader.result)
          this.tree = parsed
          this.treeSource = 'file'
          this.treeStatus = ''
          try {
            localStorage.setItem(TREE_STORAGE_KEY, reader.result)
          } catch {
            // Over quota -- the tree still works this session, just not cached.
          }
        } catch (error) {
          this.tree = null
          this.treeSource = ''
          this.treeStatus = `Could not parse that file as JSON: ${error.message}`
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
    // Fetch the sim's graph-tree dump from the SIM target directory. It is a
    // plain target file (the user copies graph_tree.json in), so it is read via
    // the storage download endpoint, trying targets_modified (an edit made in
    // COSMOS) before the packaged targets copy.
    async loadGraphTree() {
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
            this.tree = JSON.parse(atob(response.data.contents))
            this.treeSource = `${TARGET_NAME} target`
            this.treeStatus = ''
            return
          }
        } catch {
          // Not in this area; fall through and try the next one.
        }
      }
      this.treeStatus =
        'Load a graph_tree.json above to enable address autocomplete.'
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
      const node = this.findNodeByAddress(suggestion)
      const hasChildren = !!node?.children?.length
      this.address = hasChildren ? `${suggestion}.` : suggestion
      this.$nextTick(() => {
        this.showSuggestions = hasChildren && this.addressSuggestions.length > 0
      })
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
      if (!this.tree) return null
      const stack = [this.tree]
      while (stack.length) {
        const node = stack.pop()
        if (node.address === address) return node
        if (node.children) stack.push(...node.children)
      }
      return null
    },
    send() {
      if (this.sendDisabled) return
      this.sending = true
      const address = this.address.trim()
      const value = this.parsedValue
      this.api
        .cmd(
          TARGET_NAME,
          COMMAND_NAME,
          { ADDRESS: address, VALUE: value },
          // Handled below, so don't let the interceptor pop its own error
          { 'Ignore-Errors': '428 500' },
        )
        .then(() => {
          this.status = `Sent ${this.preview}`
          this.statusError = false
          this.addHistory(address, value, true)
          this.$notify.normal({
            title: `Set ${address}`,
            body: `${JSON.stringify(value)}`,
            severity: 'success',
          })
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
    addHistory(address, value, success, error = null) {
      this.history.unshift({
        time: new Date().toLocaleTimeString(),
        address,
        value: JSON.stringify(value),
        success,
        error,
      })
      this.history = this.history.slice(0, MAX_HISTORY)
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
</style>
