<template>
  <div class="ai-chat-container">
    <van-nav-bar title="AI新闻助手" right-text="新对话" fixed @click-right="startNewConversation" />
    
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
            <div v-if="message.role === 'assistant' && message.toolCalls?.length" class="tool-calls">
              <div class="tool-calls-title">已使用工具</div>
              <div v-for="(toolCall, toolIndex) in message.toolCalls" :key="`${toolCall.name}-${toolIndex}`" class="tool-call-item">
                <span>{{ toolCall.name }}</span>
                <span>{{ toolCall.summary }}</span>
              </div>
            </div>
            <div v-if="message.role === 'assistant' && message.memoryStatus === 'unavailable'" class="memory-warning">
              对话记忆暂不可用，本次回答未受影响。
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
          :disabled="!isLoading && !userInput.trim()"
          @click="isLoading ? stopGeneration() : sendMessage()"
        >
          {{ isLoading ? '停止生成' : '发送' }}
        </van-button>
      </div>
    </div>
    
    <tab-bar />
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue';
import { useRouter } from 'vue-router';
import TabBar from '../components/TabBar.vue';
import { showToast } from 'vant';
import * as marked from 'marked';
import DOMPurify from 'dompurify';
import { streamNewsAgent } from '../api/ai';
import { readConversationId } from '../api/agentConversation';
import { createIncrementalTextRenderer } from '../api/streamTextRenderer';
import { useUserStore } from '../store/user';
import { appendChatMessage } from '../utils/chatMessages';

const userStore = useUserStore();
const router = useRouter();

// 聊天消息
const createWelcomeMessage = () => ({
  role: 'assistant',
  content: '你好！我是AI新闻助手，可以检索新闻，也可以查询你的收藏和浏览历史。',
  citations: [],
  toolCalls: [],
  memoryStatus: 'empty',
});

const messages = ref([createWelcomeMessage()]);
const userInput = ref('');
const messagesContainer = ref(null);
const isLoading = ref(false);
const conversationId = ref(null);
const streamController = ref(null);

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
  messages.value.push({ role: 'user', content: userMessage, citations: [], toolCalls: [] });
  userInput.value = '';

  const assistantMessage = appendChatMessage(messages, {
    role: 'assistant',
    content: '',
    citations: [],
    toolCalls: [],
    memoryStatus: 'empty',
  });

  await nextTick();
  scrollToBottom();

  const controller = new AbortController();
  const textRenderer = createIncrementalTextRenderer((text) => {
    assistantMessage.content += text;
  });
  streamController.value = controller;
  let completed = false;
  isLoading.value = true;
  try {
    await streamNewsAgent(
      userMessage,
      conversationId.value,
      userStore.token,
      {
        signal: controller.signal,
        onEvent: ({ event, data }) => {
          if (event === 'meta' && data.conversationId) {
            conversationId.value = readConversationId(data);
            assistantMessage.memoryStatus = data.memoryStatus || 'empty';
          } else if (event === 'delta') {
            textRenderer.enqueue(data.text || '');
          } else if (event === 'tool') {
            assistantMessage.toolCalls.push(data);
          } else if (event === 'citation') {
            if (!assistantMessage.citations.some((item) => item.newsId === data.newsId)) {
              assistantMessage.citations.push(data);
            }
          } else if (event === 'done') {
            completed = true;
            conversationId.value = readConversationId(data);
            assistantMessage.citations = data.citations || assistantMessage.citations;
            assistantMessage.toolCalls = data.toolCalls || assistantMessage.toolCalls;
            assistantMessage.memoryStatus = data.memoryStatus || assistantMessage.memoryStatus;
          }
        },
      },
    );
    if (!completed) throw new Error('AI 流在完成前中断');
    await textRenderer.whenIdle();
  } catch (error) {
    console.error('AI Agent 请求失败:', error);
    if (error.name === 'AbortError') {
      textRenderer.stop();
      assistantMessage.content = assistantMessage.content
        ? `${assistantMessage.content}\n\n_已停止生成。_`
        : '已停止生成。';
    } else if (error.status === 401) {
      textRenderer.stop();
      userStore.logout();
      messages.value.pop();
      showToast({ message: '登录已失效，请重新登录', position: 'bottom' });
      await router.replace('/login');
    } else {
      await textRenderer.whenIdle();
      assistantMessage.content = assistantMessage.content ||
        error.message || '问答服务暂时不可用，请稍后重试';
    }
  } finally {
    if (streamController.value === controller) {
      streamController.value = null;
      isLoading.value = false;
    }
    await nextTick();
    scrollToBottom();
  }
};

const stopGeneration = () => {
  streamController.value?.abort();
};

const startNewConversation = () => {
  if (isLoading.value) return;
  conversationId.value = null;
  messages.value = [createWelcomeMessage()];
  userInput.value = '';
  showToast({ message: '已开始新对话', position: 'bottom' });
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

.tool-calls,
.memory-warning {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
  font-size: 12px;
}

.tool-calls-title {
  color: #8790a3;
  margin-bottom: 4px;
}

.tool-call-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: #666;
  margin-bottom: 3px;
}

.tool-call-item span:first-child {
  color: #1989fa;
}

.memory-warning {
  color: #ed6a0c;
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
