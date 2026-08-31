import assert from 'node:assert/strict'
import test from 'node:test'
import { ref, watch } from 'vue'

import { appendChatMessage } from '../src/utils/chatMessages.js'


test('appendChatMessage returns the reactive message stored in the conversation', () => {
  const messages = ref([])
  const originalMessage = { role: 'assistant', content: '' }
  const storedMessage = appendChatMessage(messages, originalMessage)
  const renderedContents = []

  watch(
    () => messages.value[0]?.content,
    (content) => renderedContents.push(content),
    { flush: 'sync' },
  )

  originalMessage.content = '不会触发界面更新'
  storedMessage.content = '会逐帧触发界面更新'

  assert.deepEqual(renderedContents, ['会逐帧触发界面更新'])
})
