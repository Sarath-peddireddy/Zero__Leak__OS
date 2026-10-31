"""Offline tests for the 2026-10-31 fixes (fake Gemini, fake Telegram, DB copy):
  1. JIT keyword fallback: lessons are fetched for topics the opponent's TEXT mentions, not only its self-tags
     (both sides; Communication_Tone lessons on every turn);
  2. Judge: Tech_Integration + Communication_Tone topics, a two-topic note becomes two lessons;
  3. notify() retries network blips (War Room DMs, 🧠 alerts / approvals, reports, notices).
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))
import os  # noqa: E402
# .env may hold dev settings: a test never starts real shadow matches (Gemini), and pins self-play.
os.environ.setdefault("ZEROLEAK_SHADOW_MATCHES", "0")
os.environ.setdefault("ZEROLEAK_SELF_PLAY", "0")

import db_init  # noqa: E402

TEST_DB = HERE / "test_1031.db"
shutil.copy(HERE / "zeroleak_backup_before_1030_failure_tests.db", TEST_DB)  # 5 sales lessons, none for Neha
db_init.DB_PATH = TEST_DB

import bot_main as B  # noqa: E402
import llm_engine  # noqa: E402
import negotiation as N  # noqa: E402
import post_match as P  # noqa: E402
from telegram.error import BadRequest, Forbidden, TimedOut  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


SCRIPT = {"procurement": [], "sales": [], "judge": []}


WATCHDOG: list[str] = []  # scripted fourth-wall watchdog verdicts (10-31); default: no slip


async def fake_generate(agent, prompt, system_instruction=None, json_mode=False, temperature=None):
    if system_instruction in sys.modules["post_match"].WATCHDOG_SYSTEM.values():
        return WATCHDOG.pop(0) if WATCHDOG else '{"violation": false}'
    return SCRIPT[agent].pop(0)

llm_engine.generate = fake_generate
N.llm_engine.generate = fake_generate
j = json.dumps
run = asyncio.run
run(db_init.init_db())

# ================================================================ 1. keyword fallback (pure)
rt = N.retrieval_tags
check("RTO in text, tags only Price -> RTO added",
      rt(["Price"], "We need ₹41/parcel and a full RTO waiver.") == ["Price", "RTO"], rt(["Price"], "full RTO waiver"))
check("payment / days -> Payment_Terms", "Payment_Terms" in rt([], "We need 60-day payment terms."))
check("bare 'days' -> Payment_Terms", "Payment_Terms" in rt([], "We pay in 60 days."))
check("volume / commitment -> Volume", rt([], "Our volume is growing.") == ["Volume"]
      and "Volume" in rt([], "a binding commitment"))
check("rival quote -> Competitor_Quote", "Competitor_Quote" in rt([], "A rival quoted ₹40/parcel."))
check("15-month -> Contract_Length", "Contract_Length" in rt([], "We can do a 15-month contract."))
check("API / tracking -> Tech_Integration", "Tech_Integration" in rt([], "How does your tracking API work?"))
check("self-tags kept first, no duplicates", rt(["RTO", "Price"], "RTO waiver at ₹41") == ["RTO", "Price"])
check("no keywords -> self-tags only", rt(["Price"], "That is too high for us.") == ["Price"])
check("new tags + aliases normalise", N.normalize_friction_points(
    ["contract", "Volume commitment", "tracking", "tone", "Tech/Integration", "Communication Tone"], cap=None)
      == ["Contract_Length", "Volume", "Tech_Integration", "Communication_Tone"])
check("agents' tag list offers the new topics", "Tech_Integration" in N.TAGGING_BLOCK
      and "Communication_Tone" in N.TAGGING_BLOCK)

# ================================================================ 1b. fallback inside the real match loop
fetched = []
real_fetch = B.fetch_heuristics


async def spy_fetch(side, tags):
    fetched.append((side, list(tags) if tags is not None else None))
    return await real_fetch(side, tags)

B.fetch_heuristics = spy_fetch
run(db_init.upsert_heuristic("sales", "Communication_Tone", "m", "Stay friendly but firm."))
run(db_init.upsert_heuristic("procurement", "RTO", "m", "Ask for the RTO waiver on 15 months."))


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append((chat_id, text))

    async def send_chat_action(self, *a, **k):
        pass


def proc(text, tags):
    return j(dict(message=text, internal_note="", current_friction_points=tags, executed_directive_ids=[],
                  proposed_price=41, payment_days=60, deal_closed=False, walk_away=False))


def sales(text, tags):
    return j(dict(message=text, proposed_price=43, offers_rto_waiver=False, contract_months=12, payment_days=30,
                  current_friction_points=tags, executed_directive_ids=[], requires_manager_approval=False,
                  escalation_message_to_manager="", deal_closed=False, walk_away=False))


async def loop_case(self_play: bool):
    N.SELF_PLAY = self_play
    sb, pb = FakeBot(), FakeBot()
    m = B.new_match(1, await db_init.fetch_mandate(), await db_init.fetch_static_ammo("sales"),
                    await db_init.fetch_static_ammo("procurement"))
    B.active_matches[-1] = m
    SCRIPT["procurement"][:] = [proc("We need ₹41/parcel and a full RTO waiver, on 60-day payment terms. "
                                     "(1.2M parcels/month.)", ["Price"]),
                                proc("Still ₹41/parcel. (1.2M parcels/month.)", ["Price"])]
    SCRIPT["sales"][:] = [sales("₹43/parcel on 12 months. I can offer the RTO waiver only on 18 months.", ["Price"])]
    B.TURN_DELAY_S, B.MAX_MESSAGES = (0, 0), 3
    fetched.clear()
    await B.run_match(-1, sb, pb)
    return m

m = run(loop_case(self_play=False))
sales_fetch = [t for s, t in fetched if s == "sales"]
check("Arjun's turn fetched RTO + Payment_Terms from Neha's TEXT (her tag: Price only)",
      sales_fetch and {"Price", "RTO", "Payment_Terms"} <= set(sales_fetch[0]), fetched)
check("Arjun's turn also fetched Communication_Tone (always loaded)",
      sales_fetch and "Communication_Tone" in sales_fetch[0], fetched)
check("lessons actually used on that turn include RTO + Payment_Terms + tone",
      {"RTO", "Payment_Terms", "Communication_Tone"} <= m["playbook_topics"], m["playbook_topics"])
check("payment days recorded from both agents' JSON",
      m["procurement_payment_days"][:1] == [60] and m["sales_payment_days"] == [30],
      (m["procurement_payment_days"], m["sales_payment_days"]))
check("Neha's lessons stay off while SELF_PLAY is off", not [1 for s, t in fetched if s == "procurement"])

run(loop_case(self_play=True))
proc_fetch = [t for s, t in fetched if s == "procurement"]
check("SELF_PLAY on: Neha's 2nd turn fetched RTO + Contract_Length from Arjun's TEXT (his tag: Price only)",
      len(proc_fetch) >= 2 and {"RTO", "Contract_Length"} <= set(proc_fetch[1]), proc_fetch)
N.SELF_PLAY = False
B.fetch_heuristics = real_fetch

# ================================================================ 2. Judge topics + two-topic split
CTX = [("Procure_Agent", "₹41/parcel, RTO waiver, peak-season worries."), ("Sales_Agent", "₹43/parcel."),
       ("Procure_Agent", "₹41 or we walk.")]


def ledger(mid, note):
    for spk, txt in CTX + [("Human_Whisper", note)]:
        run(db_init.log_message(mid, spk, txt))

check("Judge format lists the new topics + split rule", "Tech_Integration" in P._JUDGE_FORMAT
      and "Communication_Tone" in P._JUDGE_FORMAT and "two lessons" in P._JUDGE_FORMAT)
rto_before = run(db_init.fetch_heuristic("sales", "RTO"))["new_directive"]
SCRIPT["judge"][:] = [j({"lessons": [
    {"scope": "standing", "topic_tag": "SLA", "past_mistake": "m", "new_directive": "Cite our 15,000+ truck fleet when she worries about peak season."},
    {"scope": "standing", "topic_tag": "RTO", "past_mistake": "m", "new_directive": "Never offer the RTO waiver on 12 months."}]}),
    j({"similarity": 80, "past_mistake": "m", "new_directive": rto_before + " Never offer it on 12 months, even under a walk-away threat."})]
ledger("t31_split", "Cite our 15,000+ truck fleet when she worries about peak season, and never offer the RTO "
                    "waiver on 12 months even if she threatens to walk.")
outs = run(P.run_judge_agent("t31_split"))
check("two-topic note -> two proposals (SLA new, RTO merged into the live rule)",
      [(o.action, o.topic_tag, bool(o.previous)) for o in outs] == [("proposed", "SLA", False), ("proposed", "RTO", True)],
      outs)
for o in outs:  # the staging gate: nothing is live until the coach approves
    run(db_init.resolve_pending(o.heuristic_id, approve=True))
check("each lesson stored under its own topic",
      "fleet" in run(db_init.fetch_heuristic("sales", "SLA"))["new_directive"]
      and "fleet" not in run(db_init.fetch_heuristic("sales", "RTO"))["new_directive"])

SCRIPT["judge"][:] = [j({"lessons": [{"scope": "standing", "topic_tag": "Tech/Integration", "past_mistake": "m",
                                      "new_directive": "When she asks about tracking, mention our API integration in under 24 hours."}]})]
ledger("t31_tech", "When she asks about tracking, mention our API integration in under 24 hours.")
outs = run(P.run_judge_agent("t31_tech"))
check("tech note -> Tech_Integration lesson (was refused as 'no topic')",
      [(o.action, o.topic_tag) for o in outs] == [("proposed", "Tech_Integration")], outs)
SCRIPT["judge"][:] = [j({"lessons": [{"scope": "standing", "topic_tag": "Communication Tone", "past_mistake": "m",
                                      "new_directive": "Keep the tone friendly but firm."}]}),
                      j({"similarity": 90, "past_mistake": "m", "new_directive": "Stay friendly but firm."})]
ledger("t31_tone", "Keep the tone friendly but firm.")
outs = run(P.run_judge_agent("t31_tone"))
check("tone note -> Communication_Tone lesson", [o.topic_tag for o in outs] == ["Communication_Tone"], outs)
SCRIPT["judge"][:] = [j({"lessons": [{"scope": "none", "topic_tag": "Price", "past_mistake": "m", "new_directive": "x"},
                                     {"scope": "standing", "topic_tag": "Other", "past_mistake": "m", "new_directive": "y"}]})]
ledger("t31_none", "Nice work on that one.")
outs = run(P.run_judge_agent("t31_none"))
check("all lessons skipped -> one skipped outcome with the first reason",
      [(o.action, o.reason) for o in outs] == [("skipped", "no_lesson")], outs)
SCRIPT["judge"][:] = [j({"scope": "standing", "topic_tag": "Volume", "past_mistake": "m", "new_directive": "Ask for tiers."})]
ledger("t31_old", "Ask for volume tiers.")
check("old single-lesson JSON still works", [o.topic_tag for o in run(P.run_judge_agent("t31_old"))] == ["Volume"])


# ================================================================ 3. notify retries
class FlakyBot:
    def __init__(self, errors):
        self.errors, self.calls, self.sent = list(errors), 0, []

    async def send_message(self, chat_id, text, **kw):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append(text)

B.NOTIFY_RETRY_DELAY_S = 0.0
import logging  # noqa: E402
logging.getLogger("zeroleak").setLevel(logging.CRITICAL)  # the expected failures below log tracebacks
fb = FlakyBot([TimedOut(), TimedOut()])
run(B.notify(fb, 5, "🧠 alert"))
check("2 network blips -> delivered on the 3rd try", fb.sent == ["🧠 alert"] and fb.calls == 3, fb.calls)
fb = FlakyBot([TimedOut()] * 5)
run(B.notify(fb, 5, "x"))
check("gives up after 3 retries (4 tries), no exception", fb.sent == [] and fb.calls == 4, fb.calls)
fb = FlakyBot([BadRequest("bad html")])
run(B.notify(fb, 5, "x"))
check("BadRequest is not retried", fb.calls == 1, fb.calls)
fb = FlakyBot([Forbidden("blocked")])
run(B.notify(fb, 5, "x"))
check("Forbidden (coach blocked the bot) is not retried", fb.calls == 1, fb.calls)

# ================================================================ 4. constraint words + setup notes (10-31 wrap-up)
old = "Never go above ₹41/parcel. RTO only for 18 months."
check("dropped_constraints: 'above', 'never' and 'only' lost", P.dropped_constraints(
    old, "Go to ₹41/parcel. RTO for 18 months.") == ["above", "never", "only"],
      P.dropped_constraints(old, "Go to ₹41/parcel. RTO for 18 months."))
check("dropped_constraints: one of two 'never' lost counts", P.dropped_constraints(
    "Never go above ₹41; never walk away.", "Never go above ₹41.") == ["never"])
check("dropped_constraints: kept or added -> none", P.dropped_constraints(old, old + " Never reveal the ceiling.") == [])
r = P.risky_change({"new_directive": "Never offer more than 30 days; 45 days only for 24 months.", "is_critical": 0},
                   {"new_directive": "Offer up to 30 days; 45 days for 24 months, ask for volume first."})
check("risky_change flags dropped limit wording (numbers all kept)", "limit wording" in r and "removes" not in r, r)
check("risky_change: safe merge still safe", P.risky_change(
    {"new_directive": "Never go above ₹41.", "is_critical": 0},
    {"new_directive": "Never go above ₹41. Anchor on the rival's ₹40 quote."}) == "")

SETUP = "Don't go above ₹41. Insist on 12 months and 60-day payment terms. Keep pushing, but never walk away."
rows = [{"speaker": "Procure_Whisper", "payload_text": P.SETUP_NOTE_PREFIX + SETUP},          # tagged brief
        {"speaker": "Human_Whisper", "payload_text": "Hold ₹43 on 12 months."},              # before message 1
        {"speaker": "Procure_Agent", "payload_text": "₹38/parcel please."},
        {"speaker": "Sales_Agent", "payload_text": "₹45/parcel."},
        {"speaker": "Procure_Whisper", "payload_text": P.SETUP_NOTE_PREFIX + "late brief"},   # tagged, mid-match
        {"speaker": "Human_Whisper", "payload_text": "Challenge the rival quote."}]          # real in-match note
N.SELF_PLAY = P.SELF_PLAY = True
blocks = P.context_blocks(rows)
check("Judge ignores setup notes (tagged, or sent before any Boardroom message)",
      [(b.side, b.text) for b in blocks] == [("sales", "Challenge the rival quote.")], [(b.side, b.text) for b in blocks])
N.SELF_PLAY = P.SELF_PLAY = False

m = B.new_match(1, run(db_init.fetch_mandate()), [], [])
run(B.add_whisper(m, "procurement", SETUP, setup=True))
run(B.add_whisper(m, "procurement", "Anchor on the rival quote."))
led = run(db_init.fetch_ledger(m["match_id"]))
check("add_whisper(setup=True): ledger row tagged, agent gets the plain text",
      [r["payload_text"] for r in led] == [P.SETUP_NOTE_PREFIX + SETUP, "Anchor on the rival quote."]
      and m["procurement_coaching_directives"][0]["text"] == SETUP, [r["payload_text"] for r in led])

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
