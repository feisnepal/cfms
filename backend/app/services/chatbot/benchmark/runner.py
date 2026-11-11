"""Run one question against one provider: a small tool loop over the synthetic tools."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.chatbot.providers import ChatMessage, ChatProvider, ProviderError

from .fixture import TOOLS, execute_tool
from .prompt import SYSTEM_PROMPT_V0

logger = logging.getLogger(__name__)

TESTSET_DIR = Path(__file__).resolve().parents[4] / "tests" / "services" / "chatbot"
TESTSET_FILES = ("testset_v1.json", "testset_v1_extra.json", "testset_v1_extra2.json")

# Handled before the model in the real design (access, cap, outage, kill switch, routing, input guard), so they say nothing about a model.
PRE_MODEL_FIXTURES = {"cap_reached", "provider_down", "local_model_down_hosted_up", "not_approved", "revoked_mid_session",
                      "kill_switch", "approval_expired", "pasted_household_row"}
# Phase C5 (free SQL) is not buildable on the synthetic tools; excluded from model comparison.
EXCLUDED_IDS = {"X10", "X11", "X13"}

MAX_ROUNDS = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}


def load_questions(include_pre_model: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for name in TESTSET_FILES:
        out += json.loads((TESTSET_DIR / name).read_text(encoding="utf-8"))["questions"]
    if include_pre_model:
        return out
    return [q for q in out if (q["context"].get("fixture") not in PRE_MODEL_FIXTURES) and q["id"] not in EXCLUDED_IDS]


def sample_questions(questions: List[Dict[str, Any]], n: int, seed: int = 7) -> List[Dict[str, Any]]:
    """Stratified by category, round-robin over a seeded shuffle, so a small run still covers every category and both scripts."""
    rng = random.Random(seed)
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for q in questions:
        buckets.setdefault(q["category"], []).append(q)
    for b in buckets.values():
        rng.shuffle(b)
    picked: List[Dict[str, Any]] = []
    while len(picked) < min(n, len(questions)):
        for cat in sorted(buckets):
            if buckets[cat] and len(picked) < n:
                picked.append(buckets[cat].pop())
    return sorted(picked, key=lambda q: q["id"])


def _opening(q: Dict[str, Any], prompt_version: str = "v0") -> List[ChatMessage]:
    if prompt_version == "v1":
        from app.services.chatbot.prompt import build_system_prompt

        step = q["context"].get("step")
        system = build_system_prompt(q["question"], step=step, forest_open=bool(step) or q["context"].get("forest") == "synthetic",
                                     read_only=q["role"] == "read_only")
    else:
        system = SYSTEM_PROMPT_V0
    msgs = [ChatMessage("system", system)]
    for turn in q.get("history", []):
        msgs.append(ChatMessage(turn["role"], turn["text"]))
    msgs.append(ChatMessage("user", q["question"]))
    return msgs


async def _chat_with_retry(provider: ChatProvider, messages, tools, retries: int, max_tokens: int):
    for attempt in range(retries + 1):
        try:
            return await provider.chat(messages, tools, max_tokens=max_tokens, temperature=0.2)
        except ProviderError as exc:
            # A dropped connection is as transient as a timeout or a 429 on a long benchmark run (seen on 2026-11-10).
            retryable = exc.kind in {"timeout", "connect"} or (exc.kind == "http" and exc.status in RETRY_STATUSES)
            if not retryable or attempt == retries:
                raise
            wait = min(65.0, 5.0 * (2 ** attempt))
            logger.info("%s: %s, waiting %.0fs", provider.name, exc, wait)
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")


async def run_question(
    provider: ChatProvider, q: Dict[str, Any], *, retries: int = 5, max_tokens: int = 1500, prompt_version: str = "v0", retrieval_db=None,
) -> Dict[str, Any]:
    messages = _opening(q, prompt_version)
    ctx = {"context": q["context"], "role": q["role"], "expected": q["expected"]}
    if retrieval_db is not None:
        from app.services.chatbot import help_search

        step = q["context"].get("step")
        ctx["search_fn"] = lambda query: [
            {"title": h.title, "text": h.text} for h in help_search.search(retrieval_db, query or q["question"], limit=3, step=step)
        ]
    called: List[str] = []
    call_log: List[Dict[str, Any]] = []
    tool_outputs: List[str] = []
    tin = tout = 0
    estimated = False
    text = ""
    error: Optional[str] = None
    start = time.perf_counter()
    try:
        for _ in range(MAX_ROUNDS):
            reply = await _chat_with_retry(provider, messages, TOOLS, retries, max_tokens)
            tin += reply.usage.input_tokens
            tout += reply.usage.output_tokens
            estimated = estimated or reply.usage.estimated
            if not reply.tool_calls:
                text = reply.text
                break
            messages.append(ChatMessage("assistant", reply.text, tool_calls=reply.tool_calls))
            for call in reply.tool_calls:
                result = execute_tool(call.name, call.arguments, ctx)
                called.append(call.name)
                call_log.append({"name": call.name, "args": call.arguments})
                tool_outputs.append(result)
                messages.append(ChatMessage("tool", result, tool_call_id=call.id, name=call.name))
        else:
            error = "tool loop did not finish"
    except ProviderError as exc:
        error = f"{exc.kind}: {exc}"
    return {
        "id": q["id"], "provider": provider.name, "model": provider.model, "text": text, "tools_called": called,
        "tool_calls": call_log, "tool_output_text": " ".join(tool_outputs), "input_tokens": tin, "output_tokens": tout,
        "tokens_estimated": estimated, "latency_s": round(time.perf_counter() - start, 2), "error": error,
    }
