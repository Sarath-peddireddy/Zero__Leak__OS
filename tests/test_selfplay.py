"""Offline tests for the Adversarial Self-Play upgrade (fake Gemini + fake Telegram, DB copy)."""

import asyncio
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(r"C:\Users\sarat\Desktop\zeroleakos")
SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

import db_init  # noqa: E402

TEST_DB = SCRATCH / "selfplay_test.db"
shutil.copy(SCRATCH / "zeroleak_backup_before_selfplay.db", TEST_DB)
db_init.DB_PATH = TEST_DB

import bot_main  # noqa: E402
import llm_engine  # noqa: E402
import negotiation as N  # noqa: E402
import post_match  # noqa: E402
import reports  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


# ------------------------------------------------------------------ fake LLM
CALLS = []          # (agent, prompt, system)
SCRIPT = {}         # agent -> list of replies (str or callable(prompt, system) -> str)


async def fake_generate(agent, prompt, system_instruction=None, json_mode=False, temperature=None):
    CALLS.append((agent, prompt, system_instruction))
    queue = SCRIPT.get(agent) or []
    if not queue:
        raise AssertionError(f"no scripted reply for {agent}")
    reply = queue.pop(0)
    return reply(prompt, system_instruction) if callable(reply) else reply


llm_engine.generate = fake_generate
N.llm_engine.generate = fake_generate


def j(**kw):
    return json.dumps(kw)


# ------------------------------------------------------------------ fake Telegram
class FakeBot:
    def __init__(self, name):
        self.name, self.sent = name, []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append((chat_id, text))

    async def send_chat_action(self, chat_id, action):
        pass


class FakeMessage:
    def __init__(self, text):
        self.text, self.replies = text, []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def fake_update(chat_id, text, private=True):
    chat = SimpleNamespace(id=chat_id, type="private" if private else "group", title="Boardroom")
    return SimpleNamespace(effective_chat=chat, message=FakeMessage(text), effective_user=SimpleNamespace(id=chat_id))


def run(coro):
    return asyncio.run(coro)


# ================================================================== Step 1: schema + migration
tiers = run(db_init.init_db())
run(db_init.init_db())  # idempotent
conn = sqlite3.connect(TEST_DB)
tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
for t in ("sales_cpq_pricing", "procurement_mandates", "sales_static_ammo", "procurement_static_ammo",
          "sales_heuristics", "procurement_heuristics", "match_transcripts"):
    check(f"table {t} exists", t in tables)
check("old cpq_pricing / playbook_heuristics gone", not ({"cpq_pricing", "playbook_heuristics"} & tables))
check("5 CPQ tiers kept", len(tiers) == 5)
check("RTO term moved into CPQ table", [t["rto_min_contract_months"] for t in tiers] == [None, None, None, 18, 18])
check("ledger rows preserved (58)", conn.execute("select count(*) from match_transcripts").fetchone()[0] == 58)
check("5 legacy lessons now in sales_heuristics",
      conn.execute("select count(*) from sales_heuristics").fetchone()[0] == 5)
for t in ("sales_heuristics", "procurement_heuristics"):
    try:
        conn.execute(f"insert into {t} (topic_tag, past_mistake, new_directive) values ('Price','a','b')")
        conn.execute(f"insert into {t} (topic_tag, past_mistake, new_directive) values ('Price','c','d')")
        check(f"{t}.topic_tag UNIQUE", False, "duplicate accepted")
    except sqlite3.IntegrityError:
        check(f"{t}.topic_tag UNIQUE", True)
    conn.rollback()
conn.close()

mandate = run(db_init.fetch_mandate())
check("mandate seeded", mandate and mandate["walk_away_price"] == 43.0 and mandate["volume"] == 1_200_000)
s_ammo, p_ammo = run(db_init.fetch_static_ammo("sales")), run(db_init.fetch_static_ammo("procurement"))
check("static ammo seeded both sides", len(s_ammo) == 4 and len(p_ammo) == 4)

# UPSERT
before = run(db_init.fetch_heuristic("sales", "RTO"))
hid = run(db_init.upsert_heuristic("sales", "RTO", "m2", "d2"))
after = run(db_init.fetch_heuristic("sales", "RTO"))
check("upsert on existing tag keeps id + overwrites", hid == before["heuristic_id"] and after["new_directive"] == "d2")
check("upsert bumps updated_at", after["updated_at"] != before["updated_at"])
run(db_init.upsert_heuristic("sales", "RTO", before["past_mistake"], before["new_directive"]))  # restore
check("sales playbook still 5 rows after upserts", len(run(db_init.fetch_heuristics("sales", None))) == 5)
got = run(db_init.fetch_heuristics("sales", ["RTO", "Price"]))
check("fetch_heuristics returns 1 per tag in tag order", [h["topic_tag"] for h in got] == ["RTO", "Price"])
check("fetch_heuristics([]) -> []", run(db_init.fetch_heuristics("sales", [])) == [])

