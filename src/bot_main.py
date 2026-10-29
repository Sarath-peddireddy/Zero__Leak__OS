"""
ZeroLeak OS - Telegram Dual-Bot Orchestrator & Simulation Loop.

Runs the Sales bot and the Procurement bot as two python-telegram-bot
Applications polling concurrently in one asyncio event loop.

Chat routing:
  * Boardroom (group)      -> welcome + inline menu (Start / Status / End / Clear). Starting a
                              negotiation registers the match and runs the Procurement <-> Sales loop.
  * Sales War Room (DM)    -> plain text is buffered as a coaching whisper; live 🛑 (offer stopped)
                              and ✅ (guidance applied) notes; deal + coaching report at the end.
  * Procurement War Room   -> DM with the Procurement bot; plain text is buffered as a coaching
                              whisper for Neha (same pending -> standing lifecycle as Sales), ✅ when
                              she applies it, then one report from Neha at the end (see reports.py).
  * /clear (/reset)        -> every chat; asks first, then deletes the chat's history and
                              shows the welcome again (chat_cleaner.py).
  * /end_negotiation, /status -> group or Sales War Room (coaching is only shown in the War Room).
  * /pause, /resume (+ ⏸/▶️ buttons) -> group or either War Room. The loop stops at the next safe
                              point (see next_turn); live pace is unchanged.
  * No "/" menu in the group (it makes Telegram post "/cmd@botname"); both bots answer bare commands.
Each chat gets its own "/" command menu and inline buttons. All chat text is written for
executives: no internal IDs or system terms (those go to the server log).

Telegram bots cannot see each other's messages, so `active_matches` (not
Telegram history) is the source of truth for every match.

Zero-hardcode: the buyer's mandate and both sides' static ammo are read from SQLite
when a match starts and passed into the prompts. Symmetrical JIT: each agent tags its
message (max 2 tags); before the opponent replies, the opponent's master lesson for each
tag is fetched from its own heuristics table (max 2 rules per turn).
"""

import asyncio
import logging
import os
import random
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    Bot, BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import chat_cleaner
import llm_engine
import negotiation
import post_match
import reports
from db_init import fetch_cpq_tiers, fetch_heuristics, fetch_mandate, fetch_static_ammo, init_db, log_message

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # .env lives in the project root

logger = logging.getLogger("zeroleak.bot")

# Every message below is read by executives (Head of Sales, Head of Procurement, CRO) in both
# the group and the DMs: plain business language only, no internal IDs, variables or system terms.
WHISPER_ACK = {
    "sales": "Noted. Arjun will use this at the right moment. Limits apply straight away.",
    "procurement": "Noted. I will use this at the right moment. Limits apply straight away.",
}

GROUP_WELCOME = (
    "🏢 Welcome to the Boardroom\n\n"
    "This is where MegaMart India and SwiftRoute Logistics negotiate a {contract}last-mile freight contract.\n\n"
    "• Neha, Procurement Manager, represents MegaMart India\n"
    "• Arjun, Sales Manager, represents SwiftRoute Logistics\n\n"
    "Tap Start negotiation to begin, and Pause whenever you want time to read or send guidance. "
    "Sales leaders coach Arjun in a personal DM with Arjun, "
    "and the Head of Procurement coaches Neha in a personal DM with Neha."
)
PAUSED_NOTICE = (
    "⏸ Negotiation paused\n\n"
    "Neha and Arjun are holding. Take your time to read, and send guidance in your personal DM with "
    "Arjun or Neha. Tap Resume to continue."
)
RESUMED_NOTICE = "▶️ Negotiation resumed."

# Two-way escalation. The two preset decisions match the Absolute Override rules in negotiation.py.
DECISION_CLOSE = "Close the deal no matter what"
DECISION_HOLD = "Hold the price, if they don't agree, walk away"
ESCALATION_DM = (
    "🙋 Arjun needs your decision\n\n"
    "{question}\n\n"
    "The negotiation is on hold until you answer. Tap an option, or type your own decision here."
)
ESCALATION_TIMEOUT_DM = (
    "No decision came in, so Arjun is continuing on his own within your limits."
)
DECISION_ACK = "Got it. Arjun will act on your decision now: “{decision}”."
APPROVAL_TIMEOUT_S = 15 * 60  # Arjun waits this long for an answer, then continues on his own
# Bot @usernames never appear in chat text: screenshots get shared publicly, and a visible
# username lets anyone message the bots. Refer to them as "a personal DM with Arjun / Neha".
BOARDROOM_OPENING = (
    "🤝 The negotiation has started\n\n"
    "MegaMart India and SwiftRoute Logistics are discussing a {contract}last-mile freight contract. "
    "Neha opens for MegaMart and Arjun responds for SwiftRoute.\n\n"
    "Both teams will receive a full report when it ends."
)
_REPORT_FOLLOWS = " Both teams will receive a full report shortly."
BOARDROOM_CLOSING = {
    "deal": "✅ Agreement reached." + _REPORT_FOLLOWS,
    "walkaway": "The negotiation has ended without agreement." + _REPORT_FOLLOWS,
    "coach": "The negotiation has been closed." + _REPORT_FOLLOWS,
    "cap": "The negotiation has ended without agreement." + _REPORT_FOLLOWS,
    "sales_walkaway": "SwiftRoute has walked away. The negotiation ended without agreement." + _REPORT_FOLLOWS,
    "error": "The negotiation has been paused due to a technical issue. Please start a new one in a few minutes.",
}
SALES_WELCOME = (
    "🎧 {greeting}\n\n"
    "This is your private line to Arjun, SwiftRoute's Sales Manager, while he negotiates with MegaMart India. "
    "Neha and MegaMart never see what you send here.\n\n"
    "How it works\n"
    "• Start a negotiation in the Boardroom group (tap Start negotiation there).\n"
    "• Type guidance here at any time, for example \"Never go below ₹43\" or \"Only give the RTO waiver "
    "for an 18-month contract\". Limits apply immediately; tactics are used when the topic comes up.\n"
    "• /floor 43 sets a minimum price Arjun cannot go below.\n"
    "• ✅ means Arjun applied your guidance. 🛑 means an offer below your floor was stopped before Neha saw it.\n"
    "• 🙋 means Arjun is stuck and needs your decision. The negotiation holds until you answer; "
    "he follows your answer exactly.\n\n"
    "When the negotiation ends you receive a deal report: terms, revenue, margin, missed upside and the "
    "lessons Arjun keeps for next time.\n\n"
    "First time? Add Arjun and Neha to your Boardroom group, and open a personal DM with Neha to coach "
    "her side and receive her reports."
)
PROC_WELCOME = (
    "📋 {greeting}\n\n"
    "I'm Neha, Procurement Manager at MegaMart India. I negotiate our last-mile freight contract with "
    "SwiftRoute Logistics.\n\n"
    "How it works\n"
    "• Type guidance here at any time, for example \"Threaten to move the volume to another carrier\" or "
    "\"Never accept above ₹42\". Limits apply immediately; tactics are used when the topic comes up.\n"
    "• ✅ means I applied your guidance. SwiftRoute never sees what you send here.\n\n"
    "When the negotiation ends I'll send you one report here: the agreed terms, savings against our current "
    "vendor, how the deal compares with our target and walk-away price, open items and the lessons I keep "
    "for next time."
)
CLEAR_CONFIRM = (
    "🧹 Clear this chat?\n\n"
    "Every message from the last 48 hours will be deleted for everyone. This can't be undone."
)
END_LABELS = {  # shown by /status
    "deal": "agreement reached", "walkaway": "MegaMart walked away", "coach": "closed by your team",
    "cap": "session limit reached", "error": "technical issue",
    "sales_walkaway": "SwiftRoute walked away",
}
MAX_MESSAGES = 30              # safety cap per match (Boardroom messages from both agents)
TURN_DELAY_S = (2.0, 3.0)      # pause between agent messages: avoids throttling, simulates typing
LEDGER_SPEAKERS = {"sales": "Sales_Agent", "procurement": "Procure_Agent"}
TELEGRAM_TIMEOUT_S = 20.0      # connect/read/write/pool timeout for Bot API calls
TELEGRAM_RETRY_DELAYS_S = (2.0, 5.0)  # Boardroom posts retried on network blips
STARTUP_RETRY_DELAYS_S = (5.0, 10.0, 20.0, 30.0)  # bot startup retried on network drops
JUDGE_WAIT_FOR_LOOP_S = 60.0   # Judge waits this long for the match loop to stop before reading the ledger
JUDGE_SHUTDOWN_WAIT_S = 90.0   # on shutdown, let running Judge reviews finish

