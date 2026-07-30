function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function readNdjsonStream(response, onEvent) {
  if (!response.body) {
    throw new Error("服务没有返回可读取的消息流");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const consume = (line) => {
    if (!line.trim()) {
      return;
    }
    try {
      onEvent(JSON.parse(line));
    } catch (error) {
      throw new Error(`无法解析 Agent 消息：${error.message}`);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    lines.forEach(consume);
    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    consume(buffer);
  }
}

export async function runDemoStream(query, threadId, onEvent) {
  onEvent({ type: "tool_call", tool: "demo_context", args: {} });
  await wait(260);
  onEvent({ type: "tool_done", tool: "demo_context" });
  await wait(180);

  const answer = `这是前端演示回复。\n\n我已经记住了本窗口的会话，当前 thread_id 为：${threadId}\n\n后端接入 MySQL Checkpointer 后，这里会替换为真实的旅游攻略 Agent 输出。`;
  const chunks = answer.match(/.{1,18}/gs) || [answer];
  for (const chunk of chunks) {
    onEvent({ type: "chunk", content: chunk });
    await wait(24);
  }
  onEvent({ type: "done" });
}
