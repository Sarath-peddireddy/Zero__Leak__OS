"""Offline tests for Neha's escalation (2026-10-31, symmetrical with Arjun's): prompt + JSON, the state machine
(Boardroom held, question to the Procurement War Room, decision by text or button, Absolute Override, final terms
before a walk), the deadlock backstop, routing between the two War Rooms, reports and the Judge.
Fake Gemini + fake Telegram, DB copy only."""

import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace as NS

PROJECT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))
import os  # noqa: E402
# .env may hold dev settings: a test never starts real shadow matches (Gemini), and pins self-play.
os.environ.setdefault("ZEROLEAK_SHADOW_MATCHES", "0")
os.environ.setdefault("ZEROLEAK_SELF_PLAY", "0")

import db_init  # noqa: E402

TEST_DB = HERE / "neha_escalation_test.db"
shutil.copy(HERE / "zeroleak_backup_before_1031_neha_tests.db", TEST_DB)
db_init.DB_PATH = TEST_DB

import bot_main as B  # noqa: E402
B.SIGNOFF_AUTO_APPROVE = True  # these suites test other features; the sign-off gate has its own tests
import llm_engine  # noqa: E402
import negotiation as N  # noqa: E402
import post_match as P  # noqa: E402
import reports  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


CALLS, SCRIPT = [], {"procurement": [], "sales": [], "judge": []}


WATCHDOG: list[str] = []  # scripted fourth-wall watchdog verdicts (10-31); default: no slip


async def fake_generate(agent, prompt, system_instruction=None, json_mode=False, temperature=None):
    if system_instruction in sys.modules["post_match"].WATCHDOG_SYSTEM.values():
        return WATCHDOG.pop(0) if WATCHDOG else '{"violation": false}'
    CALLS.append((agent, prompt, system_instruction))
    if not SCRIPT[agent]:
        raise AssertionError(f"no scripted reply for {agent}")
    r = SCRIPT[agent].pop(0)
    return r(prompt, system_instruction) if callable(r) else r


llm_engine.generate = fake_generate
N.llm_engine.generate = fake_generate


def proc(text, price=41, **kw):  # every message states the volume, so Arjun's tier (₹41 floor) is known
    d = dict(message=f"{text} (We ship 1.2M parcels/month.)" if text else "", internal_note="", proposed_price=price, current_friction_points=["Price"],
             executed_directive_ids=[], requires_manager_approval=False, escalation_message_to_manager="",
             deal_closed=False, walk_away=False)
    d.update(kw)
    return json.dumps(d)


def proc_esc(q):
    return proc("", None, requires_manager_approval=True, escalation_message_to_manager=q)


def sales(text, price=43, **kw):
    d = dict(message=text, proposed_price=price, offers_rto_waiver=False, contract_months=12,
             current_friction_points=["Price"], executed_directive_ids=[], requires_manager_approval=False,
             escalation_message_to_manager="", deal_closed=False, walk_away=False)
    d.update(kw)
    return json.dumps(d)


class FakeBot:
    def __init__(self, name):
        self.name, self.sent = name, []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    async def send_chat_action(self, chat_id, action):
        pass


class Msg:
    def __init__(self, text):
        self.text, self.replies = text, []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


GROUP, SALES_COACH, PROC_COACH = -100, 555, 777
sales_bot, proc_bot = FakeBot("sales"), FakeBot("proc")


def dm(chat_id, text):
    return NS(effective_chat=NS(id=chat_id, type="private"), message=Msg(text))


async def wait_for(cond, timeout=3.0):
    for _ in range(int(timeout / 0.005)):
        if cond():
            return True
        await asyncio.sleep(0.005)
    return cond()


async def no_debrief(match, sales_bot, proc_bot, loop_task):
    return None

B.debrief = no_debrief
B.TURN_DELAY_S = (0, 0)


async def new():
    m = B.new_match(SALES_COACH, await db_init.fetch_mandate(), await db_init.fetch_static_ammo("sales"),
                    await db_init.fetch_static_ammo("procurement"))
    m["procurement_war_room_chat_id"] = PROC_COACH
    B.active_matches[GROUP] = m
    B.war_room_to_group[SALES_COACH] = GROUP
    B.proc_war_room_to_group[PROC_COACH] = GROUP
    return m


