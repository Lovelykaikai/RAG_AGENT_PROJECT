import {
  createSession as createRemoteSession,
  getSessionMessages,
  listSessions,
  resetSession as resetRemoteSession,
  streamChat,
  deleteSession as deleteRemoteSession,
  renameSession as renameRemoteSession,
} from "./api-client.js";
import { SessionStore } from "./state.js";
import {
  appendMessage,
  appendMessageText,
  appendToolEvent,
  appendTypingMessage,
  renderConversation,
  renderSessions,
  toolLabel,
  updateMessage,
} from "./message-renderer.js";

const store = new SessionStore();
const elements = {
  sidebar: document.querySelector("#sidebar"),
  sidebarBackdrop: document.querySelector("#sidebarBackdrop"),
  sessionList: document.querySelector("#sessionList"),
  sessionCount: document.querySelector("#sessionCount"),
  sessionTitle: document.querySelector("#sessionTitle"),
  chatLog: document.querySelector("#chatLog"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  sendBtn: document.querySelector("#sendBtn"),
  clearBtn: document.querySelector("#clearBtn"),
  newSessionBtn: document.querySelector("#newSessionBtn"),
  menuBtn: document.querySelector("#menuBtn"),
  connectionStatus: document.querySelector("#connectionStatus"),
  storageMode: document.querySelector("#storageMode"),
};

let isBusy = false;
let backendReady = false;

function render() {
  const session = store.activeSession;
  if (!session) {
    return;
  }
  renderSessions(elements.sessionList, store.sessions, store.activeThreadId, activateSession);
  renderConversation(elements.chatLog, session);
  elements.sessionCount.textContent = String(store.sessions.length);
  elements.sessionTitle.textContent = session.title;
}

function setBusy(busy) {
  isBusy = busy;
  elements.sendBtn.disabled = busy;
  elements.messageInput.disabled = busy;
  elements.newSessionBtn.disabled = busy;
  elements.clearBtn.disabled = busy;
  elements.sendBtn.querySelector(".send-label").textContent = busy ? "生成中" : "发送";
  elements.connectionStatus.textContent = busy ? "Agent 正在工作" : "等待输入";
  const statusDot = elements.connectionStatus.previousElementSibling;
  statusDot?.classList.toggle("is-ready", !busy);
  statusDot?.classList.remove("is-error");
}

function setBackendState(isReady) {
  backendReady = isReady;
  elements.storageMode.textContent = isReady ? "MySQL 会话已连接" : "本地演示模式";
}

async function loadHistory(threadId) {
  if (!backendReady) {
    return;
  }
  try {
    const messages = await getSessionMessages(threadId);
    store.replaceMessages(messages, threadId);
  } catch (error) {
    // localStorage 中的旧会话可能尚未同步到 MySQL，保留本地消息作为回退。
    if (error.status !== 404) {
      console.warn("无法加载服务器历史消息，将继续显示本地缓存。", error);
    }
  }
}

async function activateSession(threadId, action) {
  // 处理重命名和删除操作
  if (action === "rename") {
    await handleRenameSession(threadId);
    return;
  }
  if (action === "delete") {
    await handleDeleteSession(threadId);
    return;
  }

  // 正常的会话切换
  if (isBusy || !store.activate(threadId)) {
    return;
  }
  render();
  closeSidebar();
  await loadHistory(threadId);
  render();
  elements.messageInput.focus();
}

async function createSession() {
  if (isBusy) {
    return;
  }
  if (backendReady) {
    try {
      store.addRemoteSession(await createRemoteSession());
    } catch (error) {
      console.warn("无法创建服务器会话，切换到本地演示模式。", error);
      setBackendState(false);
      store.createSession();
    }
  } else {
    store.createSession();
  }
  render();
  closeSidebar();
  elements.messageInput.focus();
}

async function clearSession() {
  if (isBusy) {
    return;
  }
  const threadId = store.activeThreadId;
  if (backendReady) {
    try {
      await resetRemoteSession(threadId);
    } catch (error) {
      if (error.status !== 404) {
        console.warn("服务器会话清空失败，保留本地清空结果。", error);
      }
    }
  }
  store.clearActiveSession();
  render();
  elements.messageInput.focus();
}

async function handleRenameSession(threadId) {
  const session = store.sessions.find((s) => s.threadId === threadId);
  if (!session) {
    return;
  }

  const newTitle = prompt("输入新的会话名称：", session.title);
  if (!newTitle || newTitle.trim() === "") {
    return;
  }

  const trimmedTitle = newTitle.trim();
  if (trimmedTitle === session.title) {
    return;
  }

  // 更新本地状态
  store.renameSession(threadId, trimmedTitle);

  // 同步到后端
  if (backendReady) {
    try {
      await renameRemoteSession(threadId, trimmedTitle);
    } catch (error) {
      console.warn("后端重命名失败，保留本地修改。", error);
    }
  }

  render();
}

async function handleDeleteSession(threadId) {
  const session = store.sessions.find((s) => s.threadId === threadId);
  if (!session) {
    return;
  }

  if (!confirm(`确定删除会话「${session.title}」吗？此操作无法撤销。`)) {
    return;
  }

  // 先从后端删除
  if (backendReady) {
    try {
      await deleteRemoteSession(threadId);
    } catch (error) {
      if (error.status !== 404) {
        console.warn("后端删除失败，仍将从本地移除。", error);
      }
    }
  }

  // 删除本地会话
  store.deleteSession(threadId);
  render();
  elements.messageInput.focus();
}

function openSidebar() {
  elements.sidebar.classList.add("is-open");
  elements.sidebarBackdrop.hidden = false;
}

function closeSidebar() {
  elements.sidebar.classList.remove("is-open");
  elements.sidebarBackdrop.hidden = true;
}

function resizeInput() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 150)}px`;
}

async function submitMessage(event) {
  event.preventDefault();
  const message = elements.messageInput.value.trim();
  const session = store.activeSession;
  if (!message || !session || isBusy) {
    return;
  }

  const threadId = session.threadId;
  store.addMessage({ role: "user", content: message }, threadId);
  store.renameFromMessage(message, threadId);
  const assistantMessage = store.addMessage({ role: "assistant", content: "", status: "pending" }, threadId);
  elements.messageInput.value = "";
  resizeInput();
  render();

  const assistantRow = elements.chatLog.querySelector(`[data-message-id="${assistantMessage.id}"]`)
    || appendTypingMessage(elements.chatLog, assistantMessage.id);
  updateMessage(assistantRow, "");
  assistantRow.dataset.started = "true";
  setBusy(true);
  let requestFailed = false;

  try {
    await streamChat({
      threadId,
      message,
      onEvent: (eventData) => handleAgentEvent(eventData, threadId, assistantMessage.id, assistantRow),
    });

    if (!assistantRow.querySelector(".message-bubble").textContent.trim()) {
      updateMessage(assistantRow, "没有生成有效回答，请换一种方式描述你的旅行需求。", true);
      store.updateMessage(assistantMessage.id, {
        content: "没有生成有效回答，请换一种方式描述你的旅行需求。",
        status: "error",
      }, threadId);
    } else {
      store.updateMessage(assistantMessage.id, { status: "complete" }, threadId);
    }
  } catch (error) {
    requestFailed = true;
    const content = error.message || "Agent 服务暂时不可用，请稍后重试。";
    updateMessage(assistantRow, content, true);
    store.updateMessage(assistantMessage.id, { content, status: "error" }, threadId);
  } finally {
    setBusy(false);
    if (requestFailed) {
      elements.connectionStatus.textContent = "服务暂时不可用";
      elements.connectionStatus.previousElementSibling?.classList.remove("is-ready");
      elements.connectionStatus.previousElementSibling?.classList.add("is-error");
    }
    renderSessions(elements.sessionList, store.sessions, store.activeThreadId, activateSession);
    elements.sessionTitle.textContent = store.activeSession?.title || "新的行程";
    elements.messageInput.focus();
  }
}

async function bootstrap() {
  try {
    const remoteSessions = await listSessions();
    setBackendState(true);
    if (remoteSessions.length) {
      store.replaceFromRemote(remoteSessions);
      await loadHistory(store.activeThreadId);
    }
  } catch (error) {
    setBackendState(false);
    console.warn("无法连接会话 API，将使用 localStorage 演示模式。", error);
  }
  render();
  elements.messageInput.focus();
}

function handleAgentEvent(eventData, threadId, assistantMessageId, assistantRow) {
  const type = eventData.type;
  if (type === "tool_call") {
    const label = toolLabel(eventData);
    appendToolEvent(elements.chatLog, label);
    store.addMessage({ role: "tool", content: label, tool: eventData.tool, status: "running" }, threadId);
    return;
  }

  if (type === "tool_done") {
    appendToolEvent(elements.chatLog, `${toolLabel(eventData)}，已完成`, true);
    return;
  }

  if (type === "chunk" || type === "message") {
    appendMessageText(assistantRow, eventData.content || "");
    store.updateMessage(assistantMessageId, {
      content: assistantRow.querySelector(".message-bubble").textContent,
      status: "streaming",
    }, threadId);
    return;
  }

  if (type === "error") {
    throw new Error(eventData.content || "Agent 执行失败");
  }
}

elements.chatForm.addEventListener("submit", submitMessage);
elements.messageInput.addEventListener("input", resizeInput);
elements.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    elements.chatForm.requestSubmit();
  }
});
elements.newSessionBtn.addEventListener("click", createSession);
elements.clearBtn.addEventListener("click", clearSession);
elements.menuBtn.addEventListener("click", openSidebar);
elements.sidebarBackdrop.addEventListener("click", closeSidebar);

bootstrap();
