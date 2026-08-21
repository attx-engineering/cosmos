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
  require 'openc3-enterprise/controllers/roles_controller'
rescue LoadError
  require 'openc3/models/role_model'

  # Manages what each role is allowed to do. Which users hold which roles is
  # the identity provider's business - this is only the permission mapping.
  #
  # Everything here requires 'admin': being able to edit roles is equivalent to
  # granting yourself any permission, so it must never be reachable by a role
  # that doesn't already have full rights.
  class RolesController < ApplicationController
    def index
      return unless authorization('admin')
      render json: OpenC3::RoleModel.all(scope: params[:scope]).values
    rescue StandardError => e
      log_error(e)
      render json: { status: 'error', message: e.message }, status: 500
    end

    # The vocabulary a custom role can be built from, so the admin UI doesn't
    # have to hardcode a list that could drift out of step with the backend.
    def permissions
      return unless authorization('admin')
      render json: {
        'permissions' => OpenC3::RoleModel::PERMISSIONS,
        'all' => OpenC3::RoleModel::ALL,
      }
    end

    def show
      return unless authorization('admin')
      model = OpenC3::RoleModel.get(name: params[:id], scope: params[:scope])
      if model.nil?
        render json: { status: 'error', message: "role not found: #{params[:id]}" }, status: 404
      else
        render json: model.as_json
      end
    rescue StandardError => e
      log_error(e)
      render json: { status: 'error', message: e.message }, status: 500
    end

    def create
      return unless authorization('admin')
      hash = role_params
      if OpenC3::RoleModel.get(name: hash['name'], scope: params[:scope])
        render json: { status: 'error', message: "role already exists: #{hash['name']}" }, status: 409
        return
      end
      # builtin is never accepted from the request - only seeding sets it
      model = OpenC3::RoleModel.new(**hash.symbolize_keys, scope: params[:scope], builtin: false)
      model.create
      OpenC3::Logger.info("Role created: #{model.name}", scope: params[:scope], user: username())
      render json: model.as_json, status: 201
    rescue OpenC3::RoleInputError => e
      render json: { status: 'error', message: e.message }, status: 400
    rescue StandardError => e
      log_error(e)
      render json: { status: 'error', message: e.message }, status: 500
    end

    def update
      return unless authorization('admin')
      existing = OpenC3::RoleModel.get(name: params[:id], scope: params[:scope])
      if existing.nil?
        render json: { status: 'error', message: "role not found: #{params[:id]}" }, status: 404
        return
      end
      hash = role_params
      # A built-in role's permissions can be tuned, but it stays built-in so it
      # can't be deleted out from under everyone
      model = OpenC3::RoleModel.new(
        **hash.symbolize_keys,
        name: params[:id],
        scope: params[:scope],
        builtin: existing.builtin,
      )
      model.update
      OpenC3::Logger.info("Role updated: #{model.name}", scope: params[:scope], user: username())
      render json: model.as_json
    rescue OpenC3::RoleInputError => e
      render json: { status: 'error', message: e.message }, status: 400
    rescue StandardError => e
      log_error(e)
      render json: { status: 'error', message: e.message }, status: 500
    end

    def destroy
      return unless authorization('admin')
      model = OpenC3::RoleModel.get(name: params[:id], scope: params[:scope])
      if model.nil?
        render json: { status: 'error', message: "role not found: #{params[:id]}" }, status: 404
        return
      end
      model.destroy
      OpenC3::Logger.info("Role deleted: #{params[:id]}", scope: params[:scope], user: username())
      render json: { name: params[:id] }
    rescue OpenC3::RoleError => e
      # Deleting a built-in role lands here
      render json: { status: 'error', message: e.message }, status: 400
    rescue StandardError => e
      log_error(e)
      render json: { status: 'error', message: e.message }, status: 500
    end

    private

    def role_params
      params.permit(
        :name, :description,
        permissions: [], targets: [], excluded_targets: [], tools: [], excluded_tools: []
      ).to_h.tap do |hash|
        # permit(key: []) drops a bare 'ALL' string, so pull the wildcards back
        # out of the raw params
        %w(targets tools).each do |key|
          raw = params[key]
          hash[key] = OpenC3::RoleModel::ALL if raw.is_a?(String) && raw.upcase == OpenC3::RoleModel::ALL
        end
      end
    end
  end
end
