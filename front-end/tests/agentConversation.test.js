import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildAgentRequest,
  readConversationId,
} from '../src/api/agentConversation.js'


test('the first agent request omits conversationId', () => {
  assert.deepEqual(buildAgentRequest('第一问', null), { message: '第一问' })
})


test('six sequential requests send only the current message and returned conversationId', () => {
  let conversationId = null
  const sent = []

  for (let index = 1; index <= 6; index += 1) {
    sent.push(buildAgentRequest(`第${index}问`, conversationId))
    conversationId = readConversationId({
      conversationId: '7c1f07e2-46db-4ce1-9724-f428561d8f45',
    })
  }

  assert.deepEqual(sent[0], { message: '第1问' })
  assert.deepEqual(sent[5], {
    message: '第6问',
    conversationId: '7c1f07e2-46db-4ce1-9724-f428561d8f45',
  })
  assert.equal(Object.hasOwn(sent[5], 'history'), false)
})


test('an invalid agent response cannot replace the active conversation', () => {
  assert.throws(
    () => readConversationId({ conversationId: '' }),
    /conversationId/,
  )
})
