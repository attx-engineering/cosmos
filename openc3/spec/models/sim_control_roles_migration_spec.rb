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
require 'openc3/models/role_model'
require 'openc3/models/scope_model'

module OpenC3
  describe 'the SimControlRoles migration' do
    let(:scope) { 'DEFAULT' }

    before(:each) do
      mock_redis()
      # Loaded without running: the migration runs here, against the roles each example makes.
      ENV['OPENC3_NO_MIGRATE'] = '1'
      require 'openc3/migrations/20261026000000_sim_control_roles'
      ENV.delete('OPENC3_NO_MIGRATE')
      allow(ScopeModel).to receive(:names).and_return([scope])
    end

    def role(name, **fields)
      RoleModel.new(name: name, scope: scope, **fields).create
    end

    def kept(name)
      RoleModel.get(name: name, scope: scope)
    end

    it 'names SIM_CONTROL wherever a role named SIM, every other choice kept' do
      role('operator', builtin: true, permissions: %w(cmd tlm), targets: 'ALL', excluded_targets: ['SIM'],
           tools: 'ALL', excluded_tools: ['simcontrol'])
      role('sim_only', permissions: %w(cmd), targets: ['SIM', 'INST'])
      role('both', permissions: %w(tlm), targets: ['SIM', 'SIM_CONTROL'], excluded_targets: ['SIM', 'INST2'])
      role('plain', permissions: %w(tlm), targets: ['INST'], excluded_targets: ['INST2'])

      SimControlRoles.run

      expect(kept('operator').excluded_targets).to eql ['SIM_CONTROL']
      expect(kept('operator').excluded_tools).to eql ['simcontrol']
      expect(kept('operator').builtin).to be true
      expect(kept('operator').allow?(permission: 'cmd', target_name: 'SIM_CONTROL')).to be false
      expect(kept('sim_only').targets).to eql ['SIM_CONTROL', 'INST']
      expect(kept('both').targets).to eql ['SIM_CONTROL']
      expect(kept('both').excluded_targets).to eql ['SIM_CONTROL', 'INST2']
      expect(kept('plain').targets).to eql ['INST']
      expect(kept('plain').excluded_targets).to eql ['INST2']
    end

    it 'leaves a role naming no SIM as it was, run again or not' do
      role('plain', permissions: %w(tlm), targets: ['INST'])
      before = kept('plain').as_json['updated_at']
      SimControlRoles.run
      SimControlRoles.run
      expect(kept('plain').as_json['updated_at']).to eql before
    end
  end
end
