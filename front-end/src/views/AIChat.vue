<template>
  <div class="ai-chat-container">
    <van-nav-bar title="AI问答" fixed />
    
    <div class="chat-content">
      <div class="messages-container" ref="messagesContainer">
        <div 
          v-for="(message, index) in messages" 
          :key="index" 
          :class="['message', message.role === 'user' ? 'user-message' : 'ai-message']"
        >
          <div class="message-content">
            <div v-if="message.role === 'assistant' && message.content === ''" class="typing-indicator">
              <span></span>
              <span></span>
              <span></span>
            </div>
            <div v-else v-html="formatMessage(message.content)"></div>
            <div v-if="message.role === 'assistant' && message.citations?.length" class="citations">
              <div class="citations-title">参考新闻</div>
              <div 
                v-for="citation in message.citations" 
                :key="citation.newsId" 
                class="citation-item"
              >
                <span class="citation-title">{{ citation.title }}</span>
                <span class="citation-excerpt">{{ citation.excerpt }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <div class="input-container">
        <van-field
          v-model="userInput"
          rows="1"
          autosize
          type="textarea"
          placeholder="请输入问题..."
          class="chat-input"
          @keypress.enter.prevent="sendMessage"
        />
        <van-button 
          type="primary" 
          class="send-button" 
          :disabled="isLoading || !userInput.trim()" 
          @click="sendMessage"
        >
          发送
        </van-button>
      </div>
    </div>
    
    <tab-bar />
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue';
import axios from 'axios';
import TabBar from '../components/TabBar.vue';
import { showToast } from 'vant';
import * as marked from 'marked';
import DOMPurify from 'dompurify';
import { apiConfig } from '../config/api';
import { useUserStore } from '../store/user';

const userStore = useUserStore();

// 聊天消息
const messages = ref([
  { role: 'assistant', content: '你好！我是AI助手，可以回答与新闻相关的问题。', citations: [] }
]);
const userInput = ref('');
const messagesContainer = ref(null);
const isLoading = ref(false);

// 格式化消息内容（支持Markdown）
const formatMessage = (content) => {
  if (!content) return '';
  return DOMPurify.sanitize(marked.parse(content));
};

// 发送消息
const sendMessage = async () => {
  if (!userInput.value.trim() || isLoading.value) return;

  if (!userStore.getLoginStatus) {
    showToast({ message: '请先登录后再提问', position: 'bottom' });
    return;
  }

  const userMessage = userInput.value.trim();
  messages.value.push({ role: 'user', content: userMessage, citations: [] });
  userInput.value = '';

  // 添加AI消息占位
  messages.value.push({ role: 'assistant', content: '', citations: [] });

  await nextTick();
  scrollToBottom();

  isLoading.value = true;
  try {
    const response = await axios.post(
      `${apiConfig.baseURL}/api/ai/qa`,
      { question: userMessage },
      { headers: { Authorization: `Bearer ${userStore.token}` } },
    );

    if (response.data.code !== 200) {
      throw new Error(response.data.message || '问答请求失败');
    }

    messages.value[messages.value.length - 1].content = response.data.data.answer;
    messages.value[messages.value.length - 1].citations = response.data.data.citations || [];
  } catch (error) {
    console.error('AI问答请求失败:', error);
    messages.value[messages.value.length - 1].content =
      error.response?.data?.message || error.message || '问答服务暂时不可用，请稍后重试';
  } finally {
    isLoading.value = false;
    await nextTick();
    scrollToBottom();
  }
};

// 滚动到底部
const scrollToBottom = () => {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
};

// 监听消息变化，自动滚动
watch(messages, () => {
  nextTick(scrollToBottom);
}, { deep: true });

// 组件挂载时滚动到底部
onMounted(() => {
  scrollToBottom();
});
</script>

<style scoped>
.ai-chat-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding-top: 46px;
  padding-bottom: 50px;
  box-sizing: border-box;
}

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.message {
  margin-bottom: 10px;
  max-width: 80%;
}

.user-message {
  margin-left: auto;
}

.ai-message {
  margin-right: auto;
}

.message-content {
  padding: 10px;
  border-radius: 10px;
  word-break: break-word;
}

.user-message .message-content {
  background-color: #007aff;
  color: white;
}

.ai-message .message-content {
  background-color: #f2f2f2;
  color: #333;
}

.input-container {
  display: flex;
  padding: 10px;
  border-top: 1px solid #eee;
  background-color: #fff;
}

.chat-input {
  flex: 1;
  margin-right: 10px;
}

.send-button {
  align-self: flex-end;
}

.citations {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}

.citations-title {
  font-size: 12px;
  color: #8790a3;
  margin-bottom: 4px;
}

.citation-item {
  display: flex;
  flex-direction: column;
  margin-bottom: 4px;
}

.citation-title {
  font-size: 13px;
  color: #1989fa;
  font-weight: 500;
}

.citation-excerpt {
  font-size: 12px;
  color: #666;
  margin-top: 2px;
  line-height: 1.5;
}

/* Markdown 样式 */
.message-content pre {
  background-color: #f8f8f8;
  padding: 10px;
  border-radius: 5px;
  overflow-x: auto;
}

.message-content code {
  background-color: rgba(0, 0, 0, 0.05);
  padding: 2px 4px;
  border-radius: 3px;
}

.message-content img {
  max-width: 100%;
}

/* 打字指示器 */
.typing-indicator {
  display: flex;
  padding: 5px;
}

.typing-indicator span {
  height: 8px;
  width: 8px;
  background-color: #999;
  border-radius: 50%;
  margin: 0 2px;
  display: inline-block;
  animation: bounce 1.5s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 60%, 100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-5px);
  }
}
</style>
