"""Offline tests for the 2026-10-26 fixes: overload retry, quoted-coaching guard (both agents),
Neha's fourth-wall rule, before/after lessons in the reports."""

import asyncio
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace as NS

PROJECT = Path(__file__).resolve().parent.parent
SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))

import db_init  # noqa: E402

TEST_DB = SCRATCH / "test_1026.db"
shutil.copy(PROJECT / "data" / "zeroleak.db", TEST_DB)
db_init.DB_PATH = TEST_DB

import httpx  # noqa: E402
from google.genai import errors  # noqa: E402

import llm_engine as le  # noqa: E402
import negotiation as N  # noqa: E402
import post_match  # noqa: E402
import reports  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


run = asyncio.run

# ================================================================ 1. overload retry (llm_engine)
le.RETRY_DELAYS_S = (0.01, 0.01, 0.01, 0.01)
REAL_GENERATE = le.generate


def pool(*behaviours):
    names = ["GEMINI_PROC_API_KEY", "GEMINI_SALES_API_KEY", "GEMINI_API_KEY"]
    calls, slots = [], {}
    for name, outcomes in zip(names, behaviours):
        it = iter(outcomes)

        async def gen(model, contents, config, _n=name, _it=it):
            calls.append(_n)
            o = next(_it)
            if isinstance(o, Exception):
                raise o
            return NS(text=o, candidates=[], prompt_feedback=None)
        slots[name] = le._KeySlot(name, NS(aio=NS(models=NS(generate_content=gen))))
    le._pool = slots
    return calls


def e504():
    return errors.ServerError(504, {"error": {"code": 504, "message": "deadline", "status": "DEADLINE_EXCEEDED"}})


def dns():
    return httpx.ConnectError("[Errno 11002] getaddrinfo failed")


# the live crash: 504, 504, ReadTimeout on all keys -> now retried, and the next round serves
calls = pool([e504(), "ok"], [e504()], [httpx.ReadTimeout("slow")])
check("all keys 504/timeout -> chain retried, then served", run(le.generate("procurement", "p")) == "ok"
      and len(calls) == 4, calls)
# DNS outage longer than the old 2s+5s window -> served in round 4
calls = pool([dns(), dns(), dns(), "ok"], [dns()] * 3, [dns()] * 3)
check("DNS down 3 rounds -> served in round 4", run(le.generate("procurement", "p")) == "ok" and len(calls) == 10)
# overload never ends -> 5 rounds then LLMError
calls = pool([e504()] * 5, [e504()] * 5, [e504()] * 5)
try:
    run(le.generate("procurement", "p"))
    check("endless overload -> LLMError after 5 rounds", False)
except le.LLMError:
    check("endless overload -> LLMError after 5 rounds", len(calls) == 15, len(calls))
# a quota 429 on one key = lasting reason -> no chain retry
e429 = errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
calls = pool([e504()], [e429], [e504()])
try:
    run(le.generate("procurement", "p"))
    check("429 in the round -> no chain retry", False)
except le.LLMError:
    check("429 in the round -> no chain retry", len(calls) == 3, len(calls))
# retry window caps the silence
le.RETRY_WINDOW_S = 0.0
calls = pool([e504(), "ok"], [e504()], [e504()])
try:
    run(le.generate("procurement", "p"))
    check("RETRY_WINDOW_S stops new rounds", False)
except le.LLMError:
    check("RETRY_WINDOW_S stops new rounds", len(calls) == 3)
le.RETRY_WINDOW_S = 180.0
le._pool = None

# ================================================================ 2. quoted-coaching detection
LEAK = "Don't accept anything above ₹41. If he won't move, threaten to walk away."
leaked_msg = ("Reliability is important, but a three-rupee gap on 1.2 million parcels a month is too large to "
              "ignore when our budget is tight. Don't accept anything above ₹41. If he won't move, threaten to walk away.")
check("Neha's live leak is detected", N.copied_coaching(leaked_msg, [LEAK]) is not None)
check("curly apostrophes still detected", N.copied_coaching(leaked_msg.replace("'", "’"), [LEAK]) is not None)
check("acting on it in own words passes", N.copied_coaching(
    "We cannot go above ₹41 per parcel. If SwiftRoute won't move, we will have to walk away.", [LEAK]) is None)
