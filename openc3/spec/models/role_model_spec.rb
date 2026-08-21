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
require 'openc3/models/role_model'

module OpenC3
  describe RoleModel do
    let(:scope) { 'DEFAULT' }

    before(:each) do
      mock_redis()
    end

    def built_in(name)
      RoleModel.new(name: name, scope: scope, builtin: true,
                    **RoleModel::BUILT_IN[name].transform_keys(&:to_sym))
    end

    describe 'admin' do
      it 'grants every permission on every target' do
        admin = built_in('admin')
        RoleModel::PERMISSIONS.each do |permission|
          expect(admin.allow?(permission: permission, target_name: 'SAT1')).to be true
        end
        expect(admin.allow?(permission: 'cmd', target_name: 'SIM')).to be true
        expect(admin.allow_tool?('simcontrol')).to be true
      end
    end

    describe 'operator' do
      let(:operator) { built_in('operator') }

      it 'commands flight targets' do
        expect(operator.allow?(permission: 'cmd', target_name: 'SAT1')).to be true
        expect(operator.allow?(permission: 'cmd_raw', target_name: 'SAT1')).to be true
        expect(operator.allow?(permission: 'script_run')).to be true
      end

      # The defining requirement for this role
      it 'cannot command the simulation target' do
        expect(operator.allow?(permission: 'cmd', target_name: 'SIM')).to be false
        expect(operator.allow?(permission: 'cmd_raw', target_name: 'SIM')).to be false
      end

      it 'excludes the target regardless of case' do
        expect(operator.allow?(permission: 'cmd', target_name: 'sim')).to be false
      end

      it 'cannot open the sim control tool' do
        expect(operator.allow_tool?('simcontrol')).to be false
        expect(operator.allow_tool?('cmdsender')).to be true
      end

      it 'has no administrative rights' do
        expect(operator.allow?(permission: 'admin')).to be false
      end
    end

    describe 'viewer' do
      let(:viewer) { built_in('viewer') }

      it 'reads telemetry and scripts' do
        expect(viewer.allow?(permission: 'tlm', target_name: 'SAT1')).to be true
        expect(viewer.allow?(permission: 'script_view')).to be true
      end

      it 'cannot command, set telemetry, or run scripts' do
        expect(viewer.allow?(permission: 'cmd', target_name: 'SAT1')).to be false
        expect(viewer.allow?(permission: 'tlm_set', target_name: 'SAT1')).to be false
        expect(viewer.allow?(permission: 'script_run')).to be false
      end
    end

    describe 'custom roles' do
      it 'restricts permissions to an explicit target list' do
        role = RoleModel.new(name: 'sat1-only', scope: scope,
                             permissions: %w(cmd tlm), targets: ['SAT1'])
        expect(role.allow?(permission: 'cmd', target_name: 'SAT1')).to be true
        expect(role.allow?(permission: 'cmd', target_name: 'SAT2')).to be false
        expect(role.allow?(permission: 'script_run')).to be false
      end

      it 'matches an explicit tool list case insensitively' do
        role = RoleModel.new(name: 'tlm-only', scope: scope,
                             permissions: ['tlm'], tools: ['TlmViewer'])
        expect(role.allow_tool?('tlmviewer')).to be true
        expect(role.allow_tool?('cmdsender')).to be false
      end

      it 'rejects a permission outside the known vocabulary' do
        expect {
          RoleModel.new(name: 'bad', scope: scope, permissions: %w(cmd nonsense))
        }.to raise_error(RoleInputError, /nonsense/)
      end

      it 'rejects a name that is not safe to use as a key' do
        expect { RoleModel.new(name: 'bad name!', scope: scope) }.to raise_error(RoleInputError)
      end

      # No implicit grants anywhere - absence of a permission is a denial
      it 'grants nothing by default' do
        role = RoleModel.new(name: 'empty', scope: scope)
        expect(role.allow?(permission: 'tlm', target_name: 'SAT1')).to be false
        expect(role.allow?(permission: 'cmd')).to be false
      end
    end

    describe 'built-in protection' do
      it 'refuses to delete a built-in role' do
        expect { built_in('admin').destroy }.to raise_error(RoleError, /built-in/)
      end

      it 'allows deleting a custom role' do
        role = RoleModel.new(name: 'temporary', scope: scope, permissions: ['tlm'])
        role.create
        expect { role.destroy }.to_not raise_error
      end

      it 'never offers superadmin as a grantable permission' do
        expect(RoleModel::PERMISSIONS).to_not include('superadmin')
      end
    end

    describe 'self.seed' do
      it 'creates the built-in roles' do
        expect(RoleModel.seed(scope: scope).sort).to eq(%w(admin operator viewer))
        expect(RoleModel.get(name: 'operator', scope: scope)).to_not be_nil
      end

      it 'is idempotent and preserves local edits' do
        RoleModel.seed(scope: scope)
        operator = RoleModel.get(name: 'operator', scope: scope)
        operator.permissions = ['tlm']
        operator.update
        expect(RoleModel.seed(scope: scope)).to be_empty
        expect(RoleModel.get(name: 'operator', scope: scope).permissions).to eq(['tlm'])
      end
    end
  end
end
