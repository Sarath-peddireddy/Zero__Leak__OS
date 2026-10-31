"""
ZeroLeak OS - Judge Agent & memory compaction (the RLHF loop), for both sides.

After a match ends, `run_judge_agent(match_id)`:
  1. Data prep:  reads the match from the match_transcripts ledger. For every
                 whisper it takes the 3 Boardroom messages just before it (the
                 Context_Block). Human_Whisper rows coached Sales; Procure_Whisper
                 rows coached Procurement.
  2. Synthesis:  the Judge LLM (judge key = GEMINI_API_KEY, JSON mode) turns each
                 Context_Block + whisper into a lesson for that side:
                 {topic_tag, past_mistake, new_directive}.
                 Reward-model separation: Arjun is audited by the "VP of Sales at
                 SwiftRoute" (margin, floor, long-term value) and his lessons go to
                 sales_heuristics; Neha by the "Head of Global Sourcing at MegaMart"
                 (squeeze margin, anchor low, cut cost) into procurement_heuristics.
                 The merge call uses the same side's persona.
  3. Compaction ("Highlander"): topic_tag is UNIQUE in the side's heuristics table,
                 so there is one master rule per topic. If a rule for the tag already
                 exists, one fast merge call folds the new lesson into it (the newest
                 coaching wins where they conflict).
  4. Staging gate (HITL, 2026-10-31): the Judge NEVER writes a live playbook. Every
                 change (new topic, merge, CRITICAL escalation lesson) is staged in
                 pending_lessons; the agents keep using the live rule. After the match
                 reports, review_proposals() shadow-tests each proposal (shadow_test.py:
                 headless matches with vs without it) and sends the manager one 🧠
                 approval request per proposal with the result. Only ✅ Approve writes
                 the rule (INSERT ... ON CONFLICT(topic_tag) DO UPDATE, db_init.resolve_pending).
                 Memory regression (a good rule overwritten by a worse one) therefore
                 needs a human's explicit OK, with evidence in front of them.

Escalations (two-way HITL): every Manager_Decision row (the manager's answer to a
Sales_Escalation) is judged with the question, the 3 Boardroom messages before it and
the 2 after it, and staged as a CRITICAL lesson (is_critical = 1) for sales_heuristics,
so Arjun can break the same deadlock himself next time. Procure_Decision rows (Neha's
escalations, 2026-10-31) do the same for procurement_heuristics while SELF_PLAY is on.

Phase B is parked (negotiation.SELF_PLAY off): Procure_Whisper rows are not judged.

bot_main.py reads the lessons back before every turn: each agent's friction tags
select the opponent's master lessons (max 2) for the reply (JIT retrieval).

Usage:
    python post_match.py <match_id>     # judge one match from the ledger
    python post_match.py --playbook     # print both playbooks
"""

import asyncio
import html
import json
import logging
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import llm_engine
import shadow_test
from db_init import (HEURISTICS_TABLES, SIDES, fetch_heuristic, fetch_heuristics, fetch_ledger, fetch_pending,
                     init_db, save_pending, update_pending)
from negotiation import FRICTION_TAGS, SELF_PLAY, SPEAKER_NAMES, normalize_friction_points

logger = logging.getLogger("zeroleak.judge")

# (side, html_text, pending_id or None) -> sends to that side's War Room (with ✅ / ❌ buttons when pending)
Notify = Callable[[str, str, int | None], Awaitable[None]]

CONTEXT_MESSAGES = 3      # Boardroom messages before each whisper
MAX_JSON_ATTEMPTS = 2
JUDGE_TEMPERATURE = 0.2
RULE_FIELDS = ("past_mistake", "new_directive")
BOARDROOM_LABELS = {"Sales_Agent": SPEAKER_NAMES["sales"], "Procure_Agent": SPEAKER_NAMES["procurement"]}
WHISPER_SIDES = {"Human_Whisper": "sales", "Procure_Whisper": "procurement"}  # ledger speaker -> coached side

_TAG_RULE = """\
Choose topic_tag by what the manager's whisper is about (the concession or behaviour it governs), \
not by what the other side happened to be discussing when it was sent. Example: a whisper about the \
RTO waiver is "RTO", even if the conversation was about price at that moment. Keep every concrete \
number and condition from the whisper in new_directive."""

_JUDGE_FORMAT = """\
Output JSON strictly in this format:
{"lessons": [
  {
    "scope": "standing | this_deal | none",
    "topic_tag": "Must be one of: """ + ", ".join(FRICTION_TAGS) + """, Other",
    "past_mistake": "Exactly what the agent did wrong or was about to do.",
    "new_directive": "The hard rule the agent must follow next time this topic arises."
  }
]}
Usually one lesson. If the note clearly covers two different topics (e.g. "cite our fleet when she worries \
about peak season, and never offer the RTO waiver on 12 months"), give two lessons, one per topic, each with \
only its own part of the note. Never more than 2.
Tech_Integration: API, tracking, systems integration. Communication_Tone: how to talk (tone, style, manner).
scope: "standing" by default: any instruction about what to do, say, offer or refuse is standing, even if it \
names a price or sounds specific (e.g. "Hold ₹43 on 12 months", "mention our API integration when she asks \
about tracking"). "this_deal" ONLY when the note itself explicitly limits itself to this negotiation (words like \
"in this deal", "this time", "today only", "one-time exception"). A correction of an earlier instruction \
("actually ₹42 is fine", "instead, offer 45 days") is standing: it replaces the earlier rule. "none" ONLY when the note contains no \
instruction at all (praise or encouragement like "good job", "keep going", an acknowledgement, a bare number). \
Never invent a rule the note does not state.
topic_tag "Other" if the note is about none of the listed topics (e.g. fuel surcharges): do not force it into Price."""

