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
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { useStatus } from '@/hooks/use-status'

import { useOAuthLogin } from './use-oauth-login'

export function useRuijieOAuthLogin(): {
  startRuijieLogin: () => Promise<boolean>
  isLoading: boolean
  isAvailable: boolean
} {
  const { t } = useTranslation()
  const {
    status,
    loading: statusLoading,
    fetching: statusFetching,
  } = useStatus()
  const { isLoading, handleCustomOAuthLogin } = useOAuthLogin(status)
  const ruijieProvider = status?.custom_oauth_providers?.find(
    (provider) => provider.slug.toLowerCase() === 'ruijie'
  )

  const startRuijieLogin = async (): Promise<boolean> => {
    if (!ruijieProvider) {
      toast.error(
        t('Failed to start {{provider}} login', { provider: 'Ruijie SSO' })
      )
      return false
    }

    return handleCustomOAuthLogin(ruijieProvider)
  }

  return {
    startRuijieLogin,
    isLoading: statusLoading || statusFetching || isLoading,
    isAvailable: Boolean(ruijieProvider),
  }
}
