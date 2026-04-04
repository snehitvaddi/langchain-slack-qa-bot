# LangChain Slack Q&A Bot

A Slack chatbot that answers questions about a fictional startup (Northstar Signal) by querying a SQLite database. Built with LangGraph, LangChain, and Slack Bolt.


## Quick Start

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

You need two tokens:

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

### 5. Enable DMs (optional but recommended)

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

**In a channel:**
1. Open any channel > click channel name > **Integrations** > **Add apps** > add **QA Bot**
2. Type: `@QA Bot which customer's issue started after the 2026-02-20 taxonomy rollout?`

**In DMs:**
1. Find **QA Bot** under Apps in the left sidebar
2. Type directly (no @mention needed): `which customer's issue started after the 2026-02-20 taxonomy rollout?`

The bot will:
1. React with eyes emoji (instant feedback)
2. Post "Thinking..." in a thread
3. Query the database using FTS and SQL
4. Replace the placeholder with the answer
5. Swap eyes for a checkmark

Follow up in the same thread for multi-turn conversations — the bot retains context.

## Running Tests

```bash
PYTHONPATH=. pytest tests/ -v
```

All 27 tests should pass (14 security + 13 tool tests).

## Running Evaluation

Tests the agent against the 6 example queries from the assessment:

```bash
python -m eval.evaluate
```

Run the full experiment suite (baseline accuracy, multi-turn, memory strategies, tool efficiency):

```bash
python -m eval.experiments
```

Run the 40-message stress test comparing memory strategies:

```bash
python -m eval.stress_test
```

## Architecture

![Architecture Diagram](assets/architecture.png)

See [DESIGN.md](DESIGN.md) for detailed architecture decisions and tradeoffs.

**Key components:**
- **Agent**: `create_agent` from `langchain.agents` (langchain 1.x) with ReAct loop
- **Tools**: `list_tables`, `get_schema`, `run_query`, `fts_search` (parameterized queries)
- **Memory**: Thread-based checkpointing via `MemorySaver`, rolling conversation summarization
- **Slack**: Slack Bolt + Socket Mode with post-then-update UX, auto-splits long messages
- **Security**: Read-only SQLite (`mode=ro`), SQL validation, parameterized queries, prompt guardrails
- **Observability**: LangSmith tracing + terminal execution traces

## Troubleshooting

**"We can't translate a manifest with errors"** — Use the JSON format (not YAML). The JSON manifest above includes the required `_metadata` field.

**"Sending messages to this app has been turned off"** — Go to App Home > enable "Allow users to send Slash commands and messages from the messages tab".

**Bot doesn't respond** — Make sure `python -m src.main` is running in your terminal. The bot runs locally via Socket Mode.

**"msg_too_long" error** — Fixed in the current version. Long answers are automatically split into multiple Slack messages.

**Markdown rendering issues** — Slack uses its own "mrkdwn" format, not standard Markdown. The bot auto-converts `**bold**` to `*bold*` and converts tables to bullet points.
