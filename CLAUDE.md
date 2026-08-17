# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
uvicorn main:app --reload
```

The app starts a FastAPI server. Open `http://localhost:8000` in a browser to access the chat UI.

To run the agent directly from the CLI (useful for quick smoke tests):

```bash
python agent/react_agent.py
```

To test the RAG service in isolation:

```bash
python rag/rag_service.py
```

## Dependencies

Managed with [uv](https://github.com/astral-sh/uv). Python ≥ 3.14 required.

```bash
uv sync          # install / sync dependencies
```

## Environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `DASHSCOPE_API_KEY` | Alibaba Cloud DashScope key (chat + embedding model) |
| `DASHSCOPE_URL` | DashScope base URL (OpenAI-compatible endpoint) |
| `CHECKPOINT_DB_URI` | MySQL connection string, e.g. `mysql://root:pass@127.0.0.1:3306/db?charset=utf8mb4` |
| `AMAP_API_KEY` / `GAODE_API_KEY` | Amap (高德) Maps API key for weather, POI, routing |
| `TAVILY_API_KEY` | Tavily web search key (optional; degrades gracefully if absent) |

## Architecture

This is a **China tourism-guide agent** built on LangChain + LangGraph with a FastAPI backend and a vanilla-JS frontend.

### Request flow

```
Browser (static/index.html + app.js)
  └─► POST /api/chat  (NDJSON streaming response)
        └─► api/routers.py  →  ReactAgent.execute_stream()
              └─► LangGraph agent  (langchain.agents.create_agent)
                    ├─► agent/tools/middleware.py   (log / monitor / prompt-switch)
                    └─► agent/tools/agent_tools.py  (tool implementations)
                          ├─► rag/rag_service.py      (local Chroma vector store)
                          ├─► integrations/web_search.py  (Tavily)
                          └─► Amap REST API           (weather, POI, routing)
```

### Key modules

- **`main.py`** — FastAPI app entrypoint. On startup, initialises `MySQLSessionStore` and `ReactAgent` on `app.state`.
- **`agent/react_agent.py`** — Wraps `create_agent` (LangGraph). Handles streaming, history serialisation, and thread reset.
- **`agent/tools/agent_tools.py`** — All eight LangChain `@tool`-decorated functions (`rag_summarize`, `get_weather`, `search_poi`, `plan_route`, `get_user_location`, `get_city_transport`, `search_web`, `fill_context_for_report`). Direct Amap REST calls are made here via `urllib.request`.
- **`agent/tools/middleware.py`** — Three LangChain agent middlewares: `log_before_model`, `monitor_tool`, and `report_prompt_switch`. The last one dynamically swaps the system prompt to the report template (`prompts/report_prompt.txt`) when the `fill_context_for_report` tool has been called in a turn.
- **`memory/mysql_checkpointer.py`** — Thin wrapper around `langgraph-checkpoint-mysql` (`PyMySQLSaver`). Persists full conversation checkpoints in MySQL.
- **`memory/session_store.py`** — Manages the `chat_sessions` table in MySQL (title, timestamps) separately from LangGraph's checkpoint tables.
- **`model/factory.py`** — Instantiates `chat_model` (DashScope via OpenAI-compatible API, model from `config/rag.yml`) and `embedding_model` (DashScope `text-embedding-v4`) as module-level singletons.
- **`rag/vector_store.py`** / **`rag/rag_service.py`** — Chroma-backed retriever. `RagSummarizeService` builds a `PromptTemplate | chat_model | StrOutputParser` chain over retrieved docs. The vector store is persisted under `chroma_db/` (path from `config/chroma.yml`).
- **`prompts/`** — Plain-text system prompts loaded at runtime. `main_prompt.txt` is the default agent system prompt; `report_prompt.txt` is used after `fill_context_for_report` fires; `rag_summarize_prompt.txt` is used by the RAG chain.
- **`config/`** — YAML configuration files (`rag.yml`, `chroma.yml`, `prompts.yml`, `agent.yml`) loaded via `utils/config_handler.py`.
- **`data/`** — Source `.txt` files for the knowledge base (China travel guides). Run the ingestion script (if present) to embed these into Chroma.

### Session model

Each browser session holds a `thread_id` (e.g. `thread_<uuid>`). This ID is used as LangGraph's `thread_id` for checkpoint isolation and as the primary key in `chat_sessions`. The API returns NDJSON with event types `chunk`, `tool_call`, `tool_done`, `error`, and `done`.

### Prompt switching

`report_prompt_switch` middleware checks `runtime.context["report"]`. This flag is set to `True` by `monitor_tool` when the agent calls `fill_context_for_report`. The flag resets to `False` at the start of each `/api/chat` request (`context={"report": False}`).
