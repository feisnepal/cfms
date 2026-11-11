"""C0.4: run the approved question set against configured providers using only synthetic data (CHATBOT_PLAN D13).

  python scripts/chatbot_benchmark.py --providers groq,gemini,lmstudio --sample 50 [--repeat 1] [--out DIR] [--judge gemini]
  python scripts/chatbot_benchmark.py --report DIR            # summary table from saved runs

Resumable: results are appended to <out>/<provider>.jsonl and a question already answered is skipped. Output holds model answers to
synthetic questions only.
"""
import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.chatbot.benchmark.runner import (  # noqa: E402
    _chat_with_retry, load_questions, run_question, sample_questions,
)
from app.services.chatbot.benchmark.scoring import score_answer  # noqa: E402
from app.services.chatbot.providers import ChatMessage, ProviderError, build_provider  # noqa: E402

JUDGE_PROMPT = """You grade an assistant's answer. Reply with JSON only: {{"score": 0|1|2, "reason": "<short>"}}.
2 = every required point is present and nothing forbidden is said; 1 = partly; 0 = wrong, missing the main point, or says something forbidden.
Accept equivalent wording and either language. The tool results below are the ground truth; a number must match them. An answer that politely
asks one useful clarifying question, or says it cannot help when no tool could, is not wrong unless it ignores a tool that would have answered.
Required points: {must_include}
Forbidden: {must_not}
The assistant could use these tools and they returned: {tool_text}
Question ({lang}): {question}
Answer: {answer}"""


def provider_from_spec(spec: str):
    """'groq' or 'groq:openai/gpt-oss-120b' (a model override for this run only)."""
    from app.core.config import settings
    from app.services.chatbot.providers.registry import SPECS

    name, _, model = spec.partition(":")
    if name not in SPECS:
        return None
    cfg = settings.copy(update={f"{SPECS[name].prefix}_MODEL": model}) if model else settings
    return build_provider(name, cfg)


def _family(model: str) -> str:
    """'openai/gpt-oss-120b' -> 'openai', 'qwen/qwen3.8-27b' -> 'qwen', 'gemini-3.6-flash' -> 'gemini'."""
    return model.split("/")[0].split("-")[0].lower()


def _done_ids(path: Path) -> set:
    """Ids already answered. A row that ended in an error is dropped from the file so a resumed run redoes it."""
    if not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    good = [r for r in rows if not r.get("error")]
    if len(good) != len(rows):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in good), encoding="utf-8")
    return {r["id"] for r in good}


async def run(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    if args.sample:
        questions = sample_questions(questions, args.sample, args.seed)
    retrieval_db = None
    if args.retrieval == "db":
        from app.core.database import SessionLocal

        retrieval_db = SessionLocal()  # reads the help cards loaded in the dev database (scripts/chatbot_load_help.py)
    print(f"{len(questions)} questions, prompt {args.prompt}, retrieval {args.retrieval}, categories: {sorted({q['category'] for q in questions})}")
    for name in args.providers.split(","):
        if not name.strip():
            continue  # --judge only
        provider = provider_from_spec(name.strip())
        if provider is None:
            print(f"[skip] {name}: not configured (key or model missing)")
            continue
        path = out / f"{provider.name}__{provider.model.replace('/', '_')}.jsonl"
        done = _done_ids(path)
        quota_hit = False
        for q in questions:
            if q["id"] in done:
                continue
            if quota_hit:
                break
            for _ in range(args.repeat):
                res = await run_question(provider, q, prompt_version=args.prompt, retrieval_db=retrieval_db)
                if (res["error"] or "").startswith("quota"):
                    print(f"[stop] {provider.name} {provider.model}: daily quota used up; rerun later, finished answers are kept")
                    quota_hit = True
                    break
                res["repeat"] = _
                res["auto"] = score_answer(q, res)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                flag = "ok " if res["auto"]["auto_pass"] else "FAIL"
                print(f"{provider.name:9} {q['id']:4} {flag} {res['latency_s']:6.1f}s {res['input_tokens']:5}+{res['output_tokens']:<4} tok  "
                      f"{res['error'] or ''}")
    if args.judge:
        await judge(out, questions, args.judge)
    report(out)


async def judge(out: Path, questions, judge_name: str) -> None:
    judge_provider = provider_from_spec(judge_name)
    if judge_provider is None:
        print(f"[skip] judge {judge_name} not configured")
        return
    by_id = {q["id"]: q for q in questions}
    judge_label = f"{judge_provider.name}:{judge_provider.model}"
    for path in sorted(out.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        done = 0
        for r in rows:
            # never grade a model from the judge's own family (gpt-oss judged by gpt-oss, Qwen by Qwen, Gemini by Gemini);
            # keep an earlier successful grade; a failed grade is retried
            if _family(r["model"]) == _family(judge_provider.model) or r.get("error") or r["id"] not in by_id:
                continue
            if r.get("judge", {}).get("score") is not None:
                continue
            q = by_id[r["id"]]
            prompt = JUDGE_PROMPT.format(
                must_include="; ".join(q["expected"]["must_include"]) or "-", must_not="; ".join(q["expected"]["must_not"]) or "-",
                tool_text=r["tool_output_text"][:1500], lang=q["lang"], question=q["question"], answer=r["text"])
            try:
                # room for the judge's own reasoning tokens, and the same retry on 429/503/timeouts as the candidates get
                reply = await _chat_with_retry(judge_provider, [ChatMessage("user", prompt)], None, 6, 1500)
                start, end = reply.text.find("{"), reply.text.rfind("}")
                r["judge"] = json.loads(reply.text[start:end + 1])
                r["judge"]["by"] = judge_label
            except (ProviderError, ValueError) as exc:
                r["judge"] = {"score": None, "reason": f"judge failed: {exc}", "by": judge_label}
            done += 1
            if done % 10 == 0:
                path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        print(f"judged {done} rows in {path.name} by {judge_label}")


def report(out: Path) -> None:
    print("\n| provider | model | n | answered | auto-pass | tool ok | no invented numbers | language ok | judge mean (0-2) | median s | tokens/q |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for path in sorted(out.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            continue
        n = len(rows)

        def pct(key: str) -> str:
            return f"{100 * sum(1 for r in rows if r['auto'].get(key)) / n:.0f}%"

        judged = [r["judge"]["score"] for r in rows if r.get("judge", {}).get("score") is not None]
        judge_cell = f"{sum(judged) / len(judged):.2f} ({len(judged)})" if judged else "-"
        ok_rows = [r for r in rows if not r.get("error")]
        median_s = statistics.median(r["latency_s"] for r in ok_rows) if ok_rows else 0
        tokens = statistics.mean(r["input_tokens"] + r["output_tokens"] for r in ok_rows) if ok_rows else 0
        print(f"| {rows[0]['provider']} | {rows[0]['model']} | {n} | {pct('answered')} | {pct('auto_pass')} | {pct('tool_ok')} | "
              f"{pct('no_invented_numbers')} | {pct('language_ok')} | {judge_cell} | {median_s:.1f} | {tokens:.0f} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "benchmark_runs"))
    ap.add_argument("--judge", default="")
    ap.add_argument("--prompt", default="v0", choices=["v0", "v1"], help="v0 = benchmark draft, v1 = services/chatbot/prompt.py")
    ap.add_argument("--retrieval", default="oracle", choices=["oracle", "db"], help="oracle = expected facts (isolates wording); db = the real help search")
    ap.add_argument("--report", default="")
    a = ap.parse_args()
    if a.report:
        report(Path(a.report))
    else:
        asyncio.run(run(a))
