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

> **Tested vs extrapolated.** Memory strategies were measured at **17 messages** (Experiment 3: summarize cheapest at 172K, full 226K, trim 199K) and **40 messages** (table above). Claims about behavior past 100 messages — i.e. that full-history eventually exceeds gpt-4o's 128K per-call context and summarize becomes the only viable strategy — are reasoning from the measured trajectory plus the context-window limit, not a measured result. Running the stress test at 100 messages is the first thing we'd add next.

## Engineering Iterations

The shipped system went through seven iterations. Each one came from a specific measurement or a real failure, not guesswork.

**Iteration 1 — the baseline.** Scored 49% on the six assessment example queries. Two of them scored zero. The Aureum/SCIM query built an over-specific seven-term FTS search and gave up on the empty result. The competitor-defection query skipped FTS entirely, tried raw SQL on a qualitative question, and hallucinated column names that were not in the schema.

**Iteration 2 — prompt tuning (49% → 64%).** Rewrote the system prompt to mandate FTS-first, short broad search terms, retry on empty results, always read `content_text` after a successful FTS, and distinguish qualitative questions (answered from artifacts) from structured ones (answered from SQL). Accuracy rose from 49% to 64%, FTS-first usage from 83% to 100%, and average tool calls from 3.0 to 2.8.

**Iteration 3 — first-cut memory.** Multi-turn worked fine up to about 15 messages because the checkpointer replays the whole thread on every invoke. Past 15, the context window starts filling with tool results and cost climbs. First version of the summarizer: drop older messages, insert a summary system message, keep recent raw.

**Iteration 4 — the orphaned tool message bug (28 errors → 0).** At the 40-message stress test, 28 of 40 requests on the summarize strategy returned HTTP 400 from OpenAI with *"messages with role 'tool' must be a response to a preceding message with 'tool_calls'."* The budget-driven summarizer walked the message list by token budget without respecting OpenAI's tool-call pairing invariant — it could sweep an assistant message into the "older" bucket while keeping its matching tool result in the "recent" bucket, orphaning the tool result. Fix: two safeguards in [src/memory.py](src/memory.py) — `_fix_tool_boundary` slides the split index forward past any orphan start, and `_remove_orphaned_tool_messages` drops tool messages whose IDs are not in the kept assistant set. After the fix: 0 errors, 87% back-reference accuracy at 40 messages.

**Iteration 5 — rolling summaries, O(history) → O(new messages).** The fixed summarizer still re-summarized every older message on every call. At message 50 it was re-processing messages 1 through 42 from scratch. Added a per-thread summary cache keyed by `thread_id`: each new summary is produced by feeding (previous cached summary + only messages new since the last cache write) to `gpt-4o-mini`. At message 100 we summarize about eight new messages, not eighty.

**Iteration 6 — caching static work.** The database is opened read-only, so the schema and the table list cannot change during process lifetime. Wrapped `get_table_names` and `get_table_schema` with `functools.lru_cache` — the first call hits SQLite, every subsequent call is free. Added a TTL-based FTS result cache (10 minutes, maximum 500 entries, hit and miss counters exposed for per-request logging) because the same customer or topic often gets searched multiple times within one conversation. See [src/db.py](src/db.py) and [src/tools.py](src/tools.py).

**Iteration 7 — observability.** Added [src/timing.py](src/timing.py), a lightweight `TimingTracker` that records elapsed milliseconds per named stage (`agent`, `slack_post`, and so on) and emits a single structured log line per request. LangSmith already auto-traces every LLM call; `timing.py` covers the non-LLM stages (Slack API latency, memory middleware, database queries) that LangSmith cannot see. The two together close the full observability loop.

**Live validation.** Sent 20 real messages through Slack in one DM thread covering four customers — deep dives, pronoun resolution, topic switching, back-references from 15+ messages earlier, and a final executive-summary question that required recalling every customer discussed. **14 of 14 scored checks passed.** Three non-scored misses were all in tool-strategy territory (Canada-wide pattern detection, MapleHarvest field mappings, at-risk customer count) — none in the memory or agent architecture.

### One counter-intuitive finding

Naive intuition says summarize should be cheapest (it compresses) and full should be most expensive (it sends everything). The 40-message stress test showed the opposite: full 414K tokens, summarize 475K, trim 554K. The reason is that *total tokens = per-call context × number of calls.* When trim or summarize drops context, the agent re-runs tools to recover lost facts, and those extra LLM roundtrips dominate the per-call savings. Trim drops the most and re-queries the most, which is why it is the worst. Summarize preserves key facts in compressed form so it re-queries less than trim but still more than full. This ordering flipped between 17 messages (where summarize won at 172K) and 40 messages — and by extrapolating the curves, it would flip again past about 100 messages when full starts exceeding gpt-4o's context window.

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
