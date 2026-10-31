"""Offline tests: two-way escalation, absolute overrides, critical Judge lessons, parked Phase B."""

import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parent.parent
SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))
import os  # noqa: E402
# .env may hold dev settings: a test never starts real shadow matches (Gemini), and pins self-play.
os.environ.setdefault("ZEROLEAK_SHADOW_MATCHES", "0")
os.environ.setdefault("ZEROLEAK_SELF_PLAY", "0")

import db_init  # noqa: E402

TEST_DB = SCRATCH / "escalation_test.db"
shutil.copy(SCRATCH / "zeroleak_backup_at_restart.db", TEST_DB)  # Phase-6 schema (pre-escalation)
db_init.DB_PATH = TEST_DB

import bot_main as B  # noqa: E402
import llm_engine  # noqa: E402
import negotiation as N  # noqa: E402
import post_match  # noqa: E402
import reports  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


CALLS, SCRIPT = [], {"procurement": [], "sales": [], "judge": []}


async def fake_generate(agent, prompt, system_instruction=None, json_mode=False, temperature=None):
    CALLS.append((agent, prompt, system_instruction))
    if not SCRIPT[agent]:
        raise AssertionError(f"no scripted reply for {agent}")
    r = SCRIPT[agent].pop(0)
    return r(prompt, system_instruction) if callable(r) else r


llm_engine.generate = fake_generate
N.llm_engine.generate = fake_generate


def proc(text, **kw):
    d = dict(message=f"{text} (We ship 1.2M parcels/month.)", internal_note="", current_friction_points=["Price"], executed_directive_ids=[],
             deal_closed=False, walk_away=False)
    d.update(kw)
    return json.dumps(d)


def sales(text, price=43, **kw):
    d = dict(message=text, proposed_price=price, offers_rto_waiver=False, contract_months=12,
             current_friction_points=["Price"], executed_directive_ids=[], requires_manager_approval=False,
             escalation_message_to_manager="", deal_closed=False, walk_away=False)
    d.update(kw)
    return json.dumps(d)


def escalation(q):
    return sales("", price=None, requires_manager_approval=True, escalation_message_to_manager=q)


DEAL_JSON = json.dumps(dict(rate_per_parcel=43, rto_waiver="not_included", payment_terms_days=30, contract_months=12,
                            buyer_commitments=[], open_items=[], procurement_summary="s", sales_summary="s",
                            next_step="n"))


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


GROUP, COACH = -100, 555
sales_bot, proc_bot = FakeBot("sales"), FakeBot("proc")


def ctx(side="sales"):
    return SimpleNamespace(bot=sales_bot if side == "sales" else proc_bot, args=[],
                           application=SimpleNamespace(bot_data={"sales_bot": sales_bot, "proc_bot": proc_bot,
                                                                 "side": side}))


def dm(text):
    return SimpleNamespace(effective_chat=SimpleNamespace(id=COACH, type="private"), message=Msg(text))


async def wait_for(cond, timeout=3.0):
    for _ in range(int(timeout / 0.005)):
        if cond():
            return True
        await asyncio.sleep(0.005)
    return cond()


async def new():
    m = B.new_match(COACH, await db_init.fetch_mandate(), await db_init.fetch_static_ammo("sales"),
                    await db_init.fetch_static_ammo("procurement"))
    m["procurement_war_room_chat_id"] = COACH
    B.active_matches[GROUP] = m
    B.war_room_to_group[COACH] = GROUP
    B.proc_war_room_to_group[COACH] = GROUP
    return m


def boardroom(match_bot_list=(sales_bot, proc_bot)):
    return [t for b in match_bot_list for c, t, _ in b.sent if c == GROUP]


def reset():
    sales_bot.sent.clear(); proc_bot.sent.clear(); CALLS.clear()
    for q in SCRIPT.values():
        q.clear()
    B.judge_tasks.clear()


