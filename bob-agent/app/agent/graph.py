"""LangGraph agent graph for Bob — Hebrew WhatsApp construction defect assistant."""

import json
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.prompts import build_system_prompt
from app.agent.state import AgentState
from app.agent.tools.add_defect import add_defect
from app.agent.tools.events import add_event, update_logo
from app.agent.tools.send_report import send_pdf_report, send_whatsapp_report
from app.agent.tools.update_defect import update_defect
from app.config import settings
from app.db.database import get_db_session
from app.db.repositories import site_repo
from app.models.webhook import MessageBody
from app.services.bridge_service import bridge

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = [add_defect, update_defect, send_whatsapp_report, send_pdf_report, add_event, update_logo]
tool_node = ToolNode(TOOLS)

# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def preprocess_node(state: AgentState) -> dict:
    """Validate the site exists, set reaction flags, load site context."""
    async with get_db_session() as session:
        site_obj = await site_repo.get_by_group_id(session, state["group_id"])

    if site_obj is None:
        # Unknown site — return minimal state so the graph can exit gracefully
        return {"site": {}, "is_reaction": False, "is_close_reaction": False}

    # Build site dict (serialisable — no ORM objects in state)
    site = {
        "id": site_obj.id,
        "name": site_obj.name or "",
        "logo_url": site_obj.logo_url or "",
        "training_phase": site_obj.training_phase,
        "context": site_obj.context or {},
    }

    messages = state.get("messages", [])
    # Detect reaction type (emoji 👍 closes the defect)
    is_reaction = False
    is_close_reaction = False
    original_text = None
    if state.get("is_reaction"):
        is_reaction = True
        is_close_reaction = state.get("emoji") == "👍"  # type: ignore[attr-defined]
        original_text = state.get("original_message_text")

    return {
        "site": site,
        "is_reaction": is_reaction,
        "is_close_reaction": is_close_reaction,
        "original_message_text": original_text,
        "tool_was_called": False,
        "iteration_count": 0,
    }


async def build_input_node(state: AgentState) -> dict:
    """Construct the chat_input JSON string from message context."""
    body_parts: dict = {
        "message": state.get("messageText") or state.get("transcript") or "",  # type: ignore
    }

    if state.get("image_url"):
        body_parts["image"] = state["image_url"]
    if state.get("is_reaction") and state.get("original_message_text"):
        body_parts["reaction"] = state.get("emoji", "")
        body_parts["originalMessage"] = state["original_message_text"]

    chat_input = json.dumps(body_parts, ensure_ascii=False)
    system_prompt = build_system_prompt(state["site"])

    return {
        "chat_input": chat_input,
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=chat_input),
        ],
    }


async def agent_node(state: AgentState) -> dict:
    """Call the LLM with bound tools."""
    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
    )
    llm_with_tools = llm.bind_tools(TOOLS)
    response = await llm_with_tools.ainvoke(state["messages"])
    tool_called = bool(getattr(response, "tool_calls", None))
    return {
        "messages": [response],
        "tool_was_called": tool_called,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def post_process_node(state: AgentState) -> dict:
    """After agent finishes, clear memory if a tool was called."""
    return {}


async def send_reply_node(state: AgentState) -> dict:
    """Send the last AI text reply to the WhatsApp group."""
    messages = state.get("messages", [])
    # Find the last AI message that has text content (not a tool call)
    reply_text = ""
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if isinstance(content, str) and content.strip():
            # Skip messages that are purely tool results
            if not getattr(msg, "tool_calls", None) and msg.__class__.__name__ != "ToolMessage":
                reply_text = content
                break

    if reply_text:
        await bridge.send_message(state["group_id"], reply_text)
    return {}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_agent(state: AgentState) -> str:
    """After the agent node: if tool calls present and within iteration cap, run tools."""
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    has_tool_calls = bool(getattr(last, "tool_calls", None))
    over_limit = state.get("iteration_count", 0) >= settings.AGENT_MAX_ITERATIONS

    if has_tool_calls and not over_limit:
        return "tools"
    return "post_process"


def route_preprocess(state: AgentState) -> str:
    """Skip the rest of the graph if the site is unknown."""
    if not state.get("site"):
        logger.warning("unknown_site", group_id=state.get("group_id"))
        return END
    return "build_input"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("preprocess", preprocess_node)
    builder.add_node("build_input", build_input_node)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)
    builder.add_node("post_process", post_process_node)
    builder.add_node("send_reply", send_reply_node)

    builder.set_entry_point("preprocess")
    builder.add_conditional_edges("preprocess", route_preprocess, {"build_input": "build_input", END: END})
    builder.add_edge("build_input", "agent")
    builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "post_process": "post_process"},
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("post_process", "send_reply")
    builder.add_edge("send_reply", END)

    cp = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=cp)


# Module-level compiled graph — uses MemorySaver by default.
# In production this can be replaced with AsyncPostgresSaver for persistence.
graph = build_graph()


# ---------------------------------------------------------------------------
# Entry point called from ARQ worker
# ---------------------------------------------------------------------------


async def run_agent(body: MessageBody) -> None:
    """Process one WhatsApp message through the agent graph."""
    session_id = f"group_{body.groupId}"
    config = {"configurable": {"thread_id": session_id}}

    initial_state: dict = {
        "group_id": body.groupId,
        "sender": body.sender,
        "session_id": session_id,
        "messages": [],
        "site": {},
        "chat_input": "",
        "tool_was_called": False,
        "iteration_count": 0,
        "transcript": None,
        "image_url": body.mediaUrl if body.mediaType == "image" else None,
        "video_url": body.mediaUrl if body.mediaType == "video" else None,
        "is_reaction": body.type == "reaction",
        "is_close_reaction": False,
        "original_message_text": body.originalMessage.text if body.originalMessage else None,
        # Carry raw fields needed by build_input_node
        "messageText": body.messageText,
        "emoji": body.emoji,
    }

    log = logger.bind(group_id=body.groupId, message_id=body.messageId)
    log.info("agent_started")

    try:
        await graph.ainvoke(initial_state, config=config)

        # Clear memory after tool calls to prevent context bleed
        state_snapshot = await graph.aget_state(config)
        if state_snapshot.values.get("tool_was_called"):
            await graph.aupdate_state(config, {"messages": []})

        log.info("agent_finished")
    except Exception as exc:
        log.error("agent_error", error=str(exc))
        raise
