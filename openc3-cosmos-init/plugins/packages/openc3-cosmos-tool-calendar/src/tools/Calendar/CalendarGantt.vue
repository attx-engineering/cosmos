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
  <div class="gantt-wrapper">
    <!-- Zoom controls -->
    <div class="zoom-bar">
      <v-btn
        icon="mdi-magnify-minus-outline"
        variant="text"
        size="x-small"
        :disabled="zoom <= MIN_ZOOM"
        data-test="gantt-zoom-out"
        @click="zoomBy(1 / ZOOM_STEP)"
      />
      <span class="zoom-level">{{ zoomLabel }}</span>
      <v-btn
        icon="mdi-magnify-plus-outline"
        variant="text"
        size="x-small"
        :disabled="zoom >= MAX_ZOOM"
        data-test="gantt-zoom-in"
        @click="zoomBy(ZOOM_STEP)"
      />
      <v-btn
        variant="outlined"
        size="x-small"
        class="ml-2"
        :disabled="zoom === 1"
        data-test="gantt-zoom-fit"
        @click="resetZoom"
      >
        Fit
      </v-btn>
      <v-btn
        variant="outlined"
        size="x-small"
        class="ml-1"
        :disabled="!nowInRange"
        data-test="gantt-scroll-now"
        @click="scrollToNow"
      >
        Now
      </v-btn>
      <v-spacer />
      <span class="zoom-hint">Scroll to zoom, drag to pan</span>
    </div>

    <div
      ref="scroll"
      class="gantt-scroll"
      :class="{ 'gantt-scroll--dragging': dragging }"
      @scroll="onScroll"
      @wheel="onWheel"
      @mousedown="startDrag"
    >
      <div class="gantt-inner" :style="{ width: `${innerWidth}px` }">
        <!-- Time axis -->
        <div class="gantt-header">
          <div class="row-label header-label">Timeline</div>
          <div class="gantt-track" :style="trackStyle">
            <div
              v-for="tick in ticks"
              :key="tick.key"
              class="tick"
              :class="{ 'tick--major': tick.major }"
              :style="{ left: tick.left }"
            >
              <span class="tick-label">{{ tick.label }}</span>
            </div>
          </div>
        </div>

        <div v-if="rows.length === 0" class="empty-hint">
          Nothing scheduled in this range.
        </div>

        <!-- One row per timeline -->
        <div
          v-for="row in rows"
          :key="row.name"
          class="gantt-row"
          :data-test="`gantt-row-${row.name}`"
        >
          <div class="row-label">
            <span class="row-swatch" :style="{ backgroundColor: row.color }" />
            <span class="row-name">{{ row.name }}</span>
            <span class="row-count">{{ row.bars.length }}</span>
          </div>
          <div class="gantt-track" :style="trackStyle">
            <div
              v-for="tick in ticks"
              :key="`${row.name}-${tick.key}`"
              class="tick tick--grid"
              :class="{ 'tick--major': tick.major }"
              :style="{ left: tick.left }"
            />
            <div v-if="nowLeft" class="now-line" :style="{ left: nowLeft }" />
            <div
              v-for="bar in row.bars"
              :key="bar.key"
              class="bar"
              :style="bar.style"
              :title="bar.tooltip"
              :data-test="`gantt-bar-${bar.event.type}`"
              @click="barClick(bar.event)"
            >
              <span
                class="bar-status"
                :class="`bar-status--${statusLevel(bar.event.status)}`"
              />
              <span class="bar-text">{{ bar.label }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { format } from 'date-fns'

// Must match .row-label width in the styles below - the zoom and pan math
// converts between pointer position and time using this offset.
const LABEL_WIDTH = 200
const MINUTE = 60 * 1000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

// Candidate spacings for the time axis, smallest first. The first one wide
// enough to keep labels from colliding wins.
const TICK_STEPS = [
  { ms: MINUTE, format: 'HH:mm', major: (d) => d.getMinutes() === 0 },
  { ms: 5 * MINUTE, format: 'HH:mm', major: (d) => d.getMinutes() === 0 },
  { ms: 15 * MINUTE, format: 'HH:mm', major: (d) => d.getMinutes() === 0 },
  { ms: 30 * MINUTE, format: 'HH:mm', major: (d) => d.getMinutes() === 0 },
  { ms: HOUR, format: 'HH:mm', major: (d) => d.getHours() === 0 },
  { ms: 3 * HOUR, format: 'HH:mm', major: (d) => d.getHours() === 0 },
  { ms: 6 * HOUR, format: 'EEE HH:mm', major: (d) => d.getHours() === 0 },
  { ms: 12 * HOUR, format: 'EEE HH:mm', major: (d) => d.getHours() === 0 },
  { ms: DAY, format: 'EEE d', major: () => true },
  { ms: 7 * DAY, format: 'MMM d', major: () => true },
]

export default {
  props: {
    // { start: Date, stop: Date } - the window the parent is showing
    range: {
      type: Object,
      required: true,
    },
    events: {
      type: Array,
      required: true,
    },
    // Drawn even when they have nothing scheduled, so an empty timeline is
    // visibly empty rather than missing
    timelines: {
      type: Array,
      default: () => [],
    },
    timeZone: {
      type: String,
      default: 'local',
    },
  },
  emits: ['select-event'],
  data() {
    return {
      MIN_ZOOM: 1,
      MAX_ZOOM: 512,
      ZOOM_STEP: 2,
      zoom: 1,
      scrollLeft: 0,
      viewportWidth: 800,
      now: new Date(),
      nowTimer: null,
      resizeObserver: null,
      dragging: false,
      // Set once a mousedown travels far enough to count as a pan, so the
      // mouseup that ends it doesn't also select whatever bar it landed on
      dragMoved: false,
      dragOrigin: null,
    }
  },
  computed: {
    span: function () {
      return this.range.stop.getTime() - this.range.start.getTime()
    },
    // Width of the time track. At zoom 1 it exactly fills the viewport, so the
    // chart only scrolls once the user has actually zoomed in.
    contentWidth: function () {
      return Math.max(this.viewportWidth - LABEL_WIDTH, 120) * this.zoom
    },
    innerWidth: function () {
      return LABEL_WIDTH + this.contentWidth
    },
    trackStyle: function () {
      return { width: `${this.contentWidth}px` }
    },
    msPerPixel: function () {
      return this.span / this.contentWidth
    },
    zoomLabel: function () {
      // The visible duration is more meaningful to an operator than "8x"
      const visibleMs = this.msPerPixel * (this.viewportWidth - LABEL_WIDTH)
      if (visibleMs >= 2 * DAY) {
        return `${(visibleMs / DAY).toFixed(1)}d`
      }
      if (visibleMs >= 2 * HOUR) {
        return `${(visibleMs / HOUR).toFixed(1)}h`
      }
      return `${Math.max(Math.round(visibleMs / MINUTE), 1)}m`
    },
    // Only the slice of time currently scrolled into view, widened by half a
    // viewport each way so panning doesn't reveal missing ticks.
    visibleWindow: function () {
      const trackVisible = Math.max(this.viewportWidth - LABEL_WIDTH, 120)
      const margin = trackVisible / 2
      const startPx = Math.max(this.scrollLeft - margin, 0)
      const stopPx = Math.min(
        this.scrollLeft + trackVisible + margin,
        this.contentWidth,
      )
      return {
        start: this.range.start.getTime() + startPx * this.msPerPixel,
        stop: this.range.start.getTime() + stopPx * this.msPerPixel,
      }
    },
    tickStep: function () {
      // Aim for a tick roughly every 90px so labels stay readable
      const target = this.msPerPixel * 90
      return TICK_STEPS.find((step) => step.ms >= target) || TICK_STEPS[TICK_STEPS.length - 1]
    },
    // Only ticks inside visibleWindow are built, so zooming to minute
    // resolution over a week doesn't create thousands of DOM nodes.
    ticks: function () {
      const step = this.tickStep
      const result = []
      // Align to the step so labels land on round times
      let t = Math.ceil(this.visibleWindow.start / step.ms) * step.ms
      while (t <= this.visibleWindow.stop) {
        const date = new Date(t)
        result.push({
          key: t,
          label: format(date, step.format),
          major: step.major(date),
          left: this.percent(t),
        })
        t += step.ms
        if (result.length > 300) break // hard stop against a pathological range
      }
      return result
    },
    nowInRange: function () {
      return this.now >= this.range.start && this.now <= this.range.stop
    },
    nowLeft: function () {
      return this.nowInRange ? this.percent(this.now.getTime()) : null
    },
    // Group events into one row per timeline, keeping empty timelines visible
    rows: function () {
      const byName = {}
      this.timelines.forEach((timeline) => {
        byName[timeline.name] = {
          name: timeline.name,
          color: timeline.color,
          bars: [],
        }
      })
      this.events.forEach((event) => {
        if (!byName[event.name]) {
          byName[event.name] = { name: event.name, color: event.color, bars: [] }
        }
        byName[event.name].bars.push(this.makeBar(event))
      })
      // Timelines first in their configured order, then Notes / Metadata
      const configured = this.timelines.map((t) => t.name)
      return Object.keys(byName)
        .sort((a, b) => {
          const ai = configured.indexOf(a)
          const bi = configured.indexOf(b)
          if (ai !== -1 && bi !== -1) return ai - bi
          if (ai !== -1) return -1
          if (bi !== -1) return 1
          return a.localeCompare(b)
        })
        .map((name) => byName[name])
    },
  },
  watch: {
    // Paging to a different week keeps the zoom level - the operator is
    // usually still interested in the same detail - but starts at its left edge
    range: function () {
      this.$nextTick(() => {
        this.setScroll(0)
      })
    },
  },
  created() {
    this.nowTimer = setInterval(() => {
      this.now = new Date()
    }, 60000)
  },
  mounted() {
    this.measure()
    if (window.ResizeObserver) {
      this.resizeObserver = new ResizeObserver(() => {
        this.measure()
      })
      this.resizeObserver.observe(this.$refs.scroll)
    } else {
      window.addEventListener('resize', this.measure)
    }
  },
  unmounted() {
    if (this.nowTimer) {
      clearInterval(this.nowTimer)
    }
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
    } else {
      window.removeEventListener('resize', this.measure)
    }
    this.endDrag()
  },
  methods: {
    measure: function () {
      if (this.$refs.scroll) {
        this.viewportWidth = this.$refs.scroll.clientWidth
        this.scrollLeft = this.$refs.scroll.scrollLeft
      }
    },
    onScroll: function (event) {
      this.scrollLeft = event.target.scrollLeft
    },
    // Ctrl/Cmd + wheel zooms about the pointer, matching how maps and trackpad
    // pinch gestures behave. A plain wheel is left alone so the page still
    // scrolls normally.
    onWheel: function (event) {
      if (!this.$refs.scroll) {
        return
      }
      // The wheel zooms rather than scrolls here - panning is done by dragging
      event.preventDefault()
      const rect = this.$refs.scroll.getBoundingClientRect()
      const pointerX = event.clientX - rect.left
      this.zoomBy(this.wheelFactor(event), pointerX)
    },

    // Scale the zoom by how far the wheel actually turned. A trackpad fires a
    // stream of small deltas where a mouse wheel fires a few large ones, so a
    // fixed step per event would slam a trackpad straight to maximum zoom.
    wheelFactor: function (event) {
      let delta = event.deltaY
      if (event.deltaMode === 1) {
        delta *= 16 // reported in lines
      } else if (event.deltaMode === 2) {
        delta *= this.viewportWidth // reported in pages
      }
      // A typical mouse notch (~100) gives about 1.26x; clamped so one
      // oversized event can't jump more than a doubling
      const clamped = Math.max(Math.min(delta, 300), -300)
      return Math.pow(2, -clamped / 300)
    },

    // Grab anywhere on the chart to pan in both directions. Listeners go on
    // the window so the drag survives the pointer leaving the element.
    startDrag: function (event) {
      if (event.button !== 0 || !this.$refs.scroll) {
        return
      }
      const el = this.$refs.scroll
      this.dragging = true
      this.dragMoved = false
      this.dragOrigin = {
        x: event.clientX,
        y: event.clientY,
        scrollLeft: el.scrollLeft,
        scrollTop: el.scrollTop,
      }
      window.addEventListener('mousemove', this.onDrag)
      window.addEventListener('mouseup', this.endDrag)
    },
    onDrag: function (event) {
      if (!this.dragging || !this.$refs.scroll) {
        return
      }
      const el = this.$refs.scroll
      const dx = event.clientX - this.dragOrigin.x
      const dy = event.clientY - this.dragOrigin.y
      // A few pixels of slop so a slightly shaky click still selects a bar
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
        this.dragMoved = true
      }
      el.scrollTop = this.dragOrigin.scrollTop - dy
      this.setScroll(this.dragOrigin.scrollLeft - dx)
    },
    endDrag: function () {
      this.dragging = false
      window.removeEventListener('mousemove', this.onDrag)
      window.removeEventListener('mouseup', this.endDrag)
    },
    barClick: function (event) {
      if (this.dragMoved) {
        this.dragMoved = false
        return
      }
      this.$emit('select-event', event)
    },
    // Keeps whatever instant sits under pointerX pinned there across the zoom
    zoomBy: function (factor, pointerX = null) {
      const next = Math.min(
        Math.max(this.zoom * factor, this.MIN_ZOOM),
        this.MAX_ZOOM,
      )
      if (next === this.zoom) {
        return
      }
      const anchorX =
        pointerX === null
          ? LABEL_WIDTH + Math.max(this.viewportWidth - LABEL_WIDTH, 120) / 2
          : pointerX
      // Fraction of the track under the anchor before the zoom
      const trackX = this.scrollLeft + anchorX - LABEL_WIDTH
      const fraction = this.contentWidth > 0 ? trackX / this.contentWidth : 0

      this.zoom = next
      this.$nextTick(() => {
        // contentWidth has already grown/shrunk, so placing the same fraction
        // back under the anchor keeps that instant pinned under the pointer
        this.setScroll(fraction * this.contentWidth - anchorX + LABEL_WIDTH)
      })
    },
    resetZoom: function () {
      this.zoom = 1
      this.$nextTick(() => {
        this.setScroll(0)
      })
    },
    scrollToNow: function () {
      if (!this.nowInRange) {
        return
      }
      const fraction =
        (this.now.getTime() - this.range.start.getTime()) / this.span
      const trackVisible = Math.max(this.viewportWidth - LABEL_WIDTH, 120)
      // Centre the current time rather than pinning it to the left edge
      this.setScroll(fraction * this.contentWidth - trackVisible / 2)
    },
    setScroll: function (value) {
      const el = this.$refs.scroll
      if (!el) {
        return
      }
      const max = Math.max(this.innerWidth - this.viewportWidth, 0)
      const clamped = Math.min(Math.max(value, 0), max)
      el.scrollLeft = clamped
      this.scrollLeft = clamped
    },
    percent: function (time) {
      const offset = time - this.range.start.getTime()
      return `${(offset / this.span) * 100}%`
    },
    makeBar: function (event) {
      // Clip to the visible window so an activity running past either edge
      // still shows a bar rather than overflowing the track
      const start = event.start < this.range.start ? this.range.start : event.start
      const stop = event.stop > this.range.stop ? this.range.stop : event.stop
      const width = Math.max(
        ((stop.getTime() - start.getTime()) / this.span) * 100,
        0.05, // floor so a momentary activity is still clickable when zoomed out
      )
      return {
        key: `${event.type}-${event.start.getTime()}-${event.summary || ''}`,
        event,
        label: event.summary || event.typeStr,
        tooltip: `${format(event.start, 'yyyy-MM-dd HH:mm:ss')} – ${format(
          event.stop,
          'HH:mm:ss',
        )}  ${event.summary || event.typeStr}`,
        style: {
          left: this.percent(start.getTime()),
          width: `${width}%`,
          backgroundColor: event.color,
          // Pass windows sit behind the work scheduled inside them
          opacity: event.activity?.kind === 'reserve' ? 0.45 : 0.95,
          zIndex: event.activity?.kind === 'reserve' ? 1 : 2,
        },
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
.gantt-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 100%;
  /* The inner scroll area handles overflow, so the parent never gets a
     second set of scrollbars */
  overflow: hidden;
}
.zoom-bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  flex: 0 0 auto;
}
.zoom-level {
  font-size: 0.8rem;
  opacity: 0.85;
  min-width: 42px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.zoom-hint {
  font-size: 0.72rem;
  opacity: 0.5;
}
.gantt-scroll {
  flex: 1 1 auto;
  overflow-x: auto;
  overflow-y: auto;
  cursor: grab;
  /* Panning would otherwise select the row labels and tick text */
  user-select: none;
}
.gantt-scroll--dragging {
  cursor: grabbing;
}
.gantt-inner {
  position: relative;
}
.gantt-header {
  display: flex;
  position: sticky;
  top: 0;
  z-index: 10;
  background-color: var(--color-background-surface-default, #1f1f1f);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  height: 34px;
}
.header-label {
  font-size: 0.8rem;
  text-transform: uppercase;
  opacity: 0.7;
}
/* Sticky so the timeline names stay put while the chart pans */
.row-label {
  flex: 0 0 auto;
  width: 200px;
  position: sticky;
  left: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border-right: 1px solid rgba(255, 255, 255, 0.2);
  background-color: var(--color-background-surface-default, #1f1f1f);
  overflow: hidden;
}
.gantt-header .row-label {
  /* Above the axis ticks that scroll underneath it */
  z-index: 11;
}
.row-name {
  font-size: 0.95rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-count {
  margin-left: auto;
  font-size: 0.75rem;
  opacity: 0.6;
}
.row-swatch {
  flex: 0 0 auto;
  width: 12px;
  height: 12px;
  border-radius: 3px;
}
.gantt-track {
  position: relative;
  flex: 0 0 auto;
  min-height: 34px;
}
.gantt-row {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  min-height: 52px;
}
.tick {
  position: absolute;
  top: 0;
  bottom: 0;
  border-left: 1px solid rgba(255, 255, 255, 0.1);
}
.tick--major {
  border-left-color: rgba(255, 255, 255, 0.28);
}
.tick--grid {
  border-left-color: rgba(255, 255, 255, 0.05);
}
.tick--grid.tick--major {
  border-left-color: rgba(255, 255, 255, 0.14);
}
.tick-label {
  position: absolute;
  left: 5px;
  top: 9px;
  font-size: 0.75rem;
  opacity: 0.75;
  white-space: nowrap;
}
.now-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background-color: #ff5252;
  z-index: 3;
  pointer-events: none;
}
.bar {
  position: absolute;
  top: 9px;
  height: 34px;
  min-width: 4px;
  border-radius: 3px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #ffffff;
  font-size: 0.82rem;
  overflow: hidden;
  box-sizing: border-box;
}
.bar:hover {
  filter: brightness(1.25);
}
.bar-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bar-status {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
.bar-status--normal {
  background-color: #4caf50;
}
.bar-status--standby {
  background-color: #2196f3;
}
.bar-status--caution {
  background-color: #ffc107;
}
.bar-status--serious {
  background-color: #f44336;
}
.bar-status--off {
  background-color: rgba(255, 255, 255, 0.5);
}
.empty-hint {
  padding: 20px;
  font-size: 0.9rem;
  opacity: 0.6;
}
</style>