async def main():
    B.TURN_DELAY_S = (0, 0)
    # ======================================================== DB migration (Phase 6 -> escalation)
    before = sqlite3.connect(TEST_DB).execute("select count(*) from match_transcripts").fetchone()[0]
    await db_init.init_db()
    await db_init.init_db()
    c = sqlite3.connect(TEST_DB)
    sql = c.execute("select sql from sqlite_master where name='match_transcripts'").fetchone()[0]
    check("ledger accepts Sales_Escalation + Manager_Decision", "'Sales_Escalation'" in sql and "'Manager_Decision'" in sql)
    check("ledger rows kept", c.execute("select count(*) from match_transcripts").fetchone()[0] == before)
    cols = {r[1] for r in c.execute("pragma table_info(sales_heuristics)")}
    check("sales_heuristics.is_critical added", "is_critical" in cols)
    check("existing lessons default not critical",
          all(r[0] == 0 for r in c.execute("select is_critical from sales_heuristics")))
    check("index on ledger kept", c.execute("select count(*) from sqlite_master where name='idx_transcripts_match'").fetchone()[0] == 1)
    c.close()

    # ======================================================== prompts
    tiers = await db_init.fetch_cpq_tiers()
    tier = tiers[3]
    s_none, _ = N.build_sales_system(tiers, tier, 1_200_000, [], escalations_left=0)
    s_esc, _ = N.build_sales_system(tiers, tier, 1_200_000, [], escalations_left=2, manager="Sarath")
    s_ovr, _ = N.build_sales_system(tiers, tier, 1_200_000, [], overrides=[B.DECISION_HOLD])
    check("JSON schema has requires_manager_approval + escalation_message_to_manager",
          '"requires_manager_approval"' in s_none and '"escalation_message_to_manager"' in s_none)
    check("escalation offered only when left > 0", "ESCALATING TO YOUR MANAGER (Sarath)" in s_esc
          and "Escalations left in this negotiation: 2" in s_esc and "ESCALATING" not in s_none)
    check("override block only with overrides", "ABSOLUTE OVERRIDE" in s_ovr and "ABSOLUTE OVERRIDE" not in s_esc)
    # Since 2026-10-26 only the fourth-wall reminder comes after the override block.
    check("override block is last in the prompt (before the fourth-wall reminder)",
          s_ovr.rstrip().endswith(N.FOURTH_WALL_REMINDER)
          and s_ovr.rstrip()[:-len(N.FOURTH_WALL_REMINDER)].rstrip().endswith("already decided."))
    for name, s in (("plain", s_none), ("escalation", s_esc), ("override", s_ovr)):
        check(f"fourth-wall rule verbatim in hard limits ({name})",
              "- NEVER break the fourth wall. NEVER use phrases like 'per our playbook', 'according to my manager', "
              "'my directives', or 'critical lesson'. You must weave your instructions organically into your "
              "persona as an independent human Account Executive." in s
              and s.index("NEVER break the fourth wall") < s.index("Respond with JSON only"))
        check(f"fourth-wall reminder is the last line ({name})", s.rstrip().endswith(N.FOURTH_WALL_REMINDER))
        check(f"no unfilled placeholders ({name})", "{fourth_wall" not in s)
    check("Step 3 'close' rule verbatim", "If the Manager says 'Close the deal no matter what', you must immediately "
          "compromise and accept the buyer's terms to close the contract" in s_ovr)
    check("Step 3 'hold' rule verbatim", "If the Manager says 'Hold the price, if they don't agree, walk away', you "
          "must state your final terms and execute a walk-away if the buyer rejects them on the next turn" in s_ovr)
    check("decision text injected", f'- "{B.DECISION_HOLD}"' in s_ovr)

    # ======================================================== escalations_left rules
    m = await new()
    check("no escalation before Arjun's 2nd message", B.escalations_left(m) == 0)
    m["transcript"] = [{"role": "sales", "text": "a"}, {"role": "sales", "text": "b"}]
    check("escalation offered from then on (3)", B.escalations_left(m) == 3)
    m["escalation_cooldown"] = True
    check("cooldown -> 0", B.escalations_left(m) == 0)
    m["escalation_cooldown"] = False
    m["escalations"] = [{}, {}, {}]
    check("cap 3 per match", B.escalations_left(m) == 0)
    m["status"] = "ENDED"

    # ======================================================== full flow: escalate -> decision -> hold -> walk away
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("1.2M parcels/month. ₹38/parcel."), proc("₹40/parcel."),
                             proc("₹41/parcel or we walk."), proc("No. ₹41/parcel, final.")]
    SCRIPT["sales"] = [sales("₹45/parcel.", 45), sales("₹43/parcel.", 43),
                       escalation("Neha is pushing for ₹41 and threatening to walk. Should I drop to the floor, or walk away?"),
                       lambda p, s: sales("₹43/parcel is our final offer.", 43),
                       lambda p, s: sales("Then we walk away. Thank you, Neha.", None, walk_away=True)]
    SCRIPT["judge"] = [DEAL_JSON,
                       json.dumps(dict(topic_tag="Price", past_mistake="Froze at ₹41 walk threat",
                                       new_directive="When she demands ₹41 and threatens to walk on 12 months, state ₹43 as final; walk away if rejected.")),
                       # an existing Price lesson is in the DB, so the Judge merges into it
                       json.dumps(dict(similarity=88, past_mistake="Froze at a ₹41 walk threat",
                                       new_directive="Hold ₹43; when she demands ₹41 and threatens to walk on 12 months, state ₹43 as final; walk away if rejected."))]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    ok = await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL")
    check("state -> AWAITING_MANAGER_APPROVAL", ok, m["status"])
    await wait_for(lambda: any(c == COACH and "needs your decision" in t for c, t, _ in sales_bot.sent))
    check("escalation NOT posted to the Boardroom", not any("drop to the floor" in t for t in boardroom()))
    dm_msgs = [(t, mk) for c, t, mk in sales_bot.sent if c == COACH]
    check("question routed to Sales War Room with buttons",
          any("Neha is pushing for ₹41" in t and mk is B.ESCALATION_MENU for t, mk in dm_msgs))
    ledger = await db_init.fetch_ledger(m["match_id"])
    check("Sales_Escalation logged", ledger[-1]["speaker"] == "Sales_Escalation")
    await asyncio.sleep(0.05)
    check("Boardroom holds while waiting (no new LLM calls)", [a for a, _, _ in CALLS].count("sales") == 3)
    check("status shows the question in the War Room",
          "waiting for your decision" in B.status_text(SimpleNamespace(id=COACH, type="private")))
    check("group status says on hold", "On hold" in B.status_text(SimpleNamespace(id=GROUP, type="group")))

    upd = dm(B.DECISION_HOLD)
    await B.buffer_whisper(upd, ctx())
    check("decision acknowledged", upd.message.replies and upd.message.replies[0].startswith("Got it."))
    check("decision is not stored as a whisper", m["active_coaching_directives"] == [])
    await wait_for(lambda: loop.done(), 3)
    sales_calls = [(p, s) for a, p, s in CALLS if a == "sales"]
    check("regenerated reply carries the Absolute Override", "ABSOLUTE OVERRIDE" in sales_calls[3][1]
          and B.DECISION_HOLD in sales_calls[3][1])
    check("no re-escalation right after the decision", "not available for this message" in sales_calls[3][1])
    check("final terms posted to the Boardroom", any("final offer" in t for t in boardroom()))
    check("walk-away executed -> sales_walkaway", m["end_code"] == "sales_walkaway", m["end_code"])
    check("Boardroom closing says SwiftRoute walked away", any("SwiftRoute has walked away" in t for t in boardroom()))
    ledger = await db_init.fetch_ledger(m["match_id"])
    check("Manager_Decision logged", any(r["speaker"] == "Manager_Decision" and r["payload_text"] == B.DECISION_HOLD
                                         for r in ledger))
    await asyncio.gather(*list(B.judge_tasks))
    # 10-31: the merge drops "never offer below this … floor" (limit wording) -> it waits for the coach's OK
    proposal = await db_init.fetch_pending(side="sales", topic_tag="Price")
    check("deadlock lesson that drops limit wording -> proposal, not saved yet",
          proposal is not None and "limit wording" in proposal["reason"]
          and "₹43 as final" not in (await db_init.fetch_heuristic("sales", "Price"))["new_directive"], proposal)
    await B.answer_lesson(proposal["pending_id"], True)  # the coach approves it
    price = await db_init.fetch_heuristic("sales", "Price")
    check("Judge stored the deadlock as a CRITICAL lesson", price["is_critical"] == 1 and "₹43 as final" in price["new_directive"])
    judge_prompts = [p for a, p, s in CALLS if a == "judge" and "ESCALATION to his manager" in p]
    check("Judge saw question, decision and what happened after",
          judge_prompts and "drop to the floor" in judge_prompts[0] and B.DECISION_HOLD in judge_prompts[0]
          and "AFTER" in judge_prompts[0] and "final offer" in judge_prompts[0])
    report = [t for c, t, _ in sales_bot.sent if c == COACH and "Deal report" in t]
    check("Sales report: outcome + escalation + critical lesson",
          report and "we walked away, on your decision" in report[0] and "🙋 Arjun asked" in report[0]
          and "waiting for your OK" in report[0] and "limit wording" in report[0], report[:1])

    # ======================================================== next match: critical lesson is fed back (JIT)
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("₹41/parcel or we walk.", deal_closed=False), proc("Fine, ₹43/parcel. Deal.", deal_closed=True)]
    SCRIPT["sales"] = [sales("₹43/parcel is final; otherwise we walk.", 43), sales("Confirmed: ₹43/parcel, 12 months. We have a deal.", 43, deal_closed=True)]
    SCRIPT["judge"] = [DEAL_JSON]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    sys_prompt = [s for a, p, s in CALLS if a == "sales"][0]
    check("next match: CRITICAL lesson in Arjun's prompt",
          "CRITICAL (a deadlock your manager had to break" in sys_prompt and "₹43 as final" in sys_prompt)
    check("deal closed by Neha", m["end_code"] == "deal")
    await asyncio.gather(*list(B.judge_tasks))

    sys_prompt_confirm = [s for a, p, s in CALLS if a == "sales"][-1]
    check("Arjun's confirming turn gets the closing check", "CLOSING CHECK" in sys_prompt_confirm)

    # ======================================================== two-sided close: conditional "acceptance" refused
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("₹43/parcel works for us."),
                             proc("We accept ₹43/parcel provided you include a full RTO waiver.", deal_closed=True),
                             proc("Fine, ₹43/parcel without the waiver.", deal_closed=True)]
    SCRIPT["sales"] = [sales("₹43/parcel for 12 months.", 43),
                       sales("I can't include the RTO waiver on 12 months; ₹43/parcel stands.", 43),
                       sales("Confirmed: ₹43/parcel, 12 months. We have a deal.", 43, deal_closed=True)]
    SCRIPT["judge"] = [DEAL_JSON]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("Neha's conditional acceptance does not end the match", len(m["transcript"]) == 6, len(m["transcript"]))
    check("deal only after Arjun confirms", m["end_code"] == "deal" and m["transcript"][-1]["role"] == "sales")
    await asyncio.gather(*list(B.judge_tasks))

    # ======================================================== button decision + close no matter what
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b"), proc("c ₹41/parcel"),
                             proc("Confirmed: ₹41/parcel.", deal_closed=True)]  # she confirms his close (10-28)
    SCRIPT["sales"] = [sales("x"), sales("y"), escalation("She insists on ₹41/parcel. Close or hold?"),
                       lambda p, s: sales("Agreed: ₹41/parcel, we have a deal.", 41, deal_closed=True)]
    SCRIPT["judge"] = [DEAL_JSON, json.dumps(dict(topic_tag="Price", past_mistake="m", new_directive="d"))]
    SCRIPT["judge"].append(json.dumps(dict(similarity=70, past_mistake="m2", new_directive="Merged directive")))
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL")
    answered = []
    q = SimpleNamespace(data="esc:close", message=SimpleNamespace(chat=SimpleNamespace(id=COACH, type="private")),
                        from_user=SimpleNamespace(id=COACH))

    async def answer(text=None, show_alert=False):
        answered.append(text)
    q.answer = answer
    await B.sales_buttons(SimpleNamespace(callback_query=q), ctx())
    await wait_for(lambda: loop.done(), 3)
    check("button sends the preset 'close' decision", m["manager_overrides"] == [B.DECISION_CLOSE], m["manager_overrides"])
    check("Arjun accepts -> deal closed by Sales", m["end_code"] == "deal")
    await asyncio.gather(*list(B.judge_tasks))
    price = await db_init.fetch_heuristic("sales", "Price")
    # 10-30: the Price lesson is CRITICAL here, so the merge waits for the coach's OK
    proposal = await db_init.fetch_pending(side="sales", topic_tag="Price")
    check("merge into a CRITICAL lesson -> proposal, live lesson untouched",
          proposal is not None and proposal["new_directive"] == "Merged directive"
          and price["new_directive"] != "Merged directive", (proposal, price))
    await B.answer_lesson(proposal["pending_id"], True)
    price = await db_init.fetch_heuristic("sales", "Price")
    check("merge keeps the lesson CRITICAL", price["is_critical"] == 1 and price["new_directive"] == "Merged directive")

    # ======================================================== walk_away without a manager decision is ignored
    reset()
    with sqlite3.connect(TEST_DB) as c:
        c.execute("UPDATE sales_heuristics SET is_critical = 0")  # no past decision in play either
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b", deal_closed=True)]
    SCRIPT["sales"] = [sales("We walk.", None, walk_away=True), sales("Confirmed: ₹43/parcel, 12 months. We have a deal.", 43, deal_closed=True)]
    SCRIPT["judge"] = [DEAL_JSON]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("unauthorised walk-away ignored (match continues)", m["end_code"] == "deal")
    await asyncio.gather(*list(B.judge_tasks))

    # ======================================================== a CRITICAL lesson in play authorises walking away
    reset()
    with sqlite3.connect(TEST_DB) as c:
        c.execute("UPDATE sales_heuristics SET is_critical = 1 WHERE topic_tag = 'Price'")
    m = await new()
    SCRIPT["procurement"] = [proc("a")]
    SCRIPT["sales"] = [sales("We walk.", None, walk_away=True)]
    SCRIPT["judge"] = [DEAL_JSON]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("CRITICAL lesson in play -> walk-away honoured", m["end_code"] == "sales_walkaway", m["end_code"])
    await asyncio.gather(*list(B.judge_tasks))
    s_crit, _ = N.build_sales_system(tiers, tier, 1_200_000, [], escalations_left=1, deadlock="x")
    check("prompt: CRITICAL lesson -> follow it, don't escalate",
          "If a CRITICAL lesson in your playbook covers the situation" in s_crit
          and "If a CRITICAL lesson covers this deadlock, execute it" in s_crit)

    # ======================================================== timeout + end while waiting
    reset()
    B.APPROVAL_TIMEOUT_S = 0.1
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b"), proc("c"), proc("d", deal_closed=True)]
    SCRIPT["sales"] = [sales("x"), sales("y"), escalation("Stuck?"), sales("Carrying on at ₹43/parcel."), sales("Confirmed: ₹43/parcel, 12 months. We have a deal.", 43, deal_closed=True)]
    SCRIPT["judge"] = [DEAL_JSON]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("timeout: Arjun continues alone, coach told", any(t == B.ESCALATION_TIMEOUT_DM for c, t, _ in sales_bot.sent))
    check("timeout: no override recorded", m["manager_overrides"] == [] and m["escalations"][0]["decision"] is None)
    await asyncio.gather(*list(B.judge_tasks))
    B.APPROVAL_TIMEOUT_S = 60

    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b"), proc("c")]
    SCRIPT["sales"] = [sales("x"), sales("y"), escalation("Stuck?")]
    SCRIPT["judge"] = [DEAL_JSON]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL")
    await B.close_negotiation(ctx(), SimpleNamespace(id=GROUP, type="group"))
    check("end while waiting: loop exits", await wait_for(lambda: loop.done(), 2))
    await asyncio.gather(*list(B.judge_tasks))

    # ======================================================== "hold ... walk away": final terms first, walk only after a reply
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b"), proc("c"), proc("No, still too high.")]
    SCRIPT["sales"] = [sales("x"), sales("y"), escalation("Hold or close?"),
                       lambda p, s: sales("₹43/parcel is final; if not, we walk away.", 43, walk_away=True),  # too early
                       lambda p, s: sales("₹43/parcel for 12 months is my final offer.", 43),  # rewrite (2026-10-26)
                       lambda p, s: sales("Then we walk away.", None, walk_away=True)]
    SCRIPT["judge"] = [DEAL_JSON, json.dumps(dict(topic_tag="Price", past_mistake="m", new_directive="d")),
                       json.dumps(dict(similarity=60, past_mistake="m", new_directive="d"))]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL")
    B.take_decision(m, B.DECISION_HOLD)
    await wait_for(lambda: loop.done(), 3)
    roles = [t["role"] for t in m["transcript"]]
    check("walk-away in the final-terms message is ignored; Neha replies; then walk",
          m["end_code"] == "sales_walkaway" and roles[-3:] == ["sales", "procurement", "sales"], roles)
    posted = [t["text"] for t in m["transcript"] if t["role"] == "sales"]
    check("too-early walk-away is rewritten before posting (not posted)",
          "₹43/parcel is final; if not, we walk away." not in posted
          and "₹43/parcel for 12 months is my final offer." in posted, posted)
    check("rewrite prompt carries the final-terms note",
          any(a == "sales" and N.FINAL_TERMS_FIRST_LINE in p for a, p, s in CALLS))
    await asyncio.gather(*list(B.judge_tasks))

    # ======================================================== backstop: required escalation the model ignored
    reset()
    with sqlite3.connect(TEST_DB) as c:
        c.execute("UPDATE sales_heuristics SET is_critical = 0")
    m = await new()
    SCRIPT["procurement"] = [proc(f"No, too high ({i}).") for i in range(8)]
    SCRIPT["sales"] = [sales(f"₹43/parcel stands ({i}).", 43) for i in range(5)] + [
        lambda p, s: sales("₹43/parcel stands, again.", 43),          # ignores the REQUIRED line
        lambda p, s: sales("Final: ₹43/parcel; otherwise we walk.", 43),
        lambda p, s: sales("Then we walk away.", None, walk_away=True)]
    SCRIPT["judge"] = [DEAL_JSON, json.dumps(dict(topic_tag="Price", past_mistake="m", new_directive="d")),
                       json.dumps(dict(similarity=60, past_mistake="m", new_directive="d")),
                       json.dumps(dict(similarity=60, past_mistake="m", new_directive="d"))]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    ok = await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL", 5)
    check("backstop: escalates after 5 identical offers", ok and len(m["escalations"]) == 1)
    forced_prompt = [s for a, p, s in CALLS if a == "sales"][5]
    check("backstop: prompt said REQUIRED", "REQUIRED: this deadlock has gone on too long" in forced_prompt)
    question = m["escalations"][0]["question"] if m["escalations"] else ""
    check("backstop: question built from measured facts, first person",
          question.startswith("We're deadlocked: I have offered ₹43/parcel in my last 5 offers")
          and "your" not in question.split("Neha's latest")[0], question)
    check("backstop: ignored draft NOT posted", not any("again" in t for t in boardroom()))
    B.take_decision(m, B.DECISION_HOLD)
    await wait_for(lambda: len([a for a, _, _ in CALLS if a == "sales"]) >= 7, 3)
    await B.close_negotiation(ctx(), SimpleNamespace(id=GROUP, type="group"))
    await wait_for(lambda: loop.done(), 3)
    check("backstop: no second forced escalation right after the decision", len(m["escalations"]) == 1)
    await asyncio.gather(*list(B.judge_tasks))

    # ======================================================== escalation when not allowed -> treated as bad JSON
    reset()
    SCRIPT["sales"] = [escalation("too early"), sales("₹45/parcel.", 45)]
    t = await N.sales_turn([{"role": "procurement", "text": "1.2M parcels/month"}], [], escalations_left=0)
    check("escalation not allowed -> rewrite into a real message", t.escalation is None and t.text == "₹45/parcel.")

    # ======================================================== 2026-10-26 fixes (walk-aways, deadlock, digits)
    SPARE_JUDGE = [DEAL_JSON] + [json.dumps(dict(topic_tag="Price", past_mistake="m", new_directive="d",
                                                 similarity=60))] * 6
    with sqlite3.connect(TEST_DB) as c:
        c.execute("UPDATE sales_heuristics SET is_critical = 0")

    # Fix 1: unauthorised walk-away -> the manager is asked; the goodbye is never posted
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b"), proc("c")]
    SCRIPT["sales"] = [sales("x"), sales("y"), sales("Goodbye, we are walking away.", 43, walk_away=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    ok = await wait_for(lambda: m["status"] == "AWAITING_MANAGER_APPROVAL")
    q = m["escalations"][0]["question"] if m["escalations"] else ""
    check("fix1: unauthorised walk-away becomes an escalation", ok and q.startswith("I'm ready to walk away"), q)
    check("fix1: the goodbye was not posted", not any("Goodbye" in t for t in boardroom()))
    check("fix1: escalation DM sent", await wait_for(
        lambda: any("I'm ready to walk away" in t for c, t, _ in sales_bot.sent if c == COACH)))
    await B.close_negotiation(ctx(), SimpleNamespace(id=GROUP, type="group"))
    await wait_for(lambda: loop.done(), 3)
    await asyncio.gather(*list(B.judge_tasks))

    # Fix 1b: no escalation available (his 1st message) -> one rewrite with the not-authorised note
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b", deal_closed=True)]
    SCRIPT["sales"] = [sales("Bye, walking away.", None, walk_away=True), sales("₹44/parcel is where we are.", 44),
                       sales("Confirmed: ₹44/parcel. Deal.", 44, deal_closed=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    posted = [t["text"] for t in m["transcript"] if t["role"] == "sales"]
    check("fix1b: walk rewritten, goodbye not posted", posted[:1] == ["₹44/parcel is where we are."], posted)
    check("fix1b: rewrite prompt has the not-authorised note",
          any(a == "sales" and N.WALK_NOT_AUTHORISED_LINE in p for a, p, s in CALLS))
    check("fix1b: match went on to a deal", m["end_code"] == "deal", m["end_code"])
    await asyncio.gather(*list(B.judge_tasks))

    # Fix 1c: still walking after the rewrite -> posted, walk ignored, match continues
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("a"), proc("b"), proc("c", deal_closed=True)]
    SCRIPT["sales"] = [sales("Bye.", None, walk_away=True), sales("Bye again.", None, walk_away=True),
                       sales("₹44/parcel then.", 44), sales("Confirmed. Deal.", 44, deal_closed=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    posted = [t["text"] for t in m["transcript"] if t["role"] == "sales"]
    check("fix1c: only one rewrite, then posted with the walk ignored",
          posted[0] == "Bye again." and m["end_code"] == "deal", (posted, m["end_code"]))
    await asyncio.gather(*list(B.judge_tasks))

    # Fix 3: the buyer meets his price -> he may not walk; rewrite tells him to close
    reset()
    m = await new()
    m["manager_overrides"] = [B.DECISION_HOLD]
    m["sales_posts_since_decision"] = 1  # final terms already stated
    SCRIPT["procurement"] = [proc("₹41/parcel.", proposed_price=41), proc("OK, ₹42/parcel, 12 months.", proposed_price=42),
                             proc("Confirmed.", proposed_price=42, deal_closed=True)]  # she confirms his close (10-28)
    SCRIPT["sales"] = [sales("₹42/parcel, final.", 42), sales("Sorry, we walk.", None, walk_away=True),
                       sales("Agreed: ₹42/parcel for 12 months. Deal.", 42, deal_closed=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("fix3: Neha's rates recorded (incl. her confirmation)", m["procurement_offers"] == [41, 42, 42],
          m["procurement_offers"])
    check("fix3: buyer meets price -> walk not posted, deal closed",
          m["end_code"] == "deal" and not any("we walk" in t for t in boardroom()), m["end_code"])
    note_prompts = [p for a, p, s in CALLS if a == "sales" and "meets your price" in p]
    check("fix3: rewrite note names both rates", note_prompts and "₹42/parcel, which meets your price of ₹42/parcel"
          in note_prompts[0])
    await asyncio.gather(*list(B.judge_tasks))

    # Fix 3b: he still walks after the note, with authority -> honoured (a forbidden term, his call)
    reset()
    m = await new()
    m["manager_overrides"] = [B.DECISION_HOLD]
    m["sales_posts_since_decision"] = 1
    SCRIPT["procurement"] = [proc("₹41/parcel.", proposed_price=41),
                             proc("₹42/parcel, but RTO on 12 months.", proposed_price=42)]
    SCRIPT["sales"] = [sales("₹42/parcel, final.", 42), sales("We walk.", None, walk_away=True),
                       sales("RTO on 12 months is not possible, so we walk away.", None, walk_away=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("fix3b: walk after the meets-note honoured when authorised", m["end_code"] == "sales_walkaway", m["end_code"])
    await asyncio.gather(*list(B.judge_tasks))

    # No small-gap close (coach 2026-10-27: "1 rupee could be a loss of millions"): a ₹1 gap is a normal walk-away
    with sqlite3.connect(TEST_DB) as c:
        c.execute("UPDATE sales_heuristics SET is_critical = 1 WHERE topic_tag = 'Price'")

    async def gap_match(neha_rates, sales_replies, coach_floor=None):
        reset()
        mm = await new()
        mm["coach_floor"] = coach_floor
        SCRIPT["procurement"] = [proc(f"₹{r:g}/parcel, 12 months.", proposed_price=r) for r in neha_rates]
        SCRIPT["sales"] = list(sales_replies)
        SCRIPT["judge"] = list(SPARE_JUDGE)
        lp = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
        B.match_tasks[GROUP] = lp
        await wait_for(lambda: lp.done() or mm["status"] == "AWAITING_MANAGER_APPROVAL", 3)
        return mm, lp

    m, loop = await gap_match([41, 41], [sales("₹42/parcel.", 42), sales("Then we walk away.", None, walk_away=True)])
    check("no small gap: ₹1 gap + CRITICAL lesson -> walk honoured, no close-the-gap note",
          m["end_code"] == "sales_walkaway" and not any("gap this small" in p for a, p, s in CALLS if a == "sales"),
          m["end_code"])
    check("no small gap: rule removed from code", not hasattr(N, "SMALL_GAP_RS") and not hasattr(B, "small_gap"))
    await asyncio.gather(*list(B.judge_tasks))

    m, loop = await gap_match([41, 41, 41], [sales("₹42/parcel.", 42), sales("₹42/parcel, final.", 42),
                                             sales("We walk.", None, walk_away=True)])
    check("no small gap: never pushed to accept ₹41", m["end_code"] == "sales_walkaway"
          and 41 not in [p for p in m["sales_offers"] if p is not None], (m["end_code"], m["sales_offers"]))
    await asyncio.gather(*list(B.judge_tasks))

    m, loop = await gap_match([41, 41], [sales("₹42/parcel.", 42), sales("We walk away.", None, walk_away=True)],
                              coach_floor=42)
    check("gap: buyer below the coach's /floor -> walk honoured", m["end_code"] == "sales_walkaway", m["end_code"])
    await asyncio.gather(*list(B.judge_tasks))

    m, loop = await gap_match([40.5, 40.5], [sales("₹42/parcel.", 42), sales("We walk away.", None, walk_away=True)])
    check("gap: ₹1.50 gap -> walk honoured (CRITICAL lesson)", m["end_code"] == "sales_walkaway", m["end_code"])
    await asyncio.gather(*list(B.judge_tasks))
    with sqlite3.connect(TEST_DB) as c:
        c.execute("UPDATE sales_heuristics SET is_critical = 0")

    # Fix 4: deadlock measure notices the buyer
    m = await new()
    m["sales_offers"] = [42] * 5
    m["procurement_offers"] = [41, 41, 41, 41, 42]
    check("fix4: buyer moving up -> no deadlock, no backstop", B.deadlock_facts(m) == "" and not B.deadlock_forced(m))
    m["procurement_offers"] = [41, 42, 42]
    check("fix4: buyer meets price -> no 'not accepted' repeat fact, no forced escalation",
          "has not accepted" not in B.deadlock_facts(m) and not B.deadlock_forced(m), B.deadlock_facts(m))
    m["sales_offers"] = [42] * 10
    check("fix4: 10 messages still a deadlock when she meets the price but terms differ",
          B.deadlock_forced(m) and "10 of your messages" in B.deadlock_facts(m))
    m["sales_offers"] = [42] * 5
    m["procurement_offers"] = [41] * 5
    check("fix4: buyer stuck below -> deadlock as before", "has not accepted" in B.deadlock_facts(m)
          and B.deadlock_forced(m))
    m["procurement_offers"] = [None, None]
    check("fix4: buyer named no rate -> as before", B.deadlock_forced(m))

    # Term-aware price (bench 2026-10-26): his ₹41 tied to 15 months does not "meet" her ₹41 for 12 months
    m = await new()
    m["sales_offers"], m["sales_offer_months"], m["procurement_offers"] = [43, 42, 41], [18, 15, 15], [41]
    check("term: only longer-term offers -> no rate for her term, not 'meets'",
          B.arjun_rate_for_buyer_term(m) is None and not B.buyer_position(m)[1])
    check("term: walk-away then needs authority (not the 'meets' close note)",
          B.walk_block(m, [], set()) == "unauthorised", B.walk_block(m, [], set()))
    m["sales_offers"], m["sales_offer_months"] = [42, 41], [12, 15]
    check("term: compares with his latest 12-month rate (₹42), so her ₹41 does not meet it",
          B.arjun_rate_for_buyer_term(m) == 42 and not B.buyer_position(m)[1])
    m["sales_offers"], m["sales_offer_months"] = [41], [None]
    check("term: unstated term counts as her term", B.buyer_position(m)[1])
    del m["sales_offer_months"]
    check("term: match without the months list behaves as before", B.buyer_position(m)[1])

    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("₹41/parcel.", proposed_price=41), proc("₹41/parcel, 12 months.", proposed_price=41),
                             proc("Fine, ₹42/parcel for 12 months, 30 days. Deal.", proposed_price=42, deal_closed=True)]
    SCRIPT["sales"] = [sales("₹41/parcel if you sign for 15 months.", 41, contract_months=15),
                       sales("Then we walk.", None, walk_away=True),
                       sales("₹42/parcel for 12 months.", 42),
                       sales("Confirmed: ₹42/parcel, 12 months, 30 days. Deal.", 42, deal_closed=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    sales_prompts = [p for a, p, s in CALLS if a == "sales"]
    check("term: offer months recorded per Sales message", m["sales_offer_months"] == [15, 12, 12],
          m["sales_offer_months"])
    check("term: no 'meets your price' note for a 15-month rate",
          not any("meets your price" in p for p in sales_prompts) and m["end_code"] == "deal", m["end_code"])
    await asyncio.gather(*list(B.judge_tasks))
    p_sys, _ = N.build_procurement_system(await db_init.fetch_mandate(), [])
    check("Neha raises payment terms before accepting", "A deal needs price, contract length AND payment terms" in p_sys)

    # "Meets" note once per price position (bench 2026-10-27: it came back every turn -> 30-message cap)
    reset()
    m = await new()
    m["manager_overrides"] = [B.DECISION_HOLD]
    m["sales_posts_since_decision"] = 1
    SCRIPT["procurement"] = [proc("₹41/parcel.", proposed_price=41),
                             proc("OK, ₹42/parcel, but 45-day terms.", proposed_price=42),
                             proc("₹42/parcel with 45-day terms, final.", proposed_price=42)]
    SCRIPT["sales"] = [sales("₹42/parcel, 30 days, final.", 42), sales("Then we walk.", None, walk_away=True),
                       sales("₹42/parcel and 30 days is final.", 42),
                       sales("30 days is final, so we walk away.", None, walk_away=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    meets_prompts = [p for a, p, s in CALLS if a == "sales" and "meets your price" in p]
    check("meets once: same position -> note once, then the authorised walk is honoured",
          m["end_code"] == "sales_walkaway" and len(meets_prompts) == 1, (m["end_code"], len(meets_prompts)))
    check("meets note respects CRITICAL lessons and the manager's decisions",
          meets_prompts and "your CRITICAL lessons and your manager's decisions" in meets_prompts[0])
    await asyncio.gather(*list(B.judge_tasks))

    # Above list price (bench 2026-10-27: "₹48 is my bottom line" on a ₹45 list)
    v, _ = N.check_offer("My bottom line is ₹48/parcel.", {"proposed_price": 48}, tier)
    check("above list: ₹48 on a ₹45 list is blocked with a coach note",
          len(v) == 1 and "above the list price of ₹45/parcel" in v[0] and "list price" in v[0].note, v)
    v, _ = N.check_offer("₹45/parcel.", {"proposed_price": 45}, tier)
    check("above list: the list price itself is allowed", v == [], v)
    check("hold decision: never raise the price", "never raise it" in s_ovr)

    # Internal wording (bench 2026-10-27: "our absolute floor rate of ₹41")
    reset()
    SCRIPT["sales"] = [sales("That is our absolute floor rate of ₹42/parcel.", 42),
                       sales("₹42/parcel is as sharp as we can go.", 42)]
    st = await N.sales_turn([{"role": "procurement", "text": "We ship 1.2M parcels/month."}], [], [], [])
    check("internal words: 'floor' rewritten, no coach note", st.text == "₹42/parcel is as sharp as we can go."
          and not st.coach_notes, st.text)
    check("internal words: rewrite prompt names the word", '"floor"' in [p for a, p, s in CALLS if a == "sales"][1])
    reset()
    SCRIPT["sales"] = [sales("Our guardrails say ₹42/parcel.", 42)] * 3
    st = await N.sales_turn([{"role": "procurement", "text": "We ship 1.2M parcels/month."}], [], [], [])
    # 10-31 lexical kill-switch: a banned word is rejected on every attempt, so it is never posted
    check("banned words: still there on the last attempt -> holding line, never the leak",
          st.fell_back and st.text == N.FALLBACK_SALES_LINE, st.text)
    check("banned words: detector", N.banned_words("our Floor price", "sales") == "Floor"
          and N.banned_words("₹42/parcel with 30-day terms", "sales") is None)

    # Two-sided close, other way round (bench 2026-10-28: Arjun "closed" at 30 days while she demanded 60)
    reset()
    m = await new()
    SCRIPT["procurement"] = [proc("₹41/parcel and 60-day terms.", proposed_price=41),
                             proc("₹42/parcel, but 60-day terms.", proposed_price=42),
                             proc("No. We said 60-day terms, not 30.", proposed_price=42),
                             proc("Fine: ₹42/parcel, 12 months, 30 days. Deal.", proposed_price=42, deal_closed=True)]
    SCRIPT["sales"] = [sales("₹42/parcel.", 42),
                       sales("Great, deal at ₹42/parcel with 30-day terms.", 42, deal_closed=True),
                       sales("₹42/parcel with 30-day terms is final.", 42),
                       sales("Confirmed: ₹42/parcel, 12 months, 30 days.", 42, deal_closed=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    proc_systems = [s for a, p, s in CALLS if a == "procurement"]
    check("seller close: Arjun's 'deal' is not final until Neha confirms; her objection keeps it going",
          m["end_code"] == "deal" and len(m["transcript"]) == 8, (m["end_code"], len(m["transcript"])))
    check("seller close: closing check only in her reply to his close",
          [("CLOSING CHECK" in s) for s in proc_systems] == [False, False, True, False],
          [("CLOSING CHECK" in s) for s in proc_systems])
    await asyncio.gather(*list(B.judge_tasks))

    reset()
    m = await new()
    real_cap, B.MAX_MESSAGES = B.MAX_MESSAGES, 2
    SCRIPT["procurement"] = [proc("₹42/parcel, 12 months, 30 days?", proposed_price=42),
                             proc("Confirmed.", proposed_price=42, deal_closed=True)]
    SCRIPT["sales"] = [sales("Deal: ₹42/parcel, 12 months, 30 days.", 42, deal_closed=True)]
    SCRIPT["judge"] = list(SPARE_JUDGE)
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    B.MAX_MESSAGES = real_cap
    check("seller close on the last allowed message: she still gets to confirm", m["end_code"] == "deal", m["end_code"])
    await asyncio.gather(*list(B.judge_tasks))

    # Digits: Arjun and Neha rewrite prices written in words (never a fallback)
    reset()
    SCRIPT["sales"] = [sales("We can do forty-one rupees per parcel.", 41), sales("We can do ₹41/parcel.", 41)]
    st = await N.sales_turn([{"role": "procurement", "text": "We ship 1.2M parcels/month."}], [], [], [])
    check("digits: Arjun rewrote the words", st.text == "We can do ₹41/parcel." and not st.coach_notes, st.text)
    check("digits: rewrite prompt quotes the words", "forty-one rupees" in [p for a, p, s in CALLS if a == "sales"][1])
    SCRIPT["sales"] = [sales("Forty-one rupees.", 41)] * 3
    st = await N.sales_turn([{"role": "procurement", "text": "We ship 1.2M parcels/month."}], [], [], [])
    check("digits: words on the last attempt are posted, no fallback", st.text == "Forty-one rupees." and not st.fell_back)
    mandate = await db_init.fetch_mandate()
    SCRIPT["procurement"] = [proc("Sixty days and a twelve-month term.", proposed_price=41),
                             proc("60 days and a 12-month term.", proposed_price=41)]
    pt = await N.procurement_turn([], mandate, [])
    check("digits: Neha rewrote the words", pt.text.startswith("60 days") and pt.proposed_price == 41, pt.text)
    s_sys, _ = N.build_sales_system(tiers, tier, 1_200_000, [])
    p_sys, _ = N.build_procurement_system(mandate, [])
    check("digits rule in both prompts", N.DIGITS_RULE in s_sys and N.DIGITS_RULE in p_sys)
    check("Neha's JSON asks for her own rate", '"proposed_price"' in p_sys)

    # ======================================================== Phase B parked
    check("SELF_PLAY off by default", N.SELF_PLAY is False)
    ledger = [
        {"speaker": "Procure_Agent", "payload_text": "x"},
        {"speaker": "Procure_Whisper", "payload_text": "Threaten Blue Dart"},
        {"speaker": "Human_Whisper", "payload_text": "Hold ₹43"},
        {"speaker": "Sales_Escalation", "payload_text": "Q?"},
        {"speaker": "Manager_Decision", "payload_text": "Hold the price"},
    ]
    kinds = [(b.side, b.kind) for b in post_match.context_blocks(ledger)]
    check("Judge skips Procure_Whisper while parked; reads whisper + escalation",
          kinds == [("sales", "whisper"), ("sales", "escalation")], kinds)
    reset()
    m = await new()
    await db_init.upsert_heuristic("procurement", "Price", "pm", "PROC-LESSON")
    m["sales_friction_points"] = ["Price"]
    SCRIPT["procurement"] = [proc("a", deal_closed=True)]
    SCRIPT["sales"] = [sales("Confirmed: ₹43/parcel, 12 months. We have a deal.", 43, deal_closed=True)]
    SCRIPT["judge"] = [DEAL_JSON]
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: loop.done(), 3)
    check("Neha gets no learned lessons while parked", "PROC-LESSON" not in [s for a, p, s in CALLS if a == "procurement"][0])
    await asyncio.gather(*list(B.judge_tasks))
    neha_report = [t for c, t, _ in proc_bot.sent if "Negotiation report" in t]
    check("Neha's report has no lessons section while parked", neha_report and "Playbook changes proposed" not in neha_report[0])

    # no internal terms in chat text
    import re
    texts = [B.ESCALATION_DM, B.ESCALATION_TIMEOUT_DM, B.DECISION_ACK, B.BOARDROOM_CLOSING["sales_walkaway"]]
    check("no internal terms / @ in new chat texts",
          not any(re.search(r"SYSTEM_ERROR|override|escalat|@|JSON", t, re.I) for t in texts))


asyncio.run(main())
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
    sys.exit(1)
