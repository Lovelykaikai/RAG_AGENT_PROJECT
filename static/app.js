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

async function sendMessage(message) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || "请求失败，请稍后重试");
  }

  return data.answer || "没有生成有效回答。";
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
    const answer = await sendMessage(message);
    loadingMessage.classList.remove("loading");
    loadingMessage.querySelector(".bubble").textContent = answer;
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

