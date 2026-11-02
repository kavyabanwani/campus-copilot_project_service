"""Campus Copilot's AI orchestrator.

    student question + conversation history
        -> Groq model (with the campus tools declared)
        -> the model asks for the tools it needs
        -> tools read the real database / RAG index
        -> results go back to the model
        -> the model writes the answer, grounded in those results
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

import ai_tools
import llm_client
from db.models import Student
from db.schemas import ChatTurn
from llm_client import LLMUnavailable
from prompts import build_system_instruction

logger = logging.getLogger("campus_copilot.agent")

MAX_TOOL_ROUNDS = 5
MAX_HISTORY_TURNS = 10


@dataclass
class AgentAnswer:
    content: str
    card_type: str | None = None
    card_data: dict | None = None
    activity_steps: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)


def _build_messages(message: str, history: list[ChatTurn]) -> list[dict]:
    messages = [
        {"role": "assistant" if turn.role == "assistant" else "user", "content": turn.content}
        for turn in history[-MAX_HISTORY_TURNS:]
        if turn.content
    ]
    # Guard against double-adding the current user question if the client included it in history
    if not (messages and messages[-1]["role"] == "user" and messages[-1]["content"].strip() == message.strip()):
        messages.append({"role": "user", "content": message})
    return messages


def _add_source(sources: list[dict], source: dict) -> None:
    """Keep one entry per document page, preferring the version that names a page and snippet."""
    for existing in sources:
        if existing["title"] != source["title"]:
            continue
        if existing.get("page") == source.get("page"):
            if not existing.get("snippet") and source.get("snippet"):
                existing["snippet"] = source["snippet"]
            return
        if existing.get("page") is None and source.get("page") is not None:
            existing["page"] = source["page"]
            if source.get("snippet"):
                existing["snippet"] = source["snippet"]
            return
        if source.get("page") is None:
            return
    sources.append(dict(source))


def run_agent(message: str, student: Student, db: Session, history: list[ChatTurn] | None = None) -> AgentAnswer:
    messages = _build_messages(message, history or [])
    system_instruction = build_system_instruction(student)

    activity_steps = ["Understanding your question"]
    sources: list[dict] = []
    cards: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        reply = llm_client.chat(system_instruction, messages, ai_tools.TOOL_DECLARATIONS)

        if not reply.tool_calls:
            if not reply.text:
                raise LLMUnavailable("The assistant returned an empty answer.")
            activity_steps.append("Writing your answer")
            primary_card = cards[0] if cards else None
            return AgentAnswer(
                content=reply.text,
                card_type=primary_card["type"] if primary_card else None,
                card_data=primary_card["data"] if primary_card else None,
                activity_steps=activity_steps,
                sources=sources,
                cards=cards,
            )

        messages.append({"role": "assistant", "tool_calls": reply.tool_calls})

        for call in reply.tool_calls:
            logger.info("tool call: %s(%s)", call.name, call.arguments)
            tool_result = ai_tools.run_tool(call.name, call.arguments, db, student)

            if tool_result.activity not in activity_steps:
                activity_steps.append(tool_result.activity)
            for source in tool_result.sources:
                _add_source(sources, source)
            if tool_result.card_type and tool_result.card_data:
                # Avoid duplicate cards of the same kind
                if not any(c.get("type") == tool_result.card_type and c.get("data") == tool_result.card_data for c in cards):
                    cards.append({"type": tool_result.card_type, "data": tool_result.card_data})

            messages.append({"role": "tool", "call": call, "result": tool_result.result})

    raise LLMUnavailable("The assistant could not finish that request. Please rephrase your question.")
