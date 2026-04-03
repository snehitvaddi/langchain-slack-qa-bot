import logging
import re
import traceback

from slack_bolt import App

from src.agent import get_agent

logger = logging.getLogger(__name__)


def register_handlers(app: App):
    """Register all Slack event handlers on the Bolt app."""

    @app.event("app_mention")
    def handle_mention(event, client, say):
        """Handle @bot mentions in channels."""
        _process_message(event, client)

    @app.event("message")
    def handle_message(event, client, say):
        """Handle direct messages and thread replies.

        Only responds to:
        - DMs (no channel_type check needed, DMs are im type)
        - Thread replies in channels where the bot was previously mentioned
        """
        # Skip bot's own messages
        if event.get("bot_id") or event.get("subtype"):
            return

        channel_type = event.get("channel_type", "")

        # Always respond to DMs
        if channel_type == "im":
            _process_message(event, client)
            return

        # In channels, only respond to thread replies (not top-level messages
        # without a mention — those are handled by app_mention)
        if event.get("thread_ts") and event.get("thread_ts") != event.get("ts"):
            _process_message(event, client)


def _process_message(event: dict, client):
    """Core message processing: invoke agent and respond in thread."""
    channel = event["channel"]
    user_text = _clean_mention(event.get("text", ""))
    thread_ts = event.get("thread_ts", event["ts"])

    if not user_text.strip():
        return

    # Step 1: Add eyes emoji for instant feedback
    try:
        client.reactions_add(channel=channel, name="eyes", timestamp=event["ts"])
    except Exception:
        pass  # Non-critical

    # Step 2: Post placeholder message in thread
    placeholder = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Thinking...",
    )

    try:
        # Step 3: Invoke agent with thread-based memory
        agent = get_agent()
        config = {"configurable": {"thread_id": f"slack-{channel}-{thread_ts}"}}
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_text}]},
            config=config,
        )

        # Log execution trace
        _log_trace(result, user_text)

        # Extract the final assistant message and convert to Slack format
        answer = _extract_answer(result)
        answer = _markdown_to_slack(answer)

        # Step 4: Send answer — split into multiple messages if too long
        _send_answer(client, channel, placeholder["ts"], answer)

    except Exception as e:
        logger.error(f"Agent error: {traceback.format_exc()}")
        client.chat_update(
            channel=channel,
            ts=placeholder["ts"],
            text=f"Sorry, I encountered an error processing your request. Please try again.\n\nError: {type(e).__name__}",
        )

    finally:
        # Step 5: Remove eyes, add checkmark
        try:
            client.reactions_remove(channel=channel, name="eyes", timestamp=event["ts"])
        except Exception:
            pass
        try:
            client.reactions_add(channel=channel, name="white_check_mark", timestamp=event["ts"])
        except Exception:
            pass


SLACK_MSG_LIMIT = 3900  # Slack's limit is 4000, leave margin


def _send_answer(client, channel: str, placeholder_ts: str, answer: str):
    """Send the answer to Slack, splitting into multiple messages if needed.

    Slack has a ~4000 char limit per message. For long answers:
    1. Update the placeholder with the first chunk
    2. Post additional chunks as follow-up messages in the same thread
    """
    if len(answer) <= SLACK_MSG_LIMIT:
        # Fits in one message — update placeholder
        blocks = _format_as_blocks(answer)
        client.chat_update(
            channel=channel,
            ts=placeholder_ts,
            text=answer[:SLACK_MSG_LIMIT],
            blocks=blocks,
        )
        return

    # Split on paragraph breaks to keep structure
    chunks = _split_message(answer)

    # First chunk updates the placeholder
    first_blocks = _format_as_blocks(chunks[0])
    client.chat_update(
        channel=channel,
        ts=placeholder_ts,
        text=chunks[0][:SLACK_MSG_LIMIT],
        blocks=first_blocks,
    )

    # Get the thread_ts from the placeholder message for follow-ups
    # The placeholder is already in a thread, so use its thread_ts
    msg_info = client.conversations_history(
        channel=channel, latest=placeholder_ts, limit=1, inclusive=True
    )
    thread_ts = placeholder_ts
    if msg_info.get("messages"):
        thread_ts = msg_info["messages"][0].get("thread_ts", placeholder_ts)

    # Post remaining chunks as follow-up messages in the thread
    for chunk in chunks[1:]:
        blocks = _format_as_blocks(chunk)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=chunk[:SLACK_MSG_LIMIT],
            blocks=blocks,
        )


