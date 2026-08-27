import axios from 'axios'

import { apiConfig } from '../config/api'
import { buildAgentRequest } from './agentConversation'


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
