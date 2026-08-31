import assert from 'node:assert/strict'
import test from 'node:test'

import { consumeSseResponse, streamNewsAgent } from '../src/api/ai.js'


function responseFromChunks(chunks, status = 200) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  }), { status, headers: { 'content-type': 'text/event-stream' } })
}


test('SSE consumer preserves split UTF-8 bytes and event fragments', async () => {
  const payload = 'event: delta\ndata: {"text":"你好"}\n\nevent: done\ndata: {"citations":[]}\n\n'
  const bytes = new TextEncoder().encode(payload)
  const received = []

  await consumeSseResponse(
    responseFromChunks([bytes.slice(0, 25), bytes.slice(25, 28), bytes.slice(28)]),
    { onEvent: (event) => received.push(event) },
  )

  assert.deepEqual(received, [
    { event: 'delta', data: { text: '你好' } },
    { event: 'done', data: { citations: [] } },
  ])
})


test('SSE consumer rejects server error events and HTTP errors', async () => {
  await assert.rejects(
    consumeSseResponse(
      responseFromChunks([new TextEncoder().encode('event: error\ndata: {"message":"服务不可用"}\n\n')]),
      { onEvent: () => {} },
    ),
    /服务不可用/,
  )

  await assert.rejects(
    consumeSseResponse(new Response('登录令牌无效', { status: 401 }), { onEvent: () => {} }),
    (error) => {
      assert.equal(error.status, 401)
      assert.match(error.message, /401/)
      return true
    },
  )
})


test('streamNewsAgent sends bearer auth and cancels its active reader', async () => {
  const controller = new AbortController()
  let cancelled = false
  let sentRequest
  const fetchImpl = async (url, options) => {
    sentRequest = { url, options }
    return {
      ok: true,
      status: 200,
      body: {
        getReader() {
          return {
            read: () => new Promise(() => {}),
            cancel: async () => { cancelled = true },
            releaseLock: () => {},
          }
        },
      },
    }
  }

  const streaming = streamNewsAgent('我的历史', null, 'app-token', {
    signal: controller.signal,
    onEvent: () => {},
    fetchImpl,
  })
  controller.abort()

  await assert.rejects(streaming, /aborted/i)
  assert.equal(cancelled, true)
  assert.equal(sentRequest.options.headers.Authorization, 'Bearer app-token')
  assert.deepEqual(JSON.parse(sentRequest.options.body), { message: '我的历史' })
})
