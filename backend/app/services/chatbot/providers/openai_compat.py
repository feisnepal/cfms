"""OpenAI-compatible chat endpoint: Groq, OpenRouter, Alibaba Qwen (DashScope compatible mode), Moonshot Kimi, and Ollama (/v1)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .base import (
    ChatMessage, ChatReply, HttpProvider, ProviderError, ToolCall, ToolSpec, Usage, estimate_usage, parse_arguments,
)


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _message_to_wire(m: ChatMessage) -> Dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content}
    wire: Dict[str, Any] = {"role": m.role, "content": m.content}
    if m.role == "assistant" and m.tool_calls:
        wire["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in m.tool_calls
        ]
    return wire


class OpenAICompatProvider(HttpProvider):
    async def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        *,
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> ChatReply:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_wire(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body = await self._post("/chat/completions", payload, headers)

        choices = body.get("choices")
        if not choices:
            raise ProviderError(f"{self.name} returned no choices", "format")
        message = choices[0].get("message") or {}
        # Reasoning models (Qwen3, DeepSeek-R1 style) may inline their thinking; it is not part of the answer.
        text = _THINK.sub("", message.get("content") or "").strip()
        calls = tuple(
            ToolCall(
                id=str(c.get("id") or f"call_{i}"),
                name=(c.get("function") or {}).get("name", ""),
                arguments=parse_arguments((c.get("function") or {}).get("arguments")),
            )
            for i, c in enumerate(message.get("tool_calls") or [])
        )
        if not text and not calls:
            raise ProviderError(f"{self.name} returned an empty reply", "format")

        raw_usage = body.get("usage") or {}
        if "prompt_tokens" in raw_usage or "completion_tokens" in raw_usage:
            usage = Usage(int(raw_usage.get("prompt_tokens", 0)), int(raw_usage.get("completion_tokens", 0)))
        else:
            usage = estimate_usage(messages, text)
        return ChatReply(
            text=text,
            tool_calls=calls,
            usage=usage,
            finish_reason=str(choices[0].get("finish_reason") or ""),
            model=str(body.get("model") or self.model),
            provider=self.name,
        )
