"""Offline tests for /pause, /resume and the Boardroom command routing (fake Gemini + fake Telegram)."""

import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parent.parent
SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))

import db_init  # noqa: E402

TEST_DB = SCRATCH / "pause_test.db"
shutil.copy(SCRATCH / "zeroleak_backup_before_selfplay.db", TEST_DB)
db_init.DB_PATH = TEST_DB

import bot_main as B  # noqa: E402
import llm_engine  # noqa: E402
import negotiation as N  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


CALLS = []
GATES = {}  # agent -> asyncio.Event the next generation waits on (simulates a slow LLM call)
GATED_STARTED = set()
REPLY_N = {"procurement": 0, "sales": 0}


def proc_reply(n, **kw):
    base = dict(message=f"Neha message {n}: we ship 1.2M parcels/month, ₹38/parcel.", internal_note="",
                current_friction_points=["Price"], executed_directive_ids=[], deal_closed=False, walk_away=False)
    base.update(kw)
    return json.dumps(base)


def sales_reply(n, **kw):
    base = dict(message=f"Arjun message {n}: ₹45/parcel.", proposed_price=45, offers_rto_waiver=False,
                contract_months=12, current_friction_points=["Price"], executed_directive_ids=[])
    base.update(kw)
    return json.dumps(base)


DEAL_AFTER = {"value": 99}


async def fake_generate(agent, prompt, system_instruction=None, json_mode=False, temperature=None):
    CALLS.append((agent, system_instruction))
    gate = GATES.pop(agent, None)
    if gate is not None:
        GATED_STARTED.add(agent)  # the gated generation is now really in flight
        await gate.wait()
    if agent == "judge":
        return json.dumps(dict(rate_per_parcel=None, rto_waiver="not_discussed", payment_terms_days=None,
                               contract_months=None, buyer_commitments=[], open_items=[],
                               procurement_summary="", sales_summary="", next_step=""))
    REPLY_N[agent] += 1
    n = REPLY_N[agent]
    if agent == "procurement":
        return proc_reply(n, deal_closed=n >= DEAL_AFTER["value"])
    return sales_reply(n)


llm_engine.generate = fake_generate
N.llm_engine.generate = fake_generate


class FakeBot:
    def __init__(self, name):
        self.name, self.sent, self.commands = name, [], {}

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        TIMELINE.append((chat_id, text))

    async def send_chat_action(self, chat_id, action):
        pass

    async def set_my_commands(self, commands, scope=None):
        self.commands[type(scope).__name__] = [c.command for c in commands]

    async def delete_my_commands(self, scope=None):
        self.commands[type(scope).__name__] = []


class FakeMessage:
    def __init__(self, text, message_id=1):
        self.text, self.message_id, self.replies, self.deleted = text, message_id, [], 0

    async def reply_text(self, text, **kw):
        self.replies.append(text)

    async def delete(self):
        self.deleted += 1


GROUP, COACH = -100, 555
TIMELINE = []  # every message from either bot, in send order
sales_bot, proc_bot = FakeBot("sales"), FakeBot("proc")


def ctx(side="sales"):
    bot = sales_bot if side == "sales" else proc_bot
    return SimpleNamespace(bot=bot, args=[], application=SimpleNamespace(
        bot_data={"sales_bot": sales_bot, "proc_bot": proc_bot, "side": side}))


def chat(private):
    return SimpleNamespace(id=COACH if private else GROUP, type="private" if private else "group", title="Boardroom")


def update(text, private, message_id=1):
    return SimpleNamespace(effective_chat=chat(private), message=FakeMessage(text, message_id),
                           effective_message=None, effective_user=SimpleNamespace(id=COACH))


def boardroom_posts():
    return [t for c, t in TIMELINE if c == GROUP and t.startswith(("Neha message", "Arjun message"))]


async def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            return False
        await asyncio.sleep(0.005)
    return True


async def setup_match():
    mandate = await db_init.fetch_mandate()
    match = B.new_match(COACH, mandate, await db_init.fetch_static_ammo("sales"),
                        await db_init.fetch_static_ammo("procurement"))
    match["procurement_war_room_chat_id"] = COACH
    B.active_matches[GROUP] = match
    B.war_room_to_group[COACH] = GROUP
    B.proc_war_room_to_group[COACH] = GROUP
    return match


B.TURN_DELAY_S_REAL = B.TURN_DELAY_S