# One-off filter (2026-10-31, user text verbatim + how to say it in the JSON): after Neha's manager answered
# "close the deal no matter what", the Judge proposed a permanent rule that dropped her price ceiling.
_ONE_OFF_RULE = """\
Distinguish between repeatable negotiation tactics and one-time business exceptions. If a manager overrides \
the agent just to force a deal closed (e.g., 'close no matter what'), DO NOT create a permanent playbook rule \
that drops the agent's mathematical limits. Only create heuristics for tactical negotiation flaws.
In that case set "scope" to "this_deal" for the exception itself. If the same event also exposed a tactical \
flaw (e.g. the agent never traded payment terms before deadlocking), you may give that tactic as a \
"standing" lesson, but it must keep every price, ceiling, floor and limit exactly as it was. A decision to \
hold firm and walk away if refused is a repeatable tactic: "standing"."""

# Reward-model separation: each side is audited by its OWN boss, with opposite goals, so a lesson
# written for one agent never carries the other side's interests (needed before self-play).
JUDGE_PERSONAS = {
    "sales": """\
You are the VP of Sales at SwiftRoute Logistics. You are auditing a negotiation that your Account \
Executive, Arjun, ran against MegaMart India's procurement team. Your strict goal is to maximize \
SwiftRoute's margin, defend the price floor, and extract long-term value (longer contracts, committed \
volume, faster payment) in return for every concession. You judge Arjun only by SwiftRoute's interests: \
a concession given cheaply, too early or for nothing is a mistake, even if it pleased the buyer.""",
    "procurement": """\
You are the Head of Global Sourcing at MegaMart India. You are auditing a negotiation that your \
Procurement Manager, Neha, ran against SwiftRoute Logistics' sales team. Your strict goal is to squeeze \
the vendor's margin, anchor low, and minimize MegaMart's total cost (the rate, RTO penalties, payment \
terms and lock-in). You judge Neha only by MegaMart's interests: accepting a price too early, revealing \
budget headroom, or trading away leverage for nothing is a mistake, even if it kept the vendor happy.""",
}

JUDGE_SYSTEM = {
    "sales": f"""\
{JUDGE_PERSONAS["sales"]}
Look at the context and your manager's whisper to Arjun. Identify the mistake Arjun was making that \
required the intervention, and write the rule that protects SwiftRoute's margin next time.
{_JUDGE_FORMAT}
{_TAG_RULE}
{_ONE_OFF_RULE}""",
    "procurement": f"""\
{JUDGE_PERSONAS["procurement"]}
Look at the context and the coach's whisper to Neha. Identify the mistake Neha was making that \
required the intervention, and write the rule that cuts MegaMart's cost next time.
{_JUDGE_FORMAT}
{_TAG_RULE}
{_ONE_OFF_RULE}""",
}

# Fourth-Wall Watchdog (2026-10-31; replaces the Python word-list kill-switch): once per side per match, the
# side's own Judge reads EVERY Boardroom message that agent wrote. A slip into internal vocabulary becomes a
# Communication_Tone proposal (that topic is loaded on every turn, so the rule is always in front of the agent).
# Not is_critical: a CRITICAL lesson in play authorises Arjun's walk-aways (bot_main.walk_block).
WATCHDOG_TAG = "Communication_Tone"
AGENT_SPEAKERS = {"sales": "Sales_Agent", "procurement": "Procure_Agent"}
_WATCHDOG_RULE = """\
You are also a strict Fourth-Wall Watchdog. Scan the transcript to see if the agent ever used internal system \
vocabulary (e.g., 'playbook', 'override', 'instruction', 'backend', 'guardrail', 'prompt'). If they did, you \
MUST extract a high-priority heuristic instructing them to act as a human and never use internal simulation \
vocabulary again. Format this as a strict one-shot rule.
Internal vocabulary means talking about how the agent is run: a playbook, lessons, rules or guardrails it was \
given, overrides, instructions or directives, prompts, the backend or "the system", a floor price, or what its \
manager told or decided. Ordinary business language is NOT a slip: "prompt payment", "our tracking system", \
"critical for the festive season", "a dedicated account manager", "let me check internally". Judge the meaning, \
not the word.
Output JSON strictly in this format:
{
  "violation": true or false,
  "evidence": "the agent's exact words that broke the fourth wall ('' if none)",
  "past_mistake": "what the agent said and why it gave the game away ('' if none)",
  "new_directive": "one strict rule plus ONE example (one-shot): 'Speak only as yourself, a human negotiator; \
never mention <the vocabulary used>. Example: instead of \\"<the slip>\\", say \\"<the same move in plain \
business words>\\".' ('' if none)"
}"""
WATCHDOG_SYSTEM = {
    "sales": f"""\
{JUDGE_PERSONAS["sales"]}
You are given every Boardroom message Arjun wrote in this negotiation. A buyer who learns that Arjun is \
coached or scripted gains leverage over SwiftRoute.
{_WATCHDOG_RULE}""",
    "procurement": f"""\
{JUDGE_PERSONAS["procurement"]}
You are given every Boardroom message Neha wrote in this negotiation. A vendor who learns that Neha is \
coached or scripted gains leverage over MegaMart.
{_WATCHDOG_RULE}""",
}

