"""
AI generator service for report sections.

Folded under the chatbot's provider interface (services/chatbot/providers, CHATBOT_TRACKER C0.2): the same providers and keys serve
both. The public contract is unchanged: ``get_generator().generate_section(prompt, max_tokens)`` returns text, or a string that starts
with ``[ERROR:`` when no provider could answer.

Note: report prompts carry real forest data. A hosted provider (Groq, Gemini) is used here only when REPORT_ALLOW_HOSTED_PROVIDERS=true,
which keeps the behaviour from before the fold (its keys were never read, so only Ollama answered). The chatbot itself never sends
real-forest data to a hosted provider (CHATBOT_PLAN D13).
"""
import logging
from typing import List, Optional, Tuple

from app.core.config import settings
from app.services.chatbot.providers import ChatMessage, ChatProvider, ProviderError, build_provider

logger = logging.getLogger(__name__)

# Order used before the fold: Groq (fast, free) -> Gemini -> Ollama (local).
_REPORT_PROVIDER_ORDER = ("groq", "gemini", "ollama")

# Only the Groq call used to carry this system prompt; the other two sent the bare prompt. Kept as it was.
_NEPALI_OFFICER_SYSTEM = (
    "You are a Nepali government forest officer. Write reports in Nepali language (Devanagari script). "
    "Technical terms can be in English."
)
_SYSTEM_BY_PROVIDER = {"groq": _NEPALI_OFFICER_SYSTEM}

_TEMPERATURE = 0.7


class ProviderTextGenerator:
    """One provider behind the old ``generate_section`` shape."""

    def __init__(self, provider: ChatProvider):
        self.provider = provider

    async def generate_section(self, prompt: str, max_tokens: int = 4096) -> str:
        messages: List[ChatMessage] = []
        system = _SYSTEM_BY_PROVIDER.get(self.provider.name)
        if system:
            messages.append(ChatMessage("system", system))
        messages.append(ChatMessage("user", prompt))
        try:
            reply = await self.provider.chat(messages, max_tokens=max_tokens, temperature=_TEMPERATURE)
        except ProviderError as exc:
            if self.provider.name == "ollama" and exc.kind == "connect":
                return ("[ERROR: Cannot connect to Ollama. Install Ollama from https://ollama.com and run: "
                        "ollama pull llama3.1]")
            return f"[ERROR: {exc}]"
        return reply.text


class FallbackGenerator:
    """Try the configured providers in order until one works."""

    def __init__(self, allow_hosted: Optional[bool] = None):
        if allow_hosted is None:
            allow_hosted = bool(getattr(settings, "REPORT_ALLOW_HOSTED_PROVIDERS", False))
        self.providers: List[Tuple[str, ProviderTextGenerator]] = []
        for name in _REPORT_PROVIDER_ORDER:
            provider = build_provider(name)
            if provider is not None and (allow_hosted or provider.data_class == "real_ok"):
                self.providers.append((name, ProviderTextGenerator(provider)))

    async def generate_section(self, prompt: str, max_tokens: int = 4096) -> str:
        errors = []
        for name, generator in self.providers:
            try:
                result = await generator.generate_section(prompt, max_tokens)
                if not result.startswith("[ERROR:"):
                    return result
                errors.append(f"{name}: {result}")
            except Exception as e:  # noqa: BLE001 -- one broken provider must not stop the next from being tried
                logger.warning("provider %s failed - trying the next one", name, exc_info=True)
                errors.append(f"{name}: {str(e)}")

        error_msg = "\n".join(errors)
        return (f"[ERROR: All AI providers failed.\n\n{error_msg}\n\nPlease configure at least one:\n"
                "- GROQ_API_KEY (free: https://console.groq.com)\n"
                "- GEMINI_API_KEY (free: https://aistudio.google.com)\n"
                "- Install Ollama: https://ollama.com]")


# Singleton instance
_generator: Optional[FallbackGenerator] = None


def get_generator() -> FallbackGenerator:
    """Return the singleton FallbackGenerator instance, creating it if needed."""
    global _generator
    if _generator is None:
        _generator = FallbackGenerator()
    return _generator