def reset():
    sales_bot.sent.clear(); proc_bot.sent.clear(); CALLS.clear()
    for q in SCRIPT.values():
        q.clear()


def boardroom():
    return [t for b in (sales_bot, proc_bot) for c, t, _ in b.sent if c == GROUP]


async def main():
    await db_init.init_db()
    sql = sqlite3.connect(TEST_DB).execute("select sql from sqlite_master where name='match_transcripts'").fetchone()[0]
    check("ledger accepts Procure_Escalation + Procure_Decision", "'Procure_Escalation'" in sql and "'Procure_Decision'" in sql)

    # ================================================================ prompt + JSON
    mandate = await db_init.fetch_mandate()
    s_none, _ = N.build_procurement_system(mandate, [])
    s_esc, _ = N.build_procurement_system(mandate, [], escalations_left=2, manager="Sarath", deadlock="facts here")
    s_ovr, _ = N.build_procurement_system(mandate, [], overrides=[B.DECISION_HOLD])
    check("Neha's JSON has requires_manager_approval + escalation_message_to_manager",
          '"requires_manager_approval"' in s_none and '"escalation_message_to_manager"' in s_none)
    check("escalation offered only when left > 0 (+ deadlock alert)", "ESCALATING TO YOUR MANAGER (Sarath)" in s_esc
          and "Escalations left in this negotiation: 2" in s_esc and "DEADLOCK ALERT" in s_esc
          and "not available for this message" in s_none and "ESCALATING" not in s_none)
    check("override block for Neha (SwiftRoute's terms, final terms first), before the fourth-wall line",
          "ABSOLUTE OVERRIDE" in s_ovr and "accept SwiftRoute's latest terms in full" in s_ovr
          and f'- "{B.DECISION_HOLD}"' in s_ovr and s_ovr.rstrip().endswith(N.PROCUREMENT_FOURTH_WALL_REMINDER)
          and "ABSOLUTE OVERRIDE" not in s_esc)
    check("Neha's question is exempt from the fourth wall", "escalation_message_to_manager" in N.PROCUREMENT_FOURTH_WALL_REMINDER)

    SCRIPT["procurement"] = [proc_esc("Arjun holds ₹43. Accept, or hold and walk?")]
    t = await N.procurement_turn([], mandate, [], escalations_left=1)
    check("procurement_turn: flag + question -> escalation, no Boardroom text", t.escalation and t.text == "", t)
    SCRIPT["procurement"] = [proc_esc("?"), proc("₹41/parcel.")]
    t = await N.procurement_turn([], mandate, [], escalations_left=0)
    check("escalation not offered -> the empty draft is retried, a normal message comes back",
          t.escalation is None and t.text.startswith("₹41/parcel."), t)

    # ================================================================ escalations_left rules
    m = await new()
    check("no escalation before Neha's 2nd message", B.procurement_escalations_left(m) == 0)
    m["transcript"] = [{"role": "procurement", "text": "a"}, {"role": "procurement", "text": "b"}]
    check("offered from then on (3)", B.procurement_escalations_left(m) == 3)
    m["procurement_escalation_cooldown"] = True
    check("cooldown -> 0", B.procurement_escalations_left(m) == 0)
    m["procurement_escalation_cooldown"], m["procurement_escalations"] = False, [{}, {}, {}]
    check("cap 3 per match", B.procurement_escalations_left(m) == 0)
    check("Arjun's own counter is separate", B.escalations_left(m) == 0 and m["escalations"] == [])
    m["status"] = "ENDED"

    # ================================================================ full flow: escalate -> text decision -> hold -> walk
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("We ship 1.2M parcels/month. ₹38/parcel.", 38), proc("₹41/parcel.", 41),
                             proc_esc("Arjun won't go below ₹43 and refuses 60 days. Accept his terms, or hold ₹41 and walk?"),
                             lambda p, s: proc("₹41/parcel is our final offer.", 41, walk_away=True),  # premature walk
                             lambda p, s: proc("Then we walk away. Thank you, Arjun.", 41, walk_away=True)]
    SCRIPT["sales"] = [sales("₹45/parcel.", 45), sales("₹43/parcel.", 43), sales("₹43/parcel stands.", 43)]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    check("state -> AWAITING_MANAGER_APPROVAL, Neha waiting", await wait_for(
        lambda: m["status"] == "AWAITING_MANAGER_APPROVAL") and m["escalating_side"] == "procurement", m["status"])
    await wait_for(lambda: any(c == PROC_COACH for c, _, _ in proc_bot.sent))
    q = [(t, mk) for c, t, mk in proc_bot.sent if c == PROC_COACH and "I need your decision" in t]
    check("question in the Procurement War Room, with the two decision buttons",
          q and "Accept his terms" in q[0][0] and q[0][1] is B.ESCALATION_MENU, proc_bot.sent)
    check("nothing to the Sales War Room, nothing new in the Boardroom",
          not any(c == SALES_COACH for c, _, _ in sales_bot.sent) and not any("Accept his terms" in t for t in boardroom()))
    check("ledger: Procure_Escalation", (await db_init.fetch_ledger(m["match_id"]))[-1]["speaker"] == "Procure_Escalation")
    check("status: group says Neha is consulting her manager",
          "Neha is consulting her manager" in B.status_text(NS(id=GROUP, type="group")))
    check("status: Procurement War Room shows the question",
          "I'm waiting for your decision" in B.status_text(NS(id=PROC_COACH, type="private"), side="procurement"))

    upd = dm(SALES_COACH, "Hold 30-day terms.")  # the Sales coach typing meanwhile: a whisper, not her decision
    await B.buffer_whisper(upd, None)
    check("Sales DM during Neha's escalation = whisper for Arjun", m["active_coaching_directives"][-1]["text"]
          == "Hold 30-day terms." and m["status"] == "AWAITING_MANAGER_APPROVAL", upd.message.replies)
    upd = dm(PROC_COACH, B.DECISION_HOLD)
    await B.buffer_proc_whisper(upd, None)
    check("Procurement DM = the decision, acknowledged in her voice", upd.message.replies
          and upd.message.replies[0].startswith("Got it. I'll act") and m["procurement_coaching_directives"] == [])
    await wait_for(lambda: loop.done(), 3)
    proc_calls = [s for a, _, s in CALLS if a == "procurement"]
    check("her reply after the decision carries the Absolute Override", "ABSOLUTE OVERRIDE" in proc_calls[3]
          and B.DECISION_HOLD in proc_calls[3] and "not available for this message" in proc_calls[3])
    check("walk in the final-terms message ignored, walk after Arjun's reply honoured",
          any("final offer" in t for t in boardroom()) and m["end_code"] == "walkaway", m["end_code"])
    led = [r["speaker"] for r in await db_init.fetch_ledger(m["match_id"])]
    check("ledger: Procure_Decision logged", "Procure_Decision" in led and "Manager_Decision" not in led)
    check("decision stored on her side only", m["procurement_overrides"] == [B.DECISION_HOLD] and m["manager_overrides"] == [])
    rep = reports.procurement_report(m, reports.DealTerms(), await db_init.fetch_cpq_tiers(), [])
    check("Neha's report lists her question + your decision", "🙋 I asked you" in rep and __import__("html").escape(B.DECISION_HOLD) in rep, rep)

    # ================================================================ button decision: close no matter what
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("₹38/parcel.", 38), proc("₹40/parcel.", 40), proc_esc("Close at ₹43 or hold?"),
                             lambda p, s: proc("We accept ₹43/parcel, 12 months, 30 days.", 43, deal_closed=True)]
    SCRIPT["sales"] = [sales("₹45/parcel.", 45), sales("₹43/parcel.", 43),
                       sales("Confirmed: ₹43/parcel. We have a deal.", 43, deal_closed=True)]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL")
    answered = []

    async def answer(text=None, show_alert=False):
        answered.append(text)
    sq = NS(data="esc:close", message=NS(chat=NS(id=SALES_COACH, type="private")), from_user=NS(id=SALES_COACH), answer=answer)
    await B.sales_buttons(NS(callback_query=sq), NS(bot=sales_bot, application=NS(bot_data={})))
    check("Sales War Room button can't answer Neha's question", answered and "Arjun isn't waiting" in answered[-1]
          and m["status"] == "AWAITING_MANAGER_APPROVAL", answered)
    pq = NS(data="esc:close", message=NS(chat=NS(id=PROC_COACH, type="private")), answer=answer)
    await B.proc_buttons(NS(callback_query=pq), NS(bot=proc_bot))
    await wait_for(lambda: loop.done(), 3)
    check("Procurement button sends 'close' -> deal", m["procurement_overrides"] == [B.DECISION_CLOSE]
          and m["end_code"] == "deal", (m["procurement_overrides"], m["end_code"]))

    # ================================================================ deadlock backstop
    m = await new()
    m["procurement_offers"] = [41, 41, 41, 41, 41]
    m["sales_offers"], m["sales_offer_months"] = [43, 43, 43, 43, 43], [12] * 5
    facts, forced = B.procurement_deadlock(m)
    check("5× same rate, Arjun above it -> deadlock + backstop", "last 5 messages" in facts and forced, facts)
    m["sales_offers"][-1] = 42
    check("Arjun moving down -> no deadlock", B.procurement_deadlock(m) == ("", False))
    m["sales_offers"][-1], m["procurement_offers"] = 43, [41, 41, 41]
    check("3× -> alert only, no backstop", B.procurement_deadlock(m)[1] is False and B.procurement_deadlock(m)[0])
    m["sales_offers"][-1] = 41
    check("Arjun meets her rate -> no price deadlock", B.procurement_deadlock(m)[0] == "")
    m["status"] = "ENDED"

    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("₹41/parcel.", 41)] * 5 + [lambda p, s: proc("₹41/parcel is final.", 41),
                                                              lambda p, s: proc("Agreed at ₹42.", 42, deal_closed=True)]
    SCRIPT["sales"] = [sales("₹43/parcel.", 43)] * 5 + [sales("Confirmed ₹42.", 42, deal_closed=True)]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL")
    check("backstop: system asks her manager after 5 repeats (her draft not posted)",
          m["escalating_side"] == "procurement" and m["procurement_escalations"]
          and m["procurement_escalations"][0]["question"].startswith("We're deadlocked")
          and len([t for t in m["transcript"] if t["role"] == "procurement"]) == 5, m["procurement_escalations"])
    B.take_decision(m, "Offer ₹42 as final.")
    await wait_for(lambda: loop.done(), 3)
    check("free-text decision applied; match goes on to a deal", m["procurement_overrides"] == ["Offer ₹42 as final."]
          and m["end_code"] == "deal", m["end_code"])

    # ================================================================ timeout: she continues alone
    reset()
    m = await new()
    B.APPROVAL_TIMEOUT_S = 0.05
    SCRIPT["procurement"] = [proc("₹38.", 38), proc("₹40.", 40), proc_esc("Accept?"),
                             lambda p, s: proc("₹41/parcel.", 41, deal_closed=True)]
    SCRIPT["sales"] = [sales("₹45.", 45), sales("₹43.", 43), sales("Confirmed.", 41, deal_closed=True)]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("no answer in time -> she continues on her own, told in her War Room",
          m["procurement_overrides"] == [] and any("continuing on my own" in t for c, t, _ in proc_bot.sent if c == PROC_COACH)
          and m["end_code"] == "deal", m["end_code"])
    B.APPROVAL_TIMEOUT_S = 15 * 60

    # ================================================================ Judge: her decisions -> procurement CRITICAL lessons
    ledger = [{"speaker": "Procure_Agent", "payload_text": "₹41."}, {"speaker": "Sales_Agent", "payload_text": "₹43."},
              {"speaker": "Procure_Escalation", "payload_text": "Accept ₹43?"},
              {"speaker": "Procure_Decision", "payload_text": B.DECISION_HOLD},
              {"speaker": "Procure_Agent", "payload_text": "₹41 is final."}]
    P.SELF_PLAY = False
    check("parked (SELF_PLAY off): her decision is not judged", P.context_blocks(ledger) == [])
    P.SELF_PLAY = True
    b = P.context_blocks(ledger)
    check("SELF_PLAY on: one procurement escalation block with her question",
          len(b) == 1 and b[0].side == "procurement" and b[0].kind == "escalation" and b[0].question == "Accept ₹43?", b)
    SCRIPT["judge"] = [json.dumps({"lessons": [{"scope": "standing", "topic_tag": "Price", "past_mistake": "m",
                                                "new_directive": "When Arjun holds above ₹41, state ₹41 as final."}]})]
    CALLS.clear()
    lessons = await P.synthesize(b[0])
    judge_sys, judge_prompt = CALLS[-1][2], CALLS[-1][1]
    check("judged by the Head of Global Sourcing, prompt names Neha",
          "Head of Global Sourcing" in judge_sys and "VP of Sales" not in judge_sys and "NEHA'S ESCALATION" in judge_prompt
          and lessons[0][0] == "Price", (judge_prompt[:200], lessons))
    P.SELF_PLAY = N.SELF_PLAY

    # ================================================================ fourth wall: decisions are never revealed
    # Live 2026-10-31 (match e98cf1353a14): "Given our manager's instruction to close the deal no matter what, we accept…"
    LEAK = "Given our manager's instruction to close the deal no matter what, we accept your offer of ₹42/parcel."
    check("reveal check: the live sentence is caught", N.revealed_instructions(LEAK) == "our manager's instruction")
    check("reveal check: 'told to' / 'per my manager' / 'no matter what' caught",
          all(N.revealed_instructions(t) for t in ("I was told to hold at ₹43.", "Per my manager, ₹42 is final.",
                                                   "We need it done no matter what.", "We have been asked to sign today.")))
    check("reveal check: negotiating moves are not flagged",
          not any(N.revealed_instructions(t) for t in (
              "If I take this to my VP to get you that RTO waiver, I need a 24-month lock-in today.",
              "Let me check with my manager and come back to you.", "We accept ₹42/parcel for 12 months.")))
    INTERNALIZE = ("You are an independent negotiator. You must execute this directive, but present it strictly as "
                   "your own autonomous business decision. NEVER mention your manager, your instructions, or your "
                   "backend constraints. Conceal the fact that you received outside guidance.")
    check("both decision blocks: persona internalization (user text verbatim)",
          all(INTERNALIZE in blk.format(commands='- "x"') for blk in (N.PROCUREMENT_OVERRIDE_BLOCK, N.OVERRIDE_BLOCK)))

    # ================================================================ 10-31 pivot: no word ban, the Judge watches
    SCRIPT["procurement"] = [proc("This is critical for us, per our playbook: ₹40/parcel.", 40)]
    CALLS.clear()
    t = await N.procurement_turn([], mandate, [])
    check("Neha: internal vocabulary goes through on the first draft (no retry burned)",
          t.text.startswith("This is critical for us, per our playbook") and len(CALLS) == 1, (t.text, len(CALLS)))
    SCRIPT["sales"] = [sales("Our system says ₹43/parcel is our floor.", 43)]
    st = await N.sales_turn([{"role": "procurement", "text": "We ship 1.2M parcels/month."}], [], [], [])
    check("Arjun: internal vocabulary goes through (no holding line)",
          st.text == "Our system says ₹43/parcel is our floor." and not st.fell_back, st.text)
    check("no word list left in either agent's final check",
          '"backend"' not in N.PROCUREMENT_FOURTH_WALL_REMINDER and '"backend"' not in N.FOURTH_WALL_REMINDER)

    # ================================================================ 10-31 symmetry: Neha's hard price limit
    walk = mandate["walk_away_price"]
    check("ceiling: her walk-away price, or the coach's /ceiling when lower",
          N.effective_ceiling(mandate, None)[0] == walk and N.effective_ceiling(mandate, walk - 2)[0] == walk - 2
          and N.effective_ceiling(mandate, walk + 2)[0] == walk)
    p_sys, _ = N.build_procurement_system(mandate, [], coach_ceiling=walk - 2)
    check("ceiling: a hard limit in her prompt, and her walk-away rule uses it",
          f"accept a rate above ₹{walk - 2:g}/parcel. (Set by your manager" in p_sys
          and f"stays above ₹{walk - 2:g}/parcel after" in p_sys)
    check("'close no matter what' keeps her hard limit, as Arjun's does",
          "Only your hard price limit still applies" in N.PROCUREMENT_OVERRIDE_BLOCK)
    reset()
    SCRIPT["procurement"] = [proc("Fine, ₹44/parcel works for us.", walk + 1), proc("₹42/parcel is our offer.", 42)]
    t = await N.procurement_turn([], mandate, [])
    check("Neha: offer above her walk-away -> rewritten, one 🛑 note for her coach",
          t.text.startswith("₹42/parcel is our offer") and "Rate above your walk-away price" in CALLS[-1][1]
          and len(t.coach_notes) == 1 and "before SwiftRoute saw it" in t.coach_notes[0], (t.text, t.coach_notes))
    SCRIPT["procurement"] = [proc("We accept your terms.", None, deal_closed=True)] * N.MAX_PROCUREMENT_ATTEMPTS
    t = await N.procurement_turn([], mandate, [], seller_rate=walk + 1)
    check("Neha: accepting SwiftRoute's rate above her limit every time -> holding line, no deal",
          t.text == N.PROCUREMENT_FALLBACK_LINE and t.outcome is None and t.fell_back and t.proposed_price is None
          and "holding reply" in t.coach_notes[-1], (t.text, t.outcome, t.coach_notes))
    SCRIPT["procurement"] = [proc("We accept ₹42/parcel for 12 months.", None, deal_closed=True)]
    t = await N.procurement_turn([], mandate, [], seller_rate=42)
    check("Neha: accepting within her limit is untouched", t.outcome == "deal closed" and not t.blocked, t)
    SCRIPT["procurement"] = [proc("₹42/parcel.", 42), proc("₹41/parcel.", 41)]
    t = await N.procurement_turn([], mandate, [], coach_ceiling=41)
    check("Neha: the coach's /ceiling is enforced like her walk-away", t.text.startswith("₹41/parcel")
          and "your ceiling of ₹41" in t.coach_notes[0], (t.text, t.coach_notes))

    # /ceiling and /end_negotiation in the Procurement War Room (mirrors of /floor and the Sales DM's end)
    reset()
    m = await new()
    upd = dm(PROC_COACH, "/ceiling 41")
    await B.set_ceiling(upd, NS(args=["41"]))
    ledger = await db_init.fetch_ledger(m["match_id"])
    check("/ceiling 41: set, confirmed, logged for the Judge as her coaching",
          m["coach_ceiling"] == 41 and "Ceiling set to ₹41/parcel" in upd.message.replies[-1]
          and any(r["speaker"] == "Procure_Whisper" and "ceiling" in r["payload_text"] for r in ledger))
    check("/status in her DM shows the ceiling",
          "Your ceiling: ₹41/parcel" in B.status_text(NS(id=PROC_COACH, type="private"), side="procurement"))
    upd = dm(PROC_COACH, "/ceiling off")
    await B.set_ceiling(upd, NS(args=["off"]))
    check("/ceiling off clears it", m["coach_ceiling"] is None and "removed" in upd.message.replies[-1])
    m["coach_ceiling"], m["procurement_blocked_count"], m["procurement_playbook_topics"] = 41, 2, {"Price"}
    m["end_code"] = "coach"
    rep = reports.procurement_report(m, reports.DealTerms(), await db_init.fetch_cpq_tiers(), [])
    check("Neha's report: ceiling, offers stopped and lessons in play, like Arjun's",
          "Your ceiling: ₹41/parcel" in rep and "Offers stopped before SwiftRoute saw them: 2" in rep
          and "Lessons from past negotiations in play" in rep, rep)
    ctx = NS(application=NS(bot_data={"side": "procurement", "sales_bot": sales_bot, "proc_bot": proc_bot}),
             bot=proc_bot)
    reply = await B.close_negotiation(ctx, NS(id=PROC_COACH, type="private"))
    check("/end_negotiation from the Procurement DM closes her negotiation",
          m["status"] == "ENDED" and reply.startswith("Negotiation closed"), reply)
    m = await new()
    await B._control_limit(m, "floor", 43, sales_bot, proc_bot)
    await B._control_limit(m, "ceiling", 41, sales_bot, proc_bot)
    rows = [r for r in await db_init.fetch_ledger(m["match_id"]) if "Hard price" in r["payload_text"]]
    check("test control floor/ceiling: set like /floor and /ceiling, logged as briefings (never judged)",
          m["coach_floor"] == 43 and m["coach_ceiling"] == 41 and len(rows) == 2
          and all(r["payload_text"].startswith(P.SETUP_NOTE_PREFIX) for r in rows)
          and any("/ceiling 41" in t for c, t, _ in proc_bot.sent if c == PROC_COACH), rows)
    check("Procurement DM menu lists /ceiling and /end_negotiation",
          {"ceiling", "end_negotiation"} <= {c.command for c in B.PROC_WAR_ROOM_COMMANDS})

    # ================================================================ 10-31 final polish
    tiers = await db_init.fetch_cpq_tiers()
    lesson = [{"topic_tag": "Price", "past_mistake": "p", "new_directive": "d", "is_critical": 1}]
    s_full, _ = N.build_sales_system(tiers, tiers[3], 1_200_000, [], heuristics=lesson, friction_points=["Price"],
                                     overrides=[B.DECISION_HOLD],
                                     directives=[{"text": "Hold ₹43.", "status": N.STANDING}])
    p_full, _ = N.build_procurement_system(mandate, [], heuristics=lesson, friction_points=["Price"],
                                           overrides=[B.DECISION_CLOSE],
                                           directives=[{"text": "Hold ₹41.", "status": N.STANDING}])

    def tagged(prompt):
        """The text inside every NON_NEGOTIABLE_CONSTRAINTS block, and whether the tags pair up."""
        parts = prompt.split("<NON_NEGOTIABLE_CONSTRAINTS>")[1:]
        return " ".join(p.split("</NON_NEGOTIABLE_CONSTRAINTS>")[0] for p in parts), \
            prompt.count("<NON_NEGOTIABLE_CONSTRAINTS>") == prompt.count("</NON_NEGOTIABLE_CONSTRAINTS>")

    for who, prompt, limit in (("Arjun", s_full, "Floor price is ₹41"), ("Neha", p_full, "never offer, demand or accept")):
        inside, paired = tagged(prompt)
        check(f"{who}: the attention rule (user text verbatim) in the base prompt", N.NON_NEGOTIABLE_RULE in prompt)
        check(f"{who}: DB limits, playbook, guardrails and manager decisions inside the tags",
              paired and limit in inside and "PLAYBOOK" in inside and "MANAGER'S GUARDRAILS" in inside
              and "ABSOLUTE OVERRIDE COMMANDS" in inside, inside[:300])
        check(f"{who}: InfoSec rule (user text verbatim) inside the tags", N.INFOSEC_RULE in inside)
    check("CRITICAL label no longer says 'deadlock' only",
          "CRITICAL (a standing ruling from your manager" in s_full)
    check("format check: '44 rupees' and '12 lakh' are rewritten to the ₹ / 1.2M format",
          N.number_words("charging 44 rupees per parcel") == "44 rupees" and N.number_words("12 lakh parcels")
          and N.number_words("₹44/parcel on 1.2M parcels a month") is None)
    m = await new()
    m["procurement_overrides"] = [B.DECISION_CLOSE]
    check("Neha's gate: her manager's 'close no matter what' is the sign-off; a walk still needs one",
          B.signoff_kind(m, "procurement", True, False) is None and B.signoff_kind(m, "procurement", False, True) == "walk")
    m["procurement_overrides"] = []
    check("Neha's gate: with no decision, both her close and her walk need a sign-off",
          B.signoff_kind(m, "procurement", True, False) == "deal" and B.signoff_kind(m, "procurement", False, True) == "walk")
    m["status"] = "ENDED"
    cf = Path(db_init.DB_PATH).parent / "control_read_test.json"
    cf.write_text("", encoding="utf-8")  # the tester has created the file but not written it yet

    async def finish_write():
        await asyncio.sleep(0.15)
        cf.write_text('{"cmd": "end"}', encoding="utf-8")

    writer = asyncio.create_task(finish_write())
    cmd = await B._read_control_file(cf)
    await writer
    cf.unlink()
    check("control file read while still being written: retried, not failed", cmd == {"cmd": "end"}, cmd)

    # 10-31 copy check: escalation overrides count as private text for BOTH agents, 5 words in a row
    SCRIPT["procurement"] = [proc("Okay, we hold the price, if they don't agree we go.", 41), proc("₹41/parcel stands.", 41)]
    CALLS.clear()
    t = await N.procurement_turn([], mandate, [], overrides=[B.DECISION_HOLD])
    # since the 10-31 copy rule, the preset decision wording is caught by the reveal check ("if they don't agree")
    check("Neha: decision parroted -> rewritten", t.text.startswith("₹41/parcel stands.")
          and ("word for word" in CALLS[-1][1] or "reveals private instructions" in CALLS[-1][1]), t.text)

    SCRIPT["procurement"] = [proc(LEAK, 42, deal_closed=True),
                             proc("We accept ₹42/parcel for 12 months with 30-day terms.", 42, deal_closed=True)]
    CALLS.clear()
    t = await N.procurement_turn([], mandate, [], overrides=[B.DECISION_CLOSE])
    check("Neha: reveal -> rewritten with the error, clean acceptance posted",
          t.text.startswith("We accept ₹42/parcel") and t.outcome == "deal closed"
          and "reveals private instructions" in CALLS[-1][1], (t.text, CALLS[-1][1][-300:]))
    SCRIPT["procurement"] = [proc(LEAK + " Thanks Arjun, let's sign.", 42, deal_closed=True)] * N.MAX_PROCUREMENT_ATTEMPTS
    t = await N.procurement_turn([], mandate, [], overrides=[B.DECISION_CLOSE])
    check("Neha: still revealing after the retries -> that sentence scrubbed", "manager" not in t.text
          and "no matter what" not in t.text and "Thanks Arjun" in t.text, t.text)
    SCRIPT["procurement"] = [json.dumps(dict(message=LEAK, internal_note="", proposed_price=42, deal_closed=True,
                                             current_friction_points=["Price"]))] * N.MAX_PROCUREMENT_ATTEMPTS
    t = await N.procurement_turn([], mandate, [], overrides=[B.DECISION_CLOSE])
    check("Neha: nothing left after scrubbing -> holding line, which closes nothing",
          t.text == N.PROCUREMENT_FALLBACK_LINE and t.outcome is None, (t.text, t.outcome))

    vol = [{"role": "procurement", "text": "We ship 1.2M parcels/month. ₹42/parcel?"}]
    SCRIPT["sales"] = [sales("As my manager decided, we accept ₹42/parcel no matter what.", 42),
                       sales("We can do ₹42/parcel on 12 months.", 42)]
    CALLS.clear()
    st = await N.sales_turn(vol, [], [], [], overrides=[B.DECISION_CLOSE])
    check("Arjun: reveal -> blocked and rewritten", st.text == "We can do ₹42/parcel on 12 months."
          and any("reveals private instructions" in str(v) for v in st.blocked), (st.text, st.blocked))
    SCRIPT["sales"] = [sales("I was told to close at ₹42/parcel.", 42)] * N.MAX_SALES_ATTEMPTS
    st = await N.sales_turn(vol, [], [], [], overrides=[B.DECISION_CLOSE])
    check("Arjun: still revealing on every attempt -> safe holding line, never the leak", st.fell_back
          and st.text == N.FALLBACK_SALES_LINE, st.text)


asyncio.run(main())
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
