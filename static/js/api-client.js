import { readNdjsonStream, runDemoStream } from "./stream-parser.js";

const API = {
  chat: "/api/chat",
  sessions: "/api/sessions",
  messages: (threadId) => `/api/sessions/${encodeURIComponent(threadId)}/messages`,
};

class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function requestJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new ApiError("后端服务不可用", 0);
  }

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(data.detail || `请求失败（${response.status}）`, response.status);
  }
  return response.json();
}

export async function listSessions() {
  return requestJson(API.sessions);
}

export async function createSession() {
  return requestJson(API.sessions, { method: "POST" });
}

export async function getSessionMessages(threadId) {
  return requestJson(API.messages(threadId));
}

export async function resetSession(threadId) {
  return requestJson(`${API.sessions}/${encodeURIComponent(threadId)}/reset`, { method: "POST" });
}

export async function renameSession(threadId, title) {
  return requestJson(`${API.sessions}/${encodeURIComponent(threadId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

async function requestChat(threadId, message) {
  let response;
  try {
    response = await fetch(API.chat, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message,
        // TODO: 后端接入 checkpointer 后，使用该 thread_id 恢复对应会话。
        thread_id: threadId,
      }),
    });
  } catch (error) {
    // 后端尚未启动时保留可操作的前端演示，不影响 localStorage 会话展示。
    return { mode: "demo", reason: error };
  }

  if (response.status === 404 || response.status === 405) {
    return { mode: "demo", reason: new ApiError("聊天接口尚未接入", response.status) };
  }

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail || `Agent 服务暂时不可用（${response.status}）`;
    throw new ApiError(detail, response.status);
  }

  return { mode: "api", response };
}

export async function streamChat({ threadId, message, onEvent }) {
  const result = await requestChat(threadId, message);
  if (result.mode === "demo") {
    await runDemoStream(message, threadId, onEvent);
    return { mode: "demo" };
  }

  await readNdjsonStream(result.response, onEvent);
  return { mode: "api" };
}

export { API, ApiError };
