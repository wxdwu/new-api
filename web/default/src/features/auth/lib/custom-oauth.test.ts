/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import {
  buildCustomOAuthAuthorizationUrl,
  buildCustomOAuthRedirectUri,
} from './custom-oauth'

describe('buildCustomOAuthAuthorizationUrl', () => {
  test('lets the provider create its downstream login URL', () => {
    const result = buildCustomOAuthAuthorizationUrl({
      clientId: 'configured-client',
      authorizationEndpoint: 'https://id.example.com/oidc/authorize',
      redirectUri: 'https://site.example.com/oauth/provider',
      state: 'fresh-state',
      scopes: 'openid profile email',
    })

    const url = new URL(result)
    assert.equal(
      url.origin + url.pathname,
      'https://id.example.com/oidc/authorize'
    )
    assert.equal(url.searchParams.get('client_id'), 'configured-client')
    assert.equal(
      url.searchParams.get('redirect_uri'),
      'https://site.example.com/oauth/provider'
    )
    assert.equal(url.searchParams.get('response_type'), 'code')
    assert.equal(url.searchParams.get('state'), 'fresh-state')
    assert.equal(url.searchParams.get('scope'), 'openid profile email')
    assert.equal(url.searchParams.has('service'), false)
    assert.equal(url.searchParams.has('client_name'), false)
  })

  test('preserves existing authorization endpoint parameters', () => {
    const result = buildCustomOAuthAuthorizationUrl({
      clientId: 'configured-client',
      authorizationEndpoint: 'https://id.example.com/authorize?tenant=a',
      redirectUri: 'https://site.example.com/oauth/provider',
      state: 'example-state',
      scopes: 'openid',
    })

    const url = new URL(result)
    assert.equal(url.searchParams.get('tenant'), 'a')
    assert.equal(url.searchParams.get('client_id'), 'configured-client')
    assert.equal(url.searchParams.get('response_type'), 'code')
    assert.equal(url.searchParams.get('state'), 'example-state')
    assert.equal(url.searchParams.get('scope'), 'openid')
  })

  test('uses the configured server address for the callback', () => {
    assert.equal(
      buildCustomOAuthRedirectUri(
        'https://site-c.example.com/',
        'https://fallback.example.com',
        'provider'
      ),
      'https://site-c.example.com/oauth/provider'
    )

    assert.equal(
      buildCustomOAuthRedirectUri(
        '',
        'https://fallback.example.com',
        'provider'
      ),
      'https://fallback.example.com/oauth/provider'
    )
  })
})