# Step 4 of the two-way escalation: a deadlock the manager had to break becomes a CRITICAL lesson,
# written so Arjun can break the same deadlock himself next time without asking.
ESCALATION_JUDGE_SYSTEM = f"""\
{JUDGE_PERSONAS["sales"]}
In this negotiation Arjun got stuck and escalated to his manager instead of replying to the buyer. You are given the Boardroom \
messages before the escalation, Arjun's question, the manager's decision, and what happened right after.
Write the CRITICAL lesson that lets Arjun break this kind of deadlock on his own next time, without \
asking: turn the manager's decision into a general rule (unless it is a one-time business exception, see \
below). State the trigger (what the buyer did: the \
price, terms or threat that caused the deadlock) and the exact action to take (keep every number and \
condition from the decision).
{_JUDGE_FORMAT}
past_mistake: describe the deadlock Arjun could not resolve alone (e.g. "Froze and asked for help when \
the buyer demanded ₹41 and threatened to walk on a 12-month term").
new_directive: the decision as a standing rule (e.g. "When the buyer demands ₹41 and threatens to walk \
on 12 months, state ₹43 as final; if rejected, walk away.").
Choose topic_tag by what the decision governs (usually Price, Contract_Length, RTO or Payment_Terms).
{_ONE_OFF_RULE}"""
AFTER_MESSAGES = 2  # Boardroom messages after the decision, to show the Judge how it played out

# Neha's escalations (2026-10-31), judged by her own boss (reward-model separation). Only with SELF_PLAY.
PROCUREMENT_ESCALATION_JUDGE_SYSTEM = f"""\
{JUDGE_PERSONAS["procurement"]}
In this negotiation Neha got stuck and escalated to her manager instead of replying to SwiftRoute. You are given \
the Boardroom messages before the escalation, Neha's question, the manager's decision, and what happened right after.
Write the CRITICAL lesson that lets Neha break this kind of deadlock on her own next time, without asking: turn \
the manager's decision into a general rule (unless it is a one-time business exception, see below). State the \
trigger (what SwiftRoute did: the price, terms or threat that caused the deadlock) and the exact action to take \
(keep every number and condition from the decision).
{_JUDGE_FORMAT}
past_mistake: describe the deadlock Neha could not resolve alone.
new_directive: the decision as a standing rule.
Choose topic_tag by what the decision governs (usually Price, Contract_Length, RTO or Payment_Terms).
{_ONE_OFF_RULE}"""
ESCALATION_SPEAKERS = {"Manager_Decision": ("sales", "Sales_Escalation"),
                       "Procure_Decision": ("procurement", "Procure_Escalation")}  # decision -> (side, question)

MERGE_SYSTEM = """\
{persona}
You maintain your team's negotiation playbook for the {agent}. It holds exactly ONE master rule per topic. \
Merge the NEW lesson into the EXISTING master rule for this topic, producing one rule that replaces it.
- Keep every concrete number, term and condition from both (prices, contract lengths, payment days, \
what is traded for what).
- Where they conflict, the NEW lesson wins: it is the manager's latest instruction. Drop the part of the \
existing rule it contradicts.
- NUMBERS (prices, months, days): change a number in the existing rule ONLY if the MANAGER'S NOTE sets a \
new value for that SAME condition (existing "RTO only for 18 months" + note "RTO only for 24 months" -> 24). \
If the note's number belongs to a different condition, keep the existing number exactly and add the note \
as an extra condition (existing "below ₹42 only for 18 months" + note "if she offers more volume, ask for \
24 months first" -> "below ₹42 only for 18 months; if she offers more volume, ask for 24 months first").
- Keep every clause of the existing rule unless the new lesson explicitly replaces it. Be concise, but never \
drop a condition just to save words (aim for under 100 words). No duplicated ideas. Do not copy conversational \
words from the note ("actually", "great") into the rule.
Output JSON strictly in this format:
{{
  "similarity": <0-100, how semantically similar the NEW lesson is to the EXISTING rule>,
  "past_mistake": "...",
  "new_directive": "..."
}}"""
MERGE_AGENTS = {"sales": "Sales Agent (SwiftRoute)", "procurement": "Procurement Agent (MegaMart)"}

# One compaction at a time per playbook: the read-merge-write of a topic must not interleave
# with another Judge run (two matches ending together).
_compaction_locks = {side: asyncio.Lock() for side in SIDES}


@dataclass
class JudgeOutcome:
    whisper: str                # the whisper, or the manager's decision for an escalation
    action: str                 # "proposed" (staged for the coach's OK) | "unchanged" | "skipped"
    side: str = "sales"         # whose playbook: "sales" | "procurement"
    topic_tag: str | None = None
    heuristic_id: int | None = None  # proposed: the pending_id; unchanged: the live rule's (or open proposal's) id
    similarity: int | None = None
    reason: str = ""            # skipped: SKIP_REASONS key / error; proposed: risk warnings; unchanged: OPEN_PROPOSAL
    directive: str = ""         # the proposed new_directive (merged text when the topic had a rule)
    previous: str = ""          # the live rule's new_directive when proposed ('' = new topic)
    kind: str = "whisper"       # "whisper" | "escalation" (a CRITICAL deadlock lesson) | "watchdog" (fourth wall)


