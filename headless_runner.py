"""
ZeroLeak OS - headless match runner and scoreboard (ROADMAP Phase B item 4, used now to measure Phase A).

Plays Arjun vs Neha back to back without Telegram. It drives the real match loop (bot_main.run_match)
with stand-in bots, so every rule of the live bot applies (price guard, walk-away checks, escalation,
deadlock backstop). It runs on COPIES of zeroleak.db, one per setup ("arm"):

    before   Arjun with an EMPTY sales playbook (as he was before any coaching)
    after    Arjun with the current sales playbook

Fair comparison:
  * Neha gets the same coaching note at the start of every match (--neha-note).
  * Arjun's escalations are answered at once by a fixed manager policy (--manager hold|close).
  * The Judge is OFF: no match changes any lesson, so every match in an arm starts from the same playbook.
  * Arms are interleaved (before, after, before, ...) so a slow or overloaded Gemini hour hits both.
Deal terms come from the same extraction call as the end-of-match report (reports.extract_terms).

Usage:
    python headless_runner.py --matches 5                 # 5 per arm
    python headless_runner.py --matches 3 --arms after --manager close
    python headless_runner.py --matches 5 --neha-note ""  # Neha without coaching
    python headless_runner.py --resume bench_runs/20261027_190000   # continue a cut-short run
While it runs, Windows is asked not to sleep on idle (closing the lid or choosing Sleep still stops it).
Output: bench_runs/<timestamp>/results.json, the two DB copies, and a summary table on stdout.
"""

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
DEFAULT_NOTE = "Don't go above ₹41. Insist on 12 months and 60-day payment terms. Keep pushing, but never walk away."
MATCH_TIMEOUT_S = 25 * 60
# Arjun's Boardroom text that mentions the system or a floor (the fourth wall / "never reveal a floor").
LEAK_RE = re.compile(r"playbook|lessons?\b|directive|guardrail|override|coach|my manager|\bfloor\b", re.I)


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--matches", type=int, default=5, help="matches per arm (default 5)")
    ap.add_argument("--arms", default="before,after", help="comma list of: before, after")
    ap.add_argument("--manager", choices=("hold", "close"), default="hold", help="answer to every escalation")
    ap.add_argument("--neha-note", default=DEFAULT_NOTE, help='coaching note for Neha ("" for none)')
    ap.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between messages (default 1)")
    ap.add_argument("--out", default=str(ROOT / "bench_runs"))
    ap.add_argument("--resume", metavar="RUN_DIR",
                    help="continue a cut-short run in RUN_DIR (same arms, note and manager; finished matches kept)")
    return ap.parse_args(argv)


ARGS = parse_args(sys.argv[1:])
os.environ["GEMINI_MODEL"] = ARGS.model  # llm_engine reads it at import

import db_init  # noqa: E402  (after GEMINI_MODEL; DB_PATH is switched per arm below)
import bot_main as B  # noqa: E402
import llm_engine  # noqa: E402
import negotiation as N  # noqa: E402
import reports  # noqa: E402

logger = logging.getLogger("zeroleak.bench")


# ------------------------------------------------------------------ stand-ins for Telegram


class QuietBot:
    """Records what would have been sent; every other Bot method is a no-op."""

    def __init__(self, name):
        self.name, self.sent, self._next_id = name, [], 1

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        self._next_id += 1
        return SimpleNamespace(message_id=self._next_id)

    def __getattr__(self, attr):
        async def noop(*a, **kw):
            return None
        return noop


