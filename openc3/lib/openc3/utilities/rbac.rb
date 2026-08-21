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

# NOTE: jwt is loaded lazily rather than at require time. This file is pulled
# in by utilities/authorization, which nearly every process loads, so a missing
# optional dependency must never be able to take the whole system down.
require 'json'
require 'net/http'
require 'openc3/models/role_model'

module OpenC3
  # Role based access control backed by Keycloak.
  #
  # Keycloak answers "who is this and what roles do they hold"; RoleModel
  # answers "what does holding that role allow". This class joins the two and is
  # the single place a permission decision is made.
  #
  # Every path through here fails closed: an unreadable token, an unknown role,
  # or an unreachable key set all result in a denial rather than a fallback to
  # permissive behaviour.
  module Rbac
    class << self
      # How long a verified token's decoded claims are reused before the
      # signature is checked again. Short enough that a revoked session stops
      # working quickly, long enough to keep per-request cost negligible.
      CLAIMS_CACHE_SECONDS = 30

      # Keycloak signing keys rotate rarely; refetching on an unknown key id
      # handles rotation without polling.
      JWKS_CACHE_SECONDS = 3600

      def enabled?
        !keycloak_url.nil? && !keycloak_url.empty?
      end

      # Loaded on first use. If role based access control is configured but the
      # library is missing, that is a misconfiguration: refuse to authorize
      # rather than quietly falling back to the shared password, which would
      # turn a broken deployment into an open one.
      def require_jwt!
        return if @jwt_loaded
        begin
          require 'jwt'
          @jwt_loaded = true
        rescue LoadError => e
          raise AuthError.new(
            "Role based access control is enabled but the 'jwt' gem is not available (#{e.message}). " \
            "Refusing to authorize. Either install it or unset OPENC3_KEYCLOAK_URL."
          )
        end
      end

      def keycloak_url
        ENV['OPENC3_KEYCLOAK_URL']
      end

      def realm
        ENV['OPENC3_KEYCLOAK_REALM'] || 'openc3'
      end

      # The service account the internal microservices authenticate with. It is
      # exempt from role checks because it *is* the system acting on its own
      # behalf - see the note in authorize! about why this is safe.
      def service_password
        ENV['OPENC3_SERVICE_PASSWORD']
      end

      # @return [Hash] the verified claims, or raises AuthError
      def verify_token(token)
        require_jwt!
        raise AuthError.new('Token is required') if token.nil? || token.empty?
        token = token.sub(/\ABearer\s+/i, '')

        cached = claims_cache[token]
        if cached && (Time.now.to_f - cached[:at]) < CLAIMS_CACHE_SECONDS
          return cached[:claims]
        end

        claims = decode(token)
        claims_cache[token] = { claims: claims, at: Time.now.to_f }
        prune_cache
        claims
      end

      # @return [Array<String>] role names the token carries. Both realm roles
      #   and roles for this client are honoured so either can be used to grant
      #   access from the Keycloak side.
      def roles_from_claims(claims)
        roles = []
        realm_access = claims['realm_access']
        roles.concat(Array(realm_access['roles'])) if realm_access.is_a?(Hash)
        resource_access = claims['resource_access']
        if resource_access.is_a?(Hash)
          client = ENV['OPENC3_API_CLIENT']
          entry = resource_access[client] if client
          roles.concat(Array(entry['roles'])) if entry.is_a?(Hash)
        end
        roles.uniq
      end

      def username_from_claims(claims)
        claims['preferred_username'] || claims['sub'] || 'unknown'
      end

      # The permission decision. Returns the username on success and raises
      # ForbiddenError otherwise.
      def authorize!(permission:, target_name: nil, scope:, token:)
        # A microservice presenting the service password is the system itself -
        # the scheduler running an activity, the operator starting an interface.
        # These have no interactive user to attribute and must not be blocked by
        # role checks. The password never leaves the cluster.
        if service_password && !service_password.empty? && token == service_password
          return 'system'
        end

        claims = verify_token(token)
        username = username_from_claims(claims)
        return username if permission.nil?

        roles = roles_from_claims(claims)
        if roles.empty?
          raise ForbiddenError.new("User #{username} has no roles assigned")
        end

        granted = roles.any? do |role_name|
          role = RoleModel.get(name: role_name, scope: scope)
          # A role Keycloak knows about but COSMOS has no definition for grants
          # nothing. Unknown means unprivileged, never privileged.
          next false if role.nil?
          role.allow?(permission: permission, target_name: target_name)
        end

        unless granted
          detail = target_name ? "#{permission} on #{target_name}" : permission
          raise ForbiddenError.new("User #{username} is not authorized for #{detail}")
        end
        username
      end

      # The caller's effective permissions, for the frontend to gate its UI
      # with. This is a convenience for rendering - it is never the enforcement
      # point, which is always authorize! on the request itself.
      def effective_permissions(token:, scope:)
        # Internal callers present the service password rather than a token and
        # are unrestricted, matching authorize!
        if service_password && !service_password.empty? && token == service_password
          return {
            'username' => 'system',
            'roles' => [],
            'permissions' => RoleModel::PERMISSIONS,
            'targets' => RoleModel::ALL,
            'excluded_targets' => [],
            'tools' => RoleModel::ALL,
            'excluded_tools' => [],
          }
        end
        claims = verify_token(token)
        roles = roles_from_claims(claims).filter_map do |name|
          RoleModel.get(name: name, scope: scope)
        end
        {
          'username' => username_from_claims(claims),
          'roles' => roles.map(&:name),
          'permissions' => roles.flat_map(&:permissions).uniq,
          'targets' => merge_scope(roles.map(&:targets)),
          'excluded_targets' => intersect(roles.map(&:excluded_targets)),
          'tools' => merge_scope(roles.map(&:tools)),
          'excluded_tools' => intersect(roles.map(&:excluded_tools)),
        }
      end

      def reset_cache
        @claims_cache = {}
        @jwt_loaded = false
        @jwks = nil
        @jwks_at = nil
      end

      private

      def claims_cache
        @claims_cache ||= {}
      end

      def prune_cache
        return if claims_cache.size < 500
        cutoff = Time.now.to_f - CLAIMS_CACHE_SECONDS
        claims_cache.delete_if { |_k, v| v[:at] < cutoff }
      end

      # Holding several roles is additive, so a wildcard anywhere wins
      def merge_scope(lists)
        return RoleModel::ALL if lists.include?(RoleModel::ALL)
        lists.flatten.uniq
      end

      # An exclusion only stands if every role the user holds excludes it
      def intersect(lists)
        return [] if lists.empty?
        lists.reduce { |a, b| a & b } || []
      end

      def decode(token)
        JWT.decode(
          token,
          nil,
          true, # verify the signature
          algorithms: ['RS256'],
          jwks: ->(options) { jwks(force: options[:kid_not_found]) },
          verify_expiration: true,
          verify_iat: true,
        ).first
      rescue JWT::ExpiredSignature
        raise AuthError.new('Token has expired')
      rescue JWT::DecodeError, JWT::JWKError => e
        raise AuthError.new("Token is invalid: #{e.message}")
      end

      # Keycloak's public signing keys. Refetched when a token names a key id we
      # have not seen, which is how key rotation is picked up.
      def jwks(force: false)
        if !force && @jwks && (Time.now.to_f - @jwks_at) < JWKS_CACHE_SECONDS
          return @jwks
        end
        uri = URI("#{keycloak_url}/realms/#{realm}/protocol/openid-connect/certs")
        response = Net::HTTP.get_response(uri)
        unless response.is_a?(Net::HTTPSuccess)
          raise AuthError.new("Could not fetch signing keys (#{response.code})")
        end
        @jwks = JWT::JWK::Set.new(JSON.parse(response.body))
        @jwks_at = Time.now.to_f
        @jwks
      rescue AuthError
        raise
      rescue StandardError => e
        # Without keys nothing can be verified, so deny rather than let requests
        # through unchecked while the identity provider is unreachable.
        raise AuthError.new("Could not reach the identity provider: #{e.message}")
      end
    end
  end
end
