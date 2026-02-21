from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # Conversation history (append-only via add_messages)
    messages: Annotated[list, add_messages]

    # WhatsApp context — set once per request, never modified
    group_id: str
    sender: str
    session_id: str

    # Populated during pre-processing
    site: dict          # Site metadata from DB (name, context, logo_url, …)
    chat_input: str     # JSON string sent to the LLM as human message
    tool_was_called: bool

    # Iteration guard (agent ↔ tools loop capped at AGENT_MAX_ITERATIONS)
    iteration_count: int

    # Media
    transcript: Optional[str]
    image_url: Optional[str]
    video_url: Optional[str]
    sonioxFileId: Optional[str]   # Pre-uploaded Soniox file ID (audio messages)

    # Reaction handling
    is_reaction: bool
    is_close_reaction: bool
    original_message_text: Optional[str]
