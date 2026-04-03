# LangGraph Slack Q&A Bot — Architecture Documentation

**Version:** 0.1 (Take-Home Submission)  
**Date:** 2026-04-02  
**Assessment:** LangChain Applied AI Engineer — Take-Home

---

## 1. Overview

### 1.1 Purpose

A Slack chatbot that answers natural language questions by querying a SQLite database containing fictional startup data (customer call transcripts, product details, implementation records, internal comms, competitor research). Built with LangGraph as the orchestration framework.

### 1.2 Scope

- Receive messages via Slack @mentions and thread replies
- Multi-turn conversation support within Slack threads
- Ground all answers in the provided SQLite database
- Security-first SQL execution (read-only, validated)

### 1.3 Architecture Style

**ReAct Agent Loop** — The LLM autonomously decides which tool to call and when, looping until it has enough information to answer. This is intentionally NOT a rigid pipeline (list_tables → schema → query → answer) because:
- Follow-up questions don't need schema re-inspection
- Some questions need FTS search first, others need SQL
- Complex questions may require multiple queries adaptively
- Efficiency matters: the agent should answer in 2-5 tool calls, not 10+

---

## 2. Architecture Diagram

See: `slack-qa-bot-architecture.drawio`

**To view:**
1. Open [app.diagrams.net](https://app.diagrams.net)
2. File → Open → Select the `.drawio` file

---

## 3. Components

### 3.1 Slack Platform

#### Slack Channel / Threads
- Users interact via `@bot` mentions in channels or thread replies
- Each Slack thread = one isolated conversation context
- Thread timestamp (`thread_ts`) serves as the conversation ID

#### Slack API (Socket Mode)
- **Technology:** Slack Bolt SDK for Python + Socket Mode
- **Why Socket Mode:** No public URL needed, no ngrok, works locally behind firewalls. Production would use HTTP Events API.
- **Security:** HMAC-SHA256 signature verification on all incoming events (handled automatically by Bolt SDK)

### 3.2 Slack Bolt Event Handler

- **Technology:** `slack_bolt` Python package
- **Purpose:** Receives Slack events, manages UX flow, invokes the LangGraph agent
- **Key Responsibilities:**
  - Auto-acknowledge events within Slack's 3-second timeout
  - Post "Thinking..." placeholder message in thread
  - Invoke LangGraph agent with conversation context
  - Replace placeholder with final answer via `chat_update`
  - Map `thread_ts` → LangGraph `thread_id` for multi-turn

### 3.3 LangGraph Agent (StateGraph)

The core of the system. A `StateGraph` with two primary nodes in a ReAct loop:

#### Agent Node
- Receives the full conversation state (`MessagesState`)
- Calls the LLM (OpenAI GPT-4o) with the system prompt and available tools
- The LLM decides: call a tool, or return a final answer

#### Tool Router (Conditional Edge)
- If the LLM returned a tool call → route to Tool Executor
- If the LLM returned a final answer → route to END

#### Tool Executor
- Executes the tool selected by the LLM
- Returns the tool result back to the Agent Node (loop continues)

#### Checkpointer (MemorySaver)
- Persists conversation state between invocations
- Keyed on `thread_ts` so each Slack thread has independent memory
- Enables multi-turn: "what about their competitor risk?" resolves correctly in context

### 3.4 Agent Tools

Five tools available to the agent (the LLM chooses which to use):

| Tool | Purpose | When Used |
|------|---------|-----------|
| `list_tables` | Lists all database tables | First interaction, orientation |
| `get_schema` | Returns CREATE TABLE DDL + 3 sample rows | Understanding table structure |
| `run_query` | Executes a SQL SELECT query | Structured data retrieval |
| `fts_search` | FTS5 MATCH search on `artifacts_fts` | Document/content search by keywords |
| `query_checker` | LLM validates SQL before execution | Safety net for complex queries |

**Key design decision:** `fts_search` is a first-class tool, not just raw SQL. The agent can choose between structured SQL queries and full-text keyword search depending on the question type. This is critical because the `artifacts` table contains long-form documents where `LIKE` queries are insufficient.

### 3.5 SQLite Database

- **File:** `synthetic_startup.sqlite`
- **Access:** Read-only (`sqlite3.connect('file:db.db?mode=ro', uri=True)`)
- **Key Tables:**
  - `artifacts` — Long-form documents (call transcripts, product specs, internal comms)
  - `artifacts_fts` — FTS5 virtual table indexed on title, summary, content
  - `scenarios` — Scenario/situation data
  - Additional startup operational tables
- **WAL Mode:** Write-ahead logging enabled (supports concurrent reads)

### 3.6 External Services

#### OpenAI API
- **Model:** GPT-4o (primary), GPT-4o-mini (potential fallback)
- **Purpose:** Powers the Agent Node's decision-making and natural language generation
- **Integration:** Via `langchain_openai.ChatOpenAI`

#### LangSmith (Optional but Recommended)
- **Purpose:** Tracing every LLM call, tool invocation, and graph execution
- **Setup:** 3 environment variables, zero code changes
- **Value:** Proves agent performance with traceable evidence; enables evaluation datasets

---

## 4. Data Flow

### 4.1 Single Question Flow
1. User posts `@bot which customer's issue started after the taxonomy rollout?` in Slack
2. Slack sends event via WebSocket (Socket Mode) to Bolt handler
3. Bolt handler: acks event, posts "Thinking..." placeholder in thread
4. Bolt invokes LangGraph agent with `{"messages": [user_msg]}` and `config={"thread_id": thread_ts}`
5. **Agent Node** (LLM) decides: call `fts_search("taxonomy rollout")`
6. **Tool Executor** runs FTS query → returns matching artifacts
7. **Agent Node** (LLM) sees results, decides: call `run_query("SELECT ... WHERE ...")`
8. **Tool Executor** runs SQL → returns BlueHarbor details
9. **Agent Node** (LLM) has enough context → returns natural language answer
10. **Tool Router** routes to END
11. Bolt handler calls `chat_update` to replace placeholder with final answer

### 4.2 Multi-Turn Follow-Up
1. User replies in same thread: "and what about their competitor risk?"
2. Same flow as above, but the checkpointer loads previous conversation state
3. LLM sees full thread history → resolves "their" = BlueHarbor from context
4. Agent may need only 1-2 tool calls since it already has relevant context

### 4.3 New Thread (Fresh Context)
1. User posts in a different thread or new @mention → new `thread_ts`
2. Checkpointer has no state for this thread → starts fresh
3. No cross-thread context leakage (by design)

---

## 5. Technology Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Slack SDK | `slack_bolt` (Python) | Official SDK, Socket Mode support, auto-ack |
| Agent Framework | LangGraph `StateGraph` | Full control over agent flow, demonstrates framework understanding |
| LLM | OpenAI GPT-4o via `langchain_openai` | Best SQL generation accuracy, tool calling support |
| Database | SQLite 3 | Provided by the assessment, FTS5 support built-in |
| Memory | LangGraph `MemorySaver` | In-memory checkpointing for dev, keyed on thread_ts |
| Observability | LangSmith | Zero-code tracing, evaluation datasets |
| Python | 3.11+ | Type hints, async support |

---

## 6. Security Considerations

### 6.1 Slack Webhook Security
- Bolt SDK verifies HMAC-SHA256 signatures on every incoming event
- Timestamp validation (rejects events >5 minutes old) prevents replay attacks

### 6.2 Database Security (Defense in Depth)
1. **Layer 1 — Read-only connection:** `sqlite3.connect('file:db.db?mode=ro', uri=True)` — SQLite engine rejects writes even if all other layers fail
2. **Layer 2 — SQL validation:** Regex allowlist ensuring only SELECT statements execute; explicit blocking of DROP, DELETE, INSERT, UPDATE, ALTER, TRUNCATE
3. **Layer 3 — LLM query checker:** `query_checker` tool validates SQL before execution
4. **Layer 4 — Prompt hardening:** System prompt explicitly forbids DML, enforces LIMIT clauses, restricts to allowed tables

### 6.3 API Key Management
- All secrets (Slack tokens, OpenAI key, LangSmith key) stored in `.env` file
- `.env` listed in `.gitignore`
- No secrets in code or commit history

---

## 7. Scalability Considerations

This is a take-home v0 running locally. Production would require:

| Concern | Current (v0) | Production |
|---------|-------------|------------|
| Deployment | Local machine | Cloud server (AWS/GCP/Railway) |
| Slack connection | Socket Mode | HTTP Events API (stateless, scalable) |
| Checkpointer | `MemorySaver` (in-memory) | `PostgresSaver` or `RedisSaver` |
| Database | Local SQLite file | Hosted database or read replicas |
| LLM failover | Single model | `model.with_fallbacks([fallback])` |
| Monitoring | LangSmith traces | LangSmith + alerting |

---

## 8. Key Design Decisions

### Why ReAct Loop over Rigid Pipeline
The Claude chat from initial research proposed a fixed pipeline (list_tables → get_schema → generate_query → check_query → execute). This is wrong for this use case because it forces 5+ tool calls on every query, even trivial follow-ups. A ReAct agent adapts: it might answer in 2 calls or 5, depending on complexity.

### Why Custom StateGraph over create_react_agent
Using `StateGraph` directly demonstrates understanding of LangGraph internals. It also gives explicit control over the ReAct loop, error handling, and potential future additions (like a query decomposition node for complex multi-hop questions).

### Why FTS Search as a Dedicated Tool
The generic SQL toolkit doesn't know about SQLite FTS5 `MATCH` syntax. A dedicated `fts_search` tool lets the agent naturally discover relevant documents by keyword, then follow up with structured SQL. This two-strategy approach (keyword search + structured queries) maps well to the question types in the assessment.

### Why MemorySaver (Not SqliteSaver)
For a take-home running locally, in-memory checkpointing is simpler and sufficient. The README documents SqliteSaver/PostgresSaver as production alternatives.

---

## 9. Evaluation & Testing

### Example Query Validation
The 6 provided example queries (4 easier + 2 harder) serve as the acceptance test suite. Each should be answerable in 2-5 tool calls.

### LangSmith Evaluation (Stretch Goal)
- Create a LangSmith dataset with the 6 Q&A pairs
- Run automated evaluators checking answer accuracy
- Use `agentevals` for trajectory evaluation (was the tool-calling path reasonable?)

---

## 10. Future Improvements (v1)

- [ ] Streaming responses in Slack (if `chat.startStream` API is available)
- [ ] Query decomposition node for complex multi-hop questions
- [ ] Conversation summarization for very long threads
- [ ] Rate limiting per Slack user
- [ ] Caching repeated schema lookups
- [ ] Model-agnostic design (swap OpenAI for Anthropic/Google)

---

*Architecture documentation for LangChain Applied AI Take-Home Assessment*
