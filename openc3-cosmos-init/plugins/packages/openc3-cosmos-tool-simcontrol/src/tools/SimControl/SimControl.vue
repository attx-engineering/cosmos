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
        <v-row dense>
          <v-col cols="12" md="8">
            <v-text-field
              v-model="address"
              label="Simulation Address"
              placeholder=".exc.spacecraft.params.mass"
              persistent-placeholder
              variant="outlined"
              density="compact"
              hide-details="auto"
              autofocus
              :disabled="!!setupError"
              data-test="sim-address"
              @keydown.enter="send"
            />
          </v-col>
          <v-col cols="12" md="4">
            <v-text-field
              v-model="value"
              label="Value"
              placeholder="5"
              persistent-placeholder
              variant="outlined"
              density="compact"
              hide-details="auto"
              :disabled="!!setupError"
              data-test="sim-value"
              @keydown.enter="send"
            />
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
import { OpenC3Api } from '@openc3/js-common/services'
import { TopBar } from '@openc3/vue-common/components'

// The SIM target and its SET_VALUE command come from a plugin (openc3-cosmos-warplink
// ships one). The interface mapped to the target owns the simulation port.
const TARGET_NAME = 'SIM'
const COMMAND_NAME = 'SET_VALUE'
const MAX_HISTORY = 20

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
        address: this.address.trim(),
        value: this.parsedValue,
      })
    },
    sendDisabled() {
      return (
        this.sending ||
        !!this.setupError ||
        this.address.trim() === '' ||
        this.value.trim() === ''
      )
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
  },
  methods: {
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
