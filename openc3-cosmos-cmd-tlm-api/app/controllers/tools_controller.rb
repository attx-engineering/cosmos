# encoding: ascii-8bit

# Copyright 2022 Ball Aerospace & Technologies Corp.
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
# Modified by OpenC3, Inc.
# All changes Copyright 2024, OpenC3, Inc.
# All Rights Reserved
#
# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.
#
# Modified by ATTX Inc.
# All changes Copyright 2026, ATTX, Inc.
# All rights reserved


require 'openc3/models/tool_model'
require 'openc3/models/role_model'
require 'openc3/utilities/rbac'

class ToolsController < ModelController
  def initialize
    @model_class = OpenC3::ToolModel
  end

  def show
    # No authorization required to read the tool list itself - the nav has to
    # render before anything else - but when roles are in play the list is
    # filtered to what the caller may actually open.
    if params[:id].downcase == 'all'
      render json: filter_by_role(@model_class.all(scope: params[:scope]))
    else
      render json: @model_class.get(name: params[:id], scope: params[:scope])
    end
  end

  # Hiding a tool is cosmetic on its own - the permissions behind it are
  # enforced separately by authorize() on each request. This exists so the nav
  # doesn't offer tools that would only fail when opened.
  def filter_by_role(tools)
    return tools unless OpenC3::Rbac.enabled?
    permissions = OpenC3::Rbac.effective_permissions(
      token: request.headers['HTTP_AUTHORIZATION'],
      scope: params[:scope],
    )
    allowed = permissions['tools']
    excluded = Array(permissions['excluded_tools'])
    tools.select do |_name, tool|
      folder = tool['folder_name'].to_s.downcase
      # Tools without a folder are structural (the base shell) and always stay
      next true if folder.empty?
      next false if excluded.include?(folder)
      allowed == OpenC3::RoleModel::ALL || Array(allowed).include?(folder)
    end
  rescue OpenC3::AuthError
    # The nav has to render before the user has a token - on the login screen
    # itself, for instance - so an unidentifiable caller gets the unfiltered
    # list rather than an empty application. This is safe because hiding a tool
    # was never the security boundary: opening one still requires permissions,
    # which authorize() checks on every request the tool makes.
    tools
  end

  # Set the tools position in the list
  # Passed position is an integer index starting with 0 being first in the list
  def position
    return unless authorization('admin')
    @model_class.set_position(name: params[:id], position: params[:position], scope: params[:scope])
    head :ok
  end

  def importmap
    result = {}
    result["imports"] = {}

    tools = @model_class.all_scopes
    inline_tools = {}
    tools.each do |key, tool|
      if tool['import_map_items']
        tool['import_map_items'].each do |item_key, item|
          result["imports"][item_key] = item
        end
      end
      if tool['inline_url']
        result["imports"]["@openc3/tool-#{tool['folder_name']}"] = "/tools/#{tool['folder_name']}/#{tool['inline_url']}"
      end
    end
    render json: result
  end

  def auth
    url = ENV['OPENC3_KEYCLOAK_EXTERNAL_URL']
    unless url
      url = ENV['OPENC3_KEYCLOAK_URL']
      if url == "http://openc3-keycloak:8080"
        # Externally should be just /auth
        url = "/auth"
      end
    end
    realm = ENV['OPENC3_KEYCLOAK_REALM']
    realm = "openc3" unless realm
    render js: "var openc3_keycloak_url = \"#{url}\"; var openc3_keycloak_realm = \"#{realm}\"; var openc3_keycloak_client_id = \"#{ENV['OPENC3_API_CLIENT']}\""
  end
end