# ================================================================== Step 3: zero-hardcode prompts
templates = {"PROCUREMENT_PERSONA": N.PROCUREMENT_PERSONA, "PROCUREMENT_SYSTEM": N.PROCUREMENT_SYSTEM,
             "SALES_PERSONA": N.SALES_PERSONA, "SALES_SYSTEM": N.SALES_SYSTEM}
for name, text in templates.items():
    check(f"{name} has no hardcoded ₹ figures", not re.search(r"₹\d", text), re.findall(r"₹\d+", text))
for name in ("BUYER", "SWIFTROUTE_VALUE_PROPS", "RTO_MIN_CONTRACT_MONTHS"):
    check(f"negotiation.{name} removed", not hasattr(N, name))

swapped = dict(mandate, volume=600_000, incumbent_price=51.0, target_price=46.0, walk_away_price=49.5,
               payment_terms_target=45, contract_months=24)
proc_sys, _ = N.build_procurement_system(swapped, p_ammo)
check("proc prompt uses swapped mandate numbers",
      all(x in proc_sys for x in ("600K", "₹51/parcel", "₹46/parcel", "₹49.5/parcel", "45-day", "24 months")))
check("proc prompt has none of the old MegaMart numbers", not any(x in proc_sys for x in ("₹43", "₹38", "₹44", "1.2M")))
check("proc prompt cites procurement ammo", all(a["value"] in proc_sys for a in p_ammo))
check("proc prompt has no sales ammo / CPQ", not any(a["value"] in proc_sys for a in s_ammo) and "Floor price" not in proc_sys)

tier4 = tiers[3]
sales_sys, _ = N.build_sales_system(tiers, tier4, 1_200_000, s_ammo)
check("sales prompt cites sales ammo", all(a["value"] in sales_sys for a in s_ammo))
check("sales prompt has no buyer mandate", not any(x in sales_sys for x in ("Walk-away price", "₹38", "₹44", "Target rate")))
check("sales prompt has no procurement ammo", not any(a["value"] in sales_sys for a in p_ammo))
check("sales prompt RTO rule from tier column", "18 months or more" in sales_sys)
check("no '12-month' hardcode in sales prompt", "12-month" not in sales_sys)
empty_sys, _ = N.build_sales_system(tiers, tier4, 1_200_000, [])
check("no ammo -> told not to cite figures", "do not cite any figures" in empty_sys)

# ================================================================== Step 4: tags + 2-cap
for name, text in (("sales", sales_sys), ("procurement", proc_sys)):
    check(f"{name} prompt has 2-tag rule", "You are limited to a MAXIMUM of 2 tags per message. "
          "Select only the primary and secondary driving factors." in text)
    check(f"{name} JSON schema has current_friction_points", '"current_friction_points"' in text)
check("normalize caps at 2", N.normalize_friction_points(["Price", "RTO", "SLA", "Volume"]) == ["Price", "RTO"])
check("normalize alias + dedupe before cap", N.normalize_friction_points(["pricing", "Price", "lock-in"]) == ["Price", "Contract_Length"])
check("normalize cap=None keeps all", len(N.normalize_friction_points(["Price", "RTO", "SLA"], cap=None)) == 3)

# RTO guard from tier column
t24 = dict(tier4, rto_min_contract_months=24)
v, _ = N.check_offer("We can waive RTO at ₹43/parcel", {"proposed_price": 43, "offers_rto_waiver": True,
                                                        "contract_months": 18}, t24)
check("RTO guard uses tier's 24-month rule", any("24 months" in x for x in v), v)
tnone = dict(tier4, rto_min_contract_months=None)
v, _ = N.check_offer("RTO waived at ₹43/parcel", {"proposed_price": 43, "offers_rto_waiver": True}, tnone)
check("RTO guard: no term rule -> allowed", v == [], v)
v, _ = N.check_offer("₹40/parcel", {"proposed_price": 40}, tier4)
check("floor guard still blocks", v and v[0].startswith(N.GUARD_ERROR))

# turns with fake LLM
SCRIPT["procurement"] = [j(message="We ship 1.2M parcels/month. ₹38/parcel.", internal_note="n",
                           current_friction_points=["Price", "Competitor_Quote", "RTO"],
                           executed_directive_ids=[0, 1, 7], deal_closed=False, walk_away=False)]
