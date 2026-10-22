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
require 'openc3'
require 'openc3/script'
require 'openc3/script/calendar'

module OpenC3
  describe Script do
    # Records each request, and answers every one as created.
    class CalendarSpecApi
      attr_reader :requests

      def initialize
        @requests = []
      end

      def shutdown
      end

      def disconnect
      end

      def generate_url
        return "http://localhost:2900"
      end

      def request(method, endpoint, **options)
        @requests << [method, endpoint, options]
        OpenStruct.new(status: 201, body: '{"kind":"command"}')
      end
    end

    before(:each) do
      mock_redis()
      setup_system()
      @api = CalendarSpecApi.new
      allow(ServerProxy).to receive(:new).and_return(@api)
      initialize_script()
    end

    after(:each) do
      shutdown_script()
    end

    describe "create_timeline_activity" do
      let(:start) { Time.now + 3600 }

      it "asks the server to approve a hazardous command when told to" do
        create_timeline_activity("TL", kind: "COMMAND", start: start, stop: start + 60,
          data: {"command" => "INST VENT"}, approve_hazardous: true)
        method, endpoint, options = @api.requests.last
        expect([method, endpoint]).to eql(["post", "/openc3-api/timeline/TL/activities"])
        expect(options[:data]["approve_hazardous"]).to be true
        expect(options[:data]["data"]).to eql({"command" => "INST VENT"})
      end

      it "never asks for an approval unless told to" do
        create_timeline_activity("TL", kind: "COMMAND", start: start, stop: start + 60, data: {"command" => "INST VENT"})
        expect(@api.requests.last[2][:data]).not_to have_key("approve_hazardous")
      end

      it "refuses approve_hazardous on an activity that is not a command" do
        expect {
          create_timeline_activity("TL", kind: "SCRIPT", start: start, stop: start + 60,
            data: {"script" => "INST/procedures/vent.rb"}, approve_hazardous: true)
        }.to raise_error(RuntimeError, "approve_hazardous is only for a command activity")
        expect(@api.requests).to be_empty
      end
    end
  end
end
