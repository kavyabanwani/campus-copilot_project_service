"""The one module that talks to the AI provider (Groq).

Campus Copilot communicates with Groq using OpenAI-compatible chat completions.
The rest of the app speaks one neutral message format:

    {"role": "user",      "content": "how much attendance do I have?"}
    {"role": "assistant", "content": "..."}                      # plain reply
    {"role": "assistant", "tool_calls": [ToolCall, ...]}         # asked for tools
    {"role": "tool",      "call": ToolCall, "result": {...}}     # what a tool returned

Includes retry logic with backoff for rate limits (429) and server errors (5xx),
as well as graceful recovery for tool-call generation failures (400).
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
import requests

from config import settings

logger = logging.getLogger("campus_copilot.llm")

REQUEST_TIMEOUT_SECONDS = 60
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0


class LLMUnavailable(Exception):
    """Raised when the AI provider cannot be reached, or is not configured."""


@dataclass
class ToolCall:
    name: str
    arguments: dict
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:24])


@dataclass
class ModelReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


def provider() -> str:
    """Always groq."""
    return "groq"


def api_key() -> str:
    return settings.GROQ_API_KEY.strip()


def model_name() -> str:
    return settings.GROQ_MODEL


def is_configured() -> bool:
    return bool(api_key())


def _groq_messages(system_instruction: str, messages: list[dict]) -> list[dict]:
    wire: list[dict] = [{"role": "system", "content": system_instruction}]

    for message in messages:
        if message["role"] == "user":
            wire.append({"role": "user", "content": message["content"]})
        elif message["role"] == "tool":
            call: ToolCall = message["call"]
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "name": call.name,
                    "content": json.dumps(message["result"], default=str),
                }
            )
        elif message.get("tool_calls"):
            wire.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or None,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments)
                                if isinstance(call.arguments, dict)
                                else str(call.arguments),
                            },
                        }
                        for call in message["tool_calls"]
                    ],
                }
            )
        else:
            wire.append({"role": "assistant", "content": message.get("content", "")})

    return wire


def _send_groq_request(payload: dict) -> dict:
    """Send request to Groq API with retry & backoff on 429/5xx, and handling of 400 tool-use failure."""
    if not is_configured():
        raise LLMUnavailable("AI service is not configured. Please set GROQ_API_KEY.")

    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "User-Agent": "CampusCopilot/1.0",
    }

    backoff = INITIAL_BACKOFF
    last_error_detail = ""

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                GROQ_CHAT_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as err:
            logger.warning("Connection error contacting Groq (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, err)
            last_error_detail = f"Could not reach Groq: {err}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise LLMUnavailable("The AI service could not be reached right now. Please try again.")

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                raise LLMUnavailable("The AI service returned an unreadable response.")

        # Rate limit (429) or Server error (5xx) -> exponential backoff retry
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                "Groq status %d on attempt %d/%d. Waiting %.1fs before retry...",
                response.status_code,
                attempt + 1,
                MAX_RETRIES,
                backoff,
            )
            last_error_detail = f"Groq HTTP {response.status_code}: {response.text[:200]}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise LLMUnavailable(
                "The AI service is experiencing heavy traffic right now. Please try again in a few moments."
            )

        # Tool-call generation failure (400)
        if response.status_code == 400:
            error_body = response.text
            logger.warning("Groq 400 error on attempt %d/%d: %s", attempt + 1, MAX_RETRIES, error_body[:300])
            last_error_detail = error_body
            if "tool" in error_body.lower() or "generation" in error_body.lower():
                # Tool-use generation failure - retry with fallback
                if attempt < MAX_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
            raise LLMUnavailable(
                "The AI assistant encountered a temporary processing error while determining tools. Please rephrase or try again."
            )

        # Other non-200 responses
        detail = response.text[:300]
        raise LLMUnavailable(f"The AI service rejected the request ({response.status_code}): {detail}")

    raise LLMUnavailable(f"The AI service is currently unavailable: {last_error_detail}")


def _groq_chat(system_instruction: str, messages: list[dict], tools: list[dict] | None) -> ModelReply:
    models_to_try = [settings.GROQ_MODEL]
    if "llama-3.1-8b-instant" not in models_to_try:
        models_to_try.append("llama-3.1-8b-instant")

    last_error = None
    for model_candidate in models_to_try:
        payload: dict = {
            "model": model_candidate,
            "messages": _groq_messages(system_instruction, messages),
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"

        try:
            result = _send_groq_request(payload)
            choices = result.get("choices") or []
            if not choices:
                raise LLMUnavailable("The AI service returned an empty response.")

            message = choices[0].get("message") or {}
            calls = []
            for raw in message.get("tool_calls") or []:
                function = raw.get("function") or {}
                raw_args = function.get("arguments") or "{}"
                if isinstance(raw_args, dict):
                    arguments = raw_args
                else:
                    try:
                        arguments = json.loads(raw_args)
                    except json.JSONDecodeError:
                        arguments = {}
                calls.append(
                    ToolCall(
                        name=function.get("name", ""),
                        arguments=arguments,
                        call_id=raw.get("id") or uuid.uuid4().hex[:24],
                    )
                )

            return ModelReply(text=(message.get("content") or "").strip(), tool_calls=calls)
        except LLMUnavailable as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    raise LLMUnavailable("The AI service could not be reached.")


def chat(system_instruction: str, messages: list[dict], tools: list[dict] | None = None) -> ModelReply:
    """Run one turn of the model via Groq."""
    return _groq_chat(system_instruction, messages, tools)
