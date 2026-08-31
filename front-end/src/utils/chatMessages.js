export function appendChatMessage(messages, message) {
  messages.value.push(message)
  return messages.value[messages.value.length - 1]
}