dirs = [{"text": "Threaten Blue Dart", "status": N.PENDING}, {"text": "old", "status": N.STANDING}]
lessons = run(db_init.fetch_heuristics("procurement", ["Price"]))
pt = run(N.procurement_turn([], mandate, p_ammo, dirs, [{"topic_tag": "Price", "past_mistake": "pm",
                                                         "new_directive": "PROC-LESSON"}], ["Price"]))
_, _, psys = CALLS[-1]
check("procurement_turn caps tags at 2", pt.friction_points == ["Price", "Competitor_Quote"], pt.friction_points)
check("procurement_turn executed ids filtered to pending", pt.executed_ids == [0], pt.executed_ids)
check("proc prompt has coaching + guardrails + playbook",
      "Threaten Blue Dart" in psys and "MANAGER'S GUARDRAILS" in psys and "PROC-LESSON" in psys
      and "Arjun's last message pushed on: Price" in psys)

SCRIPT["sales"] = [j(message="₹45/parcel, and our 99.98% SLA.", proposed_price=45, offers_rto_waiver=False,
                     contract_months=12, current_friction_points=["Price", "SLA", "Volume"], executed_directive_ids=[])]
st = run(N.sales_turn([{"role": "procurement", "text": "We ship 1.2M parcels/month."}], [], [], [], ammo=s_ammo))
check("sales_turn returns capped tags", st.friction_points == ["Price", "SLA"], st.friction_points)

# ================================================================== Step 2: Judge UPSERT (both sides)
MID = "selfplaytest1"
ledger_rows = [
    ("Procure_Agent", "We need ₹38/parcel and a full RTO waiver."),
    ("Sales_Agent", "I can do ₹44/parcel."),
    ("Human_Whisper", "Only give RTO for a 24-month lock-in."),
    ("Procure_Agent", "Fine, but 60-day payment terms."),
    ("Procure_Whisper", "Threaten to use Blue Dart right now."),
    ("Sales_Agent", "60 days is hard for us."),
    ("Procure_Whisper", "Mention Blue Dart's ₹39 quote when he holds on price."),
]
for spk, txt in ledger_rows:
    run(db_init.log_message(MID, spk, txt))
blocks = post_match.context_blocks(run(db_init.fetch_ledger(MID)))
check("context_blocks sides", [b.side for b in blocks] == ["sales", "procurement", "procurement"])
check("context = 3 boardroom rows, whispers excluded",
      all(r["speaker"] in ("Sales_Agent", "Procure_Agent") for r in blocks[2].before) and len(blocks[2].before) == 3)

rto_before = run(db_init.fetch_heuristic("sales", "RTO"))
SCRIPT["judge"] = [
    j(topic_tag="RTO", past_mistake="Offered RTO cheaply", new_directive="RTO only for 24 months"),   # sales synth
    j(similarity=91, past_mistake="Gave RTO away", new_directive="RTO only for a 24-month lock-in."),  # sales merge
    j(topic_tag="Competitor_Quote", past_mistake="Never used competitor threat", new_directive="Threaten Blue Dart"),
    j(topic_tag="competitor", past_mistake="Did not cite the quote", new_directive="Cite Blue Dart ₹39"),
    j(similarity=85, past_mistake="Did not use competitor leverage",
      new_directive="Threaten Blue Dart; cite its ₹39/parcel quote when Arjun holds on price."),
]
CALLS.clear()
outcomes = run(post_match.run_judge_agent(MID))
check("judge outcomes", [(o.side, o.action, o.topic_tag) for o in outcomes] == [
    ("sales", "merged", "RTO"), ("procurement", "inserted", "Competitor_Quote"),
    ("procurement", "merged", "Competitor_Quote")], [(o.side, o.action, o.topic_tag) for o in outcomes])
rto_after = run(db_init.fetch_heuristic("sales", "RTO"))
check("sales RTO merged in place (same id, new text)",
      rto_after["heuristic_id"] == rto_before["heuristic_id"] and "24-month" in rto_after["new_directive"])
check("sales playbook still 5 rows (Highlander)", len(run(db_init.fetch_heuristics("sales", None))) == 5)
proc_rules = run(db_init.fetch_heuristics("procurement", None))
check("procurement playbook: 1 merged master rule", len(proc_rules) == 1 and "₹39" in proc_rules[0]["new_directive"])
merge_prompts = [p for a, p, s in CALLS if s and "ONE master rule" in s]
check("merge call sees existing rule text", any(rto_before["new_directive"] in p for p in merge_prompts))
# Reward-model separation (2026-10-26): calls are sales synth, sales merge, proc synth, proc synth, proc merge
judge_sys = [s for a, p, s in CALLS if a == "judge"]
VP, HEAD = "VP of Sales at SwiftRoute", "Head of Global Sourcing at MegaMart"
check("5 judge calls in order", len(judge_sys) == 5, len(judge_sys))
check("Human_Whisper judged + merged as the VP of Sales only",
      all(VP in s and HEAD not in s for s in judge_sys[:2]))