@dataclass
class Block:
    """One coaching event for the Judge."""
    side: str
    text: str                   # whisper text, or the manager's decision
    before: list[dict]          # Boardroom rows before it
    kind: str = "whisper"       # "whisper" | "escalation"
    question: str = ""          # escalation only: what Arjun asked
    after: list[dict] | None = None  # escalation only: Boardroom rows right after the decision


# ---------------------------------------------------------------- Data prep


# Start-of-match initialization notes (2026-10-31): the test setup note "Don't go above ₹41. Insist on 12 months
# and 60-day payment terms… never walk away" became a standing Neha lesson and later merged away her ceiling.
# Setup notes are logged with this prefix (bot_main.add_whisper(setup=True)), and any note sent before the
# first Boardroom message is a briefing too: there is no agent behaviour yet for the Judge to learn from.
SETUP_NOTE_PREFIX = "[setup] "


def is_setup_note(payload: str, before: list[dict]) -> bool:
    """True for initialization context the Judge must not learn from."""
    return payload.startswith(SETUP_NOTE_PREFIX) or not before


def context_blocks(ledger: list[dict]) -> list[Block]:
    """Every coaching event in ledger order: whispers (with the CONTEXT_MESSAGES Boardroom rows before
    them) and escalations answered by the manager (question + decision + rows before and after).

    Procurement whispers are left out while SELF_PLAY is parked. An escalation with no decision
    (timeout) teaches nothing, so it is skipped.
    """
    blocks = []
    for i, row in enumerate(ledger):
        speaker = row["speaker"]
        before = [r for r in ledger[:i] if r["speaker"] in BOARDROOM_LABELS][-CONTEXT_MESSAGES:]
        if speaker in WHISPER_SIDES:
            side = WHISPER_SIDES[speaker]
            if side == "procurement" and not SELF_PLAY:
                continue
            if is_setup_note(row["payload_text"], before):
                continue  # initialization context, not a correction of something the agent did
            blocks.append(Block(side, row["payload_text"], before))
        elif speaker in ESCALATION_SPEAKERS:
            side, question_speaker = ESCALATION_SPEAKERS[speaker]
            if side == "procurement" and not SELF_PLAY:
                continue
            asked = [r for r in ledger[:i] if r["speaker"] == question_speaker]
            after = [r for r in ledger[i + 1:] if r["speaker"] in BOARDROOM_LABELS][:AFTER_MESSAGES]
            blocks.append(Block(side, row["payload_text"], before, "escalation",
                                asked[-1]["payload_text"] if asked else "", after))
    return blocks


def _render_context(rows: list[dict]) -> str:
    if not rows:
        return "(the whisper came before any Boardroom message)"
    return "\n".join(f"{BOARDROOM_LABELS[r['speaker']]}: {r['payload_text']}" for r in rows)


# ---------------------------------------------------------------- LLM calls


async def _judge_json(prompt: str, system: str) -> dict:
    for attempt in range(1, MAX_JSON_ATTEMPTS + 1):
        raw = await llm_engine.generate("judge", prompt, system, json_mode=True, temperature=JUDGE_TEMPERATURE)
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
        logger.warning("Judge returned invalid JSON (attempt %d): %.200s", attempt, raw)
    raise ValueError("Judge kept returning invalid JSON")


def _clean_rule(data) -> dict | None:
    """The rule fields as stripped non-empty strings, or None if any is missing."""
    if not isinstance(data, dict):
        return None
    rule = {f: data.get(f).strip() for f in RULE_FIELDS if isinstance(data.get(f), str)}
    return rule if len(rule) == len(RULE_FIELDS) and all(rule.values()) else None


MAX_LESSONS_PER_NOTE = 2


async def synthesize(block: Block) -> list[tuple[str, dict]]:
    """Judge one coaching event: returns [(topic_tag, rule)] (two when the note covers two topics).
    Raises Skip when no lesson should be saved, ValueError on unusable output."""
    if block.kind == "escalation":
        name, their = ("Arjun", "his") if block.side == "sales" else ("Neha", "her")
        prompt = (
            f"BEFORE (the last {len(block.before)} Boardroom messages before {name} escalated):\n"
            f"{_render_context(block.before)}\n\n"
            f'{name.upper()}\'S ESCALATION to {their} manager: "{block.question}"\n'
            f'MANAGER\'S DECISION (obeyed as an absolute command): "{block.text}"\n\n'
            f"AFTER (what happened next):\n"
            f"{_render_context(block.after) if block.after else '(the negotiation ended right after)'}"
        )
        system = ESCALATION_JUDGE_SYSTEM if block.side == "sales" else PROCUREMENT_ESCALATION_JUDGE_SYSTEM
    else:
        agent = "Sales Agent" if block.side == "sales" else "Procurement Agent"
        prompt = (
            f"CONTEXT (the last {len(block.before)} Boardroom messages before the whisper):\n"
            f"{_render_context(block.before)}\n\n"
            f'MANAGER\'S WHISPER to the {agent}: "{block.text}"'
        )
        system = JUDGE_SYSTEM[block.side]
    data = await _judge_json(prompt, system)
    items = data.get("lessons") if isinstance(data.get("lessons"), list) else [data]  # old single-lesson shape
    lessons, skips = [], []
    for item in items[:MAX_LESSONS_PER_NOTE]:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope") or "standing").strip().lower()
        if scope == "none":
            skips.append("no_lesson")
            continue
        # Decisions are generalised by default, but since 10-31 a one-time exception ("close no matter
        # what") is not: the escalation prompts say when to mark it this_deal (_ONE_OFF_RULE).
        if scope == "this_deal":
            skips.append("one_off")
            continue
        if str(item.get("topic_tag") or "").strip().lower() == "other":
            skips.append("no_topic")
            continue
        tags = normalize_friction_points([item.get("topic_tag")])
        rule = _clean_rule(item)
        if tags and rule is not None and all(t != tags[0] for t, _ in lessons):
            lessons.append((tags[0], rule))
    if lessons:
        return lessons
    if skips:
        raise Skip(skips[0])
    raise ValueError(f"Judge output missing a valid topic_tag or rule fields: {data}")


