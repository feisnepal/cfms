"""Google Gemini generateContent. The key goes in a header, not the URL (URLs end up in proxy and access logs)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import (
    ChatMessage, ChatReply, HttpProvider, ProviderError, ToolCall, ToolSpec, Usage, estimate_usage, parse_arguments,
)


def _to_wire(messages: List[ChatMessage]) -> tuple[str, List[Dict[str, Any]]]:
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        elif m.role == "tool":
            part = {"functionResponse": {"name": m.name or "", "response": {"result": m.content}}}
            if contents and contents[-1]["role"] == "user" and contents[-1]["parts"] \
                    and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
        elif m.role == "assistant":
            parts: List[Dict[str, Any]] = []
            if m.content:
                parts.append({"text": m.content})
            for c in m.tool_calls:
                part: Dict[str, Any] = {"functionCall": {"name": c.name, "args": c.arguments}}
                if c.signature:
                    part["thoughtSignature"] = c.signature  # Gemini 3 refuses the next turn without it (HTTP 400)
                parts.append(part)
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        else:
            contents.append({"role": "user", "parts": [{"text": m.content}]})
    return "\n\n".join(system_parts), contents


class GeminiProvider(HttpProvider):
    async def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        *,
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> ChatReply:
        system, contents = _to_wire(messages)
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            # Gemini accepts an OpenAPI subset: tool schemas must stay simple (no additionalProperties, no $ref).
            payload["tools"] = [{
                "functionDeclarations": [
                    {"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools
                ]
            }]
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._api_key}

        body = await self._post(f"/models/{self.model}:generateContent", payload, headers)

        candidates = body.get("candidates")
        if not candidates:
            raise ProviderError(f"{self.name} returned no candidates", "format")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
        calls = tuple(
            ToolCall(id=f"call_{i}", name=p["functionCall"].get("name", ""), arguments=parse_arguments(p["functionCall"].get("args")),
                     signature=p.get("thoughtSignature"))
            for i, p in enumerate(x for x in parts if "functionCall" in x)
        )
        if not text and not calls:
            raise ProviderError(f"{self.name} returned an empty reply", "format")

        meta = body.get("usageMetadata") or {}
        if "promptTokenCount" in meta or "candidatesTokenCount" in meta:
            usage = Usage(int(meta.get("promptTokenCount", 0)), int(meta.get("candidatesTokenCount", 0)))
        else:
            usage = estimate_usage(messages, text)
        return ChatReply(
            text=text,
            tool_calls=calls,
            usage=usage,
            finish_reason=str(candidates[0].get("finishReason") or ""),
            model=self.model,
            provider=self.name,
        )
