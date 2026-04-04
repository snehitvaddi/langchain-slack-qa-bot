# LangChain Slack Q&A Bot

A Slack chatbot that answers natural language questions about a fictional startup (Northstar Signal) by querying a SQLite database. Built with LangGraph, LangChain, and Slack Bolt.


## Architecture

![Architecture Diagram](assets/architecture.png)

- **Agent**: `create_agent` from `langchain.agents` (langchain 1.x) with ReAct loop — LLM decides which tool to call, observes the result, decides again until it has enough to answer
- **Tools**: `fts_search` (FTS5 full-text search), `run_query` (parameterized SQL), `get_schema`, `list_tables`
- **Memory**: Thread-based checkpointing via `MemorySaver` + rolling conversation summarization for long threads
- **Slack**: Slack Bolt + Socket Mode, post-then-update UX pattern, automatic message splitting for long answers
- **Security**: Read-only SQLite (`mode=ro`), SQL statement validation, parameterized queries, prompt-level guardrails
- **Observability**: LangSmith tracing + terminal execution traces for every tool call

See [DESIGN.md](DESIGN.md) for detailed architecture decisions and tradeoffs.

## Key Results

- **94% multi-turn accuracy** — pronoun resolution, topic switching, and back-references all work across conversation threads
- **100% FTS-first tool selection** — every query starts with full-text search, then follows up with targeted SQL
- **2.8 avg tool calls** per query (assessment target: 2-5, not 30)
- **87% back-reference accuracy** at 40 messages using rolling conversation summarization
- **27/27 security tests passing** — SQL injection prevention, DML blocking, read-only enforcement
- **0 summarization errors** after fixing an orphaned tool message bug discovered through stress testing

### Memory Strategy Comparison (40-message stress test)

| Strategy | Tokens | Back-Ref Accuracy | Errors |
|----------|--------|-------------------|--------|
| Full history | 414K | 88% | 0 |
| Summarize (rolling) | 475K | 87% | 0 |
| Trim (drop old) | 554K | 78% | 0 |

Rolling summarization matches full history accuracy while staying viable at any conversation length. Trim is the weakest — dropping context causes re-querying and lower recall.

### Iterative Improvement

We ran experiments before and after prompt tuning to measure the impact of our changes:

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Overall accuracy | 49% | 64% | +15pp |
| FTS usage rate | 83% | 100% | +17pp |
| Avg tool calls | 3.0 | 2.8 | -0.2 |
| Summarization errors (40 msgs) | 28 | 0 | Fixed |

Key changes: FTS-first strategy in system prompt, retry on empty searches, tool boundary detection for summarization.

Full experiment data: [`eval/EXPERIMENTS.md`](eval/EXPERIMENTS.md) | Raw results: [`eval/results.json`](eval/results.json)

## Design Decisions

**Why `create_agent` over raw `StateGraph`** — It's LangChain's current recommended API (langchain 1.x). Gives us the ReAct loop, middleware support, and checkpointing without wiring up the graph manually. Still uses LangGraph under the hood.

**Why FTS as a dedicated tool** — The database has an FTS5 index on artifact content. Making this a separate `fts_search` tool (instead of hoping the LLM writes correct FTS5 MATCH syntax in raw SQL) gives better results and uses parameterized queries for security.

**Why rolling summaries** — At 15+ messages, we compress older conversation into a summary and keep recent messages raw. Each new summary builds on the previous one (not re-summarizing from scratch). Discovered and fixed an orphaned tool message bug through stress testing.

**Why post-then-update Slack UX** — Slack requires HTTP 200 within 3 seconds, but LLM calls take 5-30s. We immediately post "Thinking..." then replace it with the answer. Eyes emoji on receipt, checkmark on completion.

See [DESIGN.md](DESIGN.md) for the full write-up.

## Running Evaluation

```bash
# Unit tests (27/27 should pass)
PYTHONPATH=. pytest tests/ -v

# Test against 6 assessment example queries
python -m eval.evaluate

# Full experiment suite (accuracy, multi-turn, memory, efficiency)
python -m eval.experiments

# 40-message stress test across memory strategies
python -m eval.stress_test
```

<details>
<summary><h2>Setup & Installation</h2></summary>

### Prerequisites

- Python 3.12+
- A Slack workspace where you can create apps
- An OpenAI API key
- (Optional) A LangSmith API key for tracing

### 1. Clone and install

```bash
git clone https://github.com/snehitvaddi/langchain-slack-qa-bot
cd langchain-slack-qa-bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install langchain langchain-openai langgraph slack-bolt python-dotenv langsmith pytest
```

### 2. Download the database

```bash
git clone https://github.com/langchain-ai/applied-ai-take-home-database.git /tmp/take-home-db
cp /tmp/take-home-db/synthetic_startup.sqlite .
```

### 3. Create a Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** > **From a manifest**
3. Select your workspace
4. Switch to the **JSON** tab and paste:

```json
{
  "_metadata": { "major_version": 1 },
  "display_information": {
    "name": "QA Bot",
    "description": "Q&A chatbot for Northstar Signal data"
  },
  "features": {
    "bot_user": { "display_name": "QA Bot", "always_online": true }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "app_mentions:read",
        "chat:write",
        "im:history",
        "im:read",
        "im:write",
        "channels:history",
        "reactions:read",
        "reactions:write"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": ["app_mention", "message.im"]
    },
    "interactivity": { "is_enabled": false },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true
  }
}
```

5. Click **Next** > **Create**

### 4. Get your tokens

**Bot Token (`xoxb-...`):**
1. In your app settings, go to **Install App** (left sidebar)
2. Click **Install to Workspace** > **Allow**
3. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

**App-Level Token (`xapp-...`):**
1. Go to **Basic Information** (left sidebar)
2. Scroll down to **App-Level Tokens**
3. Click **Generate Token and Scopes**
4. Name it anything (e.g. "socket")
5. Add the scope: **`connections:write`**
6. Click **Generate**
7. Copy the token (starts with `xapp-`)

### 5. Enable DMs (optional)

To message the bot directly (not just @mentions in channels):
1. Go to **App Home** (left sidebar, under Features)
2. Check **"Allow users to send Slash commands and messages from the messages tab"**
3. Save

### 6. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token
OPENAI_API_KEY=sk-your-openai-key
DATABASE_PATH=synthetic_startup.sqlite

# Optional: LangSmith tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_your-langsmith-key
LANGCHAIN_PROJECT=slack-qa-bot
```

### 7. Run the bot

```bash
source .venv/bin/activate
python -m src.main
```

You should see: `Starting Slack bot in Socket Mode...`

### 8. Use it in Slack

**In a channel:** Open any channel > Integrations > Add apps > add **QA Bot** > type `@QA Bot your question`

**In DMs:** Find QA Bot under Apps in sidebar > type directly (no @mention needed)

</details>

<details>
<summary><h2>Troubleshooting</h2></summary>

**"We can't translate a manifest with errors"** — Use the JSON format (not YAML). The JSON manifest above includes the required `_metadata` field.

**"Sending messages to this app has been turned off"** — Go to App Home > enable "Allow users to send Slash commands and messages from the messages tab".

**Bot doesn't respond** — Make sure `python -m src.main` is running in your terminal. The bot runs locally via Socket Mode.

**"msg_too_long" error** — Fixed in the current version. Long answers are automatically split into multiple Slack messages.

**Markdown rendering issues** — Slack uses its own "mrkdwn" format, not standard Markdown. The bot auto-converts `**bold**` to `*bold*` and converts tables to bullet points.

</details>
