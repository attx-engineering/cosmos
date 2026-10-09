# encoding: ascii-8bit

# Copyright 2023 OpenC3, Inc.
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

# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.

require 'date'
require 'time' # Time.parse, for pass times given as strings

module OpenC3
  module Script

    private

    def list_timelines(scope: $openc3_scope)
      response = $api_server.request('get', "/openc3-api/timeline", scope: scope)
      return _cal_handle_response(response, 'Failed to list timelines')
    end

    def create_timeline(name, color: nil, scope: $openc3_scope)
      data = {}
      data['name'] = name
      data['color'] = color if color
      response = $api_server.request('post', "/openc3-api/timeline", data: data, json: true, scope: scope)
      return _cal_handle_response(response, 'Failed to create timeline')
    end

    def get_timeline(name, scope: $openc3_scope)
      response = $api_server.request('get', "/openc3-api/timeline/#{name}", scope: scope)
      return _cal_handle_response(response, 'Failed to get timeline')
    end

    def set_timeline_color(name, color, scope: $openc3_scope)
      post_data = {}
      post_data['color'] = color
      response = $api_server.request('post', "/openc3-api/timeline/#{name}/color", data: post_data, json: true, scope: scope)
      return _cal_handle_response(response, 'Failed to set timeline color')
    end

    def delete_timeline(name, force: false, scope: $openc3_scope)
      url = "/openc3-api/timeline/#{name}"
      if force
        url += "?force=true"
      end
      response = $api_server.request('delete', url, scope: scope)
      return _cal_handle_response(response, 'Failed to delete timeline')
    end

    def create_timeline_activity(name, kind:, start:, stop:, data: {}, scope: $openc3_scope)
      kind = kind.to_s.downcase()
      kinds = %w(command script reserve)
      unless kinds.include?(kind)
        raise "Unknown kind: #{kind}. Must be one of #{kinds.join(', ')}."
      end
      post_data = {}
      post_data['start'] = start.to_datetime.iso8601
      post_data['stop'] = stop.to_datetime.iso8601
      post_data['kind'] = kind
      post_data['data'] = data
      response = $api_server.request('post', "/openc3-api/timeline/#{name}/activities", data: post_data, json: true, scope: scope)
      return _cal_handle_response(response, 'Failed to create timeline activity')
    end

    def get_timeline_activity(name, start, uuid, scope: $openc3_scope)
      response = $api_server.request('get', "/openc3-api/timeline/#{name}/activity/#{start}/#{uuid}", scope: scope)
      return _cal_handle_response(response, 'Failed to get timeline activity')
    end

    def get_timeline_activities(name, start: nil, stop: nil, limit: nil, scope: $openc3_scope)
      url = "/openc3-api/timeline/#{name}/activities"
      if start and stop
        url += "?start=#{start}&stop=#{stop}"
      end
      if limit
        url += "?limit=#{limit}"
      end
      response = $api_server.request('get', url, scope: scope)
      return _cal_handle_response(response, 'Failed to get timeline activities')
    end

    def delete_timeline_activity(name, start, uuid, scope: $openc3_scope)
      response = $api_server.request('delete', "/openc3-api/timeline/#{name}/activity/#{start}/#{uuid}", scope: scope)
      return _cal_handle_response(response, 'Failed to delete timeline activity')
    end

    # Publish satellite pass windows onto a timeline as 'reserve' activities.
    #
    # A reserve activity occupies time on the calendar without executing
    # anything, which is exactly what a pass window is: it shows when the
    # spacecraft is visible so commands and scripts can be scheduled inside it.
    #
    # @param passes [Array<Hash>] each entry needs a start and a stop, given as
    #   a Time, a DateTime, an ISO 8601 String, or epoch seconds. Any other keys
    #   (satellite, ground_station, max_elevation, ...) are stored on the
    #   activity and shown in the calendar.
    # @param timeline [String] timeline to publish onto, created if missing
    # @param color [String] color for the timeline when it has to be created
    # @param replace [Boolean] remove existing reserve activities that fall in
    #   the range being published before adding the new ones, so re-running
    #   against updated propagation replaces passes rather than duplicating them
    # @return [Hash] counts of what happened, with the skipped passes listed
    def create_pass_activities(passes, timeline: 'PASSES', color: '#8E24AA', replace: true, scope: $openc3_scope)
      normalized = passes.map do |pass|
        pass = pass.transform_keys(&:to_s)
        start = _cal_to_time(pass.delete('start'))
        stop = _cal_to_time(pass.delete('stop'))
        raise "Pass requires both a start and a stop: #{pass}" if start.nil? or stop.nil?
        raise "Pass start #{start} is not before stop #{stop}" if start >= stop
        { 'start' => start, 'stop' => stop, 'data' => pass }
      end
      return { 'created' => 0, 'deleted' => 0, 'skipped' => [] } if normalized.empty?

      # Create the timeline on first use so callers don't have to
      unless list_timelines(scope: scope).any? { |t| t['name'] == timeline }
        create_timeline(timeline, color: color, scope: scope)
      end

      normalized.sort_by! { |pass| pass['start'] }
      range_start = normalized.first['start']
      range_stop = normalized.last['stop']

      deleted = 0
      if replace
        existing = get_timeline_activities(timeline, start: range_start.to_datetime.iso8601,
                                           stop: range_stop.to_datetime.iso8601, scope: scope)
        existing.each do |activity|
          # Only clear passes - a command or script scheduled inside a pass
          # window belongs to the operator, not to the propagation run.
          next unless activity['kind'] == 'reserve'
          delete_timeline_activity(timeline, activity['start'], activity['uuid'], scope: scope)
          deleted += 1
        end
      end

      created = 0
      skipped = []
      now = Time.now
      normalized.each do |pass|
        # Activities cannot be created in the past, so a pass already underway
        # is reported rather than raising and abandoning the rest of the set.
        if pass['start'] <= now
          skipped << { 'start' => pass['start'], 'stop' => pass['stop'], 'reason' => 'already started' }
          next
        end
        create_timeline_activity(timeline, kind: 'reserve', start: pass['start'], stop: pass['stop'],
                                 data: pass['data'], scope: scope)
        created += 1
      end
      return { 'created' => created, 'deleted' => deleted, 'skipped' => skipped }
    end

    # Accepts the several shapes a pass time can arrive in from a propagator
    def _cal_to_time(value)
      return nil if value.nil?
      case value
      when Time then value
      when DateTime, Date then value.to_time
      when Numeric then Time.at(value)
      when String then Time.parse(value)
      else
        raise "Cannot interpret #{value.inspect} as a time"
      end
    end

    # Helper method to handle the response
    def _cal_handle_response(response, error_message)
      return nil if response.nil?
      if response.status >= 400
        result = JSON.parse(response.body, allow_nan: true, create_additions: true)
        raise "#{error_message} due to #{result['message']}"
      end
      return JSON.parse(response.body, allow_nan: true, create_additions: true)
    end
  end
end
