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

require 'spec_helper'
require 'openssl'
require 'jwt'
require 'openc3/utilities/authorization'
require 'openc3/utilities/rbac'
require 'openc3/models/role_model'

module OpenC3
  describe Rbac do
    let(:scope) { 'DEFAULT' }
    let(:key) { @@key ||= OpenSSL::PKey::RSA.generate(2048) }
    let(:jwk) { JWT::JWK.new(key) }

    # Generating an RSA key is slow, so share one across the whole example group
    @@key = nil

    before(:each) do
      mock_redis()
      RoleModel.seed(scope: scope)
      ENV['OPENC3_KEYCLOAK_URL'] = 'http://openc3-keycloak:8080'
      ENV['OPENC3_API_CLIENT'] = 'api'
      ENV['OPENC3_SERVICE_PASSWORD'] = 'svc-secret'
      Rbac.reset_cache
      # Serve the test key rather than reaching out to Keycloak
      allow(Rbac).to receive(:jwks).and_return(JWT::JWK::Set.new([jwk.export]))
    end

    after(:each) do
      ENV.delete('OPENC3_KEYCLOAK_URL')
      ENV.delete('OPENC3_API_CLIENT')
      ENV.delete('OPENC3_SERVICE_PASSWORD')
      Rbac.reset_cache
    end

    def token_for(roles, username: 'alice', exp: Time.now.to_i + 300, signing_key: nil)
      JWT.encode(
        {
          'preferred_username' => username,
          'iat' => Time.now.to_i,
          'exp' => exp,
          'realm_access' => { 'roles' => roles },
        },
        signing_key || key, 'RS256', { kid: jwk[:kid] }
      )
    end

    def auth(token, permission, target = nil)
      Rbac.authorize!(permission: permission, target_name: target, scope: scope, token: token)
    end

    describe '#enabled?' do
      it 'is off when no identity provider is configured' do
        ENV.delete('OPENC3_KEYCLOAK_URL')
        expect(Rbac.enabled?).to be false
      end
    end

    describe 'granting' do
      it 'authorizes a role that allows the permission' do
        expect(auth(token_for(['admin']), 'cmd', 'SIM')).to eq('alice')
        expect(auth(token_for(['operator']), 'cmd', 'SAT1')).to eq('alice')
        expect(auth(token_for(['viewer']), 'tlm', 'SAT1')).to eq('alice')
      end

      it 'combines multiple roles additively' do
        expect(auth(token_for(%w(viewer admin)), 'cmd', 'SIM')).to eq('alice')
      end

      it 'accepts a Bearer prefix' do
        expect(auth("Bearer #{token_for(['admin'])}", 'cmd', 'SAT1')).to eq('alice')
      end
    end

    describe 'denying' do
      it 'refuses an operator commanding the simulation target' do
        expect { auth(token_for(['operator']), 'cmd', 'SIM') }.to raise_error(ForbiddenError)
      end

      it 'refuses a viewer commanding or running scripts' do
        expect { auth(token_for(['viewer']), 'cmd', 'SAT1') }.to raise_error(ForbiddenError)
        expect { auth(token_for(['viewer']), 'script_run') }.to raise_error(ForbiddenError)
      end

      it 'still refuses SIM when the extra role does not lift the exclusion' do
        expect { auth(token_for(%w(operator viewer)), 'cmd', 'SIM') }.to raise_error(ForbiddenError)
      end

      # A role the identity provider knows about but COSMOS has no definition
      # for must be treated as unprivileged, never as privileged
      it 'grants nothing for a role with no COSMOS definition' do
        expect { auth(token_for(['some-ad-group']), 'cmd', 'SAT1') }.to raise_error(ForbiddenError)
      end

      it 'refuses a token carrying no roles' do
        expect { auth(token_for([]), 'tlm') }.to raise_error(ForbiddenError)
      end
    end

    describe 'token integrity' do
      it 'rejects a token signed by a different key' do
        other = OpenSSL::PKey::RSA.generate(2048)
        expect {
          auth(token_for(['admin'], signing_key: other), 'cmd', 'SAT1')
        }.to raise_error(AuthError)
      end

      it 'rejects an expired token' do
        expect {
          auth(token_for(['admin'], exp: Time.now.to_i - 10), 'cmd', 'SAT1')
        }.to raise_error(AuthError)
      end

      # The classic JWT downgrade attack
      it 'rejects an unsigned alg=none token' do
        forged = JWT.encode({ 'preferred_username' => 'mallory', 'exp' => Time.now.to_i + 300,
                              'realm_access' => { 'roles' => ['admin'] } }, nil, 'none')
        expect { auth(forged, 'cmd', 'SAT1') }.to raise_error(AuthError)
      end

      it 'rejects malformed, nil and empty tokens' do
        expect { auth('not-a-token', 'tlm') }.to raise_error(AuthError)
        expect { auth(nil, 'tlm') }.to raise_error(AuthError)
        expect { auth('', 'tlm') }.to raise_error(AuthError)
      end
    end

    describe 'service account' do
      it 'authorizes internal callers presenting the service password' do
        expect(auth('svc-secret', 'cmd', 'SIM')).to eq('system')
      end

      it 'does not accept a wrong service password' do
        expect { auth('svc-wrong', 'cmd', 'SIM') }.to raise_error(AuthError)
      end
    end

    describe '#effective_permissions' do
      it 'reports the operator exclusions for the frontend to gate on' do
        result = Rbac.effective_permissions(token: token_for(['operator']), scope: scope)
        expect(result['roles']).to eq(['operator'])
        expect(result['permissions']).to include('cmd')
        expect(result['excluded_targets']).to eq(['SIM'])
        expect(result['excluded_tools']).to eq(['simcontrol'])
      end

      it 'drops an exclusion when another held role does not share it' do
        result = Rbac.effective_permissions(token: token_for(%w(operator admin)), scope: scope)
        expect(result['excluded_targets']).to be_empty
        expect(result['excluded_tools']).to be_empty
      end
    end
  end
end
