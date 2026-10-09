/*
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

# Modified by ATTX, Inc.
# All changes Copyright 2026, ATTX, Inc.
# All Rights Reserved
*/

// Two authentication modes live here and which one is used is decided by the
// backend, not the browser: /openc3-api/auth.js sets openc3_keycloak_url when an
// identity provider is configured. Without one, the original single shared
// password behaviour applies unchanged.

// Keep this in step with the vendored file in public/js
const ADAPTER_URL = '/js/keycloak-26.2.4.js'

const emptyPromise = function (resolution = null) {
  return new Promise((resolve) => {
    resolve(resolution)
  })
}

// The shared password flow. Unchanged from before role based access control.
class PasswordAuth {
  updateToken(value, from_401 = false) {
    if (!localStorage.openc3Token || from_401) {
      this.clearTokens()
      this.login(location.href)
    }
    return emptyPromise()
  }
  setTokens() {}
  clearTokens() {
    delete localStorage.openc3Token
  }
  login(redirect) {
    let url = new URL(redirect)
    let result = url.pathname
    if (url.search) {
      result = result + url.search
    }
    if (!/^\/login/.test(location.pathname))
      location = `/login?redirect=${encodeURI(result)}`
  }
  logout() {
    this.clearTokens()
    location.reload()
  }
  user() {
    return { name: 'Anonymous' }
  }
  userroles() {
    return ['admin']
  }
  getInitOptions() {}
  init() {
    return emptyPromise(true)
  }
}

// Keycloak backed authentication. The access token is a JWT the backend
// verifies on every request, so unlike the password flow the browser cannot
// grant itself anything by editing localStorage.
class KeycloakAuth {
  constructor() {
    this.keycloak = null
    this.KeycloakCtor = null
    this.roles = []
  }

  getInitOptions() {
    return {
      // Nothing in COSMOS is usable anonymously, so send people straight to the
      // login page rather than rendering an empty shell first.
      onLoad: 'login-required',
      checkLoginIframe: false,
      pkceMethod: 'S256',
      enableLogging: false,
    }
  }

  // keycloak-js 26 is ESM only and Keycloak no longer serves the adapter itself
  // (that endpoint was removed after v24), so it is vendored alongside the other
  // third party scripts and pulled in with a dynamic import.
  loadAdapter() {
    if (this.KeycloakCtor) {
      return emptyPromise()
    }
    return import(ADAPTER_URL)
      .then((module) => {
        this.KeycloakCtor = module.default
      })
      .catch((error) => {
        throw new Error(
          `Could not load the Keycloak adapter from ${ADAPTER_URL}: ${error.message}`,
        )
      })
  }

  init(options) {
    return this.loadAdapter().then(() => {
      this.keycloak = new this.KeycloakCtor({
        url: openc3_keycloak_url,
        realm: openc3_keycloak_realm,
        clientId: openc3_keycloak_client_id,
      })
      return this.keycloak
        .init(options || this.getInitOptions())
        .then((authenticated) => {
          if (authenticated) {
            this.setTokens()
          }
          return authenticated
        })
    })
  }

  // Refresh when the token has less than minValidity seconds left. Resolves
  // true when a refresh actually happened so the caller can re-read the token.
  updateToken(minValidity, from_401 = false) {
    if (!this.keycloak) {
      return emptyPromise(false)
    }
    if (from_401) {
      // A 401 against a token we believe is valid means the session is gone -
      // a refresh will not recover it, so start over.
      this.clearTokens()
      return this.login(location.href)
    }
    return this.keycloak.updateToken(minValidity)
  }

  setTokens() {
    localStorage.openc3Token = this.keycloak.token
    localStorage.openc3RefreshToken = this.keycloak.refreshToken
    this.roles = (this.keycloak.tokenParsed?.realm_access?.roles || []).slice()
  }

  clearTokens() {
    delete localStorage.openc3Token
    delete localStorage.openc3RefreshToken
  }

  login(redirect) {
    return this.keycloak.login({ redirectUri: redirect || location.href })
  }

  logout() {
    this.clearTokens()
    return this.keycloak.logout({ redirectUri: location.origin })
  }

  user() {
    const parsed = this.keycloak?.tokenParsed || {}
    return {
      name: parsed.name || parsed.preferred_username || 'Unknown',
      username: parsed.preferred_username,
      email: parsed.email,
      roles: this.roles,
    }
  }

  userroles() {
    return this.roles
  }
}

// openc3_keycloak_url is defined by /openc3-api/auth.js, which the backend only
// populates when an identity provider is configured.
const keycloakConfigured =
  typeof openc3_keycloak_url !== 'undefined' &&
  openc3_keycloak_url !== null &&
  openc3_keycloak_url !== ''

let OpenC3Auth = keycloakConfigured ? new KeycloakAuth() : new PasswordAuth()

Object.defineProperty(OpenC3Auth, 'defaultMinValidity', {
  value: 30,
  writable: false,
  enumerable: true,
  configurable: false,
})
