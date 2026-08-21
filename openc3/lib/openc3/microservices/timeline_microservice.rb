# encoding: ascii-8bit

# Copyright 2026 OpenC3, Inc.
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

require 'openc3/microservices/microservice'
require 'openc3/topics/timeline_topic'
require 'openc3/models/timeline_model'
require 'openc3/models/activity_model'
require 'openc3/models/script_status_model'
require 'openc3/script/script'
require 'openc3/utilities/authentication'
require 'openc3/utilities/thread_manager'
require 'openc3/api/api'

module OpenC3
  # Executes activities handed to it on a queue. Kept separate from the scheduling
  # so a long running script can never delay the dispatch of the next activity.
  class TimelineWorker
    # NOTE: Api provides cmd() directly rather than proxying it over HTTP the way
    # OpenC3::Script does. Scripts are launched through an explicit
    # ScriptServerProxy below so that including Script - and taking its HTTP
    # flavored cmd() with it - is not necessary.
    include Api

    # Terminal script states mapped to whether the activity was fulfilled
    SCRIPT_SUCCESS_STATES = %w(completed).freeze
    SCRIPT_FAILURE_STATES = %w(completed_errors error crashed stopped killed).freeze

    # How long to wait for a launched script to reach a terminal state before
    # giving up on tracking it. The script itself keeps running - we just stop
    # updating the activity.
    SCRIPT_TIMEOUT_SECONDS = 86_400

    def initialize(name:, logger:, scope:, queue:)
      @timeline_name = name
      @logger = logger
      @scope = scope
      @queue = queue
      @cancel_thread = false
      @script_api = nil
    end

    # Lazily built so constructing a worker never requires the script runner to
    # be reachable - only actually running a script does.
    def script_api
      @script_api ||= ScriptServerProxy.new
    end

    def run
      @logger.info "TimelineWorker running for timeline #{@timeline_name}"
      until @cancel_thread
        begin
          activity = @queue.pop
          break if activity.nil? # nil is the shutdown signal
          run_activity(activity)
        rescue StandardError => e
          @logger.error "TimelineWorker failed to run activity on #{@timeline_name}\n#{e.formatted}"
        end
      end
      @logger.info "TimelineWorker exiting for timeline #{@timeline_name}"
    end

    # Dispatch on the activity kind. See ActivityModel::VALID_KINDS.
    def run_activity(activity)
      # A timeline can be switched off without deleting it. Its activities still
      # occupy the calendar, they just don't execute.
      unless timeline_executes?
        @logger.info "TimelineWorker skipping activity at #{activity.start}, timeline #{@timeline_name} is not executing"
        activity.commit(status: 'disabled', message: 'timeline execution is disabled', fulfillment: false)
        return
      end

      case activity.kind
      when 'command'
        run_command(activity)
      when 'script'
        run_script(activity)
      when 'reserve'
        # Reserve blocks time on the calendar but has nothing to execute, so it
        # is fulfilled the moment its start time arrives. This is also the kind
        # used for satellite pass windows.
        activity.commit(status: 'completed', message: 'reserved time elapsed', fulfillment: true)
      when 'expire'
        # An internal bookkeeping marker, exempt from the normal start time and
        # duration validation. This microservice never creates them, so one only
        # shows up in data written elsewhere - acknowledge it rather than
        # reporting a failure the operator can do nothing about.
        activity.commit(status: 'completed', message: 'expired', fulfillment: true)
      else
        @logger.error "TimelineWorker unknown activity kind #{activity.kind} on #{@timeline_name}"
        activity.commit(status: 'failed', message: "unknown activity kind: #{activity.kind}", fulfillment: false)
      end
    end

    # Read fresh each time rather than caching, so toggling execute on the
    # timeline takes effect on the very next activity.
    def timeline_executes?
      timeline = TimelineModel.get(name: @timeline_name, scope: @scope)
      return true if timeline.nil? # Fail open - a missing timeline model shouldn't silently stop ops
      return timeline.execute
    rescue StandardError => e
      @logger.error "TimelineWorker failed to read timeline #{@timeline_name}, assuming it executes\n#{e.message}"
      return true
    end

    def run_command(activity)
      command = activity.data['command']
      if command.nil? or command.empty?
        activity.commit(status: 'failed', message: 'no command given', fulfillment: false)
        return
      end
      activity.commit(status: 'started', message: command)
      begin
        message = command
        begin
          cmd(command, scope: @scope)
        rescue HazardousError => e
          # There is nobody to prompt at execution time. Scheduling the activity
          # is the operator's approval, so the command is resent with the check
          # bypassed - but it is logged and recorded on the activity so the
          # approval is auditable after the fact.
          @logger.warn "TimelineWorker sending hazardous command #{command} for #{@timeline_name}: #{e.hazardous_description}"
          cmd_no_hazardous_check(command, scope: @scope)
          message = "#{command} (hazardous, approved by scheduling)"
        end
        @logger.info "TimelineWorker sent command #{command} for #{@timeline_name}"
        activity.commit(status: 'completed', message: message, fulfillment: true)
      rescue StandardError => e
        @logger.error "TimelineWorker failed to send command #{command} for #{@timeline_name}\n#{e.message}"
        activity.commit(status: 'failed', message: e.message, fulfillment: false)
      end
    end

    def run_script(activity)
      filename = activity.data['script']
      if filename.nil? or filename.empty?
        activity.commit(status: 'failed', message: 'no script given', fulfillment: false)
        return
      end

      begin
        script_id = start_script(filename, activity)
      rescue StandardError => e
        @logger.error "TimelineWorker failed to start script #{filename} for #{@timeline_name}\n#{e.message}"
        activity.commit(status: 'failed', message: e.message, fulfillment: false)
        return
      end

      @logger.info "TimelineWorker started script #{filename} (id #{script_id}) for #{@timeline_name}"
      activity.commit(status: 'started', message: "#{filename} started as script #{script_id}")
      monitor_script(activity, filename, script_id)
    end

    # POST the run request to the script runner api and return the new script id.
    # Mirrors OpenC3::Script#script_run without pulling in the Script module.
    def start_script(filename, activity)
      # The script gets the activity identifiers in its environment so it can
      # report progress back against the activity that launched it.
      env_data = []
      Array(activity.data['environment']).each do |env|
        env_data << { 'key' => env['key'], 'value' => env['value'] } if env['key']
      end
      env_data << { 'key' => 'OPENC3_TIMELINE_NAME', 'value' => @timeline_name }
      env_data << { 'key' => 'OPENC3_ACTIVITY_START', 'value' => activity.start.to_s }
      env_data << { 'key' => 'OPENC3_ACTIVITY_UUID', 'value' => activity.uuid.to_s }

      response = script_api.request(
        'post',
        "/script-api/scripts/#{filename}/run",
        json: true,
        data: { environment: env_data },
        scope: @scope
      )
      if response.nil?
        raise "No response starting script #{filename}"
      elsif response.status != 200
        raise "Failed to start #{filename} (#{response.status}): #{response.body}"
      end
      return Integer(response.body)
    end

    # Poll the script status until it reaches a terminal state so the activity
    # reflects what actually happened rather than just that it was launched.
    def monitor_script(activity, filename, script_id)
      last_state = nil
      give_up_at = Time.now.to_f + SCRIPT_TIMEOUT_SECONDS
      until @cancel_thread
        sleep(1)
        return if @cancel_thread
        if Time.now.to_f > give_up_at
          activity.commit(status: 'failed', message: "stopped tracking #{filename} after #{SCRIPT_TIMEOUT_SECONDS}s", fulfillment: false)
          return
        end

        status = ScriptStatusModel.get(name: script_id.to_s, scope: @scope)
        next if status.nil?

        state = status['state']
        next if state == last_state
        last_state = state

        if SCRIPT_SUCCESS_STATES.include?(state)
          activity.commit(status: 'completed', message: "#{filename} #{state}", fulfillment: true)
          return
        elsif SCRIPT_FAILURE_STATES.include?(state)
          message = "#{filename} #{state}"
          errors = status['errors']
          message += ": #{errors}" if errors and !errors.to_s.empty?
          activity.commit(status: 'failed', message: message, fulfillment: false)
          return
        else
          # Intermediate states (running, paused, waiting, breakpoint) are recorded
          # so the calendar can show live progress.
          activity.commit(status: state, message: filename)
        end
      end
    end

    def shutdown
      @cancel_thread = true
      @queue << nil
      @script_api.shutdown if @script_api
    end
  end

  # Holds the activities for the near future in memory and pushes them onto the
  # worker queue as their start times arrive.
  #
  # Activities are read from Redis rather than trusted from the topic alone, so a
  # microservice that restarts or misses a notification still recovers the full
  # schedule on its next refresh.
  class TimelineScheduler
    # ActivityModel.activities returns START_GRACE_SECONDS in the past through an
    # hour ahead. Refreshing well inside that hour keeps the schedule from going
    # stale between notifications.
    REFRESH_SECONDS = 60

    # How far past its start time an activity may still be run. An activity older
    # than this was missed (the microservice was down) and is marked as such
    # rather than fired late. Matches ActivityModel::START_GRACE_SECONDS.
    GRACE_SECONDS = ActivityModel::START_GRACE_SECONDS

    attr_reader :schedule

    def initialize(name:, logger:, scope:, queue:)
      @timeline_name = name
      @logger = logger
      @scope = scope
      @queue = queue
      @cancel_thread = false
      @mutex = Mutex.new
      # key => activity, for everything in the current window that has not fired
      @schedule = {}
      # keys already dispatched, so a refresh can never fire the same activity twice
      @dispatched = {}
      @last_refresh = 0.0
    end

    # Uniquely identifies an occurrence. A recurring activity shares a uuid across
    # occurrences, so the start time has to be part of the key.
    def self.key(activity)
      "#{activity.start}__#{activity.uuid}"
    end

    def run
      @logger.info "TimelineScheduler running for timeline #{@timeline_name}"
      refresh()
      until @cancel_thread
        begin
          refresh() if Time.now.to_f - @last_refresh >= REFRESH_SECONDS
          dispatch_due()
        rescue StandardError => e
          @logger.error "TimelineScheduler error on #{@timeline_name}\n#{e.formatted}"
        end
        # Tick once a second. Activities are scheduled to the second, so this is
        # as fine grained as the data model needs.
        sleep(1)
      end
      @logger.info "TimelineScheduler exiting for timeline #{@timeline_name}"
    end

    # Reload the upcoming window from Redis, preserving what has already fired.
    def refresh
      activities = ActivityModel.activities(name: @timeline_name, scope: @scope)
      @mutex.synchronize do
        @schedule = {}
        activities.each do |activity|
          key = self.class.key(activity)
          next if @dispatched.key?(key)
          @schedule[key] = activity
        end
        # Forget dispatched keys that have fallen out of the window so the hash
        # does not grow without bound.
        cutoff = Time.now.to_i - 3600
        @dispatched.delete_if { |_key, start| start < cutoff }
      end
      @last_refresh = Time.now.to_f
    end

    # Push every activity whose start time has arrived onto the worker queue.
    def dispatch_due
      now = Time.now.to_i
      due = []
      @mutex.synchronize do
        @schedule.each do |key, activity|
          next if activity.start > now
          due << [key, activity]
        end
        due.each do |key, activity|
          @schedule.delete(key)
          @dispatched[key] = activity.start
        end
      end

      due.each do |_key, activity|
        if now - activity.start > GRACE_SECONDS
          @logger.warn "TimelineScheduler missed activity at #{activity.start} on #{@timeline_name}"
          begin
            activity.commit(status: 'failed', message: 'missed activity start time', fulfillment: false)
          rescue StandardError => e
            @logger.error "TimelineScheduler failed to mark missed activity on #{@timeline_name}\n#{e.message}"
          end
          next
        end
        @queue << activity
      end
    end

    # Called when a topic notification says this timeline changed. Reloading from
    # Redis is cheap and avoids having to reconcile every notification kind.
    def request_update
      refresh()
    rescue StandardError => e
      @logger.error "TimelineScheduler failed to update #{@timeline_name}\n#{e.message}"
    end

    def shutdown
      @cancel_thread = true
    end
  end

  # One microservice per timeline. Deployed by TimelineModel#deploy.
  class TimelineMicroservice < Microservice
    attr_reader :timeline_name, :scheduler, :worker

    def initialize(*args)
      super(*args)
      # Name is SCOPE__TIMELINE__NAME
      @timeline_name = @name.split('__')[2]
      @queue = Queue.new
      @scheduler = TimelineScheduler.new(name: @timeline_name, logger: @logger, scope: @scope, queue: @queue)
      @worker = TimelineWorker.new(name: @timeline_name, logger: @logger, scope: @scope, queue: @queue)
      @scheduler_thread = nil
      @worker_thread = nil
      @read_topic = true
      @logger.info "TimelineMicroservice initialized for timeline #{@timeline_name} in scope #{@scope}"
    end

    def run
      @logger.info "TimelineMicroservice running for #{@timeline_name}"
      @scheduler_thread = Thread.new { @scheduler.run }
      @worker_thread = Thread.new { @worker.run }
      ThreadManager.instance.register(@scheduler_thread)
      ThreadManager.instance.register(@worker_thread)

      loop do
        break if @cancel_thread
        block_for_updates()
      end

      @scheduler.shutdown()
      @worker.shutdown()
      @scheduler_thread.join() if @scheduler_thread
      @worker_thread.join() if @worker_thread
      @logger.info "TimelineMicroservice exiting for #{@timeline_name}"
    end

    # Watch the timeline topic for activity changes on this timeline.
    def block_for_updates
      @read_topic = true
      while @read_topic && !@cancel_thread
        begin
          TimelineTopic.read_topics(@topics) do |_topic, _msg_id, msg_hash, _redis|
            next unless msg_hash['timeline'] == @timeline_name
            @count += 1
            case msg_hash['type']
            when 'activity'
              @scheduler.request_update()
            when 'timeline'
              # The timeline itself changed (color, execute flag). Nothing to
              # reschedule, but pick up the new settings on the next activity.
              @logger.debug "TimelineMicroservice #{@timeline_name} #{msg_hash['kind']}"
            end
          end
        rescue StandardError => e
          @logger.error "TimelineMicroservice failed to read topics #{@topics}\n#{e.formatted}"
        end
      end
    end

    def shutdown
      @read_topic = false
      @scheduler.shutdown() if @scheduler
      @worker.shutdown() if @worker
      super
    end
  end
end

if __FILE__ == $0
  OpenC3::TimelineMicroservice.run
  OpenC3::ThreadManager.instance.shutdown
  OpenC3::ThreadManager.instance.join
end
