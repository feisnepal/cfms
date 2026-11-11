"""C0.2: the provider interface, one fake HTTP server (httpx.MockTransport) per adapter. No network, no database."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.chatbot.providers import (
    ChatMessage, ProviderError, ToolCall, ToolSpec, build_provider, configured_providers, provider_order,
)
from app.services.chatbot.providers.anthropic import AnthropicProvider
from app.services.chatbot.providers.gemini import GeminiProvider
from app.services.chatbot.providers.openai_compat import OpenAICompatProvider

TOOL = ToolSpec("get_area", "Area of a block", {"type": "object", "properties": {"block": {"type": "string"}}})
CONVO = [ChatMessage("system", "be brief"), ChatMessage("user", "area of block 2?")]


def run(coro):
    return asyncio.run(coro)


def transport(handler):
    return httpx.MockTransport(handler)


def capture(response_json, status=200):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(status, json=response_json)

    return seen, transport(handler)


# ---------------------------------------------------------------- OpenAI-compatible

def openai(t, key="sk-test"):
    return OpenAICompatProvider("groq", "m1", "synthetic_only", "https://api.example/v1", key, transport=t)


def test_openai_text_reply_and_usage():
    seen, t = capture({"model": "m1", "choices": [{"message": {"content": " hello "}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
    reply = run(openai(t).chat(CONVO, max_tokens=50))
    assert reply.text == "hello" and reply.usage.total == 15 and not reply.usage.estimated
    assert seen["url"] == "https://api.example/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer sk-test"
    assert seen["body"]["max_tokens"] == 50 and seen["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert "tools" not in seen["body"]


def test_openai_tool_call_string_arguments_and_tool_round_trip():
    seen, t = capture({"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "get_area", "arguments": "{\"block\": \"2\"}"}}]}}]})
    reply = run(openai(t).chat(CONVO, [TOOL]))
    assert reply.tool_calls == (ToolCall("c1", "get_area", {"block": "2"}),)
    assert seen["body"]["tools"][0]["function"]["name"] == "get_area"

    seen2, t2 = capture({"choices": [{"message": {"content": "12 ha"}}]})
    history = CONVO + [ChatMessage("assistant", "", tool_calls=reply.tool_calls),
                       ChatMessage("tool", "12", tool_call_id="c1", name="get_area")]
    run(openai(t2).chat(history, [TOOL]))
    wire = seen2["body"]["messages"]
    assert wire[2]["tool_calls"][0]["function"]["arguments"] == "{\"block\": \"2\"}"
    assert wire[3] == {"role": "tool", "tool_call_id": "c1", "content": "12"}


def test_openai_object_arguments_accepted_and_missing_usage_is_estimated():
    _, t = capture({"choices": [{"message": {"content": "ok", "tool_calls": [
        {"function": {"name": "get_area", "arguments": {"block": "3"}}}]}}]})
    reply = run(openai(t).chat(CONVO, [TOOL]))
    assert reply.tool_calls[0].arguments == {"block": "3"} and reply.tool_calls[0].id == "call_0"
    assert reply.usage.estimated and reply.usage.input_tokens > 0


def test_openai_no_key_sends_no_authorization_header_for_ollama():
    seen, t = capture({"choices": [{"message": {"content": "hi"}}]})
    run(openai(t, key="").chat(CONVO))
    assert "authorization" not in seen["headers"]


@pytest.mark.parametrize("body,kind", [({"choices": []}, "format"), ({"choices": [{"message": {"content": ""}}]}, "format")])
def test_openai_bad_bodies(body, kind):
    _, t = capture(body)
    with pytest.raises(ProviderError) as exc:
        run(openai(t).chat(CONVO))
    assert exc.value.kind == kind


def test_openai_malformed_tool_arguments():
    _, t = capture({"choices": [{"message": {"tool_calls": [{"function": {"name": "x", "arguments": "{not json"}}]}}]})
    with pytest.raises(ProviderError) as exc:
        run(openai(t).chat(CONVO, [TOOL]))
    assert exc.value.kind == "format"


def test_http_error_timeout_and_connect_are_provider_errors_and_never_echo_the_key():
    key = "sk-secret-123"
    _, t = capture({"error": "bad"}, status=429)
    with pytest.raises(ProviderError) as exc:
        run(openai(t, key).chat(CONVO))
    assert exc.value.kind == "http" and exc.value.status == 429 and key not in str(exc.value)

    def boom(kind):
        def handler(request):
            raise kind("x")
        return transport(handler)

    with pytest.raises(ProviderError) as exc:
        run(openai(boom(httpx.ReadTimeout)).chat(CONVO))
    assert exc.value.kind == "timeout"
    with pytest.raises(ProviderError) as exc:
        run(openai(boom(httpx.ConnectError)).chat(CONVO))
    assert exc.value.kind == "connect"


def test_non_json_body():
    t = transport(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(ProviderError) as exc:
        run(openai(t).chat(CONVO))
    assert exc.value.kind == "format"


# ---------------------------------------------------------------- Anthropic

def claude(t):
    return AnthropicProvider("anthropic", "claude-x", "synthetic_only", "https://api.anthropic.test", "ak-1", transport=t)


def test_anthropic_request_shape_and_reply():
    seen, t = capture({"model": "claude-x", "stop_reason": "end_turn", "content": [{"type": "text", "text": "12 ha"}],
                       "usage": {"input_tokens": 20, "output_tokens": 4}})
    reply = run(claude(t).chat(CONVO, [TOOL], max_tokens=99))
    b = seen["body"]
    assert seen["url"] == "https://api.anthropic.test/v1/messages"
    assert seen["headers"]["x-api-key"] == "ak-1" and seen["headers"]["anthropic-version"] == "2023-06-01"
    assert b["system"] == "be brief" and b["messages"] == [{"role": "user", "content": "area of block 2?"}]
    assert b["max_tokens"] == 99 and b["tools"][0]["input_schema"]["type"] == "object"
    assert reply.text == "12 ha" and reply.usage.total == 24 and reply.finish_reason == "end_turn"


def test_anthropic_tool_use_and_results_are_merged_into_one_user_turn():
    _, t = capture({"content": [{"type": "text", "text": "checking"},
                                {"type": "tool_use", "id": "tu1", "name": "get_area", "input": {"block": "2"}}]})
    reply = run(claude(t).chat(CONVO, [TOOL]))
    assert reply.text == "checking" and reply.tool_calls == (ToolCall("tu1", "get_area", {"block": "2"}),)

    seen, t2 = capture({"content": [{"type": "text", "text": "done"}]})
    history = CONVO + [ChatMessage("assistant", "checking", tool_calls=(ToolCall("tu1", "a", {}), ToolCall("tu2", "b", {}))),
                       ChatMessage("tool", "1", tool_call_id="tu1", name="a"),
                       ChatMessage("tool", "2", tool_call_id="tu2", name="b")]
    run(claude(t2).chat(history, [TOOL]))
    wire = seen["body"]["messages"]
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert [b["type"] for b in wire[1]["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in wire[2]["content"]] == ["tu1", "tu2"]


def test_anthropic_empty_content_is_an_error():
    _, t = capture({"content": []})
    with pytest.raises(ProviderError):
        run(claude(t).chat(CONVO))


# ---------------------------------------------------------------- Gemini

def gemini(t):
    return GeminiProvider("gemini", "gem-x", "synthetic_only", "https://gen.test/v1beta", "gk-1", transport=t)


def test_gemini_key_is_in_a_header_not_the_url():
    seen, t = capture({"candidates": [{"content": {"parts": [{"text": "12 ha"}]}, "finishReason": "STOP"}],
                       "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 2}})
    reply = run(gemini(t).chat(CONVO, [TOOL], max_tokens=70))
    assert seen["url"] == "https://gen.test/v1beta/models/gem-x:generateContent"
    assert "gk-1" not in seen["url"] and seen["headers"]["x-goog-api-key"] == "gk-1"
    b = seen["body"]
    assert b["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert b["contents"] == [{"role": "user", "parts": [{"text": "area of block 2?"}]}]
    assert b["generationConfig"]["maxOutputTokens"] == 70
    assert b["tools"][0]["functionDeclarations"][0]["name"] == "get_area"
    assert reply.text == "12 ha" and reply.usage.total == 11


def test_gemini_function_call_and_response_round_trip():
    _, t = capture({"candidates": [{"content": {"parts": [{"functionCall": {"name": "get_area", "args": {"block": "2"}}}]}}]})
    reply = run(gemini(t).chat(CONVO, [TOOL]))
    assert reply.tool_calls == (ToolCall("call_0", "get_area", {"block": "2"}),)

    seen, t2 = capture({"candidates": [{"content": {"parts": [{"text": "12"}]}}]})
    history = CONVO + [ChatMessage("assistant", "", tool_calls=reply.tool_calls),
                       ChatMessage("tool", "12", tool_call_id="call_0", name="get_area")]
    run(gemini(t2).chat(history, [TOOL]))
    contents = seen["body"]["contents"]
    assert contents[1] == {"role": "model", "parts": [{"functionCall": {"name": "get_area", "args": {"block": "2"}}}]}
    assert contents[2]["parts"][0]["functionResponse"] == {"name": "get_area", "response": {"result": "12"}}


def test_gemini_thought_signature_is_kept_and_sent_back():
    _, t = capture({"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "get_area", "args": {}}, "thoughtSignature": "sig-abc"}]}}]})
    reply = run(gemini(t).chat(CONVO, [TOOL]))
    assert reply.tool_calls[0].signature == "sig-abc"

    seen, t2 = capture({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
    history = CONVO + [ChatMessage("assistant", "", tool_calls=reply.tool_calls),
                       ChatMessage("tool", "1", tool_call_id="call_0", name="get_area")]
    run(gemini(t2).chat(history, [TOOL]))
    assert seen["body"]["contents"][1]["parts"][0]["thoughtSignature"] == "sig-abc"
    # a provider that sends no signature must not get an empty field
    _, t3 = capture({"candidates": [{"content": {"parts": [{"functionCall": {"name": "x", "args": {}}}]}}]})
    assert run(gemini(t3).chat(CONVO, [TOOL])).tool_calls[0].signature is None


def test_gemini_no_candidates():
    _, t = capture({"candidates": []})
    with pytest.raises(ProviderError):
        run(gemini(t).chat(CONVO))


# ---------------------------------------------------------------- registry

def cfg(**kw):
    return SimpleNamespace(**kw)


def test_unconfigured_providers_are_none_and_ollama_needs_no_key():
    s = cfg()
    assert build_provider("groq", s) is None and build_provider("gemini", s) is None
    assert build_provider("anthropic", s) is None
    ollama = build_provider("ollama", s)
    assert ollama is not None and ollama.data_class == "real_ok" and ollama.base_url == "http://localhost:11434/v1"


def test_qwen_and_kimi_need_an_explicit_model():
    assert build_provider("qwen", cfg(QWEN_API_KEY="k")) is None
    p = build_provider("qwen", cfg(QWEN_API_KEY="k", QWEN_MODEL="some-model"))
    assert p is not None and p.model == "some-model" and "dashscope" in p.base_url
    k = build_provider("kimi", cfg(KIMI_API_KEY="k", KIMI_MODEL="m", KIMI_BASE_URL="https://kimi.test/v1"))
    assert k.base_url == "https://kimi.test/v1"


def test_hosted_providers_are_synthetic_only_and_only_ollama_is_real_ok():
    s = cfg(GROQ_API_KEY="a", GEMINI_API_KEY="b", ANTHROPIC_API_KEY="c", QWEN_API_KEY="d", QWEN_MODEL="m",
            KIMI_API_KEY="e", KIMI_MODEL="m", OPENROUTER_API_KEY="f", OPENROUTER_MODEL="m")
    classes = {p.name: p.data_class for p in configured_providers(s)}
    assert classes.pop("ollama") == "real_ok"
    assert set(classes.values()) == {"synthetic_only"} and len(classes) == 7 - 1


def test_ollama_bare_host_setting_gets_v1_appended():
    p = build_provider("ollama", cfg(OLLAMA_BASE_URL="http://gpu-box:11434/", OLLAMA_MODEL="qwen2.5"))
    assert p.base_url == "http://gpu-box:11434/v1" and p.model == "qwen2.5"


def test_provider_order_setting():
    assert provider_order(cfg(CHATBOT_PROVIDER_ORDER="ollama, GROQ ,nonsense")) == ["ollama", "groq"]
    assert "ollama" in provider_order(cfg(CHATBOT_PROVIDER_ORDER=""))
    assert [p.name for p in configured_providers(cfg(CHATBOT_PROVIDER_ORDER="groq,ollama", GROQ_API_KEY="k"))] == ["groq", "ollama"]


# ---------------------------------------------------------------- report generator fold

def test_report_generator_keeps_its_error_string_contract(monkeypatch):
    from app.services.report import ai_generator

    class Down:
        name = "ollama"

        async def chat(self, *a, **k):
            raise ProviderError("cannot connect to ollama", "connect")

    gen = ai_generator.ProviderTextGenerator(Down())
    text = run(gen.generate_section("p"))
    assert text.startswith("[ERROR:") and "ollama pull" in text

    fb = ai_generator.FallbackGenerator()
    fb.providers = [("ollama", gen)]
    assert run(fb.generate_section("p")).startswith("[ERROR: All AI providers failed.")


def test_report_generator_skips_hosted_providers_unless_allowed(monkeypatch):
    from app.core.config import settings
    from app.services.report import ai_generator

    monkeypatch.setattr(settings, "GROQ_API_KEY", "k", raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k", raising=False)
    assert [n for n, _ in ai_generator.FallbackGenerator(allow_hosted=False).providers] == ["ollama"]
    assert [n for n, _ in ai_generator.FallbackGenerator(allow_hosted=True).providers] == ["groq", "gemini", "ollama"]
    assert settings.REPORT_ALLOW_HOSTED_PROVIDERS is False


def test_report_generator_returns_text_and_uses_groq_system_prompt():
    from app.services.report import ai_generator

    seen, t = capture({"choices": [{"message": {"content": "section text"}}]})
    gen = ai_generator.ProviderTextGenerator(openai(t))
    assert run(gen.generate_section("write", max_tokens=100)) == "section text"
    assert seen["body"]["messages"][0]["content"].startswith("You are a Nepali government forest officer")
    assert seen["body"]["temperature"] == 0.7 and seen["body"]["max_tokens"] == 100
