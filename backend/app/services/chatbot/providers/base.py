"""Provider-neutral chat types and the HTTP plumbing every adapter shares.

The chatbot talks to one interface, ``ChatProvider.chat(messages, tools) -> ChatReply``. Which company is behind it is configuration
(``registry.py``). Keys are never put in a URL, a log line or an error message.
"""
from __future__ import annotations

import abc
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

import httpx

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant", "tool"]

# D13 (owner, 2026-11-10): a hosted provider may only see synthetic data; real-forest tool results go to a local model only.
DataClass = Literal["synthetic_only", "real_ok"]

# Devanagari costs more tokens than the 4 characters per token Latin text averages, so an estimate errs on the high side.
_CHARS_PER_TOKEN_ESTIMATE = 3


@dataclass(frozen=True)
class ToolSpec:
    """A function the model may ask us to run. ``parameters`` is a JSON-schema object."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]
    # Opaque provider token that must travel back with the call (Gemini 3 "thoughtSignature"); None for every other provider.
    signature: Optional[str] = None


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str = ""
    # assistant turn that asked for tools
    tool_calls: tuple = ()
    # tool turn: which call this answers (and the tool's name, which Gemini needs)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # True when the provider sent no usage block and the figure is a character-count guess (cap accounting, R2)
    estimated: bool = False

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ChatReply:
    text: str
    tool_calls: tuple
    usage: Usage
    finish_reason: str
    model: str
    provider: str


class ProviderError(Exception):
    """A provider call failed. ``kind`` is one of config, timeout, connect, http, format. Never carries a key."""

    def __init__(self, message: str, kind: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE) if text else 0


def estimate_usage(messages: List[ChatMessage], reply_text: str) -> Usage:
    prompt_chars = sum(len(m.content) for m in messages)
    return Usage(
        input_tokens=max(1, prompt_chars // _CHARS_PER_TOKEN_ESTIMATE) if prompt_chars else 0,
        output_tokens=estimate_tokens(reply_text),
        estimated=True,
    )


def parse_arguments(raw: Any) -> Dict[str, Any]:
    """Tool arguments arrive as a JSON string (OpenAI style) or already as an object (Ollama, Gemini, Anthropic)."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderError("tool arguments are not valid JSON", "format") from exc
    if not isinstance(value, dict):
        raise ProviderError("tool arguments are not a JSON object", "format")
    return value


class ChatProvider(abc.ABC):
    """One model behind one endpoint."""

    def __init__(self, name: str, model: str, data_class: DataClass):
        self.name = name
        self.model = model
        self.data_class = data_class

    @abc.abstractmethod
    async def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        *,
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> ChatReply:
        """Send the conversation, return the model's reply. Raises ProviderError, never returns an error string."""


class HttpProvider(ChatProvider):
    """Adds the single place where HTTP errors become ProviderError."""

    def __init__(
        self,
        name: str,
        model: str,
        data_class: DataClass,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 60.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        super().__init__(name, model, data_class)
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._transport = transport  # tests inject httpx.MockTransport

    async def _post(self, path: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("provider %s timed out", self.name)
            raise ProviderError(f"{self.name} timed out", "timeout") from exc
        except httpx.ConnectError as exc:
            logger.warning("provider %s unreachable", self.name)
            raise ProviderError(f"cannot connect to {self.name}", "connect") from exc
        except httpx.HTTPError as exc:
            logger.warning("provider %s transport error: %s", self.name, type(exc).__name__)
            raise ProviderError(f"{self.name} transport error", "connect") from exc

        if response.status_code != 200:
            # The body is trimmed and the key is never echoed back by these APIs, but we also never log the request.
            snippet = response.text[:200]
            logger.warning("provider %s answered %s", self.name, response.status_code)
            if response.status_code == 429 and "PerDay" in response.text:
                # A daily cap does not clear in a minute: do not retry, tell the caller.
                raise ProviderError(f"{self.name} daily quota used up", "quota", 429)
            raise ProviderError(f"{self.name} returned {response.status_code}: {snippet}", "http", response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name} sent a body that is not JSON", "format") from exc
