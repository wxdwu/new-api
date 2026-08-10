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
interface CustomOAuthAuthorizationUrlOptions {
  clientId: string
  authorizationEndpoint: string
  redirectUri: string
  state: string
  scopes?: string
}

export function buildCustomOAuthAuthorizationUrl(
  options: CustomOAuthAuthorizationUrlOptions
): string {
  const url = new URL(options.authorizationEndpoint)
  url.searchParams.set('client_id', options.clientId)
  url.searchParams.set('redirect_uri', options.redirectUri)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('state', options.state)

  if (options.scopes) {
    url.searchParams.set('scope', options.scopes)
  } else {
    url.searchParams.delete('scope')
  }

  return url.toString()
}

export function buildCustomOAuthRedirectUri(
  serverAddress: unknown,
  fallbackOrigin: string,
  slug: string
): string {
  const configuredAddress =
    typeof serverAddress === 'string' ? serverAddress.trim() : ''
  const baseAddress = (configuredAddress || fallbackOrigin).replace(/\/+$/, '')

  return `${baseAddress}/oauth/${slug}`
}
