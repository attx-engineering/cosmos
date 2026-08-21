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
  <div class="month-grid">
    <div class="weekday-row">
      <div v-for="label in dayLabels" :key="label" class="weekday">
        {{ label }}
      </div>
    </div>
    <div class="weeks">
      <div v-for="(week, index) in weeks" :key="index" class="week">
        <div
          v-for="day in week"
          :key="day.key"
          class="day"
          :class="{
            'day--outside': !day.inMonth,
            'day--today': day.isToday,
          }"
        >
          <div class="day-label" @click="$emit('select-day', day.date)">
            {{ day.label }}
          </div>
          <div class="day-events">
            <div
              v-for="entry in day.visible"
              :key="entry.key"
              class="chip"
              :style="{ backgroundColor: entry.event.color }"
              :data-test="`event-${entry.event.type}`"
              @click.stop="$emit('select-event', entry.event)"
            >
              <span
                class="chip-status"
                :class="`chip-status--${statusLevel(entry.event.status)}`"
              />
              <span class="chip-text">
                {{ entry.timeLabel }} {{ entry.event.summary || entry.event.name }}
              </span>
            </div>
            <!-- Overflow opens the full list for that day rather than growing the cell -->
            <div
              v-if="day.overflow > 0"
              class="more"
              @click.stop="$emit('select-event', day.allEvents)"
            >
              +{{ day.overflow }} more
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import {
  addDays,
  endOfDay,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  startOfDay,
  startOfMonth,
  startOfWeek,
} from 'date-fns'

// Beyond this a cell becomes unreadable, so the rest collapse into "+N more"
const MAX_CHIPS_PER_DAY = 3

export default {
  props: {
    focus: {
      type: Date,
      required: true,
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
  emits: ['select-day', 'select-event'],
  data() {
    return {
      dayLabels: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    }
  },
  computed: {
    weeks: function () {
      const start = startOfWeek(startOfMonth(this.focus))
      const stop = endOfWeek(endOfMonth(this.focus))
      const today = new Date()
      const weeks = []
      let current = start
      while (current <= stop) {
        const week = []
        for (let i = 0; i < 7; i++) {
          const dayStart = startOfDay(current)
          const dayEnd = endOfDay(current)
          const dayEvents = this.events.filter(
            (event) => event.start <= dayEnd && event.stop >= dayStart,
          )
          const entries = dayEvents.map((event, index) => ({
            key: `${event.type}-${event.start.getTime()}-${index}`,
            event,
            timeLabel: format(event.start, 'HH:mm'),
          }))
          week.push({
            key: current.toISOString(),
            date: current,
            label: format(current, 'd'),
            inMonth: isSameMonth(current, this.focus),
            isToday: isSameDay(current, today),
            visible: entries.slice(0, MAX_CHIPS_PER_DAY),
            overflow: Math.max(entries.length - MAX_CHIPS_PER_DAY, 0),
            allEvents: dayEvents,
          })
          current = addDays(current, 1)
        }
        weeks.push(week)
      }
      return weeks
    },
  },
  methods: {
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
.month-grid {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.weekday-row {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}
.weekday {
  text-align: center;
  padding: 4px 0;
  font-size: 0.7rem;
  text-transform: uppercase;
  opacity: 0.7;
  border-left: 1px solid rgba(255, 255, 255, 0.12);
}
.weeks {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}
.week {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  flex: 1 1 0;
  min-height: 96px;
}
.day {
  border-left: 1px solid rgba(255, 255, 255, 0.12);
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  padding: 2px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.day--outside {
  opacity: 0.4;
}
.day--today {
  background-color: rgba(255, 255, 255, 0.05);
}
.day-label {
  font-size: 0.75rem;
  text-align: right;
  padding: 0 2px;
  cursor: pointer;
}
.day-label:hover {
  text-decoration: underline;
}
.day--today .day-label {
  font-weight: 700;
  color: rgb(var(--v-theme-primary));
}
.day-events {
  flex: 1 1 auto;
  overflow: hidden;
}
.chip {
  display: flex;
  align-items: center;
  gap: 3px;
  border-radius: 3px;
  padding: 0 3px;
  margin-bottom: 1px;
  font-size: 0.65rem;
  color: #ffffff;
  cursor: pointer;
}
.chip:hover {
  filter: brightness(1.2);
}
.chip-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip-status {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.chip-status--normal {
  background-color: #4caf50;
}
.chip-status--standby {
  background-color: #2196f3;
}
.chip-status--caution {
  background-color: #ffc107;
}
.chip-status--serious {
  background-color: #f44336;
}
.chip-status--off {
  background-color: rgba(255, 255, 255, 0.5);
}
.more {
  font-size: 0.65rem;
  opacity: 0.75;
  cursor: pointer;
  padding-left: 3px;
}
.more:hover {
  text-decoration: underline;
}
</style>
