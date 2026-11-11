"""Claude through the Messages API over plain httpx (no SDK, so the hashed lock file is untouched)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import (
    ChatMessage, ChatReply, HttpProvider, ProviderError, ToolCall, ToolSpec, Usage, estimate_usage, parse_arguments,
)

_API_VERSION = "2023-06-01"


def _to_wire(messages: List[ChatMessage]) -> tuple[str, List[Dict[str, Any]]]:
    """Anthropic keeps the system prompt apart and wants consecutive tool results in ONE user turn."""
    system_parts: List[str] = []
    wire: List[Dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        elif m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id or "", "content": m.content}
            if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list) \
                    and wire[-1]["content"] and wire[-1]["content"][0].get("type") == "tool_result":
                wire[-1]["content"].append(block)
            else:
                wire.append({"role": "user", "content": [block]})
        elif m.role == "assistant" and m.tool_calls:
            blocks: List[Dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
            wire.append({"role": "assistant", "content": blocks})
        else:
            wire.append({"role": m.role, "content": m.content})
    return "\n\n".join(system_parts), wire


class AnthropicProvider(HttpProvider):
    async def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        *,
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> ChatReply:
        system, wire = _to_wire(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": wire,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
        }

        body = await self._post("/v1/messages", payload, headers)

        blocks = body.get("content")
        if not isinstance(blocks, list):
            raise ProviderError(f"{self.name} returned no content", "format")
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        calls = tuple(
            ToolCall(id=str(b.get("id") or f"call_{i}"), name=b.get("name", ""), arguments=parse_arguments(b.get("input")))
            for i, b in enumerate(x for x in blocks if x.get("type") == "tool_use")
        )
        if not text and not calls:
            raise ProviderError(f"{self.name} returned an empty reply", "format")

        raw_usage = body.get("usage") or {}
        if "input_tokens" in raw_usage or "output_tokens" in raw_usage:
            usage = Usage(int(raw_usage.get("input_tokens", 0)), int(raw_usage.get("output_tokens", 0)))
        else:
            usage = estimate_usage(messages, text)
        return ChatReply(
            text=text,
            tool_calls=calls,
            usage=usage,
            finish_reason=str(body.get("stop_reason") or ""),
            model=str(body.get("model") or self.model),
            provider=self.name,
        )
