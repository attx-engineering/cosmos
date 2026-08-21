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

require 'openc3/models/model'

module OpenC3
  class RoleError < StandardError; end

  class RoleInputError < RoleError; end

  # Defines what a role is allowed to do. The identity provider says which roles
  # a user holds; this model says what holding a role actually grants.
  #
  # Keeping the mapping here rather than in the identity provider means
  # permissions can be tuned from the COSMOS admin UI without touching Keycloak,
  # and means a role can carry COSMOS specific concepts - target scoping and
  # tool access - that a plain identity provider role has no way to express.
  class RoleModel < Model
    PRIMARY_KEY = 'openc3_roles'.freeze

    # Every permission the system understands. Anything checked by
    # authorize(permission:) must appear here or it can never be granted.
    # 'superadmin' is deliberately excluded - see BUILT_IN below.
    PERMISSIONS = %w(
      system system_set
      tlm tlm_set
      cmd cmd_raw cmd_info
      script_view script_run
      admin
    ).freeze

    # Wildcard for target and tool lists
    ALL = 'ALL'.freeze

    # The three roles that ship with the system. They are recreated on startup
    # if missing and cannot be deleted, so an operator can never lock everyone
    # out by removing the last administrative role.
    BUILT_IN = {
      'admin' => {
        'description' => 'Full access, including simulation control and user administration',
        'permissions' => PERMISSIONS,
        'targets' => ALL,
        'tools' => ALL,
      },
      'operator' => {
        'description' => 'Send commands and run scripts on flight targets, but not simulation control',
        'permissions' => %w(system system_set tlm tlm_set cmd cmd_raw cmd_info script_view script_run),
        'targets' => ALL,
        # Sim Control drives the SIM target, so excluding both the target and the
        # tool is what actually keeps an operator out of it - hiding the tool
        # alone would still leave the API reachable.
        'excluded_targets' => ['SIM'],
        'tools' => ALL,
        'excluded_tools' => ['simcontrol'],
      },
      'viewer' => {
        'description' => 'Read-only access to telemetry and scripts',
        'permissions' => %w(system tlm cmd_info script_view),
        'targets' => ALL,
        # Simulation is administrative, so viewers are kept out of the SIM
        # target as well as the tool. Without this a viewer is blocked from
        # opening Sim Control but can still read SIM command definitions
        # through the API, which is an inconsistent boundary.
        'excluded_targets' => ['SIM'],
        'tools' => ALL,
        'excluded_tools' => ['simcontrol'],
      },
    }.freeze

    attr_reader :description, :permissions, :targets, :excluded_targets, :tools, :excluded_tools, :builtin

    def self.get(name:, scope:)
      json = super("#{scope}__#{PRIMARY_KEY}", name: name)
      return nil if json.nil?
      self.from_json(json, scope: scope)
    end

    def self.names(scope:)
      super("#{scope}__#{PRIMARY_KEY}")
    end

    def self.all(scope:)
      super("#{scope}__#{PRIMARY_KEY}")
    end

    def self.from_json(json, scope:)
      json = JSON.parse(json, allow_nan: true, create_additions: true) if String === json
      raise RoleError.new('json data is nil') if json.nil?
      self.new(**json.transform_keys(&:to_sym), scope: scope)
    end

    # Recreate any missing built-in role. Safe to call repeatedly - roles that
    # already exist are left alone so local edits to them survive a restart.
    def self.seed(scope:)
      created = []
      BUILT_IN.each do |name, definition|
        next if self.get(name: name, scope: scope)
        self.new(name: name, scope: scope, builtin: true, **definition.transform_keys(&:to_sym)).create
        created << name
      end
      created
    end

    def initialize(
      name:,
      scope:,
      description: nil,
      permissions: [],
      targets: ALL,
      excluded_targets: [],
      tools: ALL,
      excluded_tools: [],
      builtin: false,
      updated_at: nil
    )
      raise RoleInputError.new('name is required') if name.nil? or name.to_s.empty?
      unless name =~ /\A[a-zA-Z0-9_-]+\z/
        raise RoleInputError.new("invalid role name: #{name}, must be alphanumeric with - or _")
      end

      super("#{scope}__#{PRIMARY_KEY}", name: name, scope: scope)
      @description = description
      self.permissions = permissions
      # Target names are upper case in COSMOS, tool folder names are lower case
      @targets = normalize_list(targets) { |v| v.upcase }
      @excluded_targets = Array(excluded_targets).map { |v| v.to_s.upcase }
      @tools = normalize_list(tools) { |v| v.downcase }
      @excluded_tools = Array(excluded_tools).map { |v| v.to_s.downcase }
      @builtin = builtin
      @updated_at = updated_at
    end

    def permissions=(values)
      values = Array(values).map(&:to_s)
      unknown = values - PERMISSIONS
      unless unknown.empty?
        raise RoleInputError.new("unknown permission(s): #{unknown.join(', ')}. Must be one of #{PERMISSIONS.join(', ')}")
      end
      @permissions = values
    end

    # @return [Boolean] whether this role grants the permission, taking any
    #   target restriction into account. Absence of a permission is a denial -
    #   there is no implicit grant.
    def allow?(permission:, target_name: nil)
      return false unless @permissions.include?(permission.to_s)
      return true if target_name.nil?
      allow_target?(target_name)
    end

    def allow_target?(target_name)
      target_name = target_name.to_s.upcase
      return false if @excluded_targets.include?(target_name)
      return true if @targets == ALL
      @targets.include?(target_name)
    end

    def allow_tool?(tool_name)
      tool_name = tool_name.to_s.downcase
      return false if @excluded_tools.include?(tool_name)
      return true if @tools == ALL
      @tools.include?(tool_name)
    end

    def destroy
      raise RoleError.new("cannot delete built-in role: #{@name}") if @builtin
      super
    end

    def as_json(*_a)
      {
        'name' => @name,
        'description' => @description,
        'permissions' => @permissions,
        'targets' => @targets,
        'excluded_targets' => @excluded_targets,
        'tools' => @tools,
        'excluded_tools' => @excluded_tools,
        'builtin' => @builtin,
        'scope' => @scope,
        'updated_at' => @updated_at,
      }
    end

    private

    # Either the ALL wildcard or an explicit list, cased by the caller's block
    def normalize_list(value, &block)
      return ALL if value == ALL or value.nil?
      list = Array(value).map(&:to_s)
      return ALL if list.include?(ALL)
      list.map(&block)
    end
  end
end
