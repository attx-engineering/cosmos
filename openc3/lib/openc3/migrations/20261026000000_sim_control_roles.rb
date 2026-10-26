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

require 'openc3/utilities/migration'
require 'openc3/models/scope_model'
require 'openc3/models/role_model'

module OpenC3
  # Sim Control's target is SIM_CONTROL, no longer SIM. Roles are seeded once and
  # then left alone, so a role that named SIM -- the built-in operator's and
  # viewer's exclusions, or one an administrator wrote -- would no longer keep
  # anyone out of Sim Control's target. Each names SIM_CONTROL in its place, in
  # both its targets and its excluded targets, with every other choice kept.
  class SimControlRoles < Migration
    def self.renamed(list)
      return list unless list.is_a?(Array) && list.include?('SIM')
      list.map { |target| target == 'SIM' ? 'SIM_CONTROL' : target }.uniq
    end

    def self.run
      ScopeModel.names.each do |scope|
        RoleModel.all(scope: scope).each do |_name, json|
          role = json.is_a?(String) ? JSON.parse(json, allow_nan: true, create_additions: true) : json
          targets = renamed(role['targets'])
          excluded = renamed(role['excluded_targets'])
          next if targets == role['targets'] && excluded == role['excluded_targets']
          role['targets'] = targets
          role['excluded_targets'] = excluded
          RoleModel.from_json(role, scope: scope).update
        end
      end
    end
  end
end

unless ENV['OPENC3_NO_MIGRATE']
  OpenC3::SimControlRoles.run
end
