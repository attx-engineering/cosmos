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

<template>
  <v-card class="fill-height sidebar">
    <!-- Mini month calendar for navigation -->
    <div class="mini-calendar">
      <div class="mini-header">
        <v-btn
          icon="mdi-chevron-left"
          variant="text"
          size="x-small"
          data-test="mini-prev"
          @click="shiftMonth(-1)"
        />
        <span class="mini-title">{{ miniTitle }}</span>
        <v-btn
          icon="mdi-chevron-right"
          variant="text"
          size="x-small"
          data-test="mini-next"
          @click="shiftMonth(1)"
        />
      </div>
      <div class="mini-grid">
        <div v-for="label in dayLabels" :key="label" class="mini-weekday">
          {{ label }}
        </div>
        <div
          v-for="day in miniDays"
          :key="day.key"
          class="mini-day"
          :class="{
            'mini-day--outside': !day.inMonth,
            'mini-day--today': day.isToday,
            'mini-day--focus': day.isFocus,
          }"
          @click="$emit('update:focus', day.date)"
        >
          {{ day.label }}
        </div>
      </div>
    </div>

    <v-divider />

    <!-- Timelines -->
    <div class="section-header">
      <span>Timelines</span>
      <v-btn
        icon="mdi-plus"
        variant="text"
        size="x-small"
        data-test="add-timeline"
        @click="$emit('create-timeline')"
      />
    </div>
    <div v-if="timelines.length === 0" class="empty-hint">
      No timelines yet. Create one to schedule activities.
    </div>
    <v-list v-else density="compact" class="timeline-list">
      <v-list-item
        v-for="timeline in timelines"
        :key="timeline.name"
        :data-test="`timeline-${timeline.name}`"
      >
        <template #prepend>
          <v-checkbox-btn
            :model-value="selectedTimelines.includes(timeline.name)"
            density="compact"
            :color="timeline.color"
            hide-details
            @update:model-value="toggleTimeline(timeline.name)"
          />
        </template>
        <v-list-item-title class="timeline-title">
          <span
            class="timeline-swatch"
            :style="{ backgroundColor: timeline.color }"
          />
          {{ timeline.name }}
        </v-list-item-title>
        <template #append>
          <!-- A paused timeline keeps its activities but will not run them -->
          <v-tooltip
            :text="
              timeline.execute ? 'Executing - click to pause' : 'Paused - click to resume'
            "
            location="bottom"
          >
            <template #activator="{ props }">
              <v-btn
                v-bind="props"
                :icon="timeline.execute ? 'mdi-play-circle' : 'mdi-pause-circle'"
                :color="timeline.execute ? 'success' : 'warning'"
                variant="text"
                size="x-small"
                :data-test="`execute-${timeline.name}`"
                @click="$emit('toggle-execute', timeline)"
              />
            </template>
          </v-tooltip>
          <v-btn
            icon="mdi-delete"
            variant="text"
            size="x-small"
            :data-test="`delete-${timeline.name}`"
            @click="$emit('delete-timeline', timeline)"
          />
        </template>
      </v-list-item>
    </v-list>

    <v-divider />

    <!-- Other overlays -->
    <div class="section-header"><span>Other</span></div>
    <v-list density="compact">
      <v-list-item>
        <template #prepend>
          <v-checkbox-btn
            :model-value="showNotes"
            density="compact"
            hide-details
            data-test="show-notes"
            @update:model-value="$emit('update:showNotes', $event)"
          />
        </template>
        <v-list-item-title class="timeline-title">
          <span class="timeline-swatch" style="background-color: #4caf50" />
          Notes
        </v-list-item-title>
      </v-list-item>
      <v-list-item>
        <template #prepend>
          <v-checkbox-btn
            :model-value="showMetadata"
            density="compact"
            hide-details
            data-test="show-metadata"
            @update:model-value="$emit('update:showMetadata', $event)"
          />
        </template>
        <v-list-item-title class="timeline-title">
          <span class="timeline-swatch" style="background-color: #9c27b0" />
          Metadata
        </v-list-item-title>
      </v-list-item>
    </v-list>
  </v-card>
</template>

<script>
import {
  addDays,
  addMonths,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  startOfMonth,
  startOfWeek,
} from 'date-fns'

export default {
  props: {
    focus: {
      type: Date,
      required: true,
    },
    timelines: {
      type: Array,
      required: true,
    },
    selectedTimelines: {
      type: Array,
      required: true,
    },
    showNotes: {
      type: Boolean,
      default: true,
    },
    showMetadata: {
      type: Boolean,
      default: true,
    },
    timeZone: {
      type: String,
      default: 'local',
    },
  },
  emits: [
    'update:focus',
    'update:selectedTimelines',
    'update:showNotes',
    'update:showMetadata',
    'create-timeline',
    'delete-timeline',
    'toggle-execute',
  ],
  data() {
    return {
      // Tracked separately from focus so paging the mini calendar doesn't
      // move the main view until a day is actually clicked.
      miniMonth: startOfMonth(this.focus),
      dayLabels: ['S', 'M', 'T', 'W', 'T', 'F', 'S'],
    }
  },
  computed: {
    miniTitle: function () {
      return format(this.miniMonth, 'MMMM yyyy')
    },
    miniDays: function () {
      const start = startOfWeek(startOfMonth(this.miniMonth))
      const stop = endOfWeek(endOfMonth(this.miniMonth))
      const today = new Date()
      const days = []
      let current = start
      while (current <= stop) {
        days.push({
          key: current.toISOString(),
          date: current,
          label: format(current, 'd'),
          inMonth: isSameMonth(current, this.miniMonth),
          isToday: isSameDay(current, today),
          isFocus: isSameDay(current, this.focus),
        })
        current = addDays(current, 1)
      }
      return days
    },
  },
  watch: {
    // Following focus keeps the mini calendar in sync when the main view pages
    focus: function (value) {
      this.miniMonth = startOfMonth(value)
    },
  },
  methods: {
    shiftMonth: function (direction) {
      this.miniMonth = addMonths(this.miniMonth, direction)
    },
    toggleTimeline: function (name) {
      const selected = [...this.selectedTimelines]
      const index = selected.indexOf(name)
      if (index === -1) {
        selected.push(name)
      } else {
        selected.splice(index, 1)
      }
      this.$emit('update:selectedTimelines', selected)
    },
  },
}
</script>

<style scoped>
.sidebar {
  overflow-y: auto;
}
.mini-calendar {
  padding: 8px;
}
.mini-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mini-title {
  font-size: 0.85rem;
  font-weight: 500;
}
.mini-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 1px;
  margin-top: 4px;
}
.mini-weekday {
  text-align: center;
  font-size: 0.65rem;
  opacity: 0.6;
  padding: 2px 0;
}
.mini-day {
  text-align: center;
  font-size: 0.7rem;
  padding: 3px 0;
  cursor: pointer;
  border-radius: 3px;
}
.mini-day:hover {
  background-color: rgba(255, 255, 255, 0.12);
}
.mini-day--outside {
  opacity: 0.35;
}
.mini-day--today {
  font-weight: 700;
  text-decoration: underline;
}
.mini-day--focus {
  background-color: rgba(255, 255, 255, 0.2);
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.7;
}
.empty-hint {
  padding: 0 12px 12px;
  font-size: 0.75rem;
  opacity: 0.6;
}
.timeline-title {
  display: flex;
  align-items: center;
  font-size: 0.8rem;
}
.timeline-swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 6px;
  flex: 0 0 auto;
}
.timeline-list {
  max-height: 40vh;
  overflow-y: auto;
}
</style>