# "/" command menus, per bot, for DMs only. Telegram command names allow only a-z, 0-9 and "_".
# The Boardroom gets NO "/" menu: with two bots in a group, Telegram appends "@botname" to every
# command picked from it. The Boardroom runs on inline buttons instead; bare typed commands
# (/pause, /resume, /status, ...) still work because both bots handle them (see build_apps).
SALES_WAR_ROOM_COMMANDS = [
    BotCommand("start", "Welcome and how coaching works"),
    BotCommand("status", "Progress and your guidance"),
    BotCommand("pause", "Pause the negotiation"),
    BotCommand("resume", "Resume the negotiation"),
    BotCommand("floor", "Set a minimum price, e.g. /floor 43"),
    BotCommand("end_negotiation", "Close the current negotiation"),
    BotCommand("clear", "Clear all messages in this chat"),
]
PROC_WAR_ROOM_COMMANDS = [
    BotCommand("start", "Welcome and how coaching works"),
    BotCommand("status", "Progress and your guidance"),
    BotCommand("pause", "Pause the negotiation"),
    BotCommand("resume", "Resume the negotiation"),
    BotCommand("clear", "Clear all messages in this chat"),
]


def _keyboard(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row]
                                 for row in rows])


BOARDROOM_MENU = _keyboard([("▶️ Start negotiation", "menu:start"), ("📊 Status", "menu:status")],
                           [("⏹ End negotiation", "menu:end"), ("🧹 Clear chat", "menu:clear")])
LIVE_MENU = _keyboard([("⏸ Pause", "menu:pause"), ("📊 Status", "menu:status")],
                      [("⏹ End negotiation", "menu:end")])
PAUSED_MENU = _keyboard([("▶️ Resume", "menu:resume"), ("📊 Status", "menu:status")],
                        [("⏹ End negotiation", "menu:end")])
AFTER_MENU = _keyboard([("▶️ New negotiation", "menu:start"), ("🧹 Clear chat", "menu:clear")])
SALES_DM_MENU = _keyboard([("📊 Status", "menu:status"), ("🧹 Clear chat", "menu:clear")])
PROC_DM_MENU = _keyboard([("📊 Status", "menu:status"), ("🧹 Clear chat", "menu:clear")])
CONFIRM_CLEAR_MENU = _keyboard([("🧹 Yes, clear chat", "clear:yes"), ("Cancel", "clear:no")])
ESCALATION_MENU = _keyboard([("✅ Close the deal no matter what", "esc:close")],
                            [("🛑 Hold the price, walk away if they refuse", "esc:hold")])
STATUS_LABELS = {
    "AWAITING_PROCUREMENT": "🟢 In progress: Neha is responding",
    "AWAITING_SALES": "🟢 In progress: Arjun is responding",
    "AWAITING_MANAGER_APPROVAL": "⏳ On hold: Arjun is consulting his manager",
    "ENDED": "🔴 Closed",
}

# Shared_State: Boardroom group_chat_id -> match state.
active_matches: dict[int, dict] = {}
# Sales War Room DM chat_id -> the Boardroom group_chat_id it coaches.
war_room_to_group: dict[int, int] = {}
# Procurement War Room DM chat_id (DM with the Procurement bot) -> the Boardroom group_chat_id it coaches.
proc_war_room_to_group: dict[int, int] = {}
# Boardroom group_chat_id -> running simulation loop.
match_tasks: dict[int, asyncio.Task] = {}
# Post-match Judge reviews in flight (strong refs so they are not garbage-collected).
judge_tasks: set[asyncio.Task] = set()
# Chat clean-ups in flight (same reason).
ui_tasks: set[asyncio.Task] = set()
# Group command messages already handled, as (chat_id, message_id). Both bots handle Boardroom
# commands, so when both receive the same message only the first one acts.
handled_commands: dict[tuple[int, int], None] = {}
HANDLED_COMMANDS_MAX = 500


def in_background(coro) -> None:
    task = asyncio.create_task(coro)
    ui_tasks.add(task)
    task.add_done_callback(ui_tasks.discard)


def _set_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


def contract_phrase(mandate: dict | None) -> str:
    """'12-month ' from the mandate row, or '' when there is none (chat text only)."""
    return f"{mandate['contract_months']}-month " if mandate else ""


def new_match(sales_war_room_chat_id: int, mandate: dict, sales_ammo: list[dict],
              procurement_ammo: list[dict]) -> dict:
    return {
        "match_id": uuid.uuid4().hex[:12],
        "status": "AWAITING_PROCUREMENT",  # Procurement opens; "AWAITING_SALES" | "ENDED"
        # /pause and /resume. `running` is set while live; the loop waits on it before each turn
        # and holds a freshly generated reply while it is clear (see next_turn).
        "paused": False,
        "running": _set_event(),
        # Bumped on every new whisper (and /floor for Sales). A reply held during a pause is
        # regenerated on resume only if its side got new guidance meanwhile.
        "coaching_rev": {"sales": 0, "procurement": 0},
        "transcript": [],                  # {"role": "sales" | "procurement", "text": str}
        # Read from SQLite once per match (zero-hardcode prompts). Each side only sees its own rows.
        "mandate": mandate,                    # procurement_mandates row (Neha's prompt + reports)
        "sales_ammo": sales_ammo,              # sales_static_ammo rows (Arjun's citable facts)
        "procurement_ammo": procurement_ammo,  # procurement_static_ammo rows (Neha's leverage)
        # {"text": str, "status": "pending_injection" | "standing_policy"}. A whisper is pending until
        # the agent acts on it, then stays in its prompt as a standing guardrail for the whole match.
        "active_coaching_directives": [],       # Sales coach -> Arjun
        "procurement_coaching_directives": [],  # Procurement coach -> Neha
        # Each agent's tags for its latest message (<= 2, negotiation.FRICTION_TAGS). They select the
        # OPPONENT's lessons for the reply: Procurement's tags -> sales_heuristics, and vice versa.
        "procurement_friction_points": [],
        "sales_friction_points": [],
        # Coach's /floor price (₹/parcel) for this match; the CPQ guard enforces it like the rate-card floor.
        "coach_floor": None,
        "sales_war_room_chat_id": sales_war_room_chat_id,
        "procurement_war_room_chat_id": None,
        "end_code": None,             # deal | walkaway | coach | cap | error
        # For the end-of-negotiation reports:
        "sales_offers": [],           # proposed_price of each Sales message (None when no rate)
        "sales_offer_months": [],     # contract length each of those offers was tied to (None = not stated)
        "meets_noted": set(),         # price positions already given the "buyer meets your price" note
        "rto_offered": False,
        "blocked_count": 0,           # drafts stopped by the price check
        "playbook_topics": set(),     # topic tags of past lessons used
        # Two-way escalation (status "AWAITING_MANAGER_APPROVAL" while Arjun waits for an answer).
        "escalations": [],            # {"question": str, "decision": str | None} per escalation
        "manager_overrides": [],      # decisions, injected as Absolute Override Commands for the rest of the match
        "decision_event": asyncio.Event(),  # set when the manager answers (or the match ends)
        "pending_decision": None,     # the manager's answer, picked up by the loop
        "escalation_cooldown": False,  # True for the Sales turn right after a decision: no re-asking
        "deadlock_baseline": 0,       # index into sales_offers where deadlock measuring restarts
        "buyer_closing": False,       # Neha said she accepts; Arjun's next turn must confirm or object
        "seller_closing": False,      # Arjun said he accepts; Neha's next turn must confirm or object
        "sales_posts_since_decision": None,  # Arjun's Boardroom messages since the latest decision
        "procurement_offers": [],     # the rate Neha named in each message (None when none): is she moving?
    }