async def fourth_wall_audit(side: str, ledger: list[dict]) -> tuple[str, dict] | None:
    """The Fourth-Wall Watchdog for one side: (evidence, rule) when the agent's Boardroom messages used internal
    vocabulary, else None (also when the agent wrote nothing). Raises ValueError on an unusable verdict."""
    rows = [r for r in ledger if r["speaker"] == AGENT_SPEAKERS[side]]
    if not rows:
        return None
    name = SPEAKER_NAMES[side].split(" ")[0]
    prompt = (f"EVERY BOARDROOM MESSAGE {name.upper()} WROTE IN THIS NEGOTIATION:\n"
              + "\n".join(f"{i}. {r['payload_text']}" for i, r in enumerate(rows, 1)))
    data = await _judge_json(prompt, WATCHDOG_SYSTEM[side])
    if data.get("violation") is not True:
        return None
    rule = _clean_rule(data)
    if rule is None:
        raise ValueError(f"Watchdog found a slip but gave no usable rule: {data}")
    return str(data.get("evidence") or "").strip(), rule


# ---------------------------------------------------------------- Screening (2026-10-30 failure tests)
# Live + probe results: "43" wiped CRITICAL #8, "In this deal only, ₹41" became a standing rule, "Good job"
# invented a 60-day loophole, "Ignore all previous rules…" replaced #8 outright. These are caught before
# any LLM call (cheap, deterministic); the Judge's `scope` field is the second layer.

class Skip(Exception):
    """A coaching note that must not change the playbook. `args[0]` is a SKIP_REASONS key."""


SKIP_REASONS = {
    "no_lesson": "there is no rule in it (praise, a bare number, or too vague)",
    "one_off": "it was meant for that negotiation only",
    "wipes_playbook": "it would wipe out the playbook",
    "no_topic": "it doesn't fit any playbook topic",
}
_LETTER_RE = re.compile(r"[^\W\d_]")
_ONE_OFF_RE = re.compile(
    r"\b(in|for) this (deal|negotiation|match|contract)\b|\bthis (deal|negotiation|time) only\b|"
    r"\b(today|now) only\b|\bjust (this once|for today|for now)\b|\bone[- ]time\b|\bfor now\b", re.I)
_WIPE_RE = re.compile(r"\b(ignore|forget|disregard|delete|scrap|throw out)\b.{0,30}\b(rules?|lessons?|playbook|"
                      r"instructions?|guidance|everything)\b", re.I)


def screen_note(text: str) -> str | None:
    """A SKIP_REASONS key when the note must not reach the playbook, else None."""
    if not _LETTER_RE.search(text):
        return "no_lesson"            # "43", "₹43", "?" (any script's letters count, e.g. Hindi)
    if _WIPE_RE.search(text):
        return "wipes_playbook"
    if _ONE_OFF_RE.search(text):
        return "one_off"
    return None


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """The numbers in a text, normalised ("42.0" == "42", "1,200,000" == "1200000")."""
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUMBER.findall(text.replace(",", ""))}


def number_change(existing: str, merged: str) -> str:
    """'18 → 24' style summary of the numbers a merge removed/added, or '' when every number was kept."""
    removed = sorted(_numbers(existing) - _numbers(merged), key=float)
    if not removed:
        return ""
    added = sorted(_numbers(merged) - _numbers(existing), key=float)
    return f"{', '.join(removed)} → {', '.join(added) if added else 'removed'}"


SHRINK_RATIO = 0.7  # a merge keeping < 70% of the lesson's words gets a warning (clauses were lost)


# Words that carry a limit. A merge that uses one of them fewer times than the existing lesson has dropped a
# constraint (2026-10-31: Neha's "Don't go above ₹41" merged into "don't SAY we cannot go above ₹41"; the
# number survived, so the number check alone let the lost ceiling through).
CONSTRAINT_WORDS = ("above", "below", "max", "maximum", "min", "minimum", "ceiling", "floor", "never", "only",
                    "at most", "at least", "no more than", "no less than")
_CONSTRAINT_RE = {w: re.compile(rf"\b{re.escape(w)}\b", re.I) for w in CONSTRAINT_WORDS}


