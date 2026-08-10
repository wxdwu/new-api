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

import type { Channel } from '../types'
import {
  CHANNEL_FORM_DEFAULT_VALUES,
  transformChannelToFormDefaults,
  transformFormDataToUpdatePayload,
} from './channel-form'

describe('channel ability tag form data', () => {
  test('loads the tagged model selection returned by the channel API', () => {
    const formData = transformChannelToFormDefaults({
      id: 1,
      name: 'tagged channel',
      type: 1,
      models: 'model-a,model-b',
      tag_enabled_models: ['model-b'],
      group: 'default',
      status: 1,
      channel_info: {
        is_multi_key: false,
        multi_key_size: 0,
        multi_key_polling_index: 0,
        multi_key_mode: 'random',
      },
    } as Channel)

    assert.deepEqual(formData.tag_enabled_models, ['model-b'])
  })

  test('keeps an explicit empty selection in the update payload', () => {
    const payload = transformFormDataToUpdatePayload(
      {
        ...CHANNEL_FORM_DEFAULT_VALUES,
        name: 'tagged channel',
        models: 'model-a,model-b',
        tag_enabled_models: [],
      },
      1
    )

    assert.deepEqual(payload.tag_enabled_models, [])
  })
})
