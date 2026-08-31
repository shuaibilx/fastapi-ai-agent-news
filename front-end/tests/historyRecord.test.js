import assert from 'node:assert/strict'
import test from 'node:test'

import { getHistoryRecordId, getHistoryRenderKey } from '../src/api/historyRecord.js'


test('history rows with the same news id use their distinct historyId values', () => {
  const firstView = { id: 16, historyId: 41, title: '同一篇新闻' }
  const secondView = { id: 16, historyId: 42, title: '同一篇新闻' }

  assert.equal(getHistoryRecordId(firstView), 41)
  assert.equal(getHistoryRecordId(secondView), 42)
  assert.notEqual(getHistoryRecordId(firstView), getHistoryRecordId(secondView))
})


test('history rows without a backend historyId are rejected instead of deleting by news id', () => {
  assert.throws(
    () => getHistoryRecordId({ id: 16, title: '缺少历史记录 ID' }),
    /historyId/,
  )
})


test('local fallback history keeps a stable key without pretending to have a server historyId', () => {
  assert.equal(
    getHistoryRenderKey({ id: 16, title: '本地历史' }),
    'local:16',
  )
})