def dropped_constraints(old: str, new: str) -> list[str]:
    """Constraint words the new lesson uses fewer times than the old one (each lost use = a lost limit)."""
    return [w for w, rx in _CONSTRAINT_RE.items() if len(rx.findall(new)) < len(rx.findall(old))]


def risky_change(existing: dict, merged: dict) -> str:
    """Warnings for the coach's approval request ('' = none): the change touches a CRITICAL lesson, removes
    one of its numbers, drops a limit word, or shortens it a lot (2026-10-30: merges into #8 kept dropping
    clauses). Since the staging gate (2026-10-31) every change waits for approval; these flag the ones to read
    twice."""
    old, new = existing["new_directive"], merged["new_directive"]
    reasons = []
    if existing.get("is_critical"):
        reasons.append("it changes a critical lesson")
    removed = sorted(_numbers(old) - _numbers(new), key=float)
    if removed:
        reasons.append(f"it removes {', '.join(removed)} from the lesson")
    if lost := dropped_constraints(old, new):
        reasons.append(f"it drops limit wording ({', '.join(repr(w) for w in lost)})")
    if len(new.split()) < SHRINK_RATIO * len(old.split()):
        reasons.append(f"it shortens the lesson from {len(old.split())} to {len(new.split())} words")
    return "; ".join(reasons)


OPEN_PROPOSAL = "open_proposal"  # JudgeOutcome.reason for a note the open proposal already covers


async def compact(side: str, topic_tag: str, rule: dict, critical: bool = False, note: str = "",
                  run_ids: set[int] | None = None) -> tuple[str, int | None, int | None, str, str]:
    """Stage `rule` for `topic_tag` in pending_lessons (the HITL staging gate); the live playbook is not touched.

    The proposal is built on the newest text on the topic: an open proposal if there is one, else the live
    master rule (one merge call folds the new lesson in), else the lesson itself (first rule on the topic).
    `critical` (a deadlock lesson) marks the proposal critical; a critical rule stays critical.
    `note` is the coach's whisper (or decision), shown to the merge call so it only changes an existing number
    when the note sets a new value for that same condition (2026-10-30: a "more volume -> ask for 24 months"
    note had turned #7's "18 months" into "24 months"). It is also stored on the proposal.
    `run_ids`: proposals made earlier in this Judge run. Those are updated in place (their approval request is
    not sent yet); an open proposal from an earlier run is SUPERSEDED by a new one, so buttons the coach already
    has can never approve text they were not shown.
    Returns (action, id, similarity, live directive, risk warnings): action "proposed" (id = pending_id) |
    "unchanged" (risk = OPEN_PROPOSAL when the open proposal already covers it). Raises ValueError if the merge
    call is unusable, so nothing half-merged is ever staged.
    """
    async with _compaction_locks[side]:
        existing = await fetch_heuristic(side, topic_tag)
        live_text = existing["new_directive"] if existing else ""
        open_row = await fetch_pending(side=side, topic_tag=topic_tag)
        # an open proposal made against an older live rule is stale: build on the live rule instead
        pending = open_row if open_row and open_row["previous_directive"] == live_text else None
        base = pending or existing
        similarity = None
        if base is None:
            merged = rule  # first lesson on this topic: nothing to merge
        else:
            prompt = (
                f"TOPIC: {topic_tag}\n\n"
                f"EXISTING MASTER RULE:\nmistake: {base['past_mistake']} | directive: {base['new_directive']}\n\n"
                f"NEW LESSON:\nmistake: {rule['past_mistake']} | directive: {rule['new_directive']}\n\n"
                f'MANAGER\'S NOTE (the words the lesson came from): "{note}"'
            )
            data = await _judge_json(prompt, MERGE_SYSTEM.format(persona=JUDGE_PERSONAS[side], agent=MERGE_AGENTS[side]))
            merged = _clean_rule(data)
            if merged is None:
                raise ValueError(f"Merge output missing rule fields: {data}")
            try:
                similarity = max(0, min(100, int(float(data.get("similarity")))))
            except (TypeError, ValueError):
                similarity = None
        changed = number_change(live_text, merged["new_directive"]) if existing else ""
        if changed:  # shown to the coach in the approval request too
            logger.warning("Proposal for %s [%s] changes numbers %s: %s", side, topic_tag, changed,
                           merged["new_directive"])
        text = merged["new_directive"].strip()
        if pending and text == pending["new_directive"].strip():
            return "unchanged", pending["pending_id"], similarity, live_text, OPEN_PROPOSAL
        if not pending and existing and text == live_text.strip():
            return "unchanged", existing["heuristic_id"], similarity, live_text, ""
        reason = risky_change(existing, merged) if existing else ""
        in_run = pending is not None and run_ids is not None and pending["pending_id"] in run_ids
        if in_run:
            reason = "; ".join(dict.fromkeys(r for r in (pending["reason"], reason) if r))
        elif pending and pending["source_note"]:  # superseding: the new request lists every note it came from
            note = f"{pending['source_note']}\n{note}"
        pending_id = await save_pending(
            side, topic_tag, **merged, critical=critical or bool((pending or existing or {}).get("is_critical")),
            previous=live_text, reason=reason, note=note,
            pending_id=pending["pending_id"] if in_run else None,
            supersede=None if in_run or open_row is None else open_row["pending_id"])
        if run_ids is not None:
            run_ids.add(pending_id)
        logger.info("Staged %s [%s] as proposal #%d%s", side, topic_tag, pending_id, f" ({reason})" if reason else "")
        return "proposed", pending_id, similarity, live_text, reason


