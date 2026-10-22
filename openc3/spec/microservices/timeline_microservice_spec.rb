# encoding: ascii-8bit

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

require 'spec_helper'
require 'openc3/microservices/timeline_microservice'
require 'openc3/models/timeline_model'
require 'openc3/models/activity_model'

module OpenC3
  describe TimelineWorker do
    let(:timeline_name) { 'TEST_TIMELINE' }
    let(:scope) { 'DEFAULT' }
    # Ruby's own logger, into a string the tests can read. Inside module OpenC3,
    # a bare Logger is OpenC3::Logger, whose argument is a level, not a device.
    let(:log) { StringIO.new }
    let(:logger) { ::Logger.new(log) }
    let(:queue) { Queue.new }
    let(:worker) { TimelineWorker.new(name: timeline_name, logger: logger, scope: scope, queue: queue) }

    before(:each) do
      mock_redis()
      TimelineModel.new(name: timeline_name, scope: scope, color: '#FF0000').create
    end

    def build_activity(kind:, data: {}, start: nil)
      start ||= Time.now.to_i + 3600
      ActivityModel.new(
        name: timeline_name,
        scope: scope,
        start: start,
        stop: start + 60,
        kind: kind,
        data: data
      ).tap(&:create)
    end

    describe '#run_activity' do
      it 'fulfills a reserve activity without executing anything' do
        activity = build_activity(kind: 'reserve')
        worker.run_activity(activity)
        expect(activity.fulfillment).to be true
        expect(activity.events.last['event']).to eq('completed')
      end

      it 'sends the command for a command activity' do
        activity = build_activity(kind: 'command', data: { 'command' => 'INST ABORT' })
        expect(worker).to receive(:cmd).with('INST ABORT', scope: scope)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be true
        expect(activity.events.map { |e| e['event'] }).to include('started', 'completed')
      end

      it 'records a failed command rather than dropping it' do
        activity = build_activity(kind: 'command', data: { 'command' => 'INST ABORT' })
        allow(worker).to receive(:cmd).and_raise('interface disconnected')
        worker.run_activity(activity)
        expect(activity.fulfillment).to be false
        expect(activity.events.last['event']).to eq('failed')
        expect(activity.events.last['message']).to eq('interface disconnected')
      end

      def hazardous
        HazardousError.new.tap { |error| error.hazardous_description = 'will vent propellant' }
      end

      def approval(command)
        { 'by' => 'operator', 'at' => '2031-04-16T01:02:00Z', 'command' => command }
      end

      it 'refuses a hazardous command that was not approved when it was scheduled' do
        activity = build_activity(kind: 'command', data: { 'command' => 'INST VENT' })
        expect(worker).to receive(:cmd).with('INST VENT', scope: scope).and_raise(hazardous)
        expect(worker).to_not receive(:cmd_no_hazardous_check)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be false
        expect(activity.events.last['event']).to eq('failed')
        expect(activity.events.last['message']).to eq('hazardous command not approved when it was scheduled: will vent propellant')
        expect(log.string).to include('refused hazardous command INST VENT')
      end

      it 'sends an approved hazardous command with the check bypassed, and records who approved it' do
        activity = build_activity(kind: 'command', data: { 'command' => 'INST VENT', 'hazardous_approval' => approval('INST VENT') })
        expect(worker).to receive(:cmd).with('INST VENT', scope: scope).and_raise(hazardous)
        expect(worker).to receive(:cmd_no_hazardous_check).with('INST VENT', scope: scope)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be true
        expect(activity.events.last['event']).to eq('completed')
        expect(activity.events.last['message']).to eq('INST VENT (hazardous, approved by operator at 2031-04-16T01:02:00Z)')
      end

      it 'refuses a hazardous command whose approval names another command' do
        activity = build_activity(kind: 'command', data: {
          'command' => 'INST VENT with AMOUNT 100',
          'hazardous_approval' => approval('INST VENT with AMOUNT 1'),
        })
        expect(worker).to receive(:cmd).and_raise(hazardous)
        expect(worker).to_not receive(:cmd_no_hazardous_check)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be false
        expect(activity.events.last['message']).to start_with('hazardous command not approved')
      end

      it 'refuses a hazardous command whose approval is not a record of one' do
        activity = build_activity(kind: 'command', data: { 'command' => 'INST VENT', 'hazardous_approval' => true })
        expect(worker).to receive(:cmd).and_raise(hazardous)
        expect(worker).to_not receive(:cmd_no_hazardous_check)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be false
        expect(activity.events.last['event']).to eq('failed')
        expect(activity.events.last['message']).to start_with('hazardous command not approved')
      end

      it 'sends an approved command that is not hazardous with the check in place' do
        activity = build_activity(kind: 'command', data: { 'command' => 'INST ABORT', 'hazardous_approval' => approval('INST ABORT') })
        expect(worker).to receive(:cmd).with('INST ABORT', scope: scope)
        expect(worker).to_not receive(:cmd_no_hazardous_check)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be true
        expect(activity.events.last['message']).to eq('INST ABORT')
      end

      it 'fails a command activity that carries no command' do
        activity = build_activity(kind: 'command', data: {})
        expect(worker).to_not receive(:cmd)
        worker.run_activity(activity)
        expect(activity.events.last['event']).to eq('failed')
      end

      it 'fails a script activity that carries no script' do
        activity = build_activity(kind: 'script', data: {})
        worker.run_activity(activity)
        expect(activity.events.last['event']).to eq('failed')
      end

      it 'does not execute activities on a timeline with execution disabled' do
        timeline = TimelineModel.get(name: timeline_name, scope: scope)
        timeline.execute = false
        timeline.update
        activity = build_activity(kind: 'command', data: { 'command' => 'INST ABORT' })
        expect(worker).to_not receive(:cmd)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be false
        expect(activity.events.last['event']).to eq('disabled')
      end
    end
  end

  describe TimelineScheduler do
    let(:timeline_name) { 'TEST_TIMELINE' }
    let(:scope) { 'DEFAULT' }
    let(:logger) { ::Logger.new(StringIO.new) }
    let(:queue) { Queue.new }
    let(:scheduler) { TimelineScheduler.new(name: timeline_name, logger: logger, scope: scope, queue: queue) }

    before(:each) do
      mock_redis()
      TimelineModel.new(name: timeline_name, scope: scope, color: '#FF0000').create
    end

    # Builds a model directly rather than through create(), so nothing is stored.
    # ActivityModel refuses a start more than START_GRACE_SECONDS in the past even
    # here, so a later time is made by moving the clock, not the activity.
    def activity_at(offset, uuid: SecureRandom.uuid)
      start = Time.now.to_i + offset
      ActivityModel.new(
        name: timeline_name,
        scope: scope,
        start: start,
        stop: start + 60,
        kind: 'reserve',
        data: {},
        uuid: uuid
      )
    end

    describe '#dispatch_due' do
      it 'queues an activity whose start time has arrived' do
        due = activity_at(-1)
        future = activity_at(600)
        allow(ActivityModel).to receive(:activities).and_return([due, future])
        scheduler.refresh
        scheduler.dispatch_due
        expect(queue.size).to eq(1)
        expect(queue.pop.uuid).to eq(due.uuid)
      end

      it 'leaves future activities on the schedule' do
        allow(ActivityModel).to receive(:activities).and_return([activity_at(600)])
        scheduler.refresh
        scheduler.dispatch_due
        expect(queue.size).to eq(0)
        expect(scheduler.schedule.size).to eq(1)
      end

      it 'never dispatches the same activity twice across refreshes' do
        due = activity_at(-1)
        allow(ActivityModel).to receive(:activities).and_return([due])
        scheduler.refresh
        scheduler.dispatch_due
        scheduler.refresh
        scheduler.dispatch_due
        expect(queue.size).to eq(1)
      end

      it 'dispatches every occurrence of a recurring activity' do
        # Recurring occurrences share a uuid and differ only by start time
        uuid = SecureRandom.uuid
        allow(ActivityModel).to receive(:activities)
          .and_return([activity_at(-2, uuid: uuid), activity_at(-1, uuid: uuid)])
        scheduler.refresh
        scheduler.dispatch_due
        expect(queue.size).to eq(2)
      end

      it 'marks an activity missed when it is dispatched past its grace window' do
        missed = activity_at(1)
        allow(ActivityModel).to receive(:activities).and_return([missed])
        allow(missed).to receive(:commit)
        scheduler.refresh
        later = Time.at(missed.start + TimelineScheduler::GRACE_SECONDS + 1)
        allow(Time).to receive(:now).and_return(later)
        scheduler.dispatch_due
        expect(queue.size).to eq(0)
        expect(missed).to have_received(:commit)
          .with(hash_including(status: 'failed', fulfillment: false))
      end

      it 'still runs an activity that is late but inside the grace window' do
        late = activity_at(-(ActivityModel::START_GRACE_SECONDS - 5))
        allow(ActivityModel).to receive(:activities).and_return([late])
        scheduler.refresh
        scheduler.dispatch_due
        expect(queue.size).to eq(1)
      end
    end
  end
end
