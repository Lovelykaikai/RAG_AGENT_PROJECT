const STORAGE_KEY = "tourism-agent-sessions-v2";

const WELCOME_MESSAGE = {
  id: "welcome",
  role: "assistant",
  content: "你好，我是你的行程规划助手。告诉我目的地、天数和出发偏好，我会帮你整理成一份可执行的旅游攻略。",
  createdAt: new Date().toISOString(),
};

function makeId() {
  if (globalThis.crypto?.randomUUID) {
    return `thread_${globalThis.crypto.randomUUID()}`;
  }
  return `thread_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function makeSession() {
  const now = new Date().toISOString();
  return {
    threadId: makeId(),
    title: "新的行程",
    createdAt: now,
    updatedAt: now,
    messages: [{ ...WELCOME_MESSAGE, id: `${makeId()}_welcome` }],
  };
}

function normalizeMessage(message) {
  return {
    id: message.id || makeId(),
    role: message.role === "user" ? "user" : message.role === "tool" ? "tool" : "assistant",
    content: typeof message.content === "string" ? message.content : String(message.content || ""),
    createdAt: message.createdAt || new Date().toISOString(),
    tool: message.tool || "",
    status: message.status || "",
  };
}

function normalizeSession(session) {
  return {
    threadId: session.threadId || makeId(),
    title: session.title || "新的行程",
    createdAt: session.createdAt || new Date().toISOString(),
    updatedAt: session.updatedAt || session.createdAt || new Date().toISOString(),
    messages: Array.isArray(session.messages) ? session.messages.map(normalizeMessage) : [],
  };
}

function loadData() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      const firstSession = makeSession();
      return {
        activeThreadId: firstSession.threadId,
        sessions: [firstSession],
      };
    }

    const parsed = JSON.parse(raw);
    const sessions = Array.isArray(parsed.sessions) && parsed.sessions.length
      ? parsed.sessions.map(normalizeSession)
      : [makeSession()];
    const activeThreadId = sessions.some((session) => session.threadId === parsed.activeThreadId)
      ? parsed.activeThreadId
      : sessions[0].threadId;

    return { activeThreadId, sessions };
  } catch (error) {
    console.warn("无法读取本地会话数据，将创建新的演示会话。", error);
    const firstSession = makeSession();
    return {
      activeThreadId: firstSession.threadId,
      sessions: [firstSession],
    };
  }
}

export class SessionStore {
  constructor() {
    this.data = loadData();
    this.persist();
  }

  persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.data));
  }

  get sessions() {
    return [...this.data.sessions].sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
  }

  get activeThreadId() {
    return this.data.activeThreadId;
  }

  get activeSession() {
    return this.data.sessions.find((session) => session.threadId === this.activeThreadId);
  }

  createSession() {
    const session = makeSession();
    this.data.sessions.push(session);
    this.data.activeThreadId = session.threadId;
    this.persist();
    return session;
  }

  activate(threadId) {
    if (!this.data.sessions.some((session) => session.threadId === threadId)) {
      return null;
    }
    this.data.activeThreadId = threadId;
    this.persist();
    return this.activeSession;
  }

  addMessage(message, threadId = this.activeThreadId) {
    const session = this.data.sessions.find((item) => item.threadId === threadId);
    if (!session) {
      return null;
    }
    session.messages.push(normalizeMessage(message));
    session.updatedAt = new Date().toISOString();
    this.persist();
    return session.messages.at(-1);
  }

  updateMessage(messageId, patch, threadId = this.activeThreadId) {
    const session = this.data.sessions.find((item) => item.threadId === threadId);
    const message = session?.messages.find((item) => item.id === messageId);
    if (!message) {
      return null;
    }
    Object.assign(message, patch);
    session.updatedAt = new Date().toISOString();
    this.persist();
    return message;
  }

  renameFromMessage(message, threadId = this.activeThreadId) {
    const session = this.data.sessions.find((item) => item.threadId === threadId);
    if (!session || session.title !== "新的行程") {
      return;
    }
    const title = message.replace(/\s+/g, " ").trim();
    if (title) {
      session.title = title.length > 24 ? `${title.slice(0, 24)}...` : title;
      session.updatedAt = new Date().toISOString();
      this.persist();
    }
  }

  clearActiveSession() {
    const session = this.activeSession;
    if (!session) {
      return null;
    }
    session.messages = [{ ...WELCOME_MESSAGE, id: `${makeId()}_welcome` }];
    session.title = "新的行程";
    session.updatedAt = new Date().toISOString();
    this.persist();
    return session;
  }
}

export { STORAGE_KEY };
