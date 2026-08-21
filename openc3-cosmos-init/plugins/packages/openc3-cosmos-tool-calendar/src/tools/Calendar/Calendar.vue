<!--
###############################################################################
# Copyright (c) ATTX, Inc. 2026. All Rights Reserved.
#
# This software and associated documentation (the "Software") are the
# proprietary and confidential information of ATTX, Inc. The Software is
# furnished under a license agreement between ATTX and the user organization
# and may be used or copied only in accordance with the terms of the agreement.
# Refer to 'license/attx_license.adoc' for standard license terms.
#
# EXPORT CONTROL NOTICE: THIS SOFTWARE MAY INCLUDE CONTENT CONTROLLED UNDER THE
# INTERNATIONAL TRAFFIC IN ARMS REGULATIONS (ITAR) OR THE EXPORT ADMINISTRATION
# REGULATIONS (EAR99). No part of the Software may be used, reproduced, or
# transmitted in any form or by any means, for any purpose, without the express
# written permission of ATTX, Inc.
###############################################################################
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
    <top-bar :menus="menus" :title="title" />
    <v-row no-gutters class="calendar-layout">
      <v-col cols="auto" class="sidebar-col">
        <calendar-sidebar
          v-model:focus="focus"
          v-model:selected-timelines="selectedTimelines"
          v-model:show-notes="showNotes"
          v-model:show-metadata="showMetadata"
          :timelines="timelines"
          :time-zone="timeZone"
          @create-timeline="showTimelineCreate = true"
          @delete-timeline="deleteTimeline"
          @toggle-execute="toggleExecute"
        />
      </v-col>

      <v-col class="calendar-col">
        <v-card class="fill-height d-flex flex-column">
          <v-toolbar density="compact" class="calendar-toolbar">
            <v-btn
              variant="outlined"
              size="small"
              class="mr-2"
              data-test="today"
              @click="focus = new Date()"
            >
              Today
            </v-btn>
            <v-btn
              icon="mdi-chevron-left"
              variant="text"
              density="comfortable"
              data-test="prev"
              @click="shift(-1)"
            />
            <v-btn
              icon="mdi-chevron-right"
              variant="text"
              density="comfortable"
              data-test="next"
              @click="shift(1)"
            />
            <v-toolbar-title class="focus-title">
              {{ focusTitle }}
            </v-toolbar-title>
            <v-spacer />
            <v-btn-toggle
              v-model="view"
              mandatory
              density="compact"
              variant="outlined"
              divided
            >
              <v-btn
                v-for="option in viewOptions"
                :key="option.value"
                :value="option.value"
                size="small"
                :data-test="`view-${option.value}`"
              >
                {{ option.label }}
              </v-btn>
            </v-btn-toggle>
          </v-toolbar>

          <div class="flex-grow-1 calendar-body">
            <calendar-month
              v-if="view === 'month'"
              :focus="focus"
              :events="events"
              :time-zone="timeZone"
              @select-day="selectDay"
              @select-event="openEvent"
            />
            <calendar-gantt
              v-else-if="view === 'gantt'"
              :range="range"
              :events="events"
              :timelines="visibleTimelines"
              :time-zone="timeZone"
              @select-event="openEvent"
            />
            <calendar-list
              v-else-if="view === 'list'"
              :events="events"
              :time-zone="timeZone"
              @select-event="openEvent"
            />
            <calendar-time-grid
              v-else
              :focus="focus"
              :days="view === 'day' ? 1 : 7"
              :events="events"
              :time-zone="timeZone"
              @select-time="createAt"
              @select-event="openEvent"
            />
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Dialogs -->
    <activity-create-dialog
      v-if="showActivityCreate"
      v-model="showActivityCreate"
      :timelines="timelines"
      :activity="editActivity"
      :date="createDate"
      :time="createTime"
      :time-zone="timeZone"
      @update="refresh"
    />
    <note-create-dialog
      v-if="showNoteCreate"
      v-model="showNoteCreate"
      :note="editNote"
      :date="createDate"
      :time="createTime"
      :time-zone="timeZone"
      @update="refresh"
    />
    <metadata-create-dialog
      v-if="showMetadataCreate"
      v-model="showMetadataCreate"
      :metadata="editMetadata"
      :date="createDate"
      :time="createTime"
      :time-zone="timeZone"
      @update="refresh"
    />
    <event-list-dialog
      v-if="showEventList"
      v-model="showEventList"
      :events="selectedEvents"
      :timelines="timelines"
      :time-zone="timeZone"
      @close="showEventList = false"
      @update="refresh"
    />

    <!-- Create timeline -->
    <v-dialog v-model="showTimelineCreate" max-width="500">
      <v-card>
        <v-toolbar height="24">
          <v-spacer />
          <span>Create Timeline</span>
          <v-spacer />
        </v-toolbar>
        <v-card-text>
          <v-text-field
            v-model="newTimelineName"
            label="Timeline Name"
            variant="outlined"
            density="compact"
            :rules="[rules.required]"
            data-test="timeline-name"
          />
          <color-select-form v-model="newTimelineColor" />
          <v-alert v-if="timelineError" type="error" density="compact">
            {{ timelineError }}
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="showTimelineCreate = false">
            Cancel
          </v-btn>
          <v-btn
            variant="flat"
            :disabled="!newTimelineName"
            data-test="create-timeline-submit"
            @click="createTimeline"
          >
            Create
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
import { Api, Cable } from '@openc3/js-common/services'
import { TopBar } from '@openc3/vue-common/components'
import { TimeFilters } from '@openc3/vue-common/util'
import {
  ActivityCreateDialog,
  ColorSelectForm,
  EventListDialog,
  MetadataCreateDialog,
  NoteCreateDialog,
} from '@openc3/vue-common/tools/calendar'
import {
  addDays,
  addMonths,
  endOfMonth,
  endOfWeek,
  format,
  startOfDay,
  startOfMonth,
  startOfWeek,
} from 'date-fns'
import CalendarGantt from './CalendarGantt.vue'
import CalendarList from './CalendarList.vue'
import CalendarMonth from './CalendarMonth.vue'
import CalendarSidebar from './CalendarSidebar.vue'
import CalendarTimeGrid from './CalendarTimeGrid.vue'

