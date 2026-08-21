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
  <div class="time-grid">
    <!-- Day headers, sticky so they stay visible while scrolling the hours -->
    <div class="grid-header" :style="columnStyle">
      <div class="gutter-header" />
      <div
        v-for="day in dayList"
        :key="day.key"
        class="day-header"
        :class="{ 'day-header--today': day.isToday }"
      >
        <div class="day-name">{{ day.weekday }}</div>
        <div class="day-number">{{ day.dayNumber }}</div>
      </div>
    </div>

    <div class="grid-body" :style="columnStyle">
      <!-- Hour labels -->
      <div class="gutter">
        <div v-for="hour in hours" :key="hour" class="hour-label">
          <span>{{ hourLabel(hour) }}</span>
        </div>
      </div>

      <!-- One column per day -->
      <div
        v-for="day in dayList"
        :key="day.key"
        class="day-column"
        :class="{ 'day-column--today': day.isToday }"
      >
        <!-- Clickable half-hour slots -->
        <div
          v-for="slot in slots"
          :key="slot"
          class="slot"
          :class="{ 'slot--half': slot % 2 === 1 }"
          @click="selectTime(day, slot)"
        />

        <!-- Current time indicator -->
        <div
          v-if="day.isToday"
          class="now-line"
          :style="{ top: `${nowOffset}%` }"
        />

        <!-- Events positioned by start/stop within the day -->
        <div
          v-for="entry in day.entries"
          :key="entry.key"
          class="event"
          :style="entry.style"
          :data-test="`event-${entry.event.type}`"
          @click.stop="$emit('select-event', entry.event)"
        >
          <span
            class="event-status"
            :class="`event-status--${statusLevel(entry.event.status)}`"
          />
          <span class="event-text">
            <strong>{{ entry.timeLabel }}</strong>
            {{ entry.event.summary || entry.event.name }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import {
  addDays,
  differenceInMinutes,
  endOfDay,
  format,
  isSameDay,
  startOfDay,
  startOfWeek,
} from 'date-fns'

const MINUTES_PER_DAY = 24 * 60

export default {
  props: {
    focus: {
      type: Date,
      required: true,
    },
    // 1 for the day view, 7 for the week view
    days: {
      type: Number,
      default: 7,
    },
    events: {
      type: Array,
      required: true,
    },
    timeZone: {
      type: String,
      default: 'local',
    },
  },
  emits: ['select-time', 'select-event'],
  data() {
    return {
      hours: Array.from({ length: 24 }, (_, i) => i),
      // Two clickable slots per hour
      slots: Array.from({ length: 48 }, (_, i) => i),
      now: new Date(),
      nowTimer: null,
    }
  },
  computed: {
    columnStyle: function () {
      return {
        gridTemplateColumns: `60px repeat(${this.dayList.length}, minmax(0, 1fr))`,
      }
    },
    dayList: function () {
      const start =
        this.days === 1 ? startOfDay(this.focus) : startOfWeek(this.focus)
      const today = new Date()
      const result = []
      for (let i = 0; i < this.days; i++) {
        const date = addDays(start, i)
        result.push({
          key: date.toISOString(),
          date,
          weekday: format(date, 'EEE'),
          dayNumber: format(date, 'd'),
          isToday: isSameDay(date, today),
          entries: this.entriesForDay(date),
        })
      }
      return result
    },
    nowOffset: function () {
      const minutes = differenceInMinutes(this.now, startOfDay(this.now))
      return (minutes / MINUTES_PER_DAY) * 100
    },
  },
  created() {
    // Move the current-time line without re-fetching anything
    this.nowTimer = setInterval(() => {
      this.now = new Date()
    }, 60000)
  },
  unmounted() {
    if (this.nowTimer) {
      clearInterval(this.nowTimer)
    }
  },
  methods: {
    hourLabel: function (hour) {
      if (hour === 0) {
        return ''
      }
      return format(new Date(2000, 0, 1, hour), 'HH:mm')
    },
    // Clip each event to the day being drawn so a multi-day activity shows a
    // band on every day it covers rather than overflowing the first one.
    entriesForDay: function (date) {
      const dayStart = startOfDay(date)
      const dayEnd = endOfDay(date)
      return this.events
        .filter((event) => event.start <= dayEnd && event.stop >= dayStart)
        .map((event, index) => {
          const start = event.start < dayStart ? dayStart : event.start
          let stop = event.stop > dayEnd ? dayEnd : event.stop
          // Zero length events (metadata) still need to be visible
          if (stop - start < 60000) {
            stop = new Date(start.getTime() + 60000)
          }
          const startMinutes = differenceInMinutes(start, dayStart)
          const durationMinutes = Math.max(
            differenceInMinutes(stop, start),
            15, // floor so a short activity stays clickable
          )
          return {
            key: `${event.type}-${event.start.getTime()}-${index}`,
            event,
            timeLabel: format(event.start, 'HH:mm'),
            style: {
              top: `${(startMinutes / MINUTES_PER_DAY) * 100}%`,
              height: `${(durationMinutes / MINUTES_PER_DAY) * 100}%`,
              backgroundColor: event.color,
              // Reserve activities (pass windows) read as a backdrop rather
              // than an action, so they are drawn faded and behind.
              opacity: event.activity?.kind === 'reserve' ? 0.45 : 0.9,
              zIndex: event.activity?.kind === 'reserve' ? 1 : 2,
            },
          }
        })
    },
    selectTime: function (day, slot) {
      const minutes = slot * 30
      const hour = Math.floor(minutes / 60)
      const minute = minutes % 60
      this.$emit('select-time', {
        date: format(day.date, 'yyyy-MM-dd'),
        time: `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00`,
      })
    },
    // Maps activity lifecycle states onto the Astro status levels the rest of
    // COSMOS uses: green nominal, yellow caution, red serious.
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
.time-grid {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}
.grid-header {
  display: grid;
  position: sticky;
  top: 0;
  z-index: 3;
  background-color: var(--color-background-surface-default, #1f1f1f);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}
.gutter-header {
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}
.day-header {
  text-align: center;
  padding: 4px 0;
  border-left: 1px solid rgba(255, 255, 255, 0.12);
}
.day-header--today .day-number {
  color: rgb(var(--v-theme-primary));
  font-weight: 700;
}
.day-name {
  font-size: 0.7rem;
  text-transform: uppercase;
  opacity: 0.7;
}
.day-number {
  font-size: 1.1rem;
}
.grid-body {
  display: grid;
  flex: 1 1 auto;
  position: relative;
}
.gutter {
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}
.hour-label {
  height: 48px;
  position: relative;
  text-align: right;
  padding-right: 6px;
}
.hour-label span {
  position: relative;
  top: -7px;
  font-size: 0.7rem;
  opacity: 0.65;
}
.day-column {
  position: relative;
  border-left: 1px solid rgba(255, 255, 255, 0.12);
}
.day-column--today {
  background-color: rgba(255, 255, 255, 0.03);
}
.slot {
  height: 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  cursor: pointer;
}
.slot:not(.slot--half) {
  border-bottom-color: rgba(255, 255, 255, 0.02);
}
.slot--half {
  border-bottom-color: rgba(255, 255, 255, 0.12);
}
.slot:hover {
  background-color: rgba(255, 255, 255, 0.06);
}
.now-line {
  position: absolute;
  left: 0;
  right: 0;
  height: 2px;
  background-color: #ff5252;
  z-index: 4;
  pointer-events: none;
}
.now-line::before {
  content: '';
  position: absolute;
  left: -4px;
  top: -3px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: #ff5252;
}
.event {
  position: absolute;
  left: 2px;
  right: 2px;
  border-radius: 3px;
  padding: 1px 4px;
  overflow: hidden;
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  gap: 4px;
  color: #ffffff;
  font-size: 0.7rem;
  line-height: 1.2;
}
.event:hover {
  filter: brightness(1.2);
}
.event-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.event-status {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 3px;
}
.event-status--normal {
  background-color: #4caf50;
}
.event-status--standby {
  background-color: #2196f3;
}
.event-status--caution {
  background-color: #ffc107;
}
.event-status--serious {
  background-color: #f44336;
}
.event-status--off {
  background-color: rgba(255, 255, 255, 0.5);
}
</style>
