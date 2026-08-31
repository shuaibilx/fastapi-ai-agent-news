const scheduleFrame = (callback) => {
  if (typeof requestAnimationFrame === 'function') {
    return requestAnimationFrame(callback)
  }
  return setTimeout(callback, 16)
}


const cancelFrame = (handle) => {
  if (typeof cancelAnimationFrame === 'function') {
    cancelAnimationFrame(handle)
    return
  }
  clearTimeout(handle)
}


export function createIncrementalTextRenderer(
  appendText,
  {
    charsPerFrame = 12,
    schedule = scheduleFrame,
    cancel = cancelFrame,
  } = {},
) {
  let bufferedText = ''
  let frameHandle = null
  let stopped = false
  const idleResolvers = []

  const resolveIdle = () => {
    if (bufferedText || frameHandle !== null) return
    while (idleResolvers.length) idleResolvers.shift()()
  }

  const renderFrame = () => {
    frameHandle = null
    if (stopped) {
      resolveIdle()
      return
    }

    const nextText = bufferedText.slice(0, charsPerFrame)
    bufferedText = bufferedText.slice(charsPerFrame)
    if (nextText) appendText(nextText)

    if (bufferedText) {
      frameHandle = schedule(renderFrame)
      return
    }
    resolveIdle()
  }

  const scheduleRender = () => {
    if (stopped || frameHandle !== null || !bufferedText) return
    frameHandle = schedule(renderFrame)
  }

  return {
    enqueue(text) {
      if (stopped || !text) return
      bufferedText += text
      scheduleRender()
    },
    whenIdle() {
      if (!bufferedText && frameHandle === null) return Promise.resolve()
      return new Promise((resolve) => idleResolvers.push(resolve))
    },
    stop() {
      stopped = true
      bufferedText = ''
      if (frameHandle !== null) cancel(frameHandle)
      frameHandle = null
      resolveIdle()
    },
    pendingCharacters() {
      return bufferedText.length
    },
  }
}
