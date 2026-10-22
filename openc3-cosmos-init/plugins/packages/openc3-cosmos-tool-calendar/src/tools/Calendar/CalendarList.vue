<!--
# Copyright 2026 ATTX, Inc.
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
-->

<template>
  <div class="list-view">
    <v-text-field
      v-model="search"
      label="Search"
      prepend-inner-icon="mdi-magnify"
      clearable
      variant="outlined"
      density="compact"
      single-line
      hide-details
      class="ma-2"
      data-test="list-search"
    />
    <v-data-table
      :headers="headers"
      :items="items"
      :search="search"
      :sort-by="[{ key: 'startRaw', order: 'asc' }]"
      density="compact"
      :items-per-page="50"
      data-test="event-list"
      @click:row="rowClick"
    >
      <template #no-data>
        <span>Nothing scheduled in this range</span>
      </template>
      <template #item.timeline="{ item }">
        <span class="swatch" :style="{ backgroundColor: item.color }" />
        {{ item.timeline }}
      </template>
      <template #item.status="{ item }">
        <span v-if="item.status">
          <span
            class="status-dot"
            :class="`status-dot--${statusLevel(item.status)}`"
          />
          {{ item.status }}
        </span>
        <span v-else class="text-disabled">&mdash;</span>
      </template>
    </v-data-table>
  </div>
</template>

<script>
import { TimeFilters } from '@openc3/vue-common/util'

export default {
  mixins: [TimeFilters],
  props: {
    events: {
      type: Array,
      required: true,
    },
    timeZone: {
      type: String,
      default: 'local',
    },
  },
  emits: ['select-event'],
  data() {
    return {
      search: '',
      headers: [
        { title: 'Start', key: 'start' },
        { title: 'Stop', key: 'stop' },
        { title: 'Timeline', key: 'timeline' },
        { title: 'Type', key: 'kind' },
        { title: 'Detail', key: 'summary' },
        { title: 'Status', key: 'status' },
      ],
    }
  },
  computed: {
    items: function () {
      return this.events.map((event) => ({
        // startRaw drives sorting so the table orders chronologically rather
        // than lexically on the formatted string
        startRaw: event.start.getTime(),
        start: this.formatDateTime(event.start, this.timeZone),
        stop: this.formatDateTime(event.stop, this.timeZone),
        timeline: event.name,
        kind: event.activity ? event.activity.kind : event.type,
        summary: event.summary || '',
        status: event.status,
        color: event.color,
        event,
      }))
    },
  },
  methods: {
    rowClick: function (_event, payload) {
      // Vuetify has moved this payload around between 3.x releases - it has
      // been both the item itself and a { raw } wrapper - so unwrap defensively
      const item = payload?.item?.raw || payload?.item
      if (item?.event) {
        this.$emit('select-event', item.event)
      }
    },
    statusLevel: function (status) {
      switch (status) {
        case 'completed':
          return 'normal'
        case 'created':
        case 'started':
        case 'running':
          return 'standby'
        case 'failed':
        case 'error':
        case 'crashed':
          return 'serious'
        case 'disabled':
        case 'stopped':
        case 'paused':
        case 'breakpoint':
        case 'completed_errors':
          return 'caution'
        default:
          return 'off'
      }
    },
  },
}
</script>

<style scoped>
.list-view :deep(tbody tr) {
  cursor: pointer;
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 6px;
}
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 5px;
}
.status-dot--normal {
  background-color: #4caf50;
}
.status-dot--standby {
  background-color: #2196f3;
}
.status-dot--caution {
  background-color: #ffc107;
}
.status-dot--serious {
  background-color: #f44336;
}
.status-dot--off {
  background-color: rgba(255, 255, 255, 0.5);
}
</style>