# ------------------------------------------------------- Simulation loop


async def notify(bot: Bot, chat_id: int | None, text: str, html: bool = False,
                 reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Best-effort side-channel message; a failed notice must not kill the match."""
    if chat_id is None:
        return
    try:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML if html else None,
                               reply_markup=reply_markup)
    except TelegramError:
        logger.warning("Could not notify chat %s", chat_id, exc_info=True)


async def typing(bot: Bot, chat_id: int) -> None:
    """Cosmetic "typing..." indicator; never worth failing a turn over."""
    try:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
    except TelegramError:
        logger.warning("Typing indicator failed for chat %s", chat_id)


async def send_with_retry(bot: Bot, chat_id: int, text: str) -> None:
    """Boardroom posts must land: retry network blips (a rare duplicate beats a dead match)."""
    for delay in (*TELEGRAM_RETRY_DELAYS_S, None):
        try:
            await bot.send_message(chat_id, text)
            return
        except NetworkError as e:  # includes TimedOut; BadRequest subclasses it but won't fix itself
            if isinstance(e, BadRequest) or delay is None:
                raise
            logger.warning("Send to %s failed (%s); retrying in %.0fs.", chat_id, type(e).__name__, delay)
            await asyncio.sleep(delay)


async def post(match: dict, group_id: int, bot: Bot, role: str, text: str) -> None:
    """Broadcast to the Boardroom, then sync the in-memory transcript and the ledger."""
    await send_with_retry(bot, group_id, text)
    match["transcript"].append({"role": role, "text": text})
    await log_message(match["match_id"], LEDGER_SPEAKERS[role], text)


async def finish_match(match: dict, group_id: int, sales_bot: Bot, proc_bot: Bot, code: str) -> None:
    """Close the match (`code` is a BOARDROOM_CLOSING key) and start the debrief in the background."""
    if match["status"] == "ENDED":
        return
    match["status"] = "ENDED"
    match["end_code"] = code
    match["paused"] = False
    match["running"].set()          # wake a paused loop so it can exit
    match["decision_event"].set()   # ...or one waiting for the manager's decision
    logger.info("Match %s ended: %s (%d messages).", match["match_id"], code, len(match["transcript"]))
    await notify(sales_bot, group_id, BOARDROOM_CLOSING[code], reply_markup=AFTER_MENU)
    task = asyncio.create_task(debrief(match, sales_bot, proc_bot, match_tasks.get(group_id)))
    judge_tasks.add(task)
    task.add_done_callback(judge_tasks.discard)


async def debrief(match: dict, sales_bot: Bot, proc_bot: Bot, loop_task: asyncio.Task | None) -> None:
    """End-of-negotiation reports: Neha -> Head of Procurement, deal + coaching report -> Head of Sales.

    The Judge runs first (both sides' whispers), so each report lists the lessons its side keeps.
    """
    if loop_task is not None and not loop_task.done():
        # The loop may still be writing its last ledger row; let it stop first.
        await asyncio.wait([loop_task], timeout=JUDGE_WAIT_FOR_LOOP_S)
    match_id = match["match_id"]
    try:
        tiers = await fetch_cpq_tiers()
        terms = await reports.extract_terms(match)
        try:
            outcomes = await post_match.run_judge_agent(match_id)
        except Exception:
            logger.exception("Judge failed for match %s", match_id)
            outcomes = None
        await notify(proc_bot, match["procurement_war_room_chat_id"],
                     reports.procurement_report(match, terms, tiers, outcomes), html=True)
        await notify(sales_bot, match["sales_war_room_chat_id"],
                     reports.sales_report(match, terms, tiers, outcomes), html=True)
    except Exception:
        logger.exception("Debrief failed for match %s", match_id)
        await notify(sales_bot, match["sales_war_room_chat_id"],
                     "The negotiation has closed, but the report could not be prepared this time.")


async def apply_executed(match: dict, side: str, executed_ids: list[int], bot: Bot, war_room: int | None) -> None:
    """Directives the agent acted on become standing guardrails; tell that side's coach (✅)."""
    key = "active_coaching_directives" if side == "sales" else "procurement_coaching_directives"
    who = "Arjun applied" if side == "sales" else "I applied"
    for i in executed_ids:
        directive = match[key][i]
        directive["status"] = negotiation.STANDING
        await notify(bot, war_room, f"✅ {who} your guidance: “{directive['text']}”. "
                                    f"{'He' if side == 'sales' else 'I'} will hold to it for the rest of the negotiation.")


def escalations_left(match: dict) -> int:
    """How many more times Arjun may ask the manager this turn (0 = escalation not offered)."""
    sales_messages = sum(t["role"] == "sales" for t in match["transcript"])
    if match["escalation_cooldown"] or sales_messages < negotiation.MIN_SALES_MESSAGES_BEFORE_ESCALATION:
        return 0
    return max(0, negotiation.MAX_ESCALATIONS_PER_MATCH - len(match["escalations"]))


DEADLOCK_REPEATS = 3    # same Sales price this many offers in a row (no deal) = deadlock
DEADLOCK_MESSAGES = 8   # or this many Sales messages with no agreement
# Backstop: past these, Arjun MUST escalate (live runs showed the model often "plays it safe"
# and keeps repeating itself instead of asking, so the learning loop never fired).
DEADLOCK_FORCE_REPEATS = 5
DEADLOCK_FORCE_MESSAGES = 10


def _last_priced(offers: list) -> float | None:
    return next((p for p in reversed(offers) if p is not None), None)


def arjun_rate_for_buyer_term(match: dict) -> float | None:
    """Arjun's latest rate that applies to the buyer's contract length (her mandate's term).

    A rate he tied to a LONGER term ("₹41 if you sign for 15 months") is not on offer for her term,
    so it is skipped. Bench 2026-10-26: Neha's ₹41 for 12 months was read as "meets your price"
    against his ₹41-for-15-months, and the system note talked him into closing ₹41 on 12 months.
    """
    mandate = match.get("mandate") or {}
    term = mandate.get("contract_months")
    months = match.get("sales_offer_months", [])
    for i in range(len(match["sales_offers"]) - 1, -1, -1):
        price = match["sales_offers"][i]
        tied = months[i] if i < len(months) else None
        if price is not None and (tied is None or term is None or tied <= term):
            return price
    return None


def buyer_position(match: dict) -> tuple[float | None, bool, bool]:
    """(Neha's latest rate, whether it meets Arjun's rate for her term, whether she just moved up).

    Live 2026-10-26: the deadlock backstop told the manager "the buyer has not accepted" right after
    Neha had moved to Arjun's price, and Arjun later walked away from a buyer who met his price.
    """
    offers = match.get("procurement_offers", [])
    latest = offers[-1] if offers else None
    previous = _last_priced(offers[:-1])
    arjun = arjun_rate_for_buyer_term(match)
    meets = latest is not None and arjun is not None and latest >= arjun
    moving = latest is not None and previous is not None and latest > previous
    return latest, meets, moving


def deadlock_forced(match: dict) -> bool:
    """True when the deadlock is past the backstop thresholds (since the last decision)."""
    _, meets, moving = buyer_position(match)
    if moving:  # the buyer is moving toward Arjun: not a deadlock
        return False
    offers = match["sales_offers"][match["deadlock_baseline"]:]
    priced = [p for p in offers if p is not None]
    repeats = next((i for i, p in enumerate(reversed(priced)) if p != priced[-1]), len(priced)) if priced else 0
    return (repeats >= DEADLOCK_FORCE_REPEATS and not meets) or len(offers) >= DEADLOCK_FORCE_MESSAGES


def deadlock_question(match: dict, facts: str) -> str:
    """The backstop question, when Arjun was required to escalate but did not."""
    last = next((t["text"] for t in reversed(match["transcript"]) if t["role"] == "procurement"), "")
    quote = f" Neha's latest: “{last[:220]}{'…' if len(last) > 220 else ''}”" if last else ""
    facts = deadlock_facts(match, first_person=True) or facts
    return (f"We're deadlocked: {facts}.{quote} Should I close the deal no matter what, "
            "or hold the price and walk away if she refuses?")


def deadlock_facts(match: dict, first_person: bool = False) -> str:
    """A measured deadlock for Arjun's prompt ("you ..."), or for his question to the manager
    (`first_person`: "I ..."); "" if there is none.

    Counted only since the manager's last decision, so holding a price the manager told him to
    hold does not trigger a fresh alert.
    """
    you, your = ("I", "my") if first_person else ("you", "your")
    _, meets, moving = buyer_position(match)
    if moving:  # she just moved toward Arjun's price
        return ""
    offers = match["sales_offers"][match["deadlock_baseline"]:]
    priced = [p for p in offers if p is not None]
    repeats = 0
    for price in reversed(priced):
        if priced and price == priced[-1]:
            repeats += 1
        else:
            break
    facts = []
    if repeats >= DEADLOCK_REPEATS and not meets:  # if she meets his price, the gap is the other terms
        facts.append(f"{you} have offered {negotiation.fmt_rate(priced[-1])}/parcel in {your} last {repeats} offers "
                     "and the buyer has not accepted")
    if len(offers) >= DEADLOCK_MESSAGES:
        facts.append(f"{len(offers)} of {your} messages without an agreement")
    return "; ".join(facts)


async def escalate(match: dict, sales_bot: Bot, question: str) -> bool:
    """Two-way escalation: hold the Boardroom, ask the manager in the Sales War Room, wait for the answer.

    Nothing is posted to the Boardroom. The answer becomes an Absolute Override Command for the rest of
    the match. Both the question and the answer go to the ledger, so the Judge can turn the deadlock
    into a lesson. Returns False if the match ended while waiting.
    """
    match["status"] = "AWAITING_MANAGER_APPROVAL"
    match["pending_decision"] = None
    match["decision_event"].clear()
    entry = {"question": question, "decision": None}
    match["escalations"].append(entry)
    await log_message(match["match_id"], "Sales_Escalation", question)
    logger.info("Match %s: Arjun escalated: %s", match["match_id"], question)
    await notify(sales_bot, match["sales_war_room_chat_id"], ESCALATION_DM.format(question=question),
                 reply_markup=ESCALATION_MENU)

    try:
        await asyncio.wait_for(match["decision_event"].wait(), timeout=APPROVAL_TIMEOUT_S)
    except TimeoutError:
        pass
    if match["status"] == "ENDED":
        return False

    decision = match["pending_decision"]
    if decision:
        entry["decision"] = decision
        match["manager_overrides"].append(decision)
        match["sales_posts_since_decision"] = 0
        await log_message(match["match_id"], "Manager_Decision", decision)
        logger.info("Match %s: manager decided: %s", match["match_id"], decision)
    else:  # no answer in time: Arjun carries on alone, within his limits
        logger.info("Match %s: no manager decision within %.0fs.", match["match_id"], APPROVAL_TIMEOUT_S)
        await notify(sales_bot, match["sales_war_room_chat_id"], ESCALATION_TIMEOUT_DM)
    match["escalation_cooldown"] = True  # his next message must be a reply, not another question
    match["deadlock_baseline"] = len(match["sales_offers"])  # measure any new deadlock from here
    match["status"] = "AWAITING_SALES"
    return True


def is_conditional_walk(decision: str) -> bool:
    """'Hold the price, if they don't agree, walk away' and similar: walk only after the buyer rejects."""
    text = decision.lower()
    return "walk" in text and any(w in text for w in ("if ", "unless", "otherwise"))


def meets_key(match: dict) -> tuple[float | None, float | None]:
    """The price position a "meets your price" note was given for: (her rate, his rate for her term)."""
    return buyer_position(match)[0], arjun_rate_for_buyer_term(match)


def walk_block(match: dict, lessons: list[dict], tried: set[str]) -> str | None:
    """Why Arjun's walk-away cannot be honoured right now, or None if it can.

    "meets": the buyer's latest rate meets his price. He is asked to close instead, once per price
      position: bench 2026-10-27 looped to the message cap when the note came back every turn while the
      open issue was payment terms that his CRITICAL lesson and the manager had both refused;
    "unauthorised": no manager decision and no CRITICAL lesson in play;
    "premature": after "Hold ..., if they don't agree, walk away" he must state final terms first.
    (No "small gap" close: the coach dropped it on 2026-10-27, a ₹1 gap is millions over a contract.)
    """
    if "meets" not in tried and buyer_position(match)[1] and meets_key(match) not in match.get("meets_noted", ()):
        return "meets"
    overrides = match["manager_overrides"]
    if not (overrides or any(h.get("is_critical") for h in lessons)):
        return "unauthorised"
    if overrides and match["sales_posts_since_decision"] == 0 and is_conditional_walk(overrides[-1]):
        return "premature"
    return None


def walk_rewrite_note(match: dict, reason: str) -> str:
    """The one-off SYSTEM NOTE for Arjun's rewrite of a walk-away that cannot be honoured."""
    if reason == "meets":
        return negotiation.BUYER_MEETS_PRICE_LINE.format(
            buyer=negotiation.fmt_rate(buyer_position(match)[0]),
            yours=negotiation.fmt_rate(arjun_rate_for_buyer_term(match)))
    if reason == "premature":
        return negotiation.FINAL_TERMS_FIRST_LINE
    return negotiation.WALK_NOT_AUTHORISED_LINE


def walk_question(match: dict) -> str:
    """Arjun wants to walk away without authority: ask the manager instead (his goodbye is not posted)."""
    last = next((t["text"] for t in reversed(match["transcript"]) if t["role"] == "procurement"), "")
    quote = f" Neha's latest: “{last[:220]}{'…' if len(last) > 220 else ''}”" if last else ""
    facts = deadlock_facts(match, first_person=True)
    why = f" {facts[0].upper()}{facts[1:]}." if facts else ""
    return (f"I'm ready to walk away from this negotiation, but I need your OK first.{why}{quote} "
            "Should I close the deal no matter what, or hold the price and walk away if she refuses?")


def take_decision(match: dict, decision: str) -> None:
    """Hand the manager's answer to the waiting loop."""
    match["pending_decision"] = decision.strip()
    match["decision_event"].set()


async def next_turn(match: dict, side: str, generate):
    """Run `generate()` (one agent turn) around the /pause gate. Returns the turn, or None if the match ended.

    Pause takes effect at the first safe point:
      * before generation: a paused match starts no new turn;
      * after generation, before posting: a reply that was being written when the coach paused is
        held, so nothing new appears in the Boardroom after the pause notice.
    On resume the held reply is posted as is (no extra LLM call), unless its side got new guidance
    during the pause; then it is regenerated so the whisper applies straight away.
    Live matches never wait here: `running` is set, so the waits return immediately.
    """
    while True:
        await match["running"].wait()
        if match["status"] == "ENDED":
            return None
        rev = match["coaching_rev"][side]
        turn = await generate()
        if match["status"] == "ENDED":  # closed mid-generation
            return None
        if match["running"].is_set():
            return turn
        await match["running"].wait()  # paused mid-generation: hold the reply
        if match["status"] == "ENDED":
            return None
        if match["coaching_rev"][side] == rev:
            return turn
        logger.info("Match %s: new %s guidance during the pause; regenerating the held reply.",
                    match["match_id"], side)


async def run_match(group_id: int, sales_bot: Bot, proc_bot: Bot) -> None:
    # Hold this match's dict directly: a new match may replace active_matches[group_id] after ENDED.
    match = active_matches[group_id]
    try:
        while match["status"] != "ENDED":
            # A close Arjun proposed on the last allowed message still gets Neha's confirming reply.
            if len(match["transcript"]) >= MAX_MESSAGES and not match.get("seller_closing"):
                await finish_match(match, group_id, sales_bot, proc_bot, "cap")
                return

            if match["status"] == "AWAITING_PROCUREMENT":
                lessons: list[dict] = []

                async def generate_procurement():
                    await typing(proc_bot, group_id)
                    # Symmetrical JIT: Sales's tags (max 2) select Procurement's master lessons for this turn.
                    # Parked while SELF_PLAY is off: Neha plays without learned lessons (a fixed opponent).
                    friction = match["sales_friction_points"]
                    lessons[:] = await fetch_heuristics("procurement", friction) if negotiation.SELF_PLAY else []
                    return await negotiation.procurement_turn(
                        match["transcript"], match["mandate"], match["procurement_ammo"],
                        match["procurement_coaching_directives"], lessons, friction,
                        seller_closing=match.get("seller_closing", False),
                    )

                turn = await next_turn(match, "procurement", generate_procurement)
                if turn is None:
                    return
                heuristics = lessons
                await post(match, group_id, proc_bot, "procurement", turn.text)
                match["procurement_friction_points"] = turn.friction_points
                match["procurement_offers"].append(turn.proposed_price)
                # Neha's private reasoning stays in the server log; her boss gets one report at the end.
                logger.info("Procurement note: %s | tags: %s | lessons used: %s", turn.internal_note,
                            turn.friction_points, [h["topic_tag"] for h in heuristics])
                await apply_executed(match, "procurement", turn.executed_ids, proc_bot,
                                     match["procurement_war_room_chat_id"])
                if turn.outcome == "buyer walked away":
                    await finish_match(match, group_id, sales_bot, proc_bot, "walkaway")
                    return
                if match.get("seller_closing") and turn.outcome == "deal closed":
                    # Arjun proposed the close and Neha confirmed it: both sides agreed.
                    await finish_match(match, group_id, sales_bot, proc_bot, "deal")
                    return
                if match.get("seller_closing"):
                    logger.info("Match %s: Neha did not confirm Arjun's close; negotiation continues.",
                                match["match_id"])
                match["seller_closing"] = False
                # Two-sided close: Neha's acceptance only counts once Arjun confirms it (she sometimes
                # "accepts" while attaching new conditions). His next turn gets a closing check.
                match["buyer_closing"] = turn.outcome == "deal closed"
                match["status"] = "AWAITING_SALES"
            else:
                lessons = []
                note = {"text": ""}  # one-off SYSTEM NOTE when a walk-away has to be rewritten
                deadlock = deadlock_facts(match)
                must_escalate = bool(deadlock) and deadlock_forced(match) and escalations_left(match) > 0

                async def generate_sales():
                    await typing(sales_bot, group_id)
                    # Symmetrical JIT: Procurement's tags (max 2) select Sales's master lessons for this turn.
                    friction = match["procurement_friction_points"]
                    lessons[:] = await fetch_heuristics("sales", friction)
                    return await negotiation.sales_turn(
                        match["transcript"], match["active_coaching_directives"], lessons, friction,
                        coach_floor=match["coach_floor"], ammo=match["sales_ammo"],
                        overrides=match["manager_overrides"], escalations_left=escalations_left(match),
                        manager=COACH_NAME or "your manager", deadlock=deadlock,
                        buyer_closing=match["buyer_closing"], must_escalate=must_escalate,
                        extra_instruction=note["text"],
                    )

                turn = await next_turn(match, "sales", generate_sales)
                if turn is None:
                    return
                # A walk-away the system cannot honour is never posted (it used to appear in the Boardroom
                # and then be ignored): Arjun asks the manager, or rewrites the message once.
                tried: set[str] = set()
                while turn.walk_away and not turn.escalation:
                    reason = walk_block(match, lessons, tried)
                    if reason is None:
                        break
                    if reason == "unauthorised" and escalations_left(match) > 0:
                        logger.info("Match %s: walk-away needs the manager (%s); asking.", match["match_id"], reason)
                        turn.escalation = walk_question(match)
                        break
                    if reason in tried:  # still walking: post it, the walk does not count
                        logger.warning("Match %s: Sales walk_away ignored after a rewrite (%s).",
                                       match["match_id"], reason)
                        turn.walk_away = False
                        break
                    tried.add(reason)
                    if reason == "meets":  # once per price position, not every turn
                        match.setdefault("meets_noted", set()).add(meets_key(match))
                    logger.info("Match %s: walk-away not honoured (%s); Arjun rewrites.", match["match_id"], reason)
                    note["text"] = walk_rewrite_note(match, reason)
                    turn = await next_turn(match, "sales", generate_sales)
                    if turn is None:
                        return
                note["text"] = ""
                if must_escalate and not (turn.escalation or turn.walk_away or turn.deal_closed):
                    # Backstop: he was required to ask but kept repeating himself. His draft is not
                    # posted; the system asks the manager on his behalf with the measured facts.
                    logger.info("Match %s: deadlock backstop, escalating for Arjun.", match["match_id"])
                    turn.escalation = deadlock_question(match, deadlock)
                if turn.escalation:
                    # Two-way escalation: nothing goes to the Boardroom; ask the manager and wait.
                    if not await escalate(match, sales_bot, turn.escalation):
                        return  # the match ended while waiting
                    continue      # Arjun now writes his Boardroom reply under the decision
                match["escalation_cooldown"] = False
                buyer_accepted = match["buyer_closing"]  # Neha's last message accepted and asked to close
                match["buyer_closing"] = False
                heuristics = lessons
                await post(match, group_id, sales_bot, "sales", turn.text)
                match["sales_friction_points"] = turn.friction_points
                war_room = match["sales_war_room_chat_id"]
                # Facts for the end-of-negotiation report.
                match["sales_offers"].append(turn.proposed_price)
                match["sales_offer_months"].append(turn.contract_months)
                match["rto_offered"] |= turn.offers_rto_waiver
                match["playbook_topics"].update(h["topic_tag"] for h in heuristics)
                match["blocked_count"] += sum(getattr(v, "note", "") not in ("", negotiation.COPY_NOTE)
                                              for v in turn.blocked)  # offers only, not quoted-coaching rewrites
                logger.info("Sales tags: %s | lessons used: %s | guard notes: %s", turn.friction_points,
                            [h["topic_tag"] for h in heuristics], turn.warnings)
                # Live coaching signals only: what was stopped, and which guidance Arjun has applied.
                # (Not named `note`: that is the rewrite-note dict generate_sales() reads.)
                for coach_note in turn.coach_notes:
                    await notify(sales_bot, war_room, f"🛑 {coach_note}")
                await apply_executed(match, "sales", turn.executed_ids, sales_bot, war_room)
                if turn.deal_closed and buyer_accepted:  # he confirmed the close she proposed: both agreed
                    await finish_match(match, group_id, sales_bot, proc_bot, "deal")
                    return
                if turn.deal_closed:
                    # Two-sided close, the other way round (bench 2026-10-28: Arjun "closed" at ₹41 with 30-day
                    # terms while Neha still demanded 60, and the deal was recorded). It only counts once she
                    # confirms; her next turn gets a closing check.
                    match["seller_closing"] = True
                    logger.info("Match %s: Arjun proposes to close; Neha must confirm.", match["match_id"])
                if match["sales_posts_since_decision"] is not None:
                    match["sales_posts_since_decision"] += 1
                if turn.walk_away:  # walk_block() cleared it before posting: authorised and not premature
                    await finish_match(match, group_id, sales_bot, proc_bot, "sales_walkaway")
                    return
                match["status"] = "AWAITING_PROCUREMENT"

            await asyncio.sleep(random.uniform(*TURN_DELAY_S))
    except Exception as e:  # LLMError, TelegramError, ...; CancelledError still propagates on shutdown
        logger.exception("Match %s crashed (%s)", match["match_id"], type(e).__name__)
        await finish_match(match, group_id, sales_bot, proc_bot, "error")
    finally:
        if match_tasks.get(group_id) is asyncio.current_task():
            del match_tasks[group_id]


# ---------------------------------------------------------------- Command routing


def host(context: ContextTypes.DEFAULT_TYPE) -> Bot:
    """The Sales bot hosts the Boardroom: every group notice and menu comes from it, whichever bot
    received the command (so button presses always reach the Sales bot's handlers)."""
    return context.application.bot_data["sales_bot"]


async def respond(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str | None) -> None:
    """Answer a command: in a DM from the bot that was messaged, in the Boardroom from the host bot."""
    if not text:
        return
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text(text)
    else:
        await notify(host(context), chat.id, text)


async def _delete_quietly(message) -> None:
    try:
        await message.delete()
    except TelegramError:  # the bot is not a group admin with "Delete messages": leave it
        pass


def group_command(handler):
    """Wrap a command handler that may run in the Boardroom.

    Both bots handle Boardroom commands: with privacy mode on, Telegram delivers a bare "/pause"
    only to the bot that posted last, which is often Neha's. When both receive the same message,
    only the first acts. The command message is then deleted where the bot is allowed to, so
    the Boardroom stays free of "/command" lines.
    """
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat, message = update.effective_chat, update.effective_message
        if chat.type != ChatType.PRIVATE and message is not None:
            key = (chat.id, message.message_id)
            if key in handled_commands:
                return
            handled_commands[key] = None
            while len(handled_commands) > HANDLED_COMMANDS_MAX:
                handled_commands.pop(next(iter(handled_commands)))
            in_background(_delete_quietly(message))
        await handler(update, context)
    return wrapped


# ---------------------------------------------------------------- Sales bot


async def begin_negotiation(context: ContextTypes.DEFAULT_TYPE, chat, user) -> str | None:
    """Start a negotiation in the Boardroom `chat` coached by `user`. Returns a problem to show, or None."""
    if chat.type == ChatType.PRIVATE:
        return "Negotiations start in the Boardroom group. Tap Start negotiation there."
    existing = active_matches.get(chat.id)
    if existing and existing["status"] != "ENDED":
        return "A negotiation is already in progress. Tap Status to follow it."

    # A user's private chat_id equals their user_id, but the bot can only DM
    # them after they have pressed Start in that DM.
    war_room = user.id
    sales_bot, proc_bot = host(context), context.application.bot_data["proc_bot"]
    try:
        await sales_bot.send_message(
            war_room,
            f"🎧 You're connected to the negotiation in “{chat.title}”.\n"
            "Send guidance for Arjun here at any time. /floor sets a minimum price.",
            reply_markup=SALES_DM_MENU,
        )
    except Forbidden:
        return ("I can't message you privately yet. Open a personal DM with Arjun, tap Start, "
                "then start the negotiation again.")

    # Zero-hardcode: every fact the agents use is read from SQLite here, once per match.
    mandate = await fetch_mandate()
    if mandate is None:
        logger.error("procurement_mandates is empty; cannot start a match.")
        return "The negotiation brief is missing, so the negotiation can't start. Please contact your admin."
    sales_ammo, procurement_ammo = await asyncio.gather(fetch_static_ammo("sales"), fetch_static_ammo("procurement"))
    match = new_match(war_room, mandate, sales_ammo, procurement_ammo)

    if await can_message(proc_bot, war_room):
        # Neha's War Room: coaching for her during the match, her report at the end.
        match["procurement_war_room_chat_id"] = war_room
        proc_war_room_to_group[war_room] = chat.id
        await notify(proc_bot, war_room,
                     f"📋 You're connected to the negotiation in “{chat.title}”.\n"
                     "Send me guidance here at any time.", reply_markup=PROC_DM_MENU)
    else:
        await notify(sales_bot, war_room,
                     "To coach Neha and receive her end-of-negotiation report, open a personal DM with Neha "
                     "and tap Start.")

    active_matches[chat.id] = match
    war_room_to_group[war_room] = chat.id
    logger.info("Match %s registered: boardroom=%s war_room=%s", match["match_id"], chat.id, war_room)
    await notify(sales_bot, chat.id, BOARDROOM_OPENING.format(contract=contract_phrase(mandate)),
                 reply_markup=LIVE_MENU)
    match_tasks[chat.id] = asyncio.create_task(run_match(chat.id, sales_bot, proc_bot))
    return None


async def start_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await respond(update, context, await begin_negotiation(context, update.effective_chat, update.effective_user))


async def can_message(bot: Bot, chat_id: int) -> bool:
    """Whether `bot` may DM this user, checked silently (a brief "typing" hint, no message)."""
    for delay in (*TELEGRAM_RETRY_DELAYS_S, None):
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
            return True
        except Forbidden:  # the user has not pressed Start with this bot
            return False
        except NetworkError as e:
            if isinstance(e, BadRequest) or delay is None:
                logger.warning("Could not check DM access for chat %s", chat_id, exc_info=True)
                return True  # assume reachable; a failed report send is logged, never fatal
            await asyncio.sleep(delay)
        except TelegramError:
            logger.warning("Could not check DM access for chat %s", chat_id, exc_info=True)
            return True
    return True


async def close_negotiation(context: ContextTypes.DEFAULT_TYPE, chat) -> str | None:
    """Close the negotiation this chat belongs to. Returns a line for the person who asked, if any."""
    private = chat.type == ChatType.PRIVATE
    group_id = war_room_to_group.get(chat.id) if private else chat.id
    match = active_matches.get(group_id)
    if not match or match["status"] == "ENDED":
        return "There's no negotiation in progress."
    await finish_match(match, group_id, host(context), context.application.bot_data["proc_bot"], "coach")
    return "Negotiation closed. Your report will follow shortly." if private else None


async def end_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await respond(update, context, await close_negotiation(context, update.effective_chat))


def side_of(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Which War Room a DM belongs to: the Sales bot's DMs coach Arjun, the Procurement bot's coach Neha."""
    return context.application.bot_data.get("side", "sales")


async def set_paused(context: ContextTypes.DEFAULT_TYPE, chat, paused: bool) -> str | None:
    """Pause or resume the negotiation this chat belongs to (Boardroom or either War Room).

    Posts the notice in the Boardroom. Returns a line for the person who asked, if any.
    """
    private = chat.type == ChatType.PRIVATE
    rooms = WHISPER_ROUTES[side_of(context)][0]
    group_id = rooms.get(chat.id) if private else chat.id
    match = active_matches.get(group_id)
    if not match or match["status"] == "ENDED":
        return "There's no negotiation in progress."
    if match["paused"] == paused:
        return "The negotiation is already paused." if paused else "The negotiation isn't paused."
    match["paused"] = paused
    if paused:
        match["running"].clear()
    else:
        match["running"].set()
    logger.info("Match %s %s.", match["match_id"], "paused" if paused else "resumed")
    await notify(host(context), group_id, PAUSED_NOTICE if paused else RESUMED_NOTICE,
                 reply_markup=PAUSED_MENU if paused else LIVE_MENU)
    if not private:
        return None
    return "⏸ Paused. Send your guidance here, then /resume." if paused else "▶️ Resumed."


async def pause_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await respond(update, context, await set_paused(context, update.effective_chat, True))


async def resume_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await respond(update, context, await set_paused(context, update.effective_chat, False))


# Per coached side: (War Room -> Boardroom map, directives key in the match, ledger speaker).
WHISPER_ROUTES = {
    "sales": (war_room_to_group, "active_coaching_directives", "Human_Whisper"),
    "procurement": (proc_war_room_to_group, "procurement_coaching_directives", "Procure_Whisper"),
}


async def _buffer(update: Update, side: str) -> None:
    """A War Room DM -> pending directive for that side's agent. No LLM call (CLAUDE.md §4)."""
    rooms, key, speaker = WHISPER_ROUTES[side]
    match = active_matches.get(rooms.get(update.effective_chat.id))
    if not match or match["status"] == "ENDED":
        await update.message.reply_text(
            "There's no live negotiation to coach. Tap Start negotiation in the Boardroom group to begin."
        )
        return
    text = update.message.text
    if side == "sales" and match["status"] == "AWAITING_MANAGER_APPROVAL":
        # Arjun asked a question: this reply is the decision (an Absolute Override), not a whisper.
        take_decision(match, text)
        await update.message.reply_text(DECISION_ACK.format(decision=text.strip()))
        return
    match[key].append({"text": text, "status": negotiation.PENDING})
    match["coaching_rev"][side] += 1  # a reply held by /pause will be rewritten with this in mind
    await log_message(match["match_id"], speaker, text)  # the Judge learns from it after the match
    await update.message.reply_text(WHISPER_ACK[side])


async def buffer_whisper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sales War Room (DM with the Sales bot)."""
    await _buffer(update, "sales")


async def buffer_proc_whisper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procurement War Room (DM with the Procurement bot)."""
    await _buffer(update, "procurement")


FLOOR_USAGE = "Usage: /floor 43 to block any price below ₹43/parcel this negotiation, or /floor off to clear it."


def parse_price(text: str) -> float | None:
    """'43', '₹43', '43.5/parcel', 'Rs 43' -> float; None if it is not a positive price."""
    cleaned = re.sub(r"₹|rs\.?|inr|/?\s*parcel|,|\s", "", text, flags=re.IGNORECASE)
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if 0 < value < 1000 else None


async def set_floor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/floor <price> in the Sales War Room: a hard minimum price for the current match."""
    chat = update.effective_chat
    if chat.type != ChatType.PRIVATE:
        await update.message.reply_text("Please set the floor privately, in your chat with me.")
        return
    match = active_matches.get(war_room_to_group.get(chat.id))
    if not match or match["status"] == "ENDED":
        await update.message.reply_text(
            "There's no live negotiation. Tap Start negotiation in the Boardroom group to begin."
        )
        return

    arg =" ".join(context.args or []).strip()
    if not arg:
        current = match["coach_floor"]
        status = f"Current floor: ₹{current:g}/parcel." if current is not None else "No floor set."
        await update.message.reply_text(f"{status}\n{FLOOR_USAGE}")
        return
    if arg.lower() in ("off", "clear", "none", "remove"):
        match["coach_floor"] = None
        match["coaching_rev"]["sales"] += 1
        await update.message.reply_text("🔓 Floor removed. The rate-card floor still applies.")
        return
    value = parse_price(arg)
    if value is None:
        await update.message.reply_text(FLOOR_USAGE)
        return

    match["coach_floor"] = value
    match["coaching_rev"]["sales"] += 1
    # Logged as a whisper so the Judge can learn from it like any other coaching.
    await log_message(match["match_id"], "Human_Whisper",
                      f"Hard price floor for this negotiation: never offer below ₹{value:g}/parcel.")
    await update.message.reply_text(
        f"🔒 Floor set to ₹{value:g}/parcel for this negotiation. Any lower offer is blocked (🛑) before "
        "Neha sees it. If this is below the rate-card floor, the rate-card floor still applies."
    )


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await respond(update, context, status_text(update.effective_chat))


async def proc_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(status_text(update.effective_chat, side="procurement"))


def status_text(chat, side: str = "sales") -> str:
    """Match progress. In a War Room (DM) it also lists that side's coaching, and only that side's."""
    war_room = chat.type == ChatType.PRIVATE
    rooms, key, _ = WHISPER_ROUTES[side]
    match = active_matches.get(rooms.get(chat.id) if war_room else chat.id)
    if not match:
        return "No negotiation yet. Tap Start negotiation in the Boardroom group to begin."

    state = STATUS_LABELS[match["status"]]
    if match["paused"] and match["status"] != "ENDED":
        state = "⏸ Paused: tap Resume to continue"
    if match["end_code"]:
        state += f" ({END_LABELS[match['end_code']]})"
    lines = ["Negotiation: MegaMart India and SwiftRoute Logistics", state,
             f"Messages so far: {len(match['transcript'])}"]
    # Coaching is private: each War Room sees only its own side's guidance; the group sees none.
    if war_room:
        directives = match[key]
        pending = [d["text"] for d in directives if d["status"] == negotiation.PENDING]
        standing = [d["text"] for d in directives if d["status"] == negotiation.STANDING]
        lines.append(f"\nYour guidance not yet used: {len(pending)}")
        lines += [f"  • {text}" for text in pending]
        lines.append(f"Applied and in force: {len(standing)}")
        lines += [f"  • {text}" for text in standing]
        if side == "sales" and match["coach_floor"] is not None:
            lines.append(f"🔒 Your floor: {negotiation.fmt_rate(match['coach_floor'])}/parcel")
        if side == "sales" and match["status"] == "AWAITING_MANAGER_APPROVAL" and match["escalations"]:
            lines.append(f"\n🙋 Arjun is waiting for your decision:\n{match['escalations'][-1]['question']}")
        if side == "sales" and match["manager_overrides"]:
            lines.append("Your decisions in force:")
            lines += [f"  • {d}" for d in match["manager_overrides"]]
    return "\n".join(lines)


# Greeting name for the DM welcomes. Set COACH_NAME in .env; Telegram profile names are never used
# (they are often handles or nicknames, and they would show up in shared screenshots).
COACH_NAME = os.getenv("COACH_NAME", "").strip()


def greeting() -> str:
    return f"Welcome, {COACH_NAME}" if COACH_NAME else "Welcome"


async def send_welcome(context: ContextTypes.DEFAULT_TYPE, chat_id: int, private: bool, user=None,
                       procurement: bool = False) -> None:
    """The opening message of each chat, also shown again after /clear."""
    bot = context.bot if procurement or private else host(context)
    if procurement:
        await notify(bot, chat_id, PROC_WELCOME.format(greeting=greeting()), reply_markup=PROC_DM_MENU)
        return
    if private:
        await notify(bot, chat_id, SALES_WELCOME.format(greeting=greeting()), reply_markup=SALES_DM_MENU)
    else:
        welcome = GROUP_WELCOME.format(contract=contract_phrase(await fetch_mandate()))
        await notify(bot, chat_id, welcome, reply_markup=BOARDROOM_MENU)


async def sales_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start, /help and /menu: the Boardroom welcome + menu in the group, the coaching welcome in the DM."""
    chat = update.effective_chat
    await send_welcome(context, chat.id, chat.type == ChatType.PRIVATE, update.effective_user)


async def proc_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_welcome(context, update.effective_chat.id, True, update.effective_user, procurement=True)


# ------------------------------------------------------------ /clear (all chats)


async def ask_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clear or /reset: ask before deleting the chat's history (in the Boardroom, via the host bot)."""
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text(CLEAR_CONFIRM, reply_markup=CONFIRM_CLEAR_MENU)
    else:
        await notify(host(context), chat.id, CLEAR_CONFIRM, reply_markup=CONFIRM_CLEAR_MENU)


async def clear_chat(context: ContextTypes.DEFAULT_TYPE, chat, user, procurement: bool) -> None:
    """Delete the chat's history with every bot that wrote in it, then show the welcome again."""
    try:
        if chat.type == ChatType.PRIVATE:
            await chat_cleaner.wipe_chat(context.bot, chat.id)
        else:
            sales_bot, proc_bot = host(context), context.application.bot_data["proc_bot"]
            delete_all = await chat_cleaner.can_delete_all(sales_bot, chat.id)
            await chat_cleaner.wipe_chat(sales_bot, chat.id, delete_all)
            await chat_cleaner.wipe_chat(proc_bot, chat.id, await chat_cleaner.can_delete_all(proc_bot, chat.id))
            match = active_matches.get(chat.id)
            if match and match["status"] == "ENDED":
                del active_matches[chat.id]  # reset: the next negotiation starts from a clean slate
    except TelegramError:
        logger.warning("Clearing chat %s failed", chat.id, exc_info=True)
    await send_welcome(context, chat.id, chat.type == ChatType.PRIVATE, user, procurement)


async def confirm_clear(update: Update, context: ContextTypes.DEFAULT_TYPE, procurement: bool) -> None:
    query = update.callback_query
    chat = query.message.chat
    if chat.type != ChatType.PRIVATE:
        match = active_matches.get(chat.id)
        if match and match["status"] != "ENDED":
            await query.answer("A negotiation is in progress. Close it first, then clear the chat.", show_alert=True)
            return
        if not await chat_cleaner.can_delete_all(context.bot, chat.id):
            await query.answer(
                "Clearing now. To remove members' messages too, make me a group admin with the "
                "\"Delete messages\" permission.", show_alert=True)
        else:
            await query.answer("Clearing the chat…")
    else:
        await query.answer("Clearing the chat…")
    in_background(clear_chat(context, chat, query.from_user, procurement))


# ------------------------------------------------------------ Buttons


async def sales_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline menu buttons in the Boardroom and the Sales War Room."""
    query = update.callback_query
    chat, data = query.message.chat, query.data
    private = chat.type == ChatType.PRIVATE
    if data == "menu:start":
        problem = await begin_negotiation(context, chat, query.from_user)
        await query.answer(problem or "Starting the negotiation…", show_alert=bool(problem))
    elif data == "menu:status":
        text = status_text(chat)
        if private:
            await query.answer()
            await notify(context.bot, chat.id, text)
        else:  # a private pop-up for whoever tapped, so the Boardroom stays clean
            await query.answer(text[:200], show_alert=True)
    elif data == "menu:end":
        reply = await close_negotiation(context, chat)
        await query.answer(reply or "Negotiation closed.", show_alert=reply == "There's no negotiation in progress.")
    elif data in ("esc:close", "esc:hold"):
        match = active_matches.get(war_room_to_group.get(chat.id)) if private else None
        if not match or match["status"] != "AWAITING_MANAGER_APPROVAL":
            await query.answer("Arjun isn't waiting for a decision right now.", show_alert=True)
            return
        decision = DECISION_CLOSE if data == "esc:close" else DECISION_HOLD
        take_decision(match, decision)
        await query.answer("Decision sent.")
        await notify(context.bot, chat.id, DECISION_ACK.format(decision=decision))
    elif data in ("menu:pause", "menu:resume"):
        paused = data == "menu:pause"
        problem = await set_paused(context, chat, paused)
        if problem and not private:  # pop-up for whoever tapped; the Boardroom notice is already posted otherwise
            await query.answer(problem, show_alert=True)
        else:
            await query.answer("Paused." if paused else "Resumed.")
            if problem:
                await notify(context.bot, chat.id, problem)
    elif data == "menu:clear":
        await query.answer()
        await notify(context.bot, chat.id, CLEAR_CONFIRM, reply_markup=CONFIRM_CLEAR_MENU)
    elif data == "clear:yes":
        await confirm_clear(update, context, procurement=False)
    elif data == "clear:no":
        await query.answer("Cancelled.")
        try:
            await query.message.delete()
        except TelegramError:
            pass
    else:
        await query.answer()


async def proc_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline buttons in the Procurement War Room (status and clearing)."""
    query = update.callback_query
    if query.data == "menu:status":
        await query.answer()
        await notify(context.bot, query.message.chat.id, status_text(query.message.chat, side="procurement"))
    elif query.data == "menu:clear":
        await query.answer()
        await notify(context.bot, query.message.chat.id, CLEAR_CONFIRM, reply_markup=CONFIRM_CLEAR_MENU)
    elif query.data == "clear:yes":
        await confirm_clear(update, context, procurement=True)
    elif query.data == "clear:no":
        await query.answer("Cancelled.")
        try:
            await query.message.delete()
        except TelegramError:
            pass
    else:
        await query.answer()


# ------------------------------------------------------------------ Wiring


async def log_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Handler error for update %s", update, exc_info=context.error)


def _app(token: str) -> Application:
    # PTB's 5s defaults are too tight for this network (Telegram connects have taken ~5s).
    return (
        Application.builder().token(token)
        .connect_timeout(TELEGRAM_TIMEOUT_S).read_timeout(TELEGRAM_TIMEOUT_S)
        .write_timeout(TELEGRAM_TIMEOUT_S).pool_timeout(TELEGRAM_TIMEOUT_S)
        .get_updates_connect_timeout(TELEGRAM_TIMEOUT_S).get_updates_pool_timeout(TELEGRAM_TIMEOUT_S)
        .build()
    )


def build_apps() -> tuple[Application, Application]:
    sales = _app(os.environ["TELEGRAM_SALES_TOKEN"])
    proc = _app(os.environ["TELEGRAM_PROC_TOKEN"])
    for app, side in ((sales, "sales"), (proc, "procurement")):
        app.bot_data.update(sales_bot=sales.bot, proc_bot=proc.bot, side=side)

    private, groups = filters.ChatType.PRIVATE, filters.ChatType.GROUPS
    # Boardroom commands. Old /start_match and /end_match names kept as aliases. Both bots get these
    # (the Procurement bot only for groups) because Telegram delivers a bare group command only to
    # the bot that posted last; group_command() makes sure just one of them acts.
    boardroom = [
        (["start_negotiation", "start_match"], start_match),
        (["end_negotiation", "end_match"], end_match),
        ("status", show_status),
        ("pause", pause_match),
        ("resume", resume_match),
        (["start", "help", "menu"], sales_help),
        (["clear", "reset"], ask_clear),
    ]
    for names, handler in boardroom:
        sales.add_handler(CommandHandler(names, group_command(handler)))  # groups + Sales War Room
        proc.add_handler(CommandHandler(names, group_command(handler), filters=groups))
    sales.add_handler(CommandHandler("floor", set_floor))
    sales.add_handler(CallbackQueryHandler(sales_buttons))
    sales.add_handler(MessageHandler(
        private & filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND, buffer_whisper
    ))
    # Procurement War Room (DM with the Procurement bot).
    proc.add_handler(CommandHandler(["start", "help", "menu"], proc_help, filters=private))
    proc.add_handler(CommandHandler("status", proc_status, filters=private))
    proc.add_handler(CommandHandler("pause", pause_match, filters=private))
    proc.add_handler(CommandHandler("resume", resume_match, filters=private))
    proc.add_handler(CommandHandler(["clear", "reset"], ask_clear, filters=private))
    proc.add_handler(CallbackQueryHandler(proc_buttons))
    proc.add_handler(MessageHandler(
        private & filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND, buffer_proc_whisper
    ))

    for app in (sales, proc):
        app.add_error_handler(log_error)
    return sales, proc


async def publish_command_menus(sales_bot: Bot, proc_bot: Bot) -> None:
    """"/" menus for the DMs only. Groups get none: picking a command from a group menu makes
    Telegram post "/command@botname" in the Boardroom (the Boardroom uses inline buttons)."""
    groups, dms = BotCommandScopeAllGroupChats(), BotCommandScopeAllPrivateChats()
    try:
        await asyncio.gather(
            sales_bot.delete_my_commands(scope=groups),
            sales_bot.set_my_commands(SALES_WAR_ROOM_COMMANDS, scope=dms),
            proc_bot.delete_my_commands(scope=groups),
            proc_bot.set_my_commands(PROC_WAR_ROOM_COMMANDS, scope=dms),
        )
    except TelegramError:  # menus are cosmetic; typed commands still work
        logger.warning("Could not publish command menus", exc_info=True)


async def initialize_with_retry(apps: tuple[Application, Application]) -> None:
    """Connect both bots, riding out short network drops (DNS/connect failures) at startup."""
    for delay in (*STARTUP_RETRY_DELAYS_S, None):
        try:
            await asyncio.gather(*(app.initialize() for app in apps))  # already-initialized apps return at once
            return
        except NetworkError as e:
            if isinstance(e, BadRequest) or delay is None:
                raise
            logger.warning("Telegram unreachable at startup (%s); retrying in %.0fs.", e, delay)
            await asyncio.sleep(delay)


async def run(stop_event: asyncio.Event | None = None) -> None:
    """Start both bots and poll until `stop_event` is set (or the task is cancelled)."""
    await init_db()
    apps = build_apps()
    sales, proc = apps
    try:
        await initialize_with_retry(apps)
        await publish_command_menus(sales.bot, proc.bot)
        await asyncio.gather(*(app.start() for app in apps))
        # In-memory state does not survive restarts, so stale updates are dropped.
        await asyncio.gather(*(app.updater.start_polling(drop_pending_updates=True) for app in apps))
        logger.info("Live: Sales @%s | Procurement @%s", sales.bot.username, proc.bot.username)
        logger.info("Start a match from the Boardroom menu (Start negotiation button or /start_negotiation).")
        await (stop_event or asyncio.Event()).wait()
    finally:
        tasks = list(match_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if judge_tasks:
            logger.info("Waiting for %d Judge review(s) to finish...", len(judge_tasks))
            await asyncio.wait(set(judge_tasks), timeout=JUDGE_SHUTDOWN_WAIT_S)
        await asyncio.gather(*(app.updater.stop() for app in apps if app.updater.running))
        await asyncio.gather(*(app.stop() for app in apps if app.running))
        await asyncio.gather(*(app.shutdown() for app in apps))
        await llm_engine.aclose()
        logger.info("Bots stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai.models").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