async def main():
    await db_init.init_db()
    check("live pace unchanged (2-3s between messages)", B.TURN_DELAY_S == (2.0, 3.0))
    B.TURN_DELAY_S = (0.01, 0.01)

    # ---------- 1. pause mid-generation holds the reply; resume without new guidance posts it as is
    match = await setup_match()
    gate = asyncio.Event()
    GATES["procurement"] = gate
    loop = asyncio.create_task(B.run_match(GROUP, sales_bot, proc_bot))
    B.match_tasks[GROUP] = loop
    await wait_for(lambda: CALLS)
    reply = await B.set_paused(ctx(), chat(False), True)
    check("pause from Boardroom: no extra reply line", reply is None)
    check("pause notice posted with Resume button", any(t == B.PAUSED_NOTICE and m is B.PAUSED_MENU
                                                       for c, t, m in sales_bot.sent if c == GROUP))
    gate.set()  # Neha's reply finishes generating while paused
    await asyncio.sleep(0.1)
    check("held reply NOT posted while paused", boardroom_posts() == [], boardroom_posts())
    check("no new LLM calls while paused", [a for a, _ in CALLS] == ["procurement"], CALLS)
    check("status shows paused", "Paused" in B.status_text(chat(False)))
    check("second pause -> already paused", await B.set_paused(ctx(), chat(False), True) == "The negotiation is already paused.")
    n_calls = len(CALLS)
    await B.set_paused(ctx(), chat(False), False)
    await wait_for(lambda: len(boardroom_posts()) >= 2)
    posts = boardroom_posts()
    check("on resume the held reply is posted first", posts[:1] == ["Neha message 1: we ship 1.2M parcels/month, ₹38/parcel."], posts)
    check("held reply was not regenerated (1 procurement call)", [a for a, _ in CALLS[:n_calls + 1]].count("procurement") == 1)
    check("resume notice with Pause button", any(t == B.RESUMED_NOTICE and m is B.LIVE_MENU for c, t, m in sales_bot.sent))

    # ---------- 2. pause mid-generation + whisper to THAT side -> regenerated with the whisper
    await wait_for(lambda: match["status"] == "AWAITING_PROCUREMENT" or len(boardroom_posts()) >= 3)
    await B.set_paused(ctx(), chat(False), True)
    await asyncio.sleep(0.05)
    # Next turn is gated before generation: nothing new happens.
    before_calls, before_posts = len(CALLS), len(boardroom_posts())
    await asyncio.sleep(0.1)
    check("paused between turns: no generation starts", len(CALLS) == before_calls)
    check("paused between turns: nothing posted", len(boardroom_posts()) == before_posts)
    await B.set_paused(ctx(), chat(False), False)
    await wait_for(lambda: len(CALLS) > before_calls)

    # Now hold a generation for the side that is about to speak, and whisper to it.
    side = "procurement" if match["status"] == "AWAITING_PROCUREMENT" else "sales"
    await wait_for(lambda: True)
    gate = asyncio.Event()
    nxt = "sales" if side == "procurement" else "procurement"
    GATED_STARTED.clear()
    GATES[nxt] = gate
    await wait_for(lambda: nxt in GATED_STARTED, timeout=10)
    await B.set_paused(ctx(), chat(False), True)
    whisper_ctx = ctx(nxt)
    upd = update("Threaten to use Blue Dart right now" if nxt == "procurement" else "Hold ₹44", private=True)
    await (B.buffer_proc_whisper if nxt == "procurement" else B.buffer_whisper)(upd, whisper_ctx)
    gate.set()
    await asyncio.sleep(0.05)
    calls_before_resume = len(CALLS)
    posts_before_resume = len(boardroom_posts())
    await B.set_paused(ctx(), chat(False), False)
    await wait_for(lambda: len(boardroom_posts()) > posts_before_resume)
    regen = CALLS[calls_before_resume:]
    check(f"{nxt} reply held during pause was regenerated after a {nxt} whisper",
          regen and regen[0][0] == nxt and upd.message.text in (regen[0][1] or ""), [a for a, _ in regen])

    # ---------- 3. pause during one side's generation + whisper to the OTHER side -> no regeneration
    gate = asyncio.Event()
    other_turn = "sales" if nxt == "procurement" else "procurement"
    GATED_STARTED.clear()
    GATES[other_turn] = gate
    await wait_for(lambda: other_turn in GATED_STARTED, timeout=10)
    await B.set_paused(ctx(), chat(False), True)
    upd2 = update("Whisper for the side that is NOT speaking", private=True)
    await (B.buffer_whisper if other_turn == "procurement" else B.buffer_proc_whisper)(
        upd2, ctx("sales" if other_turn == "procurement" else "procurement"))
    gate.set()
    await asyncio.sleep(0.05)
    calls_before = len(CALLS)
    await B.set_paused(ctx(), chat(False), False)
    await wait_for(lambda: len(CALLS) > calls_before)
    check("other side's whisper does not regenerate the held reply", CALLS[calls_before][0] != other_turn,
          [a for a, _ in CALLS[calls_before:]])

    # ---------- 4. pause / resume from the War Room DMs
    reply = await B.set_paused(ctx("procurement"), chat(True), True)
    check("pause from Neha's DM works + DM reply", reply and reply.startswith("⏸ Paused") and match["paused"])
    reply = await B.set_paused(ctx("sales"), chat(True), False)
    check("resume from Arjun's DM works", reply == "▶️ Resumed." and not match["paused"])

    # ---------- 5. end while paused: loop exits, debrief runs
    await B.set_paused(ctx(), chat(False), True)
    await asyncio.sleep(0.05)
    await B.close_negotiation(ctx(), chat(False))
    done = await wait_for(lambda: loop.done(), timeout=2)
    check("end while paused: loop exits", done)
    await asyncio.gather(*list(B.judge_tasks))
    check("end while paused: reports sent", any("Deal report" in t for c, t, _ in sales_bot.sent if c == COACH))
    check("pause after end -> no negotiation", await B.set_paused(ctx(), chat(False), True) == "There's no negotiation in progress.")

    # ---------- 6. not paused: the gate adds no delay
    m2 = await setup_match()
    t0 = time.perf_counter()
    turn = await B.next_turn(m2, "sales", lambda: asyncio.sleep(0, result="T"))
    check("next_turn adds no delay when live", turn == "T" and time.perf_counter() - t0 < 0.01)
    m2["status"] = "ENDED"

    # ---------- 7. group command routing: both bots, handled once, command message deleted
    hits = []

    async def handler(u, c):
        hits.append(c.application.bot_data["side"])

    wrapped = B.group_command(handler)
    msg = FakeMessage("/pause", message_id=4242)
    u = SimpleNamespace(effective_chat=chat(False), effective_message=msg, message=msg)
    await wrapped(u, ctx("procurement"))
    await wrapped(u, ctx("sales"))  # same message delivered to the other bot too
    await asyncio.sleep(0.01)
    check("group command handled once across both bots", hits == ["procurement"], hits)
    check("group command message deleted (best effort)", msg.deleted == 1)
    dm = FakeMessage("/pause", message_id=4242)
    await wrapped(SimpleNamespace(effective_chat=chat(True), effective_message=dm, message=dm), ctx("sales"))
    check("DM commands not deduped or deleted", hits == ["procurement", "sales"] and dm.deleted == 0)

    # Replies to group commands always come from the host (Sales) bot.
    sales_bot.sent.clear(); proc_bot.sent.clear()
    await B.show_status(update("/status", private=False), ctx("procurement"))
    check("group /status via Procurement bot -> answered by host bot", sales_bot.sent and not proc_bot.sent)

    # ---------- 8. menus: no "/" menu in groups (no @botname), DM menus have pause/resume
    await B.publish_command_menus(sales_bot, proc_bot)
    check("no group '/' menu for either bot",
          sales_bot.commands.get("BotCommandScopeAllGroupChats") == [] and
          proc_bot.commands.get("BotCommandScopeAllGroupChats") == [])
    for bot in (sales_bot, proc_bot):
        dms = bot.commands.get("BotCommandScopeAllPrivateChats", [])
        check(f"{bot.name} DM menu has pause + resume", "pause" in dms and "resume" in dms, dms)

    # ---------- 9. handler wiring (needs no network)
    import os
    os.environ.setdefault("TELEGRAM_SALES_TOKEN", "1:x")
    sales_app, proc_app = B.build_apps()

    def commands(app, chat_filter=None):
        out = set()
        for h in app.handlers[0]:
            if hasattr(h, "commands"):
                out |= set(h.commands)
        return out
    check("Sales bot handles pause/resume", {"pause", "resume"} <= commands(sales_app))
    check("Procurement bot handles Boardroom commands too",
          {"pause", "resume", "status", "start_negotiation", "end_negotiation"} <= commands(proc_app))

    # ---------- 10. no @ / internal terms in new chat text
    texts = [B.PAUSED_NOTICE, B.RESUMED_NOTICE, B.GROUP_WELCOME]
    check("no @ in pause texts / welcome", not any("@" in t for t in texts))
    all_sent = [t for c, t, _ in sales_bot.sent + proc_bot.sent]
    check("no @ in anything the bots sent", not any("@" in t for t in all_sent))


asyncio.run(main())
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
    sys.exit(1)