class Collector(logging.Handler):
    """Keeps this match's log lines, to count guard blocks and walk-away rewrites."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def count(self, needle):
        return sum(needle in line for line in self.lines)


async def bench_debrief(match, sales_bot, proc_bot, loop_task):
    """Replaces bot_main.debrief: deal extraction only. No Judge (lessons stay fixed), no reports."""
    if loop_task is not None and not loop_task.done():
        await asyncio.wait([loop_task], timeout=60)
    try:
        match["_terms"] = await reports.extract_terms(match)
    except Exception as e:  # noqa: BLE001  (a failed extraction must not stop the run)
        match["_terms_error"] = repr(e)


async def auto_manager(match, decision):
    """Answers every escalation at once with the fixed policy."""
    while match["status"] != "ENDED":
        if match["status"] == "AWAITING_MANAGER_APPROVAL" and not match["decision_event"].is_set():
            B.take_decision(match, decision)
        await asyncio.sleep(0.1)


# ------------------------------------------------------------------ one match


def keep_awake(on: bool) -> None:
    """Windows only: stop idle sleep while the run lasts (the 2026-10-26 overnight run died when the PC slept)."""
    if sys.platform != "win32":
        return
    import ctypes
    es_continuous, es_system_required = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | (es_system_required if on else 0))


def prepare_db(run_dir: Path, arm: str, reuse: bool = False) -> Path:
    path = run_dir / f"db_{arm}.db"
    if reuse and path.exists():  # --resume: keep the copy the finished matches were played on
        return path
    shutil.copy(ROOT / "zeroleak.db", path)
    if arm == "before":
        with sqlite3.connect(path) as c:
            c.execute("DELETE FROM sales_heuristics")
    return path


def _priced(offers):
    return [p for p in offers if p is not None]


def score(arm, idx, match, collector, seconds, sales_bot):
    sales_texts = [t["text"] for t in match["transcript"] if t["role"] == "sales"]
    proc_texts = [t["text"] for t in match["transcript"] if t["role"] == "procurement"]
    terms = match.get("_terms")
    questions = [e["question"] for e in match["escalations"]]
    arjun, neha = _priced(match["sales_offers"]), _priced(match.get("procurement_offers", []))
    leaks = [t for t in sales_texts if LEAK_RE.search(t)]
    deal = match["end_code"] == "deal"
    return {
        "arm": arm, "index": idx, "match_id": match["match_id"], "end_code": match["end_code"],
        "deal": deal, "seconds": round(seconds), "messages": len(match["transcript"]),
        "rate": terms.rate if terms and deal else None,
        "payment_days": terms.payment_days if terms and deal else None,
        "contract_months": terms.contract_months if terms and deal else None,
        "rto_waiver": terms.rto_waiver if terms and deal else None,
        "arjun_first": arjun[0] if arjun else None, "arjun_lowest": min(arjun) if arjun else None,
        "arjun_last": arjun[-1] if arjun else None, "neha_last": neha[-1] if neha else None,
        "escalations": len(questions),
        "escalations_self": sum(not (q.startswith("We're deadlocked") or q.startswith("I'm ready to walk away"))
                                for q in questions),
        "escalations_backstop": sum(q.startswith("We're deadlocked") for q in questions),
        "escalations_walk": sum(q.startswith("I'm ready to walk away") for q in questions),
        "guard_blocks": collector.count("Sales draft blocked"),
        "walk_rewrites": collector.count("walk-away not honoured"),
        "walks_ignored": collector.count("walk_away ignored"),
        "proc_rewrites": collector.count("Procurement draft rewritten"),
        "fallbacks": sum(t == N.FALLBACK_SALES_LINE for t in sales_texts),
        "leaks": len(leaks), "leak_samples": [t[:200] for t in leaks[:3]],
        "number_words": sum(bool(N.number_words(t)) for t in sales_texts + proc_texts),
        "lessons_used": sorted(match["playbook_topics"]),
        "terms_error": match.get("_terms_error"),
        "transcript": match["transcript"],
        "escalation_questions": questions,
    }


async def play(arm, idx, decision, note, collector):
    group, coach = -900_000 - idx, 900_000 + idx
    sales_bot, proc_bot = QuietBot("sales"), QuietBot("proc")
    match = B.new_match(coach, await db_init.fetch_mandate(), await db_init.fetch_static_ammo("sales"),
                        await db_init.fetch_static_ammo("procurement"))
    match["procurement_war_room_chat_id"] = coach
    if note:
        match["procurement_coaching_directives"].append({"text": note, "status": N.PENDING})
    B.active_matches[group] = match
    collector.lines.clear()
    started = time.monotonic()
    loop = asyncio.create_task(B.run_match(group, sales_bot, proc_bot))
    B.match_tasks[group] = loop
    manager = asyncio.create_task(auto_manager(match, decision))
    try:
        await asyncio.wait_for(asyncio.shield(loop), timeout=MATCH_TIMEOUT_S)
    except TimeoutError:
        logger.warning("Match %s hit the %ds timeout; ending it.", match["match_id"], MATCH_TIMEOUT_S)
        await B.finish_match(match, group, sales_bot, proc_bot, "cap")
        await asyncio.wait([loop], timeout=60)
    manager.cancel()
    await asyncio.gather(*list(B.judge_tasks), return_exceptions=True)  # bench_debrief tasks
    B.active_matches.pop(group, None)
    return score(arm, idx, match, collector, time.monotonic() - started, sales_bot)


# ------------------------------------------------------------------ summary


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def summarise(rows):
    out = {}
    for arm in dict.fromkeys(r["arm"] for r in rows):
        rs = [r for r in rows if r["arm"] == arm]
        deals = [r for r in rs if r["deal"]]
        out[arm] = {
            "matches": len(rs),
            "deals": len(deals),
            "deal_rate_pct": round(100 * len(deals) / len(rs)),
            "arjun_walkaways": sum(r["end_code"] == "sales_walkaway" for r in rs),
            "neha_walkaways": sum(r["end_code"] == "walkaway" for r in rs),
            "capped_or_errors": sum(r["end_code"] in ("cap", "error") for r in rs),
            "avg_deal_rate": _avg(r["rate"] for r in deals),
            "avg_margin_over_floor": _avg((r["rate"] - 41) if r["rate"] is not None else None for r in deals),
            "avg_payment_days": _avg(r["payment_days"] for r in deals),
            "rto_given_in_deals": sum(r["rto_waiver"] == "included" for r in deals),
            "avg_lowest_offer": _avg(r["arjun_lowest"] for r in rs),
            "avg_escalations": _avg(r["escalations"] for r in rs),
            "avg_messages": _avg(r["messages"] for r in rs),
            "guard_blocks": sum(r["guard_blocks"] for r in rs),
            "walk_rewrites": sum(r["walk_rewrites"] for r in rs),
            "leaks": sum(r["leaks"] for r in rs),
            "number_words": sum(r["number_words"] for r in rs),
        }
    return out


def print_table(summary):
    rows = [("Matches", "matches"), ("Deals", "deals"), ("Deal rate %", "deal_rate_pct"),
            ("Arjun walked away", "arjun_walkaways"), ("Neha walked away", "neha_walkaways"),
            ("Capped / errors", "capped_or_errors"), ("Avg deal ₹/parcel", "avg_deal_rate"),
            ("Avg margin over ₹41", "avg_margin_over_floor"), ("Avg payment days", "avg_payment_days"),
            ("RTO waiver in deals", "rto_given_in_deals"), ("Avg lowest offer ₹", "avg_lowest_offer"),
            ("Avg escalations", "avg_escalations"), ("Avg messages", "avg_messages"),
            ("Guard blocks", "guard_blocks"), ("Walk-away rewrites", "walk_rewrites"),
            ("Leak-word messages", "leaks"), ("Numbers in words", "number_words")]
    arms = list(summary)
    print("\n" + f"{'':24}" + "".join(f"{a:>12}" for a in arms))
    for label, key in rows:
        print(f"{label:24}" + "".join(f"{str(summary[a][key]):>12}" for a in arms))


# ------------------------------------------------------------------ main


def load_previous(run_dir: Path) -> tuple[dict, list[dict]]:
    """(config, finished match rows) of a run to resume."""
    path = run_dir / "results.json"
    if not path.exists():
        raise SystemExit(f"--resume: no results.json in {run_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["config"], data.get("matches", [])


async def main():
    previous, rows = None, []
    if ARGS.resume:
        run_dir = Path(ARGS.resume)
        previous, rows = load_previous(run_dir)
        arms, matches, decision = previous["arms"], previous["matches_per_arm"], previous["manager"]
        neha_note = previous["neha_note"]
    else:
        arms = [a.strip() for a in ARGS.arms.split(",") if a.strip()]
        matches, neha_note = ARGS.matches, ARGS.neha_note
        decision = B.DECISION_HOLD if ARGS.manager == "hold" else B.DECISION_CLOSE
        run_dir = Path(ARGS.out) / datetime.now().strftime("%Y%m%d_%H%M%S")
    if not arms or any(a not in ("before", "after") for a in arms):
        raise SystemExit("--arms must list before and/or after")
    run_dir.mkdir(parents=True, exist_ok=True)
    dbs = {arm: prepare_db(run_dir, arm, reuse=bool(previous)) for arm in arms}
    for path in dbs.values():
        db_init.DB_PATH = path
        await db_init.init_db()

    B.TURN_DELAY_S = (ARGS.delay, ARGS.delay)
    B.debrief = bench_debrief
    collector = Collector()
    logging.getLogger("zeroleak").addHandler(collector)

    if previous:
        config = previous
        config.setdefault("resumed", []).append(datetime.now().isoformat(timespec="seconds"))
    else:
        config = {"started": datetime.now().isoformat(timespec="seconds"), "model": ARGS.model,
                  "matches_per_arm": matches, "arms": arms, "manager": decision, "neha_note": neha_note,
                  "self_play": N.SELF_PLAY,
                  "playbook_after": [{"topic_tag": t, "critical": bool(c), "directive": d}
                                     for t, c, d in sqlite3.connect(dbs["after"]).execute(
                                         "SELECT topic_tag, is_critical, new_directive FROM sales_heuristics")]
                  if "after" in dbs else []}
    done = {(r["arm"], r["index"]) for r in rows}
    results = run_dir / "results.json"
    keep_awake(True)
    try:
        for i in range(matches):
            for arm in arms:
                if (arm, i) in done:
                    continue
                db_init.DB_PATH = dbs[arm]
                logger.info("=== %s match %d/%d", arm, i + 1, matches)
                row = await play(arm, i, decision, neha_note, collector)
                rows.append(row)
                print(f"[{arm} {i + 1}/{matches}] {row['end_code']:15} msgs={row['messages']:<3} "
                      f"rate={row['rate']} days={row['payment_days']} months={row['contract_months']} "
                      f"rto={row['rto_waiver']} lowest={row['arjun_lowest']} esc={row['escalations']} "
                      f"leaks={row['leaks']} ({row['seconds']}s)", flush=True)
                results.write_text(json.dumps({"config": config, "summary": summarise(rows), "matches": rows},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        keep_awake(False)
        await llm_engine.aclose()
    summary = summarise(rows)
    results.write_text(json.dumps({"config": config, "summary": summary, "matches": rows},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    print_table(summary)
    print(f"\nResults: {results}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
