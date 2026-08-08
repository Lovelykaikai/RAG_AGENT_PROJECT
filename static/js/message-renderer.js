function makeElement(tag, className, text = "") {
  const element = document.createElement(tag);
  element.className = className;
  if (text) {
    element.textContent = text;
  }
  return element;
}

function scrollToBottom(container) {
  container.scrollTop = container.scrollHeight;
}

function renderMarkdown(markdown) {
  if (!markdown || typeof markdown !== "string") {
    return "";
  }

  // marked 和 DOMPurify 通过 <script> 标签全局引入
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    console.warn("Markdown 渲染库未加载，回退到纯文本显示");
    return markdown;
  }

  try {
    const rawHtml = marked.parse(markdown, {
      breaks: true,        // 单换行转 <br>
      gfm: true,           // GitHub Flavored Markdown（表格、删除线等）
    });
    return DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: [
        "p", "br", "strong", "em", "u", "s", "code", "pre",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li",
        "blockquote",
        "table", "thead", "tbody", "tr", "th", "td",
        "a", "img",
      ],
      ALLOWED_ATTR: ["href", "src", "alt", "title", "class"],
    });
  } catch (error) {
    console.error("Markdown 渲染失败:", error);
    return markdown;
  }
}

export function renderSessions(container, sessions, activeThreadId, onSelect) {
  container.replaceChildren();

  sessions.forEach((session) => {
    const button = makeElement("button", `session-item${session.threadId === activeThreadId ? " is-active" : ""}`);
    button.type = "button";
    button.dataset.threadId = session.threadId;
    button.setAttribute("aria-current", session.threadId === activeThreadId ? "page" : "false");

    const copy = makeElement("span", "session-copy");
    copy.append(
      makeElement("span", "session-name", session.title),
      makeElement("span", "session-meta", formatSessionTime(session.updatedAt)),
    );
    button.append(copy);
    button.addEventListener("click", () => onSelect(session.threadId));
    container.append(button);
  });
}

export function renderConversation(container, session) {
  container.replaceChildren();

  const welcome = makeElement("section", "welcome-block");
  welcome.append(
    makeElement("h3", "", "把下一段旅程交给我"),
    makeElement("p", "", "从目的地和日期开始，也可以直接描述你的预算、同行人和偏好。我会逐步查找资料、安排路线，并把结果整理成清晰的攻略。"),
  );
  container.append(welcome);

  session.messages
    .filter((message) => !message.id.endsWith("_welcome"))
    .forEach((message) => appendStoredMessage(container, message));
  scrollToBottom(container);
}

function appendStoredMessage(container, message) {
  if (message.role === "tool") {
    return appendToolEvent(container, message.content, message.status === "complete");
  }
  return appendMessage(container, message.role, message.content, message.id, message.status === "error");
}

export function appendMessage(container, role, content, messageId = "", isError = false) {
  const row = makeElement("article", `message-row ${role}${isError ? " is-error" : ""}`);
  if (messageId) {
    row.dataset.messageId = messageId;
  }

  const contentWrap = makeElement("div", "message-content");
  const bubble = makeElement("div", "message-bubble");

  if (role === "user") {
    bubble.textContent = content;
  } else {
    bubble.innerHTML = renderMarkdown(content);
  }

  contentWrap.append(
    makeElement("div", "message-label", role === "user" ? "YOU" : "TRAVEL DESK"),
    bubble,
  );
  row.append(contentWrap);
  container.append(row);
  scrollToBottom(container);
  return row;
}

export function appendTypingMessage(container, messageId) {
  const row = appendMessage(container, "assistant", "", messageId);
  const bubble = row.querySelector(".message-bubble");
  bubble.replaceChildren(
    makeElement("span", "typing-indicator"),
  );
  const indicator = bubble.querySelector(".typing-indicator");
  indicator.append(makeElement("span"), makeElement("span"), makeElement("span"));
  return row;
}

export function appendToolEvent(container, label, isComplete = false) {
  const event = makeElement("div", `tool-event${isComplete ? " is-complete" : ""}`, label);
  container.append(event);
  scrollToBottom(container);
  return event;
}

export function updateMessage(row, content, isError = false) {
  row.classList.toggle("is-error", isError);
  const bubble = row.querySelector(".message-bubble");

  // Assistant 消息渲染 Markdown，用户消息和错误消息用纯文本
  if (row.classList.contains("user") || isError) {
    bubble.textContent = content;
  } else {
    bubble.innerHTML = renderMarkdown(content);
  }

  return bubble;
}

export function appendMessageText(row, content) {
  const bubble = row.querySelector(".message-bubble");
  if (row.dataset.started !== "true") {
    bubble.textContent = "";
    row.dataset.started = "true";
  }

  // 流式输出时先累加纯文本，避免每个 chunk 都重新解析 Markdown
  const currentText = bubble.dataset.rawContent || "";
  const newText = currentText + content;
  bubble.dataset.rawContent = newText;

  // 渲染 Markdown（assistant 消息）
  if (!row.classList.contains("user")) {
    bubble.innerHTML = renderMarkdown(newText);
  } else {
    bubble.textContent = newText;
  }

  return bubble;
}

export function formatSessionTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚更新";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function toolLabel(event) {
  const labels = {
    search_poi: "正在搜索景点",
    get_weather: "正在查询天气",
    get_city_transport: "正在整理城市交通",
    plan_route: "正在规划路线",
    rag_summarize: "正在查阅旅行资料",
    search_web: "正在搜索最新信息",
    fill_context_for_report: "正在准备攻略报告",
  };
  return labels[event.tool] || `正在调用 ${event.tool || "旅行工具"}`;
}
