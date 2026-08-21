# encoding: ascii-8bit

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

require 'spec_helper'
require 'openc3/microservices/timeline_microservice'
require 'openc3/models/timeline_model'
require 'openc3/models/activity_model'

module OpenC3
  describe TimelineWorker do
    let(:timeline_name) { 'TEST_TIMELINE' }
    let(:scope) { 'DEFAULT' }
    let(:logger) { Logger.new(STDOUT) }
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

      it 'resends a hazardous command with the check bypassed and records the approval' do
        activity = build_activity(kind: 'command', data: { 'command' => 'INST VENT' })
        error = HazardousError.new
        error.hazardous_description = 'will vent propellant'
        expect(worker).to receive(:cmd).with('INST VENT', scope: scope).and_raise(error)
        expect(worker).to receive(:cmd_no_hazardous_check).with('INST VENT', scope: scope)
        worker.run_activity(activity)
        expect(activity.fulfillment).to be true
        expect(activity.events.last['event']).to eq('completed')
        expect(activity.events.last['message']).to include('hazardous')
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
    let(:logger) { Logger.new(STDOUT) }
    let(:queue) { Queue.new }
    let(:scheduler) { TimelineScheduler.new(name: timeline_name, logger: logger, scope: scope, queue: queue) }

    before(:each) do
      mock_redis()
      TimelineModel.new(name: timeline_name, scope: scope, color: '#FF0000').create
    end

    # Builds a model directly rather than through create() so activities can be
    # placed in the past, which ActivityModel deliberately refuses to store.
    def activity_at(offset, uuid: SecureRandom.uuid)
      start = Time.now.to_i + offset
      ActivityModel.new(
        name: timeline_name,
        scope: scope,
        start: start,
        stop: start + 60,
        kind: 'reserve',
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

      it 'marks an activity missed while the microservice was down' do
        missed = activity_at(-600)
        allow(ActivityModel).to receive(:activities).and_return([missed])
        allow(missed).to receive(:commit)
        scheduler.refresh
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
