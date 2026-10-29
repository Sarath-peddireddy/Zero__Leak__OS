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
  3. Compaction ("Highlander" UPSERT): topic_tag is UNIQUE in the side's heuristics
                 table, so there is one master rule per topic. If a rule for the
                 tag already exists, one fast merge call folds the new lesson into
                 it (the newest coaching wins where they conflict). Then
                 INSERT ... ON CONFLICT(topic_tag) DO UPDATE writes the row.
                 The playbook stays at one row per topic, so lookups stay O(1).

Escalations (two-way HITL): every Manager_Decision row (the manager's answer to a
Sales_Escalation) is judged with the question, the 3 Boardroom messages before it and
the 2 after it, and stored as a CRITICAL lesson (is_critical = 1) in sales_heuristics,
so Arjun can break the same deadlock himself next time.

Phase B is parked (negotiation.SELF_PLAY off): Procure_Whisper rows are not judged.

bot_main.py reads the lessons back before every turn: each agent's friction tags
select the opponent's master lessons (max 2) for the reply (JIT retrieval).

Usage:
    python post_match.py <match_id>     # judge one match from the ledger
    python post_match.py --playbook     # print both playbooks
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass

import llm_engine
from db_init import HEURISTICS_TABLES, SIDES, fetch_heuristic, fetch_heuristics, fetch_ledger, init_db, upsert_heuristic
from negotiation import SELF_PLAY, SPEAKER_NAMES, normalize_friction_points

logger = logging.getLogger("zeroleak.judge")

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
{
  "topic_tag": "Must be one of: Price, RTO, Payment_Terms, Contract_Length, Volume, SLA, Competitor_Quote",
  "past_mistake": "Exactly what the agent did wrong or was about to do.",
  "new_directive": "The hard rule the agent must follow next time this topic arises."
}"""

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
{_TAG_RULE}""",
    "procurement": f"""\
{JUDGE_PERSONAS["procurement"]}
Look at the context and the coach's whisper to Neha. Identify the mistake Neha was making that \
required the intervention, and write the rule that cuts MegaMart's cost next time.
{_JUDGE_FORMAT}
{_TAG_RULE}""",
}

# Step 4 of the two-way escalation: a deadlock the manager had to break becomes a CRITICAL lesson,
# written so Arjun can break the same deadlock himself next time without asking.
ESCALATION_JUDGE_SYSTEM = f"""\
{JUDGE_PERSONAS["sales"]}
In this negotiation Arjun got stuck and escalated to his manager instead of replying to the buyer. You are given the Boardroom \
messages before the escalation, Arjun's question, the manager's decision, and what happened right after.
Write the CRITICAL lesson that lets Arjun break this kind of deadlock on his own next time, without \
asking: turn the manager's decision into a general rule. State the trigger (what the buyer did: the \
price, terms or threat that caused the deadlock) and the exact action to take (keep every number and \
condition from the decision).
{_JUDGE_FORMAT}
past_mistake: describe the deadlock Arjun could not resolve alone (e.g. "Froze and asked for help when \
the buyer demanded ₹41 and threatened to walk on a 12-month term").
new_directive: the decision as a standing rule (e.g. "When the buyer demands ₹41 and threatens to walk \
on 12 months, state ₹43 as final; if rejected, walk away.").
Choose topic_tag by what the decision governs (usually Price, Contract_Length, RTO or Payment_Terms)."""
AFTER_MESSAGES = 2  # Boardroom messages after the decision, to show the Judge how it played out