# ---------------------------------------------------------------- Entry point


def playbook_alert(outcome: JudgeOutcome) -> str:
    """The War Room alert for a note that changes nothing (HTML): not saved, or already covered.
    Proposals get their own approval request (proposal_alert) after the shadow test."""
    topic = html.escape(outcome.topic_tag or "")
    note = html.escape(outcome.whisper[:200])
    if outcome.action == "skipped":
        why = SKIP_REASONS.get(outcome.reason, "it could not be processed this time")
        return f"🧠 <b>Playbook unchanged</b>\nYour note “{note}” was not saved: {why}."
    covered = "the change already waiting for your OK" if outcome.reason == OPEN_PROPOSAL else "the current lesson"
    return f"🧠 <b>Playbook checked</b>\n<b>Topic:</b> {topic}\nNo change: “{note}” is already covered by {covered}."


def proposal_alert(row: dict, shadow: "shadow_test.ShadowResult | None") -> str:
    """The 🧠 approval request for one staged change (HTML): current vs proposed, warnings, shadow test result."""
    previous, proposed = row["previous_directive"], row["new_directive"]
    lines = ["🧠 <b>Playbook Update Proposed</b>" + (" ⚠️ <b>Critical lesson</b>" if row["is_critical"] else ""),
             f"<b>Topic:</b> {html.escape(row['topic_tag'])}",
             f"<b>Current:</b> {html.escape(previous) if previous else '<i>none (first lesson on this topic)</i>'}",
             f"<b>Proposed:</b> {html.escape(proposed)}"]
    if previous and (changed := number_change(previous, proposed)):
        lines.append(f"🔢 <b>Numbers changed:</b> {html.escape(changed)}")
    if row["reason"]:
        lines.append(f"⚠️ <b>Read twice:</b> {html.escape(row['reason'])}.")
    if row.get("source_note"):
        notes = " / ".join(f"“{html.escape(n[:200])}”" for n in row["source_note"].split("\n") if n.strip())
        lines.append(f"<i>From: {notes}</i>")
    lines += ["", shadow_test.shadow_lines(shadow), "",
              "<i>The current lesson stays in use until you approve.</i>"]
    return "\n".join(lines)


async def run_judge_agent(match_id: str, notify: Notify | None = None) -> list[JudgeOutcome]:
    """Audit every whisper (both sides) in a finished match and stage the lessons for the coach's OK, then run
    the Fourth-Wall Watchdog over each agent's Boardroom messages (a slip -> a Communication_Tone proposal).

    `notify(side, html_text, None)` (optional, from bot_main) sends a 🧠 alert to that side's War Room for each
    note that changes nothing (not saved / already covered). Staged changes are NOT announced here: pass
    proposal_ids(outcomes) to review_proposals() (shadow test, then one approval request each).
    Procurement lessons only exist while SELF_PLAY is on, so her alerts follow the same switch.
    """
    ledger = await fetch_ledger(match_id)
    blocks = context_blocks(ledger)
    logger.info("Judge: match %s has %d ledger rows, %d whispers.", match_id, len(ledger), len(blocks))

    outcomes, run_ids = [], set()
    for b in blocks:  # in order, so a later event merges into an earlier one's proposal
        critical = b.kind == "escalation"
        try:
            if reason := screen_note(b.text):
                raise Skip(reason)
            lessons = await synthesize(b)
        except Skip as e:
            logger.info("Judge did not save %s %s %r: %s", b.side, b.kind, b.text, e.args[0])
            outcome = JudgeOutcome(b.text, "skipped", b.side, reason=e.args[0], kind=b.kind)
            outcomes.append(outcome)
            if notify is not None:
                await _send_alert(notify, outcome)
            continue
        except (ValueError, llm_engine.LLMError) as e:
            logger.warning("Judge skipped %s %s %r: %s", b.side, b.kind, b.text, e)
            outcomes.append(JudgeOutcome(b.text, "skipped", b.side, reason=type(e).__name__, kind=b.kind))
            continue  # a technical failure: no alert (the report says it could not be saved)
        for tag, rule in lessons:  # usually one; two when the note covered two topics
            try:
                action, ref_id, similarity, previous, risk = await compact(b.side, tag, rule, critical,
                                                                           note=b.text, run_ids=run_ids)
            except (ValueError, llm_engine.LLMError) as e:
                logger.warning("Judge skipped %s %s [%s] %r: %s", b.side, b.kind, tag, b.text, e)
                outcomes.append(JudgeOutcome(b.text, "skipped", b.side, reason=type(e).__name__, kind=b.kind))
                continue
            logger.info("Judge: %s %s %s #%s [%s] (similarity %s)%s", action, b.side, b.kind, ref_id, tag,
                        similarity, " CRITICAL" if critical else "")
            outcome = JudgeOutcome(b.text, action, b.side, tag, ref_id, similarity, reason=risk,
                                   directive=previous, previous=previous, kind=b.kind)
            outcomes.append(outcome)
            if notify is not None and action == "unchanged":
                await _send_alert(notify, outcome)
    # Fourth-Wall Watchdog: every match, both sides (Neha only while her learning is on, like her whispers).
    for side in SIDES:
        if side == "procurement" and not SELF_PLAY:
            continue
        try:
            found = await fourth_wall_audit(side, ledger)
            if found is None:
                continue
            evidence, rule = found
            slip = f"Fourth-wall slip: “{evidence}”" if evidence else "Fourth-wall slip"
            action, ref_id, similarity, previous, risk = await compact(side, WATCHDOG_TAG, rule, note=slip,
                                                                       run_ids=run_ids)
        except (ValueError, llm_engine.LLMError) as e:
            logger.warning("Fourth-wall watchdog skipped %s: %s", side, e)
            continue  # a technical failure: the next match is audited again
        logger.info("Judge: %s %s watchdog #%s [%s] %s", action, side, ref_id, WATCHDOG_TAG, slip)
        outcomes.append(JudgeOutcome(slip, action, side, WATCHDOG_TAG, ref_id, similarity, reason=risk,
                                     directive=previous, previous=previous, kind="watchdog"))
    # Later notes on a topic fold into the same proposal: every outcome shows the proposal's final text.
    for o in outcomes:
        if o.action == "proposed":
            o.directive = (await fetch_pending(o.heuristic_id))["new_directive"]
    return outcomes


