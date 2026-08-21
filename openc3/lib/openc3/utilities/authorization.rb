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

# Modified by OpenC3, Inc.
# All changes Copyright 2024, OpenC3, Inc.
# All Rights Reserved
#
# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.

require 'openc3/models/auth_model'
require 'openc3/utilities/rbac'

begin
  require 'openc3-enterprise/utilities/authorization'
rescue LoadError
  # If we're not in openc3-enterprise we define our own
  module OpenC3
    class AuthError < StandardError
    end

    class ForbiddenError < StandardError
    end

    module Authorization
      private

      # Raises an exception if unauthorized, otherwise does nothing
      def authorize(permission: nil, target_name: nil, packet_name: nil, interface_name: nil, router_name: nil, manual: false, scope: nil, token: nil)
        raise AuthError.new("Scope is required") unless scope

        # When an identity provider is configured, role based access control is
        # the authority and the shared password is not accepted for user
        # requests. Without one, fall back to the single password behaviour so a
        # local or offline deployment still works.
        if OpenC3::Rbac.enabled?
          return OpenC3::Rbac.authorize!(
            permission: permission,
            target_name: target_name,
            scope: scope,
            token: token,
          )
        end

        if $openc3_authorize
          raise AuthError.new("Token is required") unless token
          unless OpenC3::AuthModel.verify(token)
            raise AuthError.new("Password is invalid")
          end
        end
        return "anonymous"
      end

      def user_info(token)
        return {} unless OpenC3::Rbac.enabled?
        claims = OpenC3::Rbac.verify_token(token)
        {
          'username' => OpenC3::Rbac.username_from_claims(claims),
          'roles' => OpenC3::Rbac.roles_from_claims(claims),
        }
      rescue StandardError
        # Callers use this for display and logging, so an unreadable token here
        # must not raise - the request itself is still gated by authorize.
        {}
      end
    end
  end
end
