"""Which providers exist, and how each is configured from settings.

Adding a company that speaks the OpenAI wire format is one ``ProviderSpec`` row. A provider whose key or (where there is no safe default)
model is blank is simply not configured, so a missing key never turns into a request that is sent and fails.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import httpx

from .anthropic import AnthropicProvider
from .base import ChatProvider, DataClass
from .gemini import GeminiProvider
from .openai_compat import OpenAICompatProvider


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    kind: str                 # "openai" | "anthropic" | "gemini"
    prefix: str               # settings fields: <PREFIX>_API_KEY, <PREFIX>_MODEL, <PREFIX>_BASE_URL
    default_base_url: str
    default_model: str        # "" = no safe default, the model must be set explicitly
    data_class: DataClass
    needs_key: bool = True
    timeout_seconds: float = 60.0


# Hosted = synthetic_only, local = real_ok (D13). Model names go stale quickly, so only models already used in this
# repo (Groq, Gemini, Ollama) or named by Anthropic's current list carry a default; Qwen and Kimi must be set explicitly.
SPECS = {
    s.name: s
    for s in (
        ProviderSpec("groq", "openai", "GROQ", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "synthetic_only"),
        ProviderSpec("gemini", "gemini", "GEMINI", "https://generativelanguage.googleapis.com/v1beta", "gemini-3.8-flash", "synthetic_only"),
        ProviderSpec("anthropic", "anthropic", "ANTHROPIC", "https://api.anthropic.com", "claude-sonnet-5-5", "synthetic_only"),
        ProviderSpec("qwen", "openai", "QWEN", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "", "synthetic_only"),
        ProviderSpec("kimi", "openai", "KIMI", "https://api.moonshot.ai/v1", "", "synthetic_only"),
        ProviderSpec("openrouter", "openai", "OPENROUTER", "https://openrouter.ai/api/v1", "", "synthetic_only"),
        # LM Studio's local server (OpenAI-compatible, :1234). The model id it reports must be set in LMSTUDIO_MODEL.
        ProviderSpec("lmstudio", "openai", "LMSTUDIO", "http://localhost:1234/v1", "", "real_ok",
                     needs_key=False, timeout_seconds=300.0),
        ProviderSpec("ollama", "openai", "OLLAMA", "http://localhost:11434/v1", "llama3.1", "real_ok",
                     needs_key=False, timeout_seconds=120.0),
    )
}

_KINDS = {"openai": OpenAICompatProvider, "anthropic": AnthropicProvider, "gemini": GeminiProvider}


def build_provider(
    name: str,
    settings: Any = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[ChatProvider]:
    """Return the configured provider, or None when it lacks a key or a required model."""
    if settings is None:
        from app.core.config import settings as app_settings
        settings = app_settings
    spec = SPECS[name]
    key = str(getattr(settings, f"{spec.prefix}_API_KEY", "") or "")
    model = str(getattr(settings, f"{spec.prefix}_MODEL", "") or spec.default_model)
    base_url = str(getattr(settings, f"{spec.prefix}_BASE_URL", "") or spec.default_base_url)
    if (spec.needs_key and not key) or not model:
        return None
    if name == "ollama" and not base_url.rstrip("/").endswith("/v1"):
        # The report generator's old setting was the bare host (http://localhost:11434); the chat endpoint lives under /v1.
        base_url = base_url.rstrip("/") + "/v1"
    return _KINDS[spec.kind](
        name=spec.name, model=model, data_class=spec.data_class, base_url=base_url,
        api_key=key, timeout_seconds=spec.timeout_seconds, transport=transport,
    )


def provider_order(settings: Any = None) -> List[str]:
    """CHATBOT_PROVIDER_ORDER (comma-separated names), unknown names dropped; blank means every known provider."""
    if settings is None:
        from app.core.config import settings as app_settings
        settings = app_settings
    raw = str(getattr(settings, "CHATBOT_PROVIDER_ORDER", "") or "")
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    return [n for n in names if n in SPECS] or list(SPECS)


def configured_providers(settings: Any = None) -> List[ChatProvider]:
    built = (build_provider(n, settings) for n in provider_order(settings))
    return [p for p in built if p is not None]
