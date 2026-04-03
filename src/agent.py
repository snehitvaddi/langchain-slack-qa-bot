from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from langchain_core.messages import trim_messages
from langgraph.checkpoint.memory import MemorySaver

from src.prompts import SYSTEM_PROMPT
from src.tools import ALL_TOOLS
from src.memory import trim_conversation_history, _estimate_tokens


# --- Memory strategy middlewares ---

@wrap_model_call
def summarize_middleware(request: ModelRequest, handler) -> ModelResponse:
    """Strategy C: Rolling summarization — builds on previous summaries."""
    messages = request.state.get("messages", [])
    if len(messages) > 15:
        # Extract thread_id from config for rolling summary cache
        thread_id = ""
        if hasattr(request, "config") and request.config:
            thread_id = request.config.get("configurable", {}).get("thread_id", "")
        trimmed = trim_conversation_history(messages, thread_id=thread_id)
        request = request.override(messages=trimmed)
    return handler(request)


@wrap_model_call
def trim_only_middleware(request: ModelRequest, handler) -> ModelResponse:
    """Strategy B: Just drop old messages (no summarization)."""
    messages = request.state.get("messages", [])
    if len(messages) > 15:
        trimmed = trim_messages(
            messages,
            max_tokens=16000,
            strategy="last",
            token_counter=_estimate_tokens,
            start_on="human",
            include_system=True,
            allow_partial=False,
        )
        request = request.override(messages=trimmed)
    return handler(request)


# No middleware = Strategy A (full history, no trimming)


def create_qa_agent(model: str = "openai:gpt-4o", memory_strategy: str = "summarize"):
    """Create the Q&A agent with configurable memory strategy.

    Args:
        model: Model identifier string
        memory_strategy: One of:
            - "full": No trimming, send everything (Strategy A)
            - "trim": Drop old messages to fit budget (Strategy B)
            - "summarize": Summarize old + keep recent raw (Strategy C, default)
    """
    checkpointer = MemorySaver()

    middleware = []
    if memory_strategy == "summarize":
        middleware = [summarize_middleware]
    elif memory_strategy == "trim":
        middleware = [trim_only_middleware]
    # "full" = no middleware

    agent = create_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=middleware,
    )

    return agent


# Singleton agent instance (uses default strategy)
_agent = None


def get_agent():
    """Get or create the singleton agent instance."""
    global _agent
    if _agent is None:
        _agent = create_qa_agent()
    return _agent