check("Procure_Whisper judged + merged as the Head of Global Sourcing only",
      all(HEAD in s and VP not in s for s in judge_sys[2:]))
check("sales persona goals: margin, floor, long-term value",
      all(k in post_match.JUDGE_PERSONAS["sales"] for k in ("maximize", "margin", "price floor", "long-term value")))
check("procurement persona goals: squeeze margin, anchor low, minimize cost",
      all(k in post_match.JUDGE_PERSONAS["procurement"] for k in ("squeeze", "anchor low", "minimize")))
check("escalation judge uses the VP of Sales persona", VP in post_match.ESCALATION_JUDGE_SYSTEM
      and HEAD not in post_match.ESCALATION_JUDGE_SYSTEM)
check("heuristics tables per side", db_init.HEURISTICS_TABLES == {"sales": "sales_heuristics",
                                                                 "procurement": "procurement_heuristics"})
check("merged outcome reports stored directive", outcomes[2].directive == proc_rules[0]["new_directive"])

# merge failure -> skipped, row untouched
MID2 = "selfplaytest2"
run(db_init.log_message(MID2, "Procure_Agent", "x"))
run(db_init.log_message(MID2, "Human_Whisper", "Hold RTO."))
SCRIPT["judge"] = [j(topic_tag="RTO", past_mistake="a", new_directive="b"), "not json", "still not json"]
o2 = run(post_match.run_judge_agent(MID2))
check("bad merge -> skipped", o2[0].action == "skipped")
check("bad merge leaves master rule intact", run(db_init.fetch_heuristic("sales", "RTO")) == rto_after)

# ================================================================== Steps 4+5: orchestrator loop
GROUP, COACH = -100, 555
sales_bot, proc_bot = FakeBot("sales"), FakeBot("proc")
match = bot_main.new_match(COACH, mandate, s_ammo, p_ammo)
match["procurement_war_room_chat_id"] = COACH
bot_main.active_matches[GROUP] = match
bot_main.war_room_to_group[COACH] = GROUP
bot_main.proc_war_room_to_group[COACH] = GROUP
bot_main.TURN_DELAY_S = (0, 0)

# Procurement whisper via the Procurement bot's DM
upd = fake_update(COACH, "Threaten to use Blue Dart right now")
run(bot_main.buffer_proc_whisper(upd, None))
check("proc whisper buffered as pending", match["procurement_coaching_directives"] == [
    {"text": "Threaten to use Blue Dart right now", "status": N.PENDING}])
check("proc whisper ack", upd.message.replies == [bot_main.WHISPER_ACK["procurement"]])
check("proc whisper logged as Procure_Whisper",
      run(db_init.fetch_ledger(match["match_id"]))[-1]["speaker"] == "Procure_Whisper")
check("sales directives untouched", match["active_coaching_directives"] == [])
upd2 = fake_update(COACH, "Hold 30-day terms")
run(bot_main.buffer_whisper(upd2, None))
check("sales whisper still goes to Arjun", match["active_coaching_directives"][0]["text"] == "Hold 30-day terms")

proc_replies = [
    j(message="We ship 1.2M parcels/month, Blue Dart is ready. ₹38/parcel.", internal_note="",
      current_friction_points=["Price", "RTO", "SLA"], executed_directive_ids=[0], deal_closed=False, walk_away=False),
    j(message="₹43/parcel and we sign.", internal_note="", current_friction_points=["Price"],
      executed_directive_ids=[], deal_closed=True, walk_away=False),
]
sales_replies = [
    j(message="₹44/parcel with our 99.98% SLA, 30-day terms.", proposed_price=44, offers_rto_waiver=False,
      contract_months=12, current_friction_points=["Payment_Terms", "SLA", "Price"], executed_directive_ids=[0]),
    j(message="Confirmed: ₹43/parcel. We have a deal.", proposed_price=43, offers_rto_waiver=False,
      contract_months=12, current_friction_points=["Price"], executed_directive_ids=[], deal_closed=True),
]
SCRIPT["procurement"], SCRIPT["sales"] = list(proc_replies), list(sales_replies)
SCRIPT["judge"] = [lambda p, s: j(rate_per_parcel=43, rto_waiver="not_discussed", payment_terms_days=30,
                                  contract_months=12, buyer_commitments=[], open_items=[],
                                  procurement_summary="ok", sales_summary="ok", next_step="sign")]