MERGE_SYSTEM = """\
{persona}
You maintain your team's negotiation playbook for the {agent}. It holds exactly ONE master rule per topic. \
Merge the NEW lesson into the EXISTING master rule for this topic, producing one rule that replaces it.
- Keep every concrete number, term and condition from both (prices, contract lengths, payment days, \
what is traded for what).
- Where they conflict, the NEW lesson wins: it is the manager's latest instruction. Drop the part of the \
existing rule it contradicts.
- Stay concise: one past_mistake and one new_directive, each under 60 words. No duplicated ideas.
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
    action: str                 # "inserted" | "merged" | "skipped"
    side: str = "sales"         # whose playbook: "sales" | "procurement"
    topic_tag: str | None = None
    heuristic_id: int | None = None
    similarity: int | None = None
    reason: str = ""            # why it was skipped, for the report
    directive: str = ""         # the rule's new_directive as stored (merged text when merged)
    previous: str = ""          # merged only: the rule's new_directive before this lesson (for the report)
    kind: str = "whisper"       # "whisper" | "escalation" (a CRITICAL deadlock lesson)


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
            blocks.append(Block(side, row["payload_text"], before))
        elif speaker == "Manager_Decision":
            asked = [r for r in ledger[:i] if r["speaker"] == "Sales_Escalation"]
            after = [r for r in ledger[i + 1:] if r["speaker"] in BOARDROOM_LABELS][:AFTER_MESSAGES]
            blocks.append(Block("sales", row["payload_text"], before, "escalation",
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


async def synthesize(block: Block) -> tuple[str, dict]:
    """Judge one coaching event: returns (topic_tag, rule). Raises ValueError on unusable output."""
    if block.kind == "escalation":
        prompt = (
            f"BEFORE (the last {len(block.before)} Boardroom messages before Arjun escalated):\n"
            f"{_render_context(block.before)}\n\n"
            f'ARJUN\'S ESCALATION to his manager: "{block.question}"\n'
            f'MANAGER\'S DECISION (obeyed as an absolute command): "{block.text}"\n\n'
            f"AFTER (what happened next):\n"
            f"{_render_context(block.after) if block.after else '(the negotiation ended right after)'}"
        )
        system = ESCALATION_JUDGE_SYSTEM
    else:
        agent = "Sales Agent" if block.side == "sales" else "Procurement Agent"
        prompt = (
            f"CONTEXT (the last {len(block.before)} Boardroom messages before the whisper):\n"
            f"{_render_context(block.before)}\n\n"
            f'MANAGER\'S WHISPER to the {agent}: "{block.text}"'
        )
        system = JUDGE_SYSTEM[block.side]
    data = await _judge_json(prompt, system)
    tags = normalize_friction_points([data.get("topic_tag")])
    rule = _clean_rule(data)
    if not tags or rule is None:
        raise ValueError(f"Judge output missing a valid topic_tag or rule fields: {data}")
    return tags[0], rule


async def compact(side: str, topic_tag: str, rule: dict,
                  critical: bool = False) -> tuple[str, int, int | None, str]:
    """UPSERT `rule` as the master rule for `topic_tag`, merging into the existing one first.

    `critical` (a deadlock lesson) marks the master rule critical; a critical rule stays critical.
    Returns (action, heuristic_id, similarity, previous directive or ""). Raises ValueError if the merge call is unusable,
    so an existing master rule is never overwritten by an unmerged lesson.
    """
    async with _compaction_locks[side]:
        existing = await fetch_heuristic(side, topic_tag)
        if existing is None:
            return "inserted", await upsert_heuristic(side, topic_tag, **rule, critical=critical), None, ""

        prompt = (
            f"TOPIC: {topic_tag}\n\n"
            f"EXISTING MASTER RULE:\nmistake: {existing['past_mistake']} | directive: {existing['new_directive']}\n\n"
            f"NEW LESSON:\nmistake: {rule['past_mistake']} | directive: {rule['new_directive']}"
        )
        data = await _judge_json(prompt, MERGE_SYSTEM.format(persona=JUDGE_PERSONAS[side], agent=MERGE_AGENTS[side]))
        merged = _clean_rule(data)
        if merged is None:
            raise ValueError(f"Merge output missing rule fields: {data}")
        try:
            similarity = max(0, min(100, int(float(data.get("similarity")))))
        except (TypeError, ValueError):
            similarity = None
        heuristic_id = await upsert_heuristic(side, topic_tag, **merged, critical=critical)
        return "merged", heuristic_id, similarity, existing["new_directive"]


# ---------------------------------------------------------------- Entry point


async def run_judge_agent(match_id: str) -> list[JudgeOutcome]:
    """Audit every whisper (both sides) in a finished match and fold the lessons into the playbooks."""
    ledger = await fetch_ledger(match_id)
    blocks = context_blocks(ledger)
    logger.info("Judge: match %s has %d ledger rows, %d whispers.", match_id, len(ledger), len(blocks))

    outcomes = []
    for b in blocks:  # in order, so a later event merges into an earlier one's rule
        critical = b.kind == "escalation"
        try:
            tag, rule = await synthesize(b)
            action, heuristic_id, similarity, previous = await compact(b.side, tag, rule, critical)
        except (ValueError, llm_engine.LLMError) as e:
            logger.warning("Judge skipped %s %s %r: %s", b.side, b.kind, b.text, e)
            outcomes.append(JudgeOutcome(b.text, "skipped", b.side, reason=type(e).__name__, kind=b.kind))
            continue
        stored = await fetch_heuristic(b.side, tag)
        logger.info("Judge: %s %s %s heuristic #%s [%s] (similarity %s)%s", action, b.side, b.kind,
                    heuristic_id, tag, similarity, " CRITICAL" if critical else "")
        outcomes.append(JudgeOutcome(b.text, action, b.side, tag, heuristic_id, similarity,
                                     directive=stored["new_directive"] if stored else rule["new_directive"],
                                     previous=previous, kind=b.kind))
    return outcomes


def format_report(match_id: str, outcomes: list[JudgeOutcome]) -> str:
    """Plain summary for the terminal (the Telegram reports are in reports.py)."""
    if not outcomes:
        return f"Judge: match {match_id} had no whispers, so there was nothing to learn."
    lines = [f"Judge reviewed {len(outcomes)} whisper(s) from match {match_id}:"]
    for o in outcomes:
        crit = " CRITICAL (deadlock)" if o.kind == "escalation" else ""
        if o.action == "merged":
            lines.append(f"• {o.side}{crit} [{o.topic_tag}] merged into master rule #{o.heuristic_id} "
                         f"({o.similarity}% similar): {o.directive}")
        elif o.action == "inserted":
            lines.append(f"• {o.side}{crit} [{o.topic_tag}] new master rule #{o.heuristic_id}: {o.directive}")
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
        elif len(args) == 1:
            print(format_report(args[0], await run_judge_agent(args[0])))
        else:
            print(__doc__)
    finally:
        await llm_engine.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_main(sys.argv[1:]))
