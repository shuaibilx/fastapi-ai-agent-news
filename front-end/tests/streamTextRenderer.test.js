import assert from 'node:assert/strict'
import test from 'node:test'

import { createIncrementalTextRenderer } from '../src/api/streamTextRenderer.js'


test('coalesced stream text is rendered across bounded animation frames before completion', async () => {
  const rendered = []
  const frames = []
  const renderer = createIncrementalTextRenderer(
    (text) => rendered.push(text),
    {
      charsPerFrame: 2,
      schedule: (callback) => {
        frames.push(callback)
        return frames.length
      },
      cancel: () => {},
    },
  )

  renderer.enqueue('甲乙丙丁')
  renderer.enqueue('戊己')
  const completion = renderer.whenIdle()

  assert.deepEqual(rendered, [])
  assert.equal(frames.length, 1)

  frames.shift()()
  assert.deepEqual(rendered, ['甲乙'])
  assert.equal(frames.length, 1)

  frames.shift()()
  assert.deepEqual(rendered, ['甲乙', '丙丁'])

  frames.shift()()
  await completion
  assert.deepEqual(rendered, ['甲乙', '丙丁', '戊己'])
})


test('stopping the renderer discards buffered text that has not been painted', () => {
  const rendered = []
  const frames = []
  const renderer = createIncrementalTextRenderer(
    (text) => rendered.push(text),
    {
      charsPerFrame: 1,
      schedule: (callback) => {
        frames.push(callback)
        return frames.length
      },
      cancel: () => {},
    },
  )

  renderer.enqueue('甲乙')
  renderer.stop()
  frames.shift()()

  assert.deepEqual(rendered, [])
  assert.equal(renderer.pendingCharacters(), 0)
})
