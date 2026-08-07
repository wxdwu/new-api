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
import { Link, useSearch } from '@tanstack/react-router'
import { Blocks, Building2, Check, ShieldCheck, Workflow } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { LanguageSwitcher } from '@/components/language-switcher'
import { useStatus } from '@/hooks/use-status'

import { TermsFooter } from '../components/terms-footer'
import { UserAuthForm } from './components/user-auth-form'

export function SignIn() {
  const { t } = useTranslation()
  const { redirect } = useSearch({ from: '/(auth)/sign-in' })
  const { status } = useStatus()
  const docsLink =
    typeof status?.docs_link === 'string' ? status.docs_link : undefined
  const workspaceFeatures = [
    {
      icon: ShieldCheck,
      title: t('Secure and trusted'),
      description: t('Enterprise SSO and unified identity management'),
    },
    {
      icon: Workflow,
      title: t('Efficient collaboration'),
      description: t('One workspace for focused, connected work'),
    },
    {
      icon: Blocks,
      title: t('Open integration'),
      description: t('Connect business services through one secure entry'),
    },
  ]

  return (
    <div className='relative min-h-svh overflow-x-hidden bg-[#eef5ff] text-[#14234d] lg:h-svh lg:overflow-hidden'>
      <div
        aria-hidden='true'
        className='absolute -top-48 -left-36 h-[34rem] w-[34rem] rounded-full bg-[#dbeaff]/80 blur-3xl'
      />
      <div
        aria-hidden='true'
        className='absolute -right-40 -bottom-56 h-[38rem] w-[38rem] rounded-full bg-[#d7e9ff]/90 blur-3xl'
      />

      <header className='relative z-10 flex h-16 w-full items-center justify-between px-5 sm:px-8 lg:px-11'>
        <Link
          to='/'
          aria-label={t('Go to home page')}
          className='flex items-center gap-3 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-[#176deb] focus-visible:ring-offset-4 focus-visible:ring-offset-[#eef5ff]'
        >
          <span className='flex items-baseline gap-2 text-[#d51f35]'>
            <span className='text-xl font-black tracking-[-0.06em] italic sm:text-2xl'>
              Ruijie
            </span>
            <span className='text-base font-extrabold sm:text-lg'>锐捷</span>
          </span>
          <span className='h-5 w-px bg-[#cbd8e8]' aria-hidden='true' />
          <span className='text-sm font-bold text-[#172449] sm:text-base'>
            {t('AI Workspace')}
          </span>
        </Link>

        <div className='hidden items-center gap-2 text-xs text-[#4c5870] sm:flex'>
          {docsLink && (
            <a
              href={docsLink}
              target='_blank'
              rel='noreferrer'
              className='transition-colors hover:text-[#176deb]'
            >
              {t('Help Center')}
            </a>
          )}
          <span className='h-3 w-px bg-[#b9c5d6]' aria-hidden='true' />
          <LanguageSwitcher showLabel />
        </div>
      </header>

      <main className='relative z-10 mx-auto grid w-full max-w-[980px] gap-8 px-5 pt-7 pb-8 sm:px-8 lg:h-[calc(100svh-4rem)] lg:grid-cols-[minmax(0,1fr)_420px] lg:items-center lg:gap-[5.5rem] lg:px-0 lg:pt-0 lg:pb-4'>
        <section className='order-2 mx-auto w-full max-w-2xl lg:order-1 lg:mx-0 lg:translate-y-[21px]'>
          <div className='mb-8 text-center lg:text-left'>
            <h1 className='text-[clamp(2.25rem,4vw,2.875rem)] leading-[1.12] font-black tracking-[-0.04em] text-[#14234d]'>
              {t('Welcome to')}
              <span className='block text-[#176deb]'>
                {t('Ruijie AI Workspace')}
              </span>
            </h1>
            <p className='mt-4 text-sm font-medium text-[#66758d] sm:text-base'>
              {t(
                'Enterprise security · Unified identity · AI-native experience'
              )}
            </p>
          </div>

          <div className='relative mx-auto mb-8 grid h-[210px] max-w-xl place-items-center overflow-hidden rounded-3xl border border-[#e7f0fc] bg-gradient-to-br from-[#d9ebff] to-[#f7fbff] lg:mx-0'>
            <div className='absolute bottom-7 left-[22%] size-1.5 rotate-45 border border-[#6ea9fa]' />
            <div className='absolute bottom-7 left-[37%] size-1 rounded-full bg-[#8dbefb]' />
            <div className='absolute right-[37%] bottom-7 size-1.5 rotate-45 border border-[#6ea9fa]' />
            <div className='absolute right-[22%] bottom-7 size-1 rounded-full bg-[#8dbefb]' />
            <div className='relative grid h-[82px] w-[120px] place-items-center rounded-[1.35rem] bg-gradient-to-br from-[#3c99ff] to-[#1761df] text-[42px] font-black tracking-[-0.04em] text-white shadow-[0_20px_28px_rgba(23,97,223,0.29)]'>
              AI
            </div>
          </div>

          <div className='grid gap-3 sm:grid-cols-3 sm:gap-3.5'>
            {workspaceFeatures.map((feature) => {
              const Icon = feature.icon
              return (
                <article
                  key={feature.title}
                  className='h-40 rounded-[14px] border border-[#dce8f7] bg-white/72 px-3 py-4 text-center shadow-[0_12px_32px_rgba(48,98,170,0.06)] backdrop-blur-sm'
                >
                  <div className='mx-auto grid size-10 place-items-center rounded-xl bg-[#e8f2ff] text-[#176deb]'>
                    <Icon className='size-5' aria-hidden='true' />
                  </div>
                  <h2 className='mt-3 text-sm font-extrabold text-[#1a294f]'>
                    {feature.title}
                  </h2>
                  <p className='mt-1.5 text-xs leading-5 text-[#6d7890]'>
                    {feature.description}
                  </p>
                </article>
              )
            })}
          </div>
        </section>

        <section className='order-1 mx-auto w-full max-w-[420px] rounded-[1.4rem] border border-white/90 bg-white/82 p-5 shadow-[0_22px_55px_rgba(48,98,170,0.14)] backdrop-blur-xl sm:p-[30px] lg:order-2 lg:translate-y-[17px]'>
          <div className='mb-5 flex items-center gap-3 rounded-[13px] border border-[#dce7f5] bg-[#f5f8fd] p-4'>
            <div className='grid size-11 shrink-0 place-items-center rounded-xl bg-[#e6f0ff] text-[#176deb]'>
              <Building2 className='size-5' aria-hidden='true' />
            </div>
            <div className='min-w-0'>
              <h2 className='truncate text-sm font-extrabold text-[#172449]'>
                {t('Ruijie Networks Co., Ltd.')}
              </h2>
              <p className='mt-1 flex items-center gap-1.5 text-xs font-medium text-[#249d70]'>
                <Check className='size-3.5' aria-hidden='true' />
                {t('Enterprise SSO is enabled')}
              </p>
            </div>
          </div>

          <UserAuthForm redirectTo={redirect} />

          <div className='mt-4 flex items-center justify-center gap-2 text-center text-xs text-[#66758d]'>
            <span
              className='size-1.5 rounded-full bg-[#29b77b]'
              aria-hidden='true'
            />
            {t('Connected to Ruijie unified identity authentication')}
          </div>

          <TermsFooter
            variant='sign-in'
            status={status}
            className='mt-4 text-center'
          />
        </section>
      </main>
    </div>
  )
}
