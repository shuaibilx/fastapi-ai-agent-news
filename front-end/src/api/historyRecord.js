export function getHistoryRecordId(item) {
  const historyId = Number(item?.historyId)
  if (!Number.isInteger(historyId) || historyId < 1) {
    throw new Error('historyId is required for a server-backed history record')
  }
  return historyId
}


export function getHistoryRenderKey(item) {
  const historyId = Number(item?.historyId)
  return Number.isInteger(historyId) && historyId > 0
    ? `server:${historyId}`
    : `local:${item?.id}`
}
