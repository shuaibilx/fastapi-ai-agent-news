import axios from 'axios'

import { apiConfig } from '../config/api.js'
import { buildAgentRequest } from './agentConversation.js'


export async function getNewsSummary(newsId, token) {
  const response = await axios.post(
    `${apiConfig.baseURL}/api/ai/news/${newsId}/summary`,
    undefined,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  return response.data
}

export async function askNewsAgent(message, conversationId, token) {
  const response = await axios.post(
    `${apiConfig.baseURL}/api/ai/agent`,
    buildAgentRequest(message, conversationId),
    { headers: { Authorization: `Bearer ${token}` } },
  )
  return response.data
}


function abortError() {
  const error = new Error('SSE request aborted')
  error.name = 'AbortError'
  return error
}


function parseSseBlock(block) {
  let event = 'message'
  const data = []
  for (const line of block.replace(/\r/g, '').split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (!data.length) return null
  try {
    return { event, data: JSON.parse(data.join('\n')) }
  } catch {
    throw new Error('SSE response contains invalid JSON data')
  }
}


export async function consumeSseResponse(response, { onEvent, signal } = {}) {
  if (!response.ok) {
    const detail = await response.text()
    const error = new Error(`SSE request failed (${response.status}): ${detail || 'unknown error'}`)
    error.status = response.status
    throw error
  }
  if (!response.body) throw new Error('SSE response body is unavailable')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let aborted = false
  const onAbort = () => {
    aborted = true
    void reader.cancel()
  }
  signal?.addEventListener('abort', onAbort, { once: true })

  const dispatch = (block) => {
    const parsed = parseSseBlock(block)
    if (!parsed) return
    if (parsed.event === 'error') {
      throw new Error(parsed.data?.message || 'AI stream failed')
    }
    onEvent?.(parsed)
  }

  try {
    if (signal?.aborted) onAbort()
    while (true) {
      if (aborted) throw abortError()
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let separator
      while ((separator = buffer.search(/\r?\n\r?\n/)) >= 0) {
        const block = buffer.slice(0, separator)
        const separatorLength = buffer.startsWith('\r\n', separator) ? 4 : 2
        buffer = buffer.slice(separator + separatorLength)
        dispatch(block)
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
    if (aborted) throw abortError()
  } finally {
    signal?.removeEventListener('abort', onAbort)
    reader.releaseLock?.()
  }
}


export async function streamNewsAgent(message, conversationId, token, {
  onEvent,
  signal,
  fetchImpl = fetch,
} = {}) {
  const response = await fetchImpl(`${apiConfig.baseURL}/api/ai/agent/stream`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(buildAgentRequest(message, conversationId)),
    signal,
  })
  await consumeSseResponse(response, { onEvent, signal })
}