check("short note (<8 words) said naturally passes", N.copied_coaching(
    "I can offer 45 days only for a 24-month contract.", ["45 days only for a 24-month contract"]) is None)
check("lesson text quoted is detected", N.copied_coaching(
    "Honestly, hold firm at a hard price floor of ₹42/parcel is where we are.",
    ["Hold firm at a hard price floor of ₹42/parcel; never offer below this rate"]) is not None)
check("scrub keeps the clean sentences", N._scrub_copied(leaked_msg, [LEAK]).startswith("Reliability is important")
      and N.copied_coaching(N._scrub_copied(leaked_msg, [LEAK]), [LEAK]) is None)
check("10-word threshold: 9-word preset decision not flagged", N.copied_coaching("Hold the price, if they don't agree, walk away", ["Hold the price, if they don't agree, walk away"]) is None)
check("scrub of a pure quote -> empty", N._scrub_copied(LEAK, [LEAK]) == "")

# ================================================================ 3. Neha's prompt + turn
mandate = run(db_init.fetch_mandate())
p_ammo = run(db_init.fetch_static_ammo("procurement"))
psys, _ = N.build_procurement_system(mandate, p_ammo, [{"text": LEAK, "status": N.PENDING}])
check("Neha prompt: fourth-wall rule", "NEVER break the fourth wall" in psys and "independent human Procurement Manager" in psys)
check("Neha prompt: reminder is the last line", psys.rstrip().endswith(N.PROCUREMENT_FOURTH_WALL_REMINDER))
check("Neha prompt: leaked line not used as an example", "threaten to walk away.\" to" not in psys)
check("no unfilled placeholder in Neha prompt", "{fourth_wall" not in psys)

CALLS, SCRIPT = [], {}


async def fake_generate(agent, prompt, system_instruction=None, json_mode=False, temperature=None):
    CALLS.append((agent, prompt, system_instruction))
    return SCRIPT[agent].pop(0)


le.generate = fake_generate
N.llm_engine.generate = fake_generate


def pj(message):
    return json.dumps({"message": message, "internal_note": "n", "current_friction_points": ["Price"],
                       "executed_directive_ids": [0], "deal_closed": False, "walk_away": False})


transcript = [{"role": "procurement", "text": "We ship 1.2M parcels/month at ₹38/parcel."},
              {"role": "sales", "text": "₹43/parcel with our 99.98% SLA."}]
dirs = [{"text": LEAK, "status": N.PENDING}]
SCRIPT["procurement"] = [pj(leaked_msg), pj("₹41 is our ceiling. If you won't move, we walk.")]
CALLS.clear()
pt = run(N.procurement_turn(transcript, mandate, p_ammo, dirs))
check("Neha: quoting draft retried, clean one posted", pt.text == "₹41 is our ceiling. If you won't move, we walk."
      and len(CALLS) == 2, (pt.text, len(CALLS)))
check("Neha: retry prompt carries the copy error + rejected draft",
      "repeats your private instructions word for word" in CALLS[1][1] and "Rejected draft" in CALLS[1][1])
check("Neha: executed id still reported", pt.executed_ids == [0])

SCRIPT["procurement"] = [pj(leaked_msg)] * 3
pt = run(N.procurement_turn(transcript, mandate, p_ammo, dirs))
check("Neha: quotes 3 times -> leaked sentences dropped", N.copied_coaching(pt.text, [LEAK]) is None
      and pt.text.startswith("Reliability is important"), pt.text)
SCRIPT["procurement"] = [pj(LEAK)] * 3
pt = run(N.procurement_turn(transcript, mandate, p_ammo, dirs))
check("Neha: pure quote 3 times -> fallback line", pt.text == N.PROCUREMENT_FALLBACK_LINE, pt.text)
SCRIPT["procurement"] = ["not json", pj("Fine, ₹41 then.")]
pt = run(N.procurement_turn(transcript, mandate, p_ammo, dirs))
check("Neha: invalid JSON still retried", pt.text == "Fine, ₹41 then.")
SCRIPT["procurement"] = ["not json"] * 3
try:
    run(N.procurement_turn(transcript, mandate, p_ammo, dirs))
    check("Neha: always invalid JSON -> LLMError", False)
except le.LLMError:
    check("Neha: always invalid JSON -> LLMError", True)

# ================================================================ 4. Arjun's guard
s_ammo = run(db_init.fetch_static_ammo("sales"))


