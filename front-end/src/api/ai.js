import axios from 'axios'

import { apiConfig } from '../config/api'


export async function getNewsSummary(newsId, token) {
  const response = await axios.post(
    `${apiConfig.baseURL}/api/ai/news/${newsId}/summary`,
    undefined,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  return response.data
}
