export function buildAgentRequest(message, conversationId) {
  const payload = { message: message.trim() }
  if (conversationId) {
    payload.conversationId = conversationId
  }
  return payload
}

export function readConversationId(data) {
  if (!data?.conversationId || typeof data.conversationId !== 'string') {
    throw new Error('Agent 响应缺少有效的 conversationId')
  }
  return data.conversationId
}