def _split_message(text: str) -> list[str]:
    """Split a long message into chunks that fit Slack's limit."""
    if len(text) <= SLACK_MSG_LIMIT:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= SLACK_MSG_LIMIT:
            current = current + "\n\n" + para if current else para
        else:
            if current:
                chunks.append(current.strip())
            # If a single paragraph is too long, force-split it
            if len(para) > SLACK_MSG_LIMIT:
                words = para.split()
                current = ""
                for word in words:
                    if len(current) + len(word) + 1 <= SLACK_MSG_LIMIT:
                        current = current + " " + word if current else word
                    else:
                        chunks.append(current.strip())
                        current = word
            else:
                current = para

    if current:
        chunks.append(current.strip())

    return chunks if chunks else [text[:SLACK_MSG_LIMIT]]


def _markdown_to_slack(text: str) -> str:
    """Convert standard Markdown to Slack mrkdwn format.

    Handles the common cases where LLMs output standard Markdown
    despite being told to use Slack format.
    """
    # Convert **bold** to *bold* (must come before single * handling)
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # Convert ### headings to *bold* lines
    text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)

    # Convert [text](url) links to <url|text>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)

    # Convert markdown tables to readable format
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect table separator line (|---|---|)
        if re.match(r'^\s*\|[\s\-:|]+\|', line):
            i += 1
            continue
        # Convert table rows to bullet points
        if line.strip().startswith('|') and line.strip().endswith('|'):
            cells = [c.strip() for c in line.strip('|').split('|')]
            cells = [c for c in cells if c]
            if len(cells) >= 2:
                # First cell as label, rest as value
                result.append(f"• *{cells[0]}:* {' | '.join(cells[1:])}")
            else:
                result.append(line)
        else:
            result.append(line)
        i += 1

    return '\n'.join(result)


def _format_as_blocks(text: str) -> list[dict]:
    """Convert answer text into Slack Block Kit blocks for rich rendering.

    Splits long text into multiple section blocks (Slack has a 3000 char
    limit per block) and uses mrkdwn type for proper formatting.
    """
    MAX_BLOCK_LEN = 2900  # leave margin under 3000 limit
    blocks = []

    # Split into chunks if needed
    if len(text) <= MAX_BLOCK_LEN:
        chunks = [text]
    else:
        # Split on double newlines (paragraph breaks) to keep structure
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > MAX_BLOCK_LEN:
                if current:
                    chunks.append(current.strip())
                current = para
            else:
                current = current + "\n\n" + para if current else para
        if current:
            chunks.append(current.strip())

    for chunk in chunks:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": chunk}
        })

    return blocks


def _log_trace(result: dict, user_text: str):
    """Log full execution trace to terminal for observability."""
    messages = result.get("messages", [])
    tool_calls = 0
    tool_names = []

    logger.info(f"\n{'='*60}")
    logger.info(f"QUERY: {user_text[:100]}")
    logger.info(f"{'='*60}")

    for i, msg in enumerate(messages):
        if not hasattr(msg, "type"):
            continue

        if msg.type == "human":
            logger.info(f"  [{i}] USER: {msg.content[:100]}")

        elif msg.type == "ai" and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls += 1
                tool_names.append(tc["name"])
                args_str = str(tc["args"])[:150]
                logger.info(f"  [{i}] TOOL CALL #{tool_calls}: {tc['name']}({args_str})")

        elif msg.type == "tool":
            content_preview = msg.content[:150] if msg.content else "(empty)"
            logger.info(f"  [{i}] TOOL RESULT: {content_preview}...")

        elif msg.type == "ai" and msg.content and not msg.tool_calls:
            logger.info(f"  [{i}] FINAL ANSWER: {msg.content[:200]}...")

    logger.info(f"\n  SUMMARY: {tool_calls} tool calls: {' → '.join(tool_names)}")
    logger.info(f"  TOTAL MESSAGES: {len(messages)}")
    logger.info(f"{'='*60}\n")


def _extract_answer(result: dict) -> str:
    """Extract the final answer from agent result."""
    messages = result.get("messages", [])
    # Walk backwards to find the last AI message that isn't a tool call
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content and not msg.tool_calls:
            return msg.content
        if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return "I wasn't able to generate a response. Please try rephrasing your question."


def _clean_mention(text: str) -> str:
    """Remove @bot mention tags from message text."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()