export default {
  components: {
    ActivityCreateDialog,
    CalendarGantt,
    CalendarList,
    CalendarMonth,
    CalendarSidebar,
    CalendarTimeGrid,
    ColorSelectForm,
    EventListDialog,
    MetadataCreateDialog,
    NoteCreateDialog,
    TopBar,
  },
  mixins: [TimeFilters],
  data() {
    return {
      title: 'Calendar',
      view: 'week',
      focus: new Date(),
      timelines: [],
      selectedTimelines: [],
      activities: [],
      notes: [],
      metadata: [],
      showNotes: true,
      showMetadata: true,
      timeZone: 'local',
      // Dialog state
      showActivityCreate: false,
      showNoteCreate: false,
      showMetadataCreate: false,
      showEventList: false,
      showTimelineCreate: false,
      editActivity: null,
      editNote: null,
      editMetadata: null,
      selectedEvents: [],
      createDate: null,
      createTime: null,
      newTimelineName: '',
      newTimelineColor: '#003784',
      timelineError: null,
      rules: {
        required: (value) => !!value || 'Required',
      },
      cable: new Cable(),
      timelineSubscription: null,
      calendarSubscription: null,
      // Coalesces the burst of notifications a recurring activity creates
      refreshTimer: null,
    }
  },
  computed: {
    viewOptions: function () {
      return [
        { label: 'Day', value: 'day' },
        { label: 'Week', value: 'week' },
        { label: 'Month', value: 'month' },
        { label: 'Gantt', value: 'gantt' },
        { label: 'List', value: 'list' },
      ]
    },
    // Only the timelines the user has ticked, so the gantt rows match what the
    // other views are drawing
    visibleTimelines: function () {
      return this.timelines.filter((timeline) =>
        this.selectedTimelines.includes(timeline.name),
      )
    },
    menus: function () {
      return [
        {
          label: 'File',
          items: [
            {
              label: 'Add Activity',
              icon: 'mdi-calendar-plus',
              command: () => {
                this.editActivity = null
                this.createDate = null
                this.createTime = null
                this.showActivityCreate = true
              },
            },
            {
              label: 'Add Note',
              icon: 'mdi-note-plus',
              command: () => {
                this.editNote = null
                this.createDate = null
                this.createTime = null
                this.showNoteCreate = true
              },
            },
            {
              label: 'Add Metadata',
              icon: 'mdi-database-plus',
              command: () => {
                this.editMetadata = null
                this.createDate = null
                this.createTime = null
                this.showMetadataCreate = true
              },
            },
            {
              divider: true,
            },
            {
              label: 'Add Timeline',
              icon: 'mdi-timeline-plus',
              command: () => {
                this.showTimelineCreate = true
              },
            },
          ],
        },
        {
          label: 'View',
          items: [
            {
              radioGroup: true,
              value: this.view,
              command: (value) => {
                this.view = value
              },
              choices: this.viewOptions,
            },
            {
              divider: true,
            },
            {
              radioGroup: true,
              value: this.timeZone,
              command: (value) => {
                this.timeZone = value
              },
              choices: [
                { label: 'Local Time', value: 'local' },
                { label: 'UTC Time', value: 'UTC' },
              ],
            },
          ],
        },
      ]
    },
    // The window currently on screen, widened to whole days so the grid
    // never shows a partially loaded edge.
    range: function () {
      let start, stop
      if (this.view === 'month') {
        start = startOfWeek(startOfMonth(this.focus))
        stop = endOfWeek(endOfMonth(this.focus))
      } else if (this.view === 'week' || this.view === 'gantt' || this.view === 'list') {
        start = startOfWeek(this.focus)
        stop = endOfWeek(this.focus)
      } else {
        start = startOfDay(this.focus)
        stop = addDays(start, 1)
      }
      return { start, stop }
    },
    focusTitle: function () {
      if (this.view === 'month') {
        return format(this.focus, 'MMMM yyyy')
      }
      if (this.view !== 'day') {
        const start = startOfWeek(this.focus)
        const stop = endOfWeek(this.focus)
        return `${format(start, 'MMM d')} – ${format(stop, 'MMM d, yyyy')}`
      }
      return format(this.focus, 'EEEE, MMMM d, yyyy')
    },
    // Everything the grids draw, normalized to one shape regardless of source.
    events: function () {
      const result = []
      this.activities.forEach((activity) => {
        if (!this.selectedTimelines.includes(activity.name)) {
          return
        }
        const timeline = this.timelines.find((t) => t.name === activity.name)
        result.push({
          type: 'activity',
          typeStr: 'Activity',
          name: activity.name,
          start: new Date(activity.start * 1000),
          stop: new Date(activity.stop * 1000),
          // EventListDialog's table reads `end` while the grids read `stop`
          end: new Date(activity.stop * 1000),
          color: timeline ? timeline.color : '#666666',
          status: this.activityStatus(activity),
          summary: this.activitySummary(activity),
          activity,
        })
      })
      if (this.showNotes) {
        this.notes.forEach((note) => {
          result.push({
            type: 'note',
            typeStr: 'Note',
            name: 'Note',
            start: new Date(note.start * 1000),
            stop: new Date(note.stop * 1000),
            end: new Date(note.stop * 1000),
            color: note.color || '#4CAF50',
            status: null,
            summary: note.description,
            note,
          })
        })
      }
      if (this.showMetadata) {
        this.metadata.forEach((meta) => {
          result.push({
            type: 'metadata',
            typeStr: 'Metadata',
            name: 'Metadata',
            start: new Date(meta.start * 1000),
            stop: new Date(meta.start * 1000),
            end: new Date(meta.start * 1000),
            color: meta.color || '#9C27B0',
            status: null,
            summary: Object.entries(meta.metadata || {})
              .map(([key, value]) => `${key}: ${value}`)
              .join(', '),
            metadata: meta,
          })
        })
      }
      return result.sort((a, b) => a.start - b.start)
    },
  },
  watch: {
    view: function () {
      this.refresh()
    },
    focus: function () {
      this.refresh()
    },
    // A newly created timeline should be visible without the user hunting for it
    timelines: function (newTimelines, oldTimelines) {
      const oldNames = oldTimelines.map((t) => t.name)
      newTimelines.forEach((timeline) => {
        if (!oldNames.includes(timeline.name)) {
          this.selectedTimelines.push(timeline.name)
        }
      })
    },
  },
  created() {
    this.loadTimelines().then(() => {
      this.refresh()
    })
    this.subscribe()
  },
  unmounted() {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer)
    }
    if (this.timelineSubscription) {
      this.timelineSubscription.unsubscribe()
    }
    if (this.calendarSubscription) {
      this.calendarSubscription.unsubscribe()
    }
    this.cable.disconnect()
  },
  methods: {
    // Timelines and activities arrive on one channel, notes and metadata on the
    // other. Both simply trigger a reload of the visible window.
    subscribe: function () {
      this.cable
        .createSubscription('TimelineEventsChannel', window.openc3Scope, {
          received: () => {
            this.cable.recordPing()
            this.queueRefresh()
          },
        })
        .then((subscription) => {
          this.timelineSubscription = subscription
        })
      this.cable
        .createSubscription('CalendarEventsChannel', window.openc3Scope, {
          received: () => {
            this.cable.recordPing()
            this.queueRefresh()
          },
        })
        .then((subscription) => {
          this.calendarSubscription = subscription
        })
    },
    // Creating a recurring activity emits one notification per occurrence, so
    // debounce rather than refetching the whole window for each one.
    queueRefresh: function () {
      if (this.refreshTimer) {
        clearTimeout(this.refreshTimer)
      }
      this.refreshTimer = setTimeout(() => {
        this.refreshTimer = null
        this.loadTimelines().then(() => {
          this.refresh()
        })
      }, 300)
    },
    loadTimelines: function () {
      return Api.get('/openc3-api/timeline')
        .then((response) => {
          this.timelines = response.data
        })
        .catch(() => {
          this.timelines = []
        })
    },
    refresh: function () {
      const start = this.range.start.toISOString()
      const stop = this.range.stop.toISOString()
      this.loadActivities(start, stop)
      this.loadNotes(start, stop)
      this.loadMetadata(start, stop)
    },
    loadActivities: function (start, stop) {
      if (this.timelines.length === 0) {
        this.activities = []
        return
      }
      Promise.all(
        this.timelines.map((timeline) =>
          Api.get(`/openc3-api/timeline/${timeline.name}/activities`, {
            params: { start, stop },
          })
            .then((response) => response.data)
            .catch(() => []),
        ),
      ).then((results) => {
        this.activities = results.flat()
      })
    },
    loadNotes: function (start, stop) {
      Api.get('/openc3-api/notes', { params: { start, stop } })
        .then((response) => {
          this.notes = response.data
        })
        .catch(() => {
          this.notes = []
        })
    },
    loadMetadata: function (start, stop) {
      Api.get('/openc3-api/metadata', { params: { start, stop } })
        .then((response) => {
          this.metadata = response.data
        })
        .catch(() => {
          this.metadata = []
        })
    },
    // The most recent event wins, matching how the activity records its history.
    activityStatus: function (activity) {
      const events = activity.events || []
      if (events.length === 0) {
        return 'created'
      }
      return events[events.length - 1].event
    },
    activitySummary: function (activity) {
      switch (activity.kind) {
        case 'command':
          return activity.data.command
        case 'script':
          return activity.data.script
        default:
          return activity.kind
      }
    },
    shift: function (direction) {
      if (this.view === 'month') {
        this.focus = addMonths(this.focus, direction)
      } else if (this.view === 'day') {
        this.focus = addDays(this.focus, direction)
      } else {
        this.focus = addDays(this.focus, 7 * direction)
      }
    },
    selectDay: function (date) {
      this.focus = date
      this.view = 'day'
    },
    // Clicking an empty slot starts a new activity pre-filled with that time
    createAt: function ({ date, time }) {
      this.editActivity = null
      this.createDate = date
      this.createTime = time
      this.showActivityCreate = true
    },
    openEvent: function (events) {
      this.selectedEvents = Array.isArray(events) ? events : [events]
      this.showEventList = true
    },
    createTimeline: function () {
      this.timelineError = null
      Api.post('/openc3-api/timeline', {
        data: { name: this.newTimelineName, color: this.newTimelineColor },
      })
        .then(() => {
          this.showTimelineCreate = false
          this.newTimelineName = ''
          this.$notify.normal({
            title: 'Created Timeline',
            body: `Timeline ${this.newTimelineName} created`,
          })
          this.loadTimelines().then(() => this.refresh())
        })
        .catch((error) => {
          this.timelineError =
            error.response?.data?.message || 'Failed to create timeline'
        })
    },
    deleteTimeline: function (timeline) {
      this.$dialog
        .confirm(
          `Are you sure you want to delete timeline ${timeline.name} and all of its activities?`,
          { okText: 'Delete', cancelText: 'Cancel' },
        )
        .then(() => {
          return Api.delete(`/openc3-api/timeline/${timeline.name}`, {
            params: { force: true },
          })
        })
        .then(() => {
          this.selectedTimelines = this.selectedTimelines.filter(
            (name) => name !== timeline.name,
          )
          this.$notify.normal({
            title: 'Deleted Timeline',
            body: `Timeline ${timeline.name} deleted`,
          })
          this.loadTimelines().then(() => this.refresh())
        })
        .catch(() => {})
    },
    // Turning execution off leaves the activities on the calendar but stops the
    // timeline microservice from running them.
    toggleExecute: function (timeline) {
      // NOTE: the endpoint reads 'enable', not 'execute', and coerces the
      // string through ConfigParser.handle_true_false - anything else arrives
      // as nil, which reads as false and can never be turned back on.
      Api.post(`/openc3-api/timeline/${timeline.name}/execute`, {
        data: { enable: (!timeline.execute).toString() },
      })
        .then(() => {
          this.loadTimelines()
        })
        .catch((error) => {
          this.$notify.caution({
            title: 'Failed to change execution',
            body: error.response?.data?.message || 'Unknown error',
          })
        })
    },
  },
}
</script>

<style scoped>
.calendar-layout {
  height: calc(100vh - 100px);
}
.sidebar-col {
  width: 280px;
  min-width: 280px;
  padding-right: 8px;
  overflow-y: auto;
}
.calendar-col {
  overflow: hidden;
}
.calendar-toolbar {
  flex: 0 0 auto;
}
.calendar-body {
  overflow: auto;
  min-height: 0;
}
.focus-title {
  font-size: 1rem;
  margin-left: 8px;
}
</style>
