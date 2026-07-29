const chatForm = document.querySelector("#chatForm");
const chatLog = document.querySelector("#chatLog");
const messageInput = document.querySelector("#messageInput");
const sendBtn = document.querySelector("#sendBtn");
const clearBtn = document.querySelector("#clearBtn");

function addMessage(role, text, extraClass = "") {
  const article = document.createElement("article");
  article.className = `message ${role} ${extraClass}`.trim();

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  article.appendChild(bubble);
  chatLog.appendChild(article);
  chatLog.scrollTop = chatLog.scrollHeight;

  return article;
}

function setBusy(isBusy) {
  sendBtn.disabled = isBusy;
  messageInput.disabled = isBusy;
  sendBtn.textContent = isBusy ? "生成中..." : "发送";
}

function appendToMessage(messageElement, text) {
  const bubble = messageElement.querySelector(".bubble");
  if (messageElement.dataset.started !== "true") {
    bubble.textContent = "";
    messageElement.dataset.started = "true";
  }
  bubble.textContent += text;
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function readStreamingAnswer(response, messageElement) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }

      const event = JSON.parse(line);
      if (event.type === "chunk") {
        appendToMessage(messageElement, event.content || "");
      }
      if (event.type === "error") {
        throw new Error(event.content || "Agent调用失败");
      }
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    if (event.type === "chunk") {
      appendToMessage(messageElement, event.content || "");
    }
    if (event.type === "error") {
      throw new Error(event.content || "Agent调用失败");
    }
  }
}

async function sendMessage(message, messageElement) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "请求失败，请稍后重试");
  }

  await readStreamingAnswer(response, messageElement);
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = messageInput.value.trim();
  if (!message) {
    return;
  }

  addMessage("user", message);
  messageInput.value = "";

  const loadingMessage = addMessage("assistant", "正在思考...", "loading");
  setBusy(true);

  try {
    await sendMessage(message, loadingMessage);
    loadingMessage.classList.remove("loading");
    if (!loadingMessage.querySelector(".bubble").textContent.trim()) {
      loadingMessage.querySelector(".bubble").textContent = "没有生成有效回答。";
    }
  } catch (error) {
    loadingMessage.classList.remove("loading");
    loadingMessage.querySelector(".bubble").textContent = error.message;
  } finally {
    setBusy(false);
    messageInput.focus();
  }
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    chatForm.requestSubmit();
  }
});

clearBtn.addEventListener("click", () => {
  chatLog.innerHTML = "";
  addMessage(
    "assistant",
    "对话已清空。你可以输入一个新的中国城市旅行需求。"
  );
  messageInput.focus();
});
