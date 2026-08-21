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
# All changes Copyright 2022, OpenC3, Inc.
# All Rights reserved
#
# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.
#
# Modified by ATTX Inc.
# All changes Copyright 2026, ATTX, Inc.
# All rights reserved


begin
  require 'openc3-enterprise/controllers/permissions_controller'
rescue LoadError
  require 'openc3/utilities/rbac'

  # Reports what the calling user may do, so the frontend can hide controls it
  # would only be refused for using.
  #
  # This is for rendering only. It is never the enforcement point - every
  # request is independently checked by authorize(), so a client that ignores
  # this endpoint entirely gains nothing.
  class PermissionsController < ApplicationController
    def index
      # Any authenticated user may ask what they themselves can do
      return unless authorization('system')

      unless OpenC3::Rbac.enabled?
        # Without an identity provider there are no roles and the shared
        # password grants everything. Say so plainly rather than implying a
        # restriction that isn't being enforced.
        render json: {
          'rbac' => false,
          'username' => username(),
          'roles' => [],
          'permissions' => OpenC3::RoleModel::PERMISSIONS,
          'targets' => OpenC3::RoleModel::ALL,
          'excluded_targets' => [],
          'tools' => OpenC3::RoleModel::ALL,
          'excluded_tools' => [],
        }
        return
      end

      result = OpenC3::Rbac.effective_permissions(
        token: request.headers['HTTP_AUTHORIZATION'],
        scope: params[:scope],
      )
      render json: result.merge('rbac' => true)
    rescue OpenC3::AuthError => e
      render json: { status: 'error', message: e.message }, status: 401
    rescue StandardError => e
      log_error(e)
      render json: { status: 'error', message: e.message }, status: 500
    end
  end
end