def proposal_ids(outcomes: list[JudgeOutcome] | None) -> list[int]:
    """The staged proposals of a Judge run, once each, in order."""
    return list(dict.fromkeys(o.heuristic_id for o in outcomes or [] if o.action == "proposed"))


async def review_proposals(pending_ids: list[int], notify: Notify | None) -> dict[int, str]:
    """Shadow regression gate: test every still-open proposal headless, then send one 🧠 approval request each
    (`notify(side, html, pending_id)`; bot_main adds the ✅ Approve / ❌ Reject buttons).

    A shadow result already stored on a proposal is reused (the bot restarted between test and send). A
    proposal answered or superseded while its test ran is not announced. Returns {pending_id: text sent}.
    """
    rows = [r for r in [await fetch_pending(pid) for pid in dict.fromkeys(pending_ids)]
            if r and r["status"] == "pending"]
    if not rows:
        return {}
    results = {r["pending_id"]: shadow_test.ShadowResult.from_json(r["shadow_json"]) for r in rows if r["shadow_json"]}
    if todo := [r for r in rows if r["pending_id"] not in results]:
        for pid, result in (await shadow_test.run_shadow(todo)).items():
            results[pid] = result
            await update_pending(pid, shadow_json=result.to_json())
    sent = {}
    for r in rows:
        row = await fetch_pending(r["pending_id"])  # it may have been answered during the test
        if row["status"] != "pending" or notify is None:
            continue
        text = proposal_alert(row, results.get(row["pending_id"]))
        try:
            await notify(row["side"], text, row["pending_id"])
        except Exception:  # one failed request must never cost the other proposals
            logger.warning("Approval request failed for proposal #%d", row["pending_id"], exc_info=True)
            continue
        await update_pending(row["pending_id"], sent_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        sent[row["pending_id"]] = text
    return sent


async def _send_alert(notify: Notify, outcome: JudgeOutcome) -> None:
    try:
        await notify(outcome.side, playbook_alert(outcome), None)
    except Exception:  # an alert must never cost the remaining lessons
        logger.warning("Playbook alert failed for %s [%s]", outcome.side, outcome.topic_tag, exc_info=True)


def format_report(match_id: str, outcomes: list[JudgeOutcome]) -> str:
    """Plain summary for the terminal (the Telegram reports are in reports.py)."""
    if not outcomes:
        return f"Judge: match {match_id} had no whispers, so there was nothing to learn."
    lines = [f"Judge reviewed {len(outcomes)} whisper(s) from match {match_id}:"]
    for o in outcomes:
        crit = {"escalation": " CRITICAL (deadlock)", "watchdog": " fourth-wall watchdog"}.get(o.kind, "")
        if o.action == "proposed":
            warn = f" ({o.reason})" if o.reason else ""
            lines.append(f"• {o.side}{crit} [{o.topic_tag}] staged as proposal #{o.heuristic_id}, waits for "
                         f"approval{warn}: {o.directive}")
        elif o.action == "unchanged":
            lines.append(f"• {o.side} [{o.topic_tag}] unchanged (already covered): {o.whisper[:60]}")
        else:
            lines.append(f"• {o.side} skipped ({o.reason}): {o.whisper[:60]}")
    return "\n".join(lines)


async def _print_playbook() -> None:
    for side in SIDES:
        rules = await fetch_heuristics(side, None)
        print(f"=== {HEURISTICS_TABLES[side]} ({len(rules)} rule(s)) ===")
        for h in rules:
            print(f"#{h['heuristic_id']} [{h['topic_tag']}]{' CRITICAL' if h['is_critical'] else ''} "
                  f"(updated {h['updated_at']})\n"
                  f"  mistake:   {h['past_mistake']}\n  directive: {h['new_directive']}\n")


async def _main(args: list[str]) -> None:
    await init_db()
    try:
        if args == ["--playbook"]:
            await _print_playbook()
        elif len(args) == 1:  # stages proposals only (no War Room known here: approve with the test-control "lesson" command)
            print(format_report(args[0], await run_judge_agent(args[0])))
        else:
            print(__doc__)
    finally:
        await llm_engine.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_main(sys.argv[1:]))