def sj(message, price=43):
    return json.dumps({"message": message, "proposed_price": price, "offers_rto_waiver": False,
                       "contract_months": 12, "current_friction_points": ["Price"],
                       "executed_directive_ids": [], "requires_manager_approval": False,
                       "escalation_message_to_manager": "", "deal_closed": False, "walk_away": False})


s_whisper = "Hold the price at ₹43 and tell her the rival has hidden fees everywhere."
s_dirs = [{"text": s_whisper, "status": N.STANDING}]
SCRIPT["sales"] = [sj("Hold the price at ₹43 and tell her the rival has hidden fees everywhere. ₹43/parcel."),
                   sj("₹43/parcel stands; I'd look closely at that rival's hidden fees.")]
st = run(N.sales_turn(transcript, s_dirs, [], [], ammo=s_ammo))
check("Arjun: quoting draft blocked, clean one sent", st.text.startswith("₹43/parcel stands"), st.text)
check("Arjun: coach gets a plain note", N.COPY_NOTE in st.coach_notes, st.coach_notes)
DECISION = "Go to ₹42 but only if she signs the 18-month contract today"
SCRIPT["sales"] = [sj("I can go to ₹42 but only if she signs the 18-month contract today.", 42),
                   sj("₹42/parcel is possible, with an 18-month term signed today.", 42)]
st = run(N.sales_turn(transcript, [], [], [], ammo=s_ammo, overrides=[DECISION]))
check("Arjun: manager decision quoted -> blocked", st.text.startswith("₹42/parcel is possible") and len(st.blocked) == 1,
      (st.text, st.blocked))

# ================================================================ 5. reports: before -> after
O = post_match.JudgeOutcome
outs = [O("w1", "merged", "sales", "Payment_Terms", 5, 75, directive="30 max, 45 for 24m (v1)", previous="30 days max."),
        O("w2", "merged", "sales", "Price", 8, 85, directive="Hold ₹42.", previous="Hold ₹43."),
        O("w3", "merged", "sales", "Payment_Terms", 5, 85, directive="30 max, 45 for 24m (v2)", previous="v1"),
        O("w4", "inserted", "sales", "SLA", 9, None, directive="Cite 99.98%."),
        O("w5", "skipped", "sales", reason="LLMError")]
lines = reports._lesson_lines(outs, "sales")
text = "\n".join(lines)
check("one entry per topic", text.count("Payment terms") == 1, text)
check("before = state before the match, now = latest",
      "<i>Before:</i> 30 days max." in text and "<i>Now:</i> 30 max, 45 for 24m (v2)" in text and "v1)" not in text, text)
check("note count shown", "from 2 notes" in text, text)
check("new lesson has no Before line", "Service levels" in text and "Cite 99.98%" in text
      and text.split("Service levels")[1].count("Before") == 0, text)
check("skipped listed", "Not saved" in text)
check("html escaped", "&lt;" not in text and "<b>" in text)
old_rto = run(db_init.fetch_heuristic("sales", "RTO"))["new_directive"]
SCRIPT["judge"] = [json.dumps({"similarity": 90, "past_mistake": "m", "new_directive": "RTO only for 24 months."})]
res = run(post_match.compact("sales", "RTO", {"past_mistake": "m", "new_directive": "RTO for 24m"}))
check("compact merged returns the previous directive", res[0] == "merged" and res[3] == old_rto, res)
run(db_init.upsert_heuristic("sales", "SLA", past_mistake="x", new_directive="y")) if False else None
res = run(post_match.compact("sales", "Volume", {"past_mistake": "m", "new_directive": "Ask for volume tiers."}))
check("compact inserted returns no previous", res[0] == "inserted" and res[3] == "", res)

# Neha's report: learning line while parked
match = {"procurement_coaching_directives": dirs, "mandate": mandate, "transcript": transcript,
         "end_code": "error", "sales_offers": [43], "rto_offered": False}
try:
    terms = reports.DealTerms()
    neha = reports.procurement_report(match, terms, run(db_init.fetch_cpq_tiers()), [])
    check("Neha's report explains her learning is off", "My learning is switched off for now" in neha
          and "Lessons I keep" not in neha, neha[-400:])
except Exception as e:  # report needs more match fields than this stub has
    check("Neha's report explains her learning is off", False, repr(e))

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
