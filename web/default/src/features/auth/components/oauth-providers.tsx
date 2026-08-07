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
import { ArrowRight, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import {
  IconDiscord,
  IconGithub,
  IconLinuxDo,
  IconWeChat,
} from '@/assets/brand-icons'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { useOAuthLogin } from '../hooks/use-oauth-login'
import type { SystemStatus } from '../types'

type OAuthProvidersProps = {
  status: SystemStatus | null
  disabled?: boolean
  className?: string
  onWeChatLogin?: () => void
  isWeChatLoading?: boolean
  redirectTo?: string
}

type ProviderButton = {
  key: string
  label: string
  onClick: () => void
  icon?: ReactNode
  disabled?: boolean
  featured?: boolean
}

export function OAuthProviders({
  status,
  disabled = false,
  className,
  onWeChatLogin,
  isWeChatLoading = false,
  redirectTo,
}: OAuthProvidersProps) {
  const { t } = useTranslation()
  const {
    isLoading,
    githubButtonText,
    githubButtonDisabled,
    handleGitHubLogin,
    handleDiscordLogin,
    handleOIDCLogin,
    handleLinuxDOLogin,
    handleTelegramLogin,
    handleCustomOAuthLogin,
  } = useOAuthLogin(status)

  const providerButtons: ProviderButton[] = []

  if (status?.wechat_login && onWeChatLogin) {
    providerButtons.push({
      key: 'wechat',
      label: t('Continue with WeChat'),
      onClick: onWeChatLogin,
      icon: <IconWeChat className='h-4 w-4' />,
      disabled: isWeChatLoading,
    })
  }

  if (status?.github_oauth) {
    providerButtons.push({
      key: 'github',
      label: githubButtonText || t('Continue with GitHub'),
      onClick: () => handleGitHubLogin(redirectTo),
      icon: <IconGithub className='h-4 w-4' />,
      disabled: githubButtonDisabled,
    })
  }

  if (status?.discord_oauth) {
    providerButtons.push({
      key: 'discord',
      label: t('Continue with Discord'),
      onClick: () => handleDiscordLogin(redirectTo),
      icon: <IconDiscord className='h-4 w-4' />,
    })
  }

  if (status?.oidc_enabled) {
    providerButtons.push({
      key: 'oidc',
      label: t('Continue with OIDC'),
      onClick: () => handleOIDCLogin(redirectTo),
    })
  }

  if (status?.linuxdo_oauth) {
    providerButtons.push({
      key: 'linuxdo',
      label: t('Continue with LinuxDO'),
      onClick: () => handleLinuxDOLogin(redirectTo),
      icon: <IconLinuxDo className='h-4 w-4' />,
    })
  }

  if (status?.telegram_oauth) {
    providerButtons.push({
      key: 'telegram',
      label: t('Continue with Telegram'),
      onClick: handleTelegramLogin,
    })
  }

  // Custom OAuth providers
  const customProviders = status?.custom_oauth_providers
  if (customProviders && customProviders.length > 0) {
    for (const provider of customProviders) {
      const isRuijieProvider = provider.slug.toLowerCase() === 'ruijie'
      providerButtons.push({
        key: `custom-${provider.slug}`,
        label: isRuijieProvider
          ? t('Sign in with Ruijie SSO')
          : t('Continue with {{name}}', { name: provider.name }),
        onClick: () => handleCustomOAuthLogin(provider, redirectTo),
        icon: isRuijieProvider ? <ShieldCheck className='size-5' /> : undefined,
        featured: isRuijieProvider,
      })
    }
  }

  if (providerButtons.length === 0) return null

  const featuredButtons = providerButtons.filter((button) => button.featured)
  const standardButtons = providerButtons.filter((button) => !button.featured)

  const renderButton = (button: ProviderButton) => (
    <Button
      key={button.key}
      variant={button.featured ? 'default' : 'outline'}
      type='button'
      disabled={disabled || isLoading || button.disabled}
      onClick={button.onClick}
      className={cn(
        'h-12 w-full justify-center gap-2 rounded-xl',
        button.featured &&
          'relative h-14 bg-gradient-to-r from-[#1768ec] to-[#278bff] px-5 text-[15px] font-extrabold text-white shadow-[0_14px_28px_rgba(24,111,240,0.28)] hover:brightness-105'
      )}
    >
      {button.icon}
      {button.label}
      {button.featured && (
        <ArrowRight className='absolute right-5 size-5' aria-hidden='true' />
      )}
    </Button>
  )

  return (
    <div className={cn('space-y-3', className)}>
      {featuredButtons.map(renderButton)}

      {standardButtons.length > 0 && (
        <div className='relative py-1'>
          <div className='absolute inset-0 flex items-center'>
            <span className='w-full border-t' />
          </div>
          <div className='relative flex justify-center text-xs uppercase'>
            <span className='bg-background text-muted-foreground px-2'>
              {t('Or continue with')}
            </span>
          </div>
        </div>
      )}

      {standardButtons.length > 0 && (
        <div className='flex flex-col gap-2'>
          {standardButtons.map(renderButton)}
        </div>
      )}
    </div>
  )
}
