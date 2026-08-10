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
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'

import { useRuijieOAuthLogin } from '@/features/auth/hooks/use-ruijie-oauth-login'

function RuijieLoginRedirect(): null {
  const navigate = useNavigate()
  const { startRuijieLogin, isLoading, isAvailable } = useRuijieOAuthLogin()
  const startedRef = useRef(false)

  useEffect(() => {
    if (isLoading || startedRef.current) return

    startedRef.current = true
    if (!isAvailable) {
      navigate({ to: '/sign-in', replace: true })
      return
    }

    void startRuijieLogin().then((started) => {
      if (!started) {
        navigate({ to: '/sign-in', replace: true })
      }
    })
  }, [isAvailable, isLoading, navigate, startRuijieLogin])

  return null
}

export const Route = createFileRoute('/')({
  component: RuijieLoginRedirect,
})
