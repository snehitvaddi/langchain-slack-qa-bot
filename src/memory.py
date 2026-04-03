from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langchain_openai import ChatOpenAI

# Budget: how many tokens we allow for the TOTAL context sent to the LLM
TOTAL_TOKEN_BUDGET = 16000
# Reserve space for the summary block
SUMMARY_TOKEN_BUDGET = 1500
# Minimum recent messages to keep
MIN_RECENT_MESSAGES = 2
# After this many messages, start summarizing
MESSAGE_THRESHOLD = 15

_summarizer = None

# Rolling summary storage: thread_id -> {"summary": str, "summarized_up_to": int}
_rolling_summaries: dict[str, dict] = {}


def _get_summarizer():
    global _summarizer
    if _summarizer is None:
        _summarizer = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=600)
    return _summarizer


def trim_conversation_history(messages: list, thread_id: str = "") -> list:
    """Manage conversation history for long threads using rolling summaries.

    Strategy:
    1. Under MESSAGE_THRESHOLD: keep everything
    2. Over threshold:
       a. Check if we have a previous rolling summary for this thread
       b. Only summarize NEW messages since last summary (not everything from scratch)
       c. Build new summary = previous summary + new unsummarized messages
       d. Keep recent messages raw
       e. Return: [rolling_summary] + [recent raw messages]

    This avoids re-summarizing the entire conversation every time.
    At message 100, we're summarizing ~8 new messages, not 80.
    """
    if len(messages) <= MESSAGE_THRESHOLD:
        return messages

    # Budget for recent messages
    recent_budget = TOTAL_TOKEN_BUDGET - SUMMARY_TOKEN_BUDGET

    # Walk backwards to find how many recent messages fit
    recent_indices = []
    tokens_used = 0

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        msg_tokens = _estimate_tokens_single(msg)

        if len(recent_indices) < MIN_RECENT_MESSAGES:
            recent_indices.append(i)
            tokens_used += msg_tokens
            continue

        if tokens_used + msg_tokens <= recent_budget:
            recent_indices.append(i)
            tokens_used += msg_tokens
        else:
            break

    recent_indices.reverse()
    split_index = recent_indices[0] if recent_indices else len(messages)

    # Fix boundary: don't split in middle of tool call sequences
    split_index = _fix_tool_boundary(messages, split_index)

    older = messages[:split_index]
    recent = messages[split_index:]

    if not older:
        return recent

    # Rolling summary: only summarize what's new since last time
    summary = _get_rolling_summary(older, thread_id)

    summary_msg = SystemMessage(
        content=f"Summary of earlier conversation:\n{summary}"
    )

    # Remove orphaned tool messages from recent
    recent = _remove_orphaned_tool_messages(recent)

    return [summary_msg] + recent


def _get_rolling_summary(older_messages: list, thread_id: str) -> str:
    """Get or update the rolling summary for this thread.

    Instead of re-summarizing ALL older messages every time,
    we build on the previous summary:

    First time:  summarize(messages 1-10) → summary_v1
    Second time: summarize(summary_v1 + messages 11-15) → summary_v2
    Third time:  summarize(summary_v2 + messages 16-20) → summary_v3

    Each call only processes ~5-10 new messages, not the entire history.
    """
    prev = _rolling_summaries.get(thread_id, {"summary": "", "summarized_up_to": 0})
    prev_summary = prev["summary"]
    prev_count = prev["summarized_up_to"]

    current_count = len(older_messages)

    # If we've already summarized up to this point, reuse
    if current_count <= prev_count and prev_summary:
        return prev_summary

    # Only summarize the NEW messages since last summary
    new_messages = older_messages[prev_count:]

    if not new_messages and prev_summary:
        return prev_summary

    # Build new summary from previous summary + new messages
    new_summary = _summarize_incremental(prev_summary, new_messages)

    # Cache for next time
    _rolling_summaries[thread_id] = {
        "summary": new_summary,
        "summarized_up_to": current_count,
    }

    return new_summary


def _summarize_incremental(previous_summary: str, new_messages: list) -> str:
    """Summarize new messages, building on a previous summary."""
    # Extract human/AI content from new messages
    new_parts = []
    for msg in new_messages:
        if not hasattr(msg, "type"):
            continue
        if msg.type == "human" and msg.content:
            new_parts.append(f"User: {msg.content[:300]}")
        elif msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
            new_parts.append(f"Assistant: {msg.content[:300]}")

    if not new_parts and previous_summary:
        return previous_summary

    new_text = "\n".join(new_parts)

    # Build the prompt
    if previous_summary:
        prompt_content = (
            f"EXISTING SUMMARY:\n{previous_summary}\n\n"
            f"NEW CONVERSATION TO ADD:\n{new_text}\n\n"
            "Update the summary to include the new information. "
            "Preserve ALL key facts from the existing summary. "
            "Add new customer names, dates, numbers, decisions, "
            "action items, and technical details."
        )
    else:
        prompt_content = (
            f"CONVERSATION:\n{new_text}\n\n"
            "Summarize this conversation concisely. Preserve ALL key facts: "
            "customer names, dates, numbers, decisions, action items, and "
            "technical details."
        )

    try:
        summarizer = _get_summarizer()
        result = summarizer.invoke([
            SystemMessage(content="You produce concise conversation summaries that preserve all specific facts."),
            HumanMessage(content=prompt_content),
        ])
        return result.content
    except Exception:
        # Fallback: append new parts to previous summary
        if previous_summary:
            return previous_summary + "\n" + "\n".join(new_parts[-3:])
        return "\n".join(new_parts[-5:])


def _fix_tool_boundary(messages: list, split_index: int) -> int:
    """Adjust split index so recent messages don't start with orphaned tool messages."""
    while split_index < len(messages):
        msg = messages[split_index]
        msg_type = getattr(msg, "type", None)
        if msg_type == "human":
            break
        if msg_type == "ai" and not getattr(msg, "tool_calls", None):
            break
        if msg_type == "ai" and getattr(msg, "tool_calls", None):
            break
        split_index += 1
    return split_index


def _remove_orphaned_tool_messages(messages: list) -> list:
    """Remove ToolMessages that don't have a preceding tool_calls AI message."""
    result = []
    seen_tool_call_ids = set()

    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                seen_tool_call_ids.add(tc.get("id", ""))
            result.append(msg)
        elif msg_type == "tool":
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id in seen_tool_call_ids:
                result.append(msg)
        else:
            result.append(msg)

    return result


def _estimate_tokens_single(msg) -> int:
    """Estimate tokens for a single message."""
    content = ""
    if hasattr(msg, "content") and msg.content:
        content = msg.content
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            content += str(tc.get("args", ""))
    return max(len(content) // 4, 1)


def _estimate_tokens(messages: list) -> int:
    """Estimate total tokens for a list of messages."""
    return sum(_estimate_tokens_single(m) for m in messages)