run(db_init.upsert_heuristic("procurement", "Payment_Terms", "pm", "PROC-PAYMENT-LESSON"))
run(db_init.upsert_heuristic("procurement", "SLA", "pm", "PROC-SLA-LESSON"))
run(db_init.upsert_heuristic("procurement", "Price", "pm", "PROC-PRICE-LESSON"))
CALLS.clear()


async def drive():
    bot_main.match_tasks[GROUP] = asyncio.current_task()
    await bot_main.run_match(GROUP, sales_bot, proc_bot)
    await asyncio.gather(*list(bot_main.judge_tasks))

SCRIPT["judge"] += [j(topic_tag="Competitor_Quote", past_mistake="a", new_directive="b"),
                    j(similarity=50, past_mistake="a2", new_directive="b2"),
                    j(topic_tag="Payment_Terms", past_mistake="c", new_directive="d"),
                    j(similarity=60, past_mistake="c2", new_directive="Hold 30 days")]
run(drive())

agent_systems = [(a, s) for a, p, s in CALLS if a in ("sales", "procurement")]
p1, s1, p2 = agent_systems[0][1], agent_systems[1][1], agent_systems[2][1]
check("loop order proc, sales, proc (+ Arjun confirms the close)", [a for a, _ in agent_systems] == ["procurement", "sales", "procurement", "sales"])
check("1st proc turn: no lessons (no Sales tags yet)", "PLAYBOOK" not in p1)
sales_playbook = s1.split("PLAYBOOK", 1)[1].split("Tagging", 1)[0] if "PLAYBOOK" in s1 else ""
tags_in_sales = re.findall(r"- \[(\w+)\] Past mistake", sales_playbook)
check("sales turn gets <= 2 sales lessons for Neha's capped tags", tags_in_sales == ["Price", "RTO"], tags_in_sales)
proc_playbook = p2.split("PLAYBOOK", 1)[1].split("Tagging", 1)[0]
tags_in_proc = re.findall(r"- \[(\w+)\] Past mistake", proc_playbook)
check("2nd proc turn gets procurement lessons for Arjun's capped tags",
      tags_in_proc == ["Payment_Terms", "SLA"] and "PROC-PRICE-LESSON" not in p2, tags_in_proc)
check("proc directive became standing + in guardrails",
      match["procurement_coaching_directives"][0]["status"] == N.STANDING and "MANAGER'S GUARDRAILS" in p2)
check("✅ sent to Procurement War Room", any("I applied your guidance" in t for c, t in proc_bot.sent if c == COACH))
check("✅ sent to Sales War Room", any("Arjun applied your guidance" in t for c, t in sales_bot.sent if c == COACH))
check("deal closed", match["end_code"] == "deal")
proc_report = [t for c, t in proc_bot.sent if c == COACH and "Negotiation report" in t]
sales_report = [t for c, t in sales_bot.sent if c == COACH and "Deal report" in t]
check("both reports sent", len(proc_report) == 1 and len(sales_report) == 1)
check("proc report uses mandate (walk-away ₹43, target ₹38)", proc_report and "Walk-away ₹43" in proc_report[0]
      and "Target ₹38" in proc_report[0])
check("proc report lists Neha's lessons", proc_report and "Lessons I keep for next time" in proc_report[0])
check("sales report lists only sales lessons",
      sales_report and "Payment terms" in sales_report[0] and "Competitor quotes" not in sales_report[0].split("Lessons saved")[1])
check("no internal terms in any chat", not any(re.search(r"SYSTEM_ERROR|match_id|heuristic|Procure_Whisper|CPQ", t)
                                               for b in (sales_bot, proc_bot) for _, t in b.sent))

grp = SimpleNamespace(id=COACH, type="private")
st_p, st_s = bot_main.status_text(grp, side="procurement"), bot_main.status_text(grp)
check("proc /status shows only Neha's guidance", "Blue Dart" in st_p and "30-day" not in st_p)
check("sales /status shows only Arjun's guidance", "30-day" in st_s and "Blue Dart" not in st_s)
check("contract_phrase from mandate", bot_main.contract_phrase(mandate) == "12-month ")
check("welcome templates format", "12-month last-mile" in bot_main.GROUP_WELCOME.format(contract="12-month ")
      and "{" not in bot_main.BOARDROOM_OPENING.format(contract=""))

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
    sys.exit(1)
