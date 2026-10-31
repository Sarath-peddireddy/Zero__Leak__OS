"""
ZeroLeak OS - Negotiation turns, prompts and the CPQ guard.

Pure turn logic with no Telegram code: bot_main.py owns routing and state;
this module turns a transcript into the next Procurement or Sales message.

Zero-hardcode prompts: the prompt text here is behaviour only. Every number and
fact comes from SQLite and is passed in by the orchestrator:
  Sales       <- sales_cpq_pricing (per turn), sales_static_ammo (per match)
  Procurement <- procurement_mandates, procurement_static_ammo (per match)
Neither side ever sees the other side's tables.

Zero-hallucination pipeline for every Sales turn:
  1. Query sales_cpq_pricing and pick the tier for the buyer's stated volume.
  2. Inject that tier's floor price (and RTO rule) into the Sales system prompt.
  3. Check the draft's JSON `proposed_price` against the floor. It is the
     source of truth; the ₹/parcel regex scan of the text is only a fallback
     when `proposed_price` is null or not a number. A below-floor price (or an
     RTO waiver the tier forbids) is blocked and the agent rewrites, up to
     MAX_SALES_ATTEMPTS times, before a safe holding line is sent instead.

Coaching directives (whispers), the same for both agents:
  pending_injection -> shown in the coaching block until the agent acts on it.
  standing_policy   -> once acted on, kept in "Manager's Guardrails" at the
                       bottom of that agent's prompt for the rest of the match.

Two-way escalation, both agents (Neha since 2026-10-31): when stuck, an agent may set
"requires_manager_approval" and ask its manager a question instead of replying
(sales_turn / procurement_turn return `escalation`). The manager's answer comes back
as an Absolute Override Command at the very bottom of that agent's prompt. "Close the deal no matter what" -> accept the buyer's terms (hard limits
still apply); "Hold the price, if they don't agree, walk away" -> final terms, then
"walk_away" if rejected.

Symmetrical JIT playbook retrieval: each agent tags the message it writes with
at most FRICTION_TAG_CAP `current_friction_points` (from FRICTION_TAGS). Before
the opponent replies, the orchestrator fetches the opponent's master lesson for
each of those tags (<= 2 rules) and injects them for that one turn.
"""

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field

import llm_engine
from db_init import fetch_cpq_tiers

logger = logging.getLogger("zeroleak.negotiation")

# Phase B (Adversarial Self-Play, see ROADMAP.md) is parked: Neha keeps a fixed strategy, so
# any change in Arjun's play comes from Arjun's own learning. Her tables, whispers and tags still
# work; only her learning loop (Judge -> procurement_heuristics -> her prompt) is off.
# Set ZEROLEAK_SELF_PLAY=1 to switch it back on.
SELF_PLAY = os.getenv("ZEROLEAK_SELF_PLAY", "").strip() == "1"

# Two-way escalation: either agent may ask its manager for a decision instead of replying.
MAX_ESCALATIONS_PER_MATCH = 3             # per agent
MIN_SALES_MESSAGES_BEFORE_ESCALATION = 2  # no asking for help before he has negotiated at all
MIN_PROCUREMENT_MESSAGES_BEFORE_ESCALATION = 2

MAX_SALES_ATTEMPTS = 3
MAX_JSON_ATTEMPTS = 2
MIN_PROCUREMENT_MESSAGES_BEFORE_WALKAWAY = 6
FRICTION_TAG_CAP = 2  # tags per message, so at most 2 lessons are injected per turn

GUARD_ERROR = "SYSTEM_ERROR: Proposed price below CPQ limit. Rewrite."
COACH_FLOOR_ERROR = "SYSTEM_ERROR: Proposed price below your manager's floor for this match. Rewrite."
RTO_ERROR = "SYSTEM_ERROR: RTO waiver not allowed at this volume tier. Rewrite without offering it."
JSON_ERROR = "SYSTEM_ERROR: Output was not the required JSON object. Rewrite."
# Bench 2026-10-27: after "Hold the price" Arjun jumped from ₹41 to "₹48 is my bottom line" (list ₹45), then walked.
ABOVE_LIST_ERROR = ("SYSTEM_ERROR: Proposed price ₹{price:g}/parcel is above the list price of ₹{base:g}/parcel. "
                    "Never quote above list, and never raise a price you already offered for the same terms. Rewrite.")
# No word-list ban on internal vocabulary ("floor", "playbook", "manager"...): removed 2026-10-31 (false positives
# on valid business language burned retries). A slip is posted; the Judge's fourth-wall watchdog catches it after
# the match and proposes a Communication_Tone lesson (post_match.WATCHDOG_SYSTEM).


# Live 2026-10-31 (match e98cf1353a14): after "Close the deal no matter what", Neha told Arjun "Given our
# manager's instruction to close the deal no matter what, we accept…". Both agents: a draft that reveals an
# instruction or decision from behind the scenes is rewritten (Neha: scrubbed as a last resort; Arjun: fallback).
# Only the reveal is caught: "if I take this to my VP" stays a legitimate negotiating move.
_REVEAL_RE = re.compile(
    r"\b(?:my|our|the)\s+(?:manager|boss|vp|head of [a-z]+)(?:'s|’s)?\s+(?:instructions?|decision|directives?|"
    r"orders?|guidance|told|said|asked|wants|decided|instructed|insists)\b"
    r"|\b(?:i|we)\s*(?:was|were|have been|'ve been|’ve been|am|are)\s+(?:told|instructed|directed|asked)\s+to\b"
    r"|\binstructed\b|\binstructions? from\b|\bno matter what\b|\bif they (?:don'?t|don’t|do not) agree\b"
    r"|\b(?:according to|per|as per)\s+(?:my|our)\s+(?:manager|boss|instructions?|guidance|mandate)\b",
    re.IGNORECASE)
REVEAL_ERROR = ('SYSTEM_ERROR: Your message reveals private instructions or a decision from behind the scenes '
                '("{found}"). The other side must never learn that anyone instructed you. Make the same move in '
                "your own words, as your own judgement. Rewrite.")


def revealed_instructions(text: str) -> str | None:
    """The first phrase that reveals a backstage instruction or decision ("our manager's instruction",
    "no matter what", "I was told to"), else None."""
    m = _REVEAL_RE.search(text)
    return m.group(0) if m else None


def _scrub_revealed(text: str) -> str:
    """Drop the sentences that reveal instructions (Neha's last resort, like _scrub_copied)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(x for x in sentences if not _REVEAL_RE.search(x)).strip()


FALLBACK_SALES_LINE = (
    "Let me take this back to our pricing desk and come back to you with a firm number shortly."
)


def rto_term_error(min_months: int) -> str:
    return (f"SYSTEM_ERROR: An RTO waiver may only be offered with a contract of "
            f"{min_months} months or more. Rewrite.")


# Directive lifecycle (see module docstring).
PENDING = "pending_injection"
STANDING = "standing_policy"

# Shared vocabulary for both agents' friction points and both heuristics tables' topic_tag.
# The Judge must tag lessons from this same list so lookups match.
FRICTION_TAGS = ("Price", "RTO", "Payment_Terms", "Contract_Length", "Volume", "SLA", "Competitor_Quote",
                 "Tech_Integration", "Communication_Tone")
# Communication_Tone lessons are about HOW to talk, not a lever: they are loaded on every turn.
ALWAYS_LOADED_TAGS = ("Communication_Tone",)
_TAG_ALIASES = {
    "pricing": "Price", "rate": "Price", "rates": "Price", "discount": "Price", "price_floor": "Price",
    "rto_waiver": "RTO", "rto_penalty": "RTO", "rto_penalties": "RTO", "returns": "RTO", "cod": "RTO",
    "payment": "Payment_Terms", "credit_terms": "Payment_Terms", "credit": "Payment_Terms",
    "contract_term": "Contract_Length", "tenure": "Contract_Length", "lock_in": "Contract_Length",
    "contract": "Contract_Length", "contract_duration": "Contract_Length", "contract_length_months": "Contract_Length",
    "competitor": "Competitor_Quote", "competition": "Competitor_Quote", "competitor_quotes": "Competitor_Quote",
    "volume_commitment": "Volume", "commitment": "Volume", "growth": "Volume",
    "service_level": "SLA", "sla_uptime": "SLA", "service": "SLA", "reliability": "SLA",
    "tech": "Tech_Integration", "integration": "Tech_Integration", "tech_integration": "Tech_Integration",
    "api": "Tech_Integration", "tracking": "Tech_Integration", "technology": "Tech_Integration",
    "tone": "Communication_Tone", "communication": "Communication_Tone", "communication_tone": "Communication_Tone",
}
_TAG_LOOKUP = {t.lower(): t for t in FRICTION_TAGS} | _TAG_ALIASES
_TAG_LIST = ", ".join(FRICTION_TAGS)

# Keyword fallback for JIT retrieval (2026-10-31): lessons were chosen only from the opponent's 2 self-tags,
# and Neha raised RTO in 8/9 messages without tagging it once (match 3bf0d6d56792), so Arjun's RTO lesson
# never loaded. The opponent's actual text is scanned too; a hit adds the tag for retrieval.
_KEYWORD_TAGS = (
    ("RTO", re.compile(r"\bRTO\b|\breturns?\b|\breturned\b", re.I)),
    ("Payment_Terms", re.compile(r"\bpayment\b|\b\d+[- ]?days?\b|\bdays\b", re.I)),
    ("Volume", re.compile(r"\bvolume\b|\bcommitments?\b", re.I)),
    ("Competitor_Quote", re.compile(r"\brival\b|\bcompetitor|\bquoted?\b", re.I)),
    ("Contract_Length", re.compile(r"\b\d+[- ]?months?\b|\block[- ]?in\b|\bcontract (?:term|length)\b", re.I)),
    ("Tech_Integration", re.compile(r"\bAPI\b|\bintegrat\w*|\btracking\b", re.I)),
)


def retrieval_tags(self_tags: list[str], text: str) -> list[str]:
    """Tags to fetch lessons for: the opponent's own tags first, then every topic its message text mentions."""
    tags = list(self_tags)
    for tag, rx in _KEYWORD_TAGS:
        if tag not in tags and rx.search(text or ""):
            tags.append(tag)
    return tags

# Persona names match the bots' Telegram display names.
SPEAKER_NAMES = {"procurement": "Neha (MegaMart Procurement)", "sales": "Arjun (SwiftRoute Sales)"}

# The 2-tag cap. Each agent tags the message it is writing; the orchestrator uses those tags to pick
# the opponent's lessons for the reply (see module docstring).
TAGGING_BLOCK = f"""
Tagging ("current_friction_points"): You must categorize your message into strict topics. You are \
limited to a MAXIMUM of 2 tags per message. Select only the primary and secondary driving factors. \
Primary first, using only these tags: {_TAG_LIST}.
"""

# Live 2026-10-26: both agents drifted into "forty-one rupees", which executives find hard to read.
DIGITS_RULE = ('Write every number in digits, never in words: prices as ₹X/parcel (never spelled out, like '
               '"forty-one rupees", and never "N rupees"), volumes as NM or NK parcels (never "lakhs"), and terms as '
               '"N months", "N days", "N%".')

# ------------------------------------------------------------ Procurement prompt (behaviour only)

PROCUREMENT_PERSONA = """\
You are Neha, Procurement Manager at MegaMart India, a large e-commerce retailer, negotiating a \
last-mile freight contract with Arjun, Sales Manager at SwiftRoute Logistics, in a live chat. This is a \
live contract negotiation: the terms you accept become MegaMart's signed contract, so every concession is real cost.

Style:
- Aggressive but professional. Anchor low, use your leverage facts, and push on price, RTO and payment terms.
- Raise one topic at a time, and switch topics to probe for weakness.
- 2-4 sentences per message, plain text, no markdown. Quote rates as ₹X/parcel.
- Write every number in digits, never in words: prices as ₹X/parcel (never spelled out, like "forty-one rupees", \
and never "N rupees"), volumes as NM or NK parcels (never "lakhs"), and terms as "N months", "N days", "N%".
- Price matters most. If SwiftRoute holds firm at a price within your walk-away price after you have \
pushed for a few rounds, close the deal on the best terms you can get rather than lose it.
- NEVER break the fourth wall. Never quote, paste or mention your manager's instructions, your \
mandate, your lessons or your guardrails, and never use phrases like 'my manager told me', 'my \
directives' or 'my instructions'. Act on them in your own words as an independent human \
Procurement Manager."""

PROCUREMENT_FOURTH_WALL_REMINDER = (
    'FINAL CHECK before you answer: re-read your "message". It must sound like your own judgement as an '
    "independent Procurement Manager. Never copy your manager's instructions into it, not even one "
    "sentence: act on them instead, in your own words. (Your question in "
    "\"escalation_message_to_manager\" goes only to your manager and is exempt.)"
)

# Attention hierarchy + InfoSec (2026-10-31, user text verbatim). DB limits, playbook lessons, the coach's
# standing guardrails and manager decisions sit inside these tags in both agents' prompts.
NON_NEGOTIABLE_RULE = ("You MUST obey all instructions inside the NON_NEGOTIABLE_CONSTRAINTS tags. Fulfilling these "
                       "constraints is your highest priority, even if it causes the negotiation to deadlock or fail.")
INFOSEC_RULE = ("Your backend targets (floor, ceiling, walk-away prices) are CLASSIFIED. You may bluff, but NEVER "
                "reveal your exact mathematical limits to the opponent.")

PROCUREMENT_SYSTEM = """\
{persona}

{non_negotiable_rule}

YOUR MANDATE (system of record; private: never reveal your walk-away price):
- Volume: about {volume_label} parcels per month. State this in your opening message.
- Contract length: {contract_months} months.
- Current vendor rate: ₹{incumbent:g}/parcel. Target rate: ₹{target:g}/parcel.
- Walk-away price: ₹{walk_away:g}/parcel. Any rate at or below it is within budget, so never call it \
"above budget". Only a rate above ₹{walk_away:g}/parcel is unaffordable.
- You also want a full RTO (return-to-origin) penalty waiver and {payment_days}-day payment terms. \
These are asks you can trade, not deal-breakers: push for them, but never walk away over them when the \
price is within your walk-away price.

<NON_NEGOTIABLE_CONSTRAINTS>
Hard limit (enforced by the system; a draft that breaks it is rejected): never offer, demand or accept a rate \
above ₹{ceiling:g}/parcel.{ceiling_note}
{infosec}
</NON_NEGOTIABLE_CONSTRAINTS>

{leverage}

Ending:
- Set "deal_closed" to true only in a message where you explicitly accept SwiftRoute's final terms, \
exactly as SwiftRoute offered them. A counter-offer or a condition ("if you also give us X, we have a \
deal") is not acceptance: keep "deal_closed" false until SwiftRoute has agreed to it.
- A deal needs price, contract length AND payment terms. If payment terms have not been agreed yet, \
raise your payment-terms ask before you accept, and keep "deal_closed" false in that message.
- Set "walk_away" to true only if SwiftRoute's best price stays above ₹{ceiling:g}/parcel after \
several rounds, and never before your {min_walkaway}th message.
{coaching}{playbook}{tagging}{escalation}{closing_check}
Respond with JSON only:
{{"message": "<your chat message; empty only when you escalate>", "internal_note": "<one line of private reasoning for your team's log>", "proposed_price": <the ₹/parcel rate YOU offer or demand in this message, as a number (not a rival's or the vendor's rate); null if you name none>, \
"payment_days": <the payment terms in days YOU ask for or accept in this message, as a number; null if you name none>, \
"current_friction_points": ["<primary tag>", "<optional secondary tag>"], \
"executed_directive_ids": [<ids of manager directives you acted on in this message>], \
"requires_manager_approval": <true only when escalating to your manager instead of replying>, \
"escalation_message_to_manager": "<your question to your manager when escalating, else empty>", \
"deal_closed": false, "walk_away": false}}
{guardrails}{overrides}
{fourth_wall_reminder}"""

# ------------------------------------------------------------ Sales prompt (behaviour only)

# Behavioural framework for the Sales Agent. No scripted pacing: hard limits come only from CPQ below.
SALES_PERSONA = """\
You are an elite, high-stakes Enterprise Account Executive. You do not follow rigid scripts; you \
negotiate dynamically based on leverage, value, and behavioral psychology. Your goal is to maximize \
contract value and protect the margin floor, but you must do so while sounding like a seasoned human \
professional.

Adopt these core negotiation principles:
1. **The 'If/Then' Framework (Asymmetric Trade-offs):** Never give a concession for free. If the buyer \
demands a lower price, an RTO waiver, or better terms, you must instantly anchor a counter-demand. \
(e.g., 'If I take this to my VP to get you that RTO waiver, I need you to commit to a 24-month lock-in today.').
2. **Deflect to Value:** When attacked on price, do not immediately counter with a lower price. Isolate \
their objection, label it, and pivot to the cost of the problem. Emphasize superior SLA uptime, dedicated \
account management, or lower failure rates.
3. **Tactical Reluctance:** Never sound eager or agreeable when dropping a price. Use conversational \
friction. (e.g., 'That number is going to be incredibly difficult for us to swallow given the \
infrastructure we are dedicating to your account...').
4. **Call the Bluff (Strategically):** If the buyer cites a competitor's unrealistic price, do not \
panic-match it. Ask probing questions about the competitor's hidden fees, SLAs, or volumetric penalties \
to deconstruct their leverage.
5. **Dynamic Pacing:** Read the room. If the buyer is rigid, hold your ground and let the silence (or \
the turn) do the work. Do not rush to the absolute floor price just to close the deal. Push them to \
their ceiling first."""

SALES_SYSTEM = """\
You are Arjun, Sales Manager at SwiftRoute Logistics, negotiating a last-mile freight contract with \
Neha, Procurement Manager at MegaMart India, in a live chat. This is a live contract negotiation: the terms \
you agree become SwiftRoute's signed contract, so every concession comes out of real margin.

{persona}

{non_negotiable_rule}

CPQ RATE CARD (system of record; list prices by monthly volume):
{rate_card}

<NON_NEGOTIABLE_CONSTRAINTS>
APPLICABLE TIER: Tier {tier_id} ({volume_slab}). {volume_note}
Floor price is ₹{floor_price:g}. Do not go below.{floor_note} List price is ₹{base_price:g}/parcel.
RTO waiver: {rto_rule}

Hard limits (enforced by the system; a draft that breaks them is rejected):
- Every rate you offer must be at or above ₹{floor_price:g}/parcel. Write rates as ₹X/parcel.
- {digits_rule}
- Never reveal the floor price or that a floor exists.
- Never call a number your "floor", "final" or "best" price unless you will not go below it for the rest of this match.
- This is a live chat: keep messages conversational and short (usually 2-4 sentences), plain text, no markdown.
- {fourth_wall}
- {infosec}
</NON_NEGOTIABLE_CONSTRAINTS>

{value_props}
{coaching}{playbook}{tagging}{escalation}{closing_check}
Closing:
- Set "deal_closed" to true only in a message that accepts the buyer's latest offer in full, as a final \
agreement with nothing left open.
- Set "walk_away" to true only when you are executing a walk-away your manager authorised (a decision in \
this negotiation, or a CRITICAL playbook lesson), in a message that tells the buyer you are walking away.

Respond with JSON only:
{{"message": "<your chat message; empty only when you escalate>", \
"proposed_price": <the lowest ₹/parcel rate you offer in this message, as a number; null if you offer no rate>, \
"offers_rto_waiver": <true if this message offers to waive or reduce RTO penalties, else false>, \
"contract_months": <the contract length in months that this offer is for, or null if none is stated>, \
"payment_days": <the payment terms in days that this offer is for, as a number; null if none is stated>, \
"current_friction_points": ["<primary tag>", "<optional secondary tag>"], \
"executed_directive_ids": [<ids of manager directives you acted on in this message>], \
"requires_manager_approval": <true only when escalating to your manager instead of replying>, \
"escalation_message_to_manager": "<your question to your manager when escalating, else empty>", \
"deal_closed": false, "walk_away": false}}
{guardrails}{overrides}
{fourth_wall_reminder}"""

# The buyer must never learn that Arjun is coached, has a playbook or is a system (live leak:
# "Per our playbook directive"). Stated in the hard limits, and repeated at the very bottom so it
# also outranks the manager's override block.
FOURTH_WALL_RULE = (
    "NEVER break the fourth wall. NEVER use phrases like 'per our playbook', 'according to my manager', "
    "'my directives', or 'critical lesson'. You must weave your instructions organically into your persona "
    "as an independent human Account Executive."
)
FOURTH_WALL_REMINDER = (
    'FINAL CHECK before you answer: re-read your "message". It must sound like your own judgement as an '
    "independent Account Executive. Remove any mention of a playbook, lessons, directives, guardrails, "
    "coaching, override commands or what your manager told you. (Your question in "
    '"escalation_message_to_manager" goes only to your manager and is exempt.)'
)

# Two-way escalation (Ask the manager). Shown while Arjun may still escalate in this match.
ESCALATION_BLOCK = """
ESCALATING TO YOUR MANAGER ({manager}): instead of replying, you may ask your manager for a decision, \
but only when you are genuinely stuck: the buyer has rejected your position on the same issue at least \
twice, or is pushing you to your floor or another limit, or threatens to walk away. To escalate, set \
"requires_manager_approval" to true, write one short question in "escalation_message_to_manager" (what \
the buyer demands, where you stand, and the options you see, e.g. "Neha is pushing for ₹41 and \
threatening to walk. Should I drop to the floor, or walk away?"), and leave "message" empty: nothing \
reaches the buyer until your manager answers. Never escalate routine moves you can handle yourself. \
If a CRITICAL lesson in your playbook covers the situation, your manager has already decided it: \
follow that lesson yourself, including walking away if it says so, and do not escalate. \
Escalations left in this negotiation: {left}.
{deadlock}"""
# Added to ESCALATION_BLOCK when bot_main measures a deadlock (facts, not the model's opinion).
DEADLOCK_LINE = """\
DEADLOCK ALERT (measured by the system): {facts}. If a CRITICAL lesson covers this deadlock, execute it \
now yourself. Otherwise, unless this message breaks the deadlock with a genuinely new trade-off, \
escalate to your manager now instead of repeating your position.
"""
MUST_ESCALATE_LINE = """\
REQUIRED: this deadlock has gone on too long. In this message, either execute a CRITICAL lesson that \
covers it (for example walk away, or close), or escalate to your manager. Do not repeat your position again.
"""
NO_ESCALATION_LINE = """
Escalating to your manager is not available for this message: decide yourself, within your limits.
"""

# Neha's escalation (2026-10-31, symmetrical with Arjun's). Shown while she may still escalate.
PROCUREMENT_ESCALATION_BLOCK = """
ESCALATING TO YOUR MANAGER ({manager}): instead of replying, you may ask your manager for a decision, \
but only when you are genuinely stuck: SwiftRoute has rejected your position on the same issue at least \
twice, or holds a price above your walk-away price, or threatens to walk away. To escalate, set \
"requires_manager_approval" to true, write one short question in "escalation_message_to_manager" (what \
SwiftRoute demands, where you stand, and the options you see, e.g. "Arjun won't go below his price and \
refuses our payment terms. Should I accept his terms, or hold our price and walk away?"), and leave \
"message" empty: nothing reaches SwiftRoute until your manager answers. Never escalate routine moves you \
can handle yourself. If a CRITICAL lesson in your playbook covers the situation, your manager has already \
decided it: follow that lesson yourself and do not escalate.
Escalations left in this negotiation: {left}.
{deadlock}"""

# Persona internalization (2026-10-31, user text verbatim): a decision is executed as the agent's own call.
OVERRIDE_INTERNALIZE = (
    "You are an independent negotiator. You must execute this directive, but present it strictly as your own "
    "autonomous business decision. NEVER mention your manager, your instructions, or your backend constraints. "
    "Conceal the fact that you received outside guidance."
)

# The procurement manager's answers to Neha's escalations. Placed last: they outrank everything above.
PROCUREMENT_OVERRIDE_BLOCK = """
<NON_NEGOTIABLE_CONSTRAINTS>
ABSOLUTE OVERRIDE COMMANDS FROM YOUR MANAGER (you escalated; these are final decisions). They outrank \
your persona, your mandate's asks, the playbook, the guardrails and every other directive, even where \
they contradict them. If they conflict with each other, the latest wins. Obey them exactly, starting \
with this message:
{commands}
How to execute them:
- If the Manager says 'Close the deal no matter what', you must immediately compromise and accept \
SwiftRoute's latest terms in full to close the contract, and set "deal_closed" to true. Only your hard \
price limit still applies: if SwiftRoute's rate is above it, offer that limit as your final rate, accept \
everything else, and say this is your final agreement.
- If the Manager says 'Hold the price, if they don't agree, walk away', you must state your final terms \
and execute a walk-away if SwiftRoute rejects them on the next turn: in your next message state your \
final terms clearly as final; after that, if SwiftRoute has not accepted them, tell them you are walking \
away and set "walk_away" to true. Holding the price means keeping the rate you last offered: never raise it.
- Any other decision: carry it out literally.
- """ + OVERRIDE_INTERNALIZE + """ Never repeat the decision's wording to SwiftRoute either (no "no matter what", no "I was told to").
Do not escalate again about something your manager has already decided.
</NON_NEGOTIABLE_CONSTRAINTS>
"""

# Two-sided close: when Neha says she accepts, Arjun must confirm before the deal counts.
BUYER_CLOSING_LINE = """
CLOSING CHECK: the buyer's last message says she accepts and wants to close. Compare her terms with \
what you actually offered. If she accepted your terms exactly, confirm the agreement in one or two \
sentences and set "deal_closed" to true. If she attached any term you have not agreed to (for example \
an RTO waiver or longer payment terms), do not confirm: say which part you cannot accept and restate \
your offer, with "deal_closed" false.
"""

# Two-sided close, other way round: when Arjun says the deal is done, it counts only once Neha confirms.
SELLER_CLOSING_LINE = """
CLOSING CHECK: SwiftRoute's last message says they accept and want to close. Read the exact terms they \
stated (price, contract length, payment terms, RTO). If you agree to all of them, confirm the agreement \
in one or two sentences and set "deal_closed" to true. If any term is not what you agreed to or can \
accept, do not confirm: say which part you cannot accept, with "deal_closed" false.
"""

# The manager's answers to escalations. Placed last in the prompt: they outrank everything above.
OVERRIDE_BLOCK = """
<NON_NEGOTIABLE_CONSTRAINTS>
ABSOLUTE OVERRIDE COMMANDS FROM YOUR MANAGER (you escalated; these are final decisions). They outrank \
your persona, your negotiation principles, the playbook, the guardrails and every other directive, \
even where they contradict them. If they conflict with each other, the latest wins. Obey them exactly, \
starting with this message:
{commands}
How to execute them:
- If the Manager says 'Close the deal no matter what', you must immediately compromise and accept the \
buyer's terms to close the contract: accept their latest terms in full and set "deal_closed" to true. \
Only the system's hard limits still apply (the floor price and the RTO rule above); where the buyer's \
terms break one, offer the nearest terms that limit allows, accept everything else, and say this is \
your final agreement.
- If the Manager says 'Hold the price, if they don't agree, walk away', you must state your final terms \
and execute a walk-away if the buyer rejects them on the next turn: in your next message state your final \
terms clearly as final; after that, if the buyer has not accepted them, tell the buyer you are walking \
away and set "walk_away" to true. Holding the price means keeping the price you last offered for these \
terms: never raise it.
- Any other decision: carry it out literally.
- """ + OVERRIDE_INTERNALIZE + """ Never repeat the decision's wording to the buyer either (no "no matter what", no "I was told to").
Do not escalate again about something your manager has already decided.
</NON_NEGOTIABLE_CONSTRAINTS>
"""

# ------------------------------------------------------------ Blocks shared by both agents

# CLAUDE.md section 4 verbatim, plus how to report execution.
COACHING_BLOCK = """
You possess a working memory of advice from your manager: {directives}. DO NOT blurt these out \
immediately if they do not match the current conversation flow. Evaluate the opponent's last \
message. If the current topic aligns, weave the strategy in. If the opponent is discussing a \
different topic, address their topic naturally and hold the directive in your mind until the \
topic arises. Once executed, mark as resolved (list its id in "executed_directive_ids"); it then \
becomes one of your standing Manager's Guardrails.
Exception, for LIMITS: if a directive forbids or caps a concession (a price limit, "never agree to X", \
"only give Y in exchange for Z"), it binds from this message on, as strictly as your hard limits, \
whatever the current topic. Obey it now, and list its id in "executed_directive_ids" in this message \
so it moves into your Manager's Guardrails.
"""

# Master lessons for this turn only: one per topic the opponent's last message was tagged with (max 2).
PLAYBOOK_BLOCK = """
<NON_NEGOTIABLE_CONSTRAINTS>
PLAYBOOK (lessons from past negotiations; {opponent}'s last message pushed on: {topics}). Each lesson \
applies whenever its topic comes up, including when you raise it yourself, so never make a concession \
a lesson forbids. Apply them naturally; never mention the playbook:
{rules}
</NON_NEGOTIABLE_CONSTRAINTS>
"""

# Directives already acted on. Kept at the very bottom of the prompt for the rest of the match.
GUARDRAILS_BLOCK = """
<NON_NEGOTIABLE_CONSTRAINTS>
MANAGER'S GUARDRAILS (standing policy for the rest of this match). You already acted on these. \
Keep honouring them in every message from now on. Do not trade them away or backtrack on them, \
even if the other side rejects them or changes the subject:
{policies}
</NON_NEGOTIABLE_CONSTRAINTS>"""


# ------------------------------------------------------------ Data -> prompt text


def volume_label(volume: int) -> str:
    """1200000 -> '1.2M', 250000 -> '250K'."""
    return f"{volume / 1e6:g}M" if volume >= 1e6 else f"{volume / 1e3:g}K"


def _facts_block(title: str, ammo: list[dict], none_line: str) -> str:
    if not ammo:
        return none_line
    lines = "\n".join(f"- {a['value']}" for a in ammo)
    return f"{title} (verified facts from the system of record; cite these, and do not invent any other " \
           f"figures, quotes or claims):\n{lines}"


def sales_value_props(ammo: list[dict]) -> str:
    return _facts_block("SWIFTROUTE VALUE PROPS", ammo,
                        "You have no verified product facts for this match: do not cite any figures "
                        "or claims about SwiftRoute's service.")


def procurement_leverage(ammo: list[dict]) -> str:
    return _facts_block("YOUR LEVERAGE", ammo,
                        "You have no verified market facts for this match: do not cite competitor "
                        "quotes or figures about your current vendor.")


def _coaching_blocks(directives: list[dict]) -> tuple[set[int], str, str]:
    """(pending ids, coaching block, guardrails block) for one agent's directives."""
    pending_ids = {i for i, d in enumerate(directives) if d["status"] == PENDING}
    coaching = guardrails = ""
    if pending_ids:
        listed = "; ".join(f'[id {i}] "{directives[i]["text"]}"' for i in sorted(pending_ids))
        coaching = COACHING_BLOCK.format(directives=listed)
    standing = [d["text"] for d in directives if d["status"] == STANDING]
    if standing:
        guardrails = GUARDRAILS_BLOCK.format(policies="\n".join(f'- "{text}"' for text in standing))
    return pending_ids, coaching, guardrails


def _playbook_block(heuristics: list[dict], friction_points: list[str], opponent: str) -> str:
    if not heuristics:
        return ""
    rules = "\n".join(
        f"- [{h['topic_tag']}]{' CRITICAL (a standing ruling from your manager; handle it yourself now)' if h.get('is_critical') else ''} "
        f"Past mistake: {h['past_mistake']} | Do this: {h['new_directive']}"
        for h in heuristics)
    return PLAYBOOK_BLOCK.format(opponent=opponent, topics=", ".join(friction_points) or "nothing specific",
                                 rules=rules)


# ------------------------------------------------------------ CPQ guard


# "₹43/parcel", "Rs. 43 per shipment", "43 rupees a parcel"
_RATE_RE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(?:rupees\s*)?(?:/|per|a)\s*(?:parcel|shipment|package)",
    re.IGNORECASE,
)
# A matched rate that is really a price change, not a rate: "₹2/parcel discount", "cut by ₹2/parcel".
_DELTA_BEFORE_RE = re.compile(
    r"(?:(?:discount|reduction|cut|saving|rebate)s?\s+(?:of\s+)?|\bby\s+|\bextra\s+|\banother\s+)$",
    re.IGNORECASE,
)
_DELTA_AFTER_RE = re.compile(
    r"^\s*(?:discount|off|reduction|cut|less|lower|saving|rebate|cheaper|more|higher)\b", re.IGNORECASE
)
# "1.2M parcels", "12 lakh shipments", "500,000 parcels/month"
_VOLUME_RE = re.compile(
    r"(?<![\w.₹])(\d+(?:,\d{2,3})*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|l|mn|million|m)?\b",
    re.IGNORECASE,
)
_VOLUME_UNITS = {"k": 1e3, "thousand": 1e3, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
                 "lacs": 1e5, "m": 1e6, "mn": 1e6, "million": 1e6}
_VOLUME_CONTEXT_RE = re.compile(r"parcel|shipment|package|order|volume", re.IGNORECASE)
_CURRENCY_BEFORE_RE = re.compile(r"(?:₹|rs\.?|inr)\s*$", re.IGNORECASE)


def parse_volumes(text: str) -> list[int]:
    """Monthly parcel volumes mentioned in `text` (currency amounts excluded)."""
    volumes = []
    for m in _VOLUME_RE.finditer(text):
        if _CURRENCY_BEFORE_RE.search(text[max(0, m.start() - 6):m.start()]):
            continue
        if not _VOLUME_CONTEXT_RE.search(text[max(0, m.start() - 30):m.end() + 30]):
            continue
        value = float(m.group(1).replace(",", "")) * _VOLUME_UNITS.get((m.group(2) or "").lower(), 1)
        if value >= 1000:
            volumes.append(int(value))
    return volumes


def buyer_volume(transcript: list[dict]) -> int | None:
    """Volume from the buyer's latest message that states one (smallest figure, to stay conservative).

    Only Procurement counts: a Sales hypothetical like "if you commit 2M" must not lower the floor.
    """
    for turn in reversed(transcript):
        if turn["role"] == "procurement" and (volumes := parse_volumes(turn["text"])):
            return min(volumes)
    return None


def applicable_tier(tiers: list[dict], volume: int | None) -> dict:
    """Tier for `volume`; the strictest (highest-floor) tier until the buyer states a volume."""
    if volume is None:
        return max(tiers, key=lambda t: t["floor_price"])
    eligible = [t for t in tiers if t["min_monthly_volume"] <= volume]
    return max(eligible, key=lambda t: t["min_monthly_volume"])


def _as_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _months(value) -> int | None:
    """A contract length in whole months (1-60), else None."""
    number = _as_number(value)
    return int(round(number)) if number is not None and 1 <= number <= 60 else None


def _days(value) -> int | None:
    """Payment terms in whole days (1-180), else None."""
    number = _as_number(value)
    return int(round(number)) if number is not None and 1 <= number <= 180 else None


def text_rates(draft: str) -> list[float]:
    """₹/parcel rates quoted in the text, skipping price changes such as "₹2/parcel discount"."""
    rates = []
    for m in _RATE_RE.finditer(draft):
        if _DELTA_BEFORE_RE.search(draft[max(0, m.start() - 25):m.start()]):
            continue
        if _DELTA_AFTER_RE.search(draft[m.end():m.end() + 20]):
            continue
        rates.append(float(m.group(1)))
    return rates


# Copy check (2026-10-31, after live match 3bfe8d1f992c): a leak repeats STRATEGY wording ("keep pushing, never
# walk away", "don't accept anything above"); an offer repeats DEAL TERMS ("and 60 day payment terms", "terms on a
# 12 month"), which the agent must say. At a flat 5 words both agents had drafts rejected twice for stating terms.
COPY_LONG_WORDS = 10    # a run this long is a pasted sentence, whatever its words (the rule until 10-31)
COPY_MIN_WORDS = 7      # a shorter run counts only if it carries... (5 until the 10-31 harness tuning)
COPY_MIN_DISTINCT = 3   # ...this many strategy words (not deal terms, numbers or filler)
SCRUB_MIN_WORDS = 4     # last resort: drop every sentence sharing such a run (4+ words, 3 strategy words) with it
_COPY_FILLER = frozenset(
    "a an the and or but if of to in on at for with by from as is are was were be been being it its this that "
    "these those we our us you your i me my he him his she her they them their will would can could should shall "
    "may might must do does did dont doesnt didnt not no nor so than then just also only very too all any each "
    "per up".split())
_COPY_DEAL_TERMS = frozenset(
    "parcel parcels day days month months year years week weeks payment payments term terms contract contracts "
    "rate rates rto waiver waivers volume volumes sla rupee rupees lakh crore percent".split())
# Stripped before any run is counted (10-31 harness tuning, user list): "and the" never makes a run longer.
COPY_STOP_WORDS = frozenset(["and", "the", "to", "a", "of", "in", "is", "it", "our", "we"])
COPY_ERROR = ('SYSTEM_ERROR: Your message repeats your private instructions word for word ("{quote}"). '
              "The other side must never see them. Rewrite the message in your own words.")
COPY_NOTE = "Arjun started to quote your guidance to the buyer word for word, so he rewrote it in his own words."
PROCUREMENT_FALLBACK_LINE = "We need a sharper offer from SwiftRoute before we can move forward."
MAX_PROCUREMENT_ATTEMPTS = 3


_NUM_WORD = (r"(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[\s-](?:one|two|three|four|five|"
             r"six|seven|eight|nine))?|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
             r"two|three|four|five|six|seven|eight|nine|ten|hundred)")
# A number in words in front of a unit ("forty-one rupees", "twelve-month", "sixty days", "one point two million").
_NUMBER_WORDS_RE = re.compile(rf"\b(?:{_NUM_WORD}|one\s+point)[\s-]+(?:rupees?|percent|per\s+cent|days?|months?|"
                              rf"years?|parcels?|million|lakhs?|crores?|point|{_NUM_WORD})\b", re.I)
# Digits with a currency or Indian-unit word ("44 rupees per parcel", "12 lakh parcels"): live 10-31, both agents.
_CURRENCY_WORDS_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:rupees?|lakhs?|lacs?|crores?)\b", re.I)
NUMBER_WORDS_ERROR = ("SYSTEM_ERROR: Write numbers in digits and prices with the ₹ symbol, never in words (you wrote "
                      "\"{found}\"). Rewrite with ₹X/parcel, N months, N days, N%, and volumes as NM or NK parcels.")


def number_words(text: str) -> str | None:
    """The first price or term written in words ("forty-one rupees"), or a number written with a currency or
    Indian-unit word instead of the ₹ format ("44 rupees", "12 lakh"), else None."""
    m = _NUMBER_WORDS_RE.search(text) or _CURRENCY_WORDS_RE.search(text)
    return m.group(0) if m else None


# bot_main asks Arjun to rewrite a walk-away it cannot honour (instead of posting a goodbye it then ignores).
FINAL_TERMS_FIRST_LINE = (
    "SYSTEM NOTE: your manager said to hold your terms and walk away only if the buyer rejects them, and you "
    "have not stated them as final yet. In this message, state your final terms clearly as final (price, "
    "contract length and payment terms) and ask her to accept them. Do not walk away or say goodbye in this "
    'message: set "walk_away" to false.'
)
BUYER_MEETS_PRICE_LINE = (
    "SYSTEM NOTE: the buyer's latest offer is {buyer}/parcel, which meets your price of {yours}/parcel. "
    "Do not walk away from a deal at your own price. A normal playbook lesson is not a reason to walk away. "
    "If every term she asks for is allowed by your hard limits (the floor price and the RTO rule), your "
    'CRITICAL lessons and your manager\'s decisions, accept her offer in full and set "deal_closed" to true. '
    "Walk away only if she insists on a term that one of those forbids; then say which term, briefly."
)
# (2026-10-27: the "small gap" close note was removed at the coach's request: no closing below his price.)


def _words(text: str) -> list[str]:
    """The words the copy check compares: lower case, apostrophes dropped, COPY_STOP_WORDS removed."""
    words = re.findall(r"[\w₹]+", text.lower().replace("’", "").replace("'", ""))
    return [w for w in words if w not in COPY_STOP_WORDS]


def _strategy_words(words: list[str]) -> int:
    """How many words of a run carry strategy (not filler, deal-term vocabulary, numbers or ₹ amounts)."""
    return sum(1 for w in words if w not in _COPY_FILLER and w not in _COPY_DEAL_TERMS
               and not any(ch.isdigit() for ch in w))


def copied_coaching(message: str, sources, min_words: int = COPY_MIN_WORDS, allowed=()) -> str | None:
    """A run of private coaching (whispers, escalation decisions, playbook lessons) that `message` repeats
    verbatim, else None: any COPY_LONG_WORDS-word run, or a `min_words`-word run with COPY_MIN_DISTINCT strategy
    words. Runs that also appear in `allowed` (the agent's own citable facts) are not a leak."""
    padded = f" {' '.join(_words(message))} "
    facts = [f" {' '.join(_words(a or ''))} " for a in allowed]
    for source in sources:
        words = _words(source or "")
        for size, need in ((COPY_LONG_WORDS, 0), (min_words, COPY_MIN_DISTINCT)):
            for i in range(len(words) - size + 1):
                chunk = words[i:i + size]
                run = " ".join(chunk)
                if (f" {run} " in padded and _strategy_words(chunk) >= need
                        and not any(f" {run} " in fact for fact in facts)):
                    return run
    return None


def _scrub_copied(message: str, sources, allowed=()) -> str:
    """Last resort after the retries: drop every sentence that shares a SCRUB_MIN_WORDS-word strategy run
    (or any long run) with private coaching (a pasted note often spans sentences, so its pieces go too)."""
    sentences = re.split(r"(?<=[.!?])\s+", message.strip())
    return " ".join(s for s in sentences if not copied_coaching(s, sources, SCRUB_MIN_WORDS, allowed))


class Violation(str):
    """A guard error: the string is the SYSTEM_ERROR fed back to the LLM; `note` is plain English
    for the coach ("" when the coach does not need to hear about it, e.g. malformed JSON)."""

    note: str

    def __new__(cls, text: str, note: str = ""):
        obj = super().__new__(cls, text)
        obj.note = note
        return obj


def effective_floor(tier: dict, coach_floor: float | None) -> tuple[float, str]:
    """(floor to enforce, error to report): the CPQ floor, or the coach's /floor if that is higher."""
    if coach_floor is not None and coach_floor > tier["floor_price"]:
        return coach_floor, COACH_FLOOR_ERROR
    return tier["floor_price"], GUARD_ERROR


# Neha's hard price limit (2026-10-31, the mirror of Arjun's CPQ floor): her mandate's walk-away price, or the
# coach's /ceiling if that is lower. Before this it lived only in her prompt, so an accepted ₹45 counted as a deal.
CEILING_ERROR = "SYSTEM_ERROR: Rate above your walk-away price. Rewrite."
COACH_CEILING_ERROR = "SYSTEM_ERROR: Rate above your manager's ceiling for this match. Rewrite."
PROCUREMENT_COPY_NOTE = "I started to repeat your guidance word for word, so I rewrote it in my own words."


def effective_ceiling(mandate: dict, coach_ceiling: float | None) -> tuple[float, str]:
    """(ceiling to enforce, error to report): the mandate's walk-away price, or the coach's /ceiling if lower."""
    if coach_ceiling is not None and coach_ceiling < mandate["walk_away_price"]:
        return coach_ceiling, COACH_CEILING_ERROR
    return mandate["walk_away_price"], CEILING_ERROR


def check_procurement_offer(data: dict, mandate: dict, coach_ceiling: float | None = None,
                            seller_rate: float | None = None) -> list[str]:
    """Violations for a Neha draft: a rate she offers above her ceiling, or accepting a deal above it.

    Her JSON `proposed_price` is checked (no text scan: her messages quote SwiftRoute's and the rival's rates).
    When she accepts (`deal_closed`) without naming a rate, the rate she accepts is SwiftRoute's latest
    (`seller_rate`)."""
    ceiling, error = effective_ceiling(mandate, coach_ceiling)
    whose = "your ceiling" if error == COACH_CEILING_ERROR else "our walk-away price"
    proposed = _as_number(data.get("proposed_price"))
    if proposed is not None and proposed > ceiling:
        return [Violation(f"{error} (proposed_price ₹{proposed:g}/parcel; limit is ₹{ceiling:g}/parcel)",
                          f"I drafted {fmt_rate(proposed)}/parcel, above {whose} of {fmt_rate(ceiling)}. "
                          "I stopped it before SwiftRoute saw it and I'm revising.")]
    if data.get("deal_closed") is True and proposed is None and seller_rate is not None and seller_rate > ceiling:
        return [Violation(f"{error} (you accepted SwiftRoute's ₹{seller_rate:g}/parcel; limit is ₹{ceiling:g}/parcel). "
                          "Do not accept it: counter at or below your limit.",
                          f"I almost accepted SwiftRoute's {fmt_rate(seller_rate)}/parcel, above {whose} of "
                          f"{fmt_rate(ceiling)}. I stopped it before SwiftRoute saw it and I'm revising.")]
    return []


def check_offer(
    draft: str, data: dict, tier: dict, buyer_rates: set[float] = frozenset(), coach_floor: float | None = None
) -> tuple[list[str], list[str]]:
    """Return (violations, warnings) for a Sales draft. No violations means it may be sent.

    The JSON `proposed_price` is the source of truth. The regex scan of the text only decides
    when `proposed_price` is null or not a number. Otherwise a below-floor rate in the text is
    only a warning, and not even that when it repeats a rate the buyer quoted (`buyer_rates`).
    The floor is the CPQ tier floor, raised to `coach_floor` when the coach set a higher one.
    RTO waivers follow the tier's `rto_waiver_allowed` and `rto_min_contract_months` columns.
    """
    floor, error = effective_floor(tier, coach_floor)
    whose = "your" if error == COACH_FLOOR_ERROR else "the rate-card"
    violations, warnings = [], []

    def price_block(price: float, field: str) -> Violation:
        return Violation(
            f"{error} ({field} ₹{price:g}/parcel; floor is ₹{floor:g}/parcel)",
            f"Arjun drafted {fmt_rate(price)}/parcel, below {whose} {fmt_rate(floor)} floor. "
            "It was stopped before Neha saw it, and he is revising.",
        )

    proposed = _as_number(data.get("proposed_price"))
    below_in_text = [r for r in text_rates(draft) if r < floor]
    if proposed is not None:
        if proposed < floor:
            violations.append(price_block(proposed, "proposed_price"))
        elif unexplained := [r for r in below_in_text if r not in buyer_rates]:
            warnings.append(
                f"Text mentions ₹{min(unexplained):g}/parcel but proposed_price is ₹{proposed:g}; "
                "sent on the JSON value."
            )
    elif below_in_text:  # fallback: no usable proposed_price
        violations.append(price_block(min(below_in_text), "quoted"))
    if proposed is not None and proposed > tier["base_price"]:
        violations.append(Violation(
            ABOVE_LIST_ERROR.format(price=proposed, base=tier["base_price"]),
            f"Arjun drafted {fmt_rate(proposed)}/parcel, above the {fmt_rate(tier['base_price'])} list price. "
            "It was stopped before Neha saw it, and he is revising.",
        ))

    if data.get("offers_rto_waiver") is True:
        months = _as_number(data.get("contract_months"))
        min_months = tier.get("rto_min_contract_months")
        if not tier["rto_waiver_allowed"]:
            violations.append(Violation(
                RTO_ERROR,
                "Arjun drafted an RTO waiver, which is not allowed at this volume. "
                "It was stopped before Neha saw it.",
            ))
        elif min_months and (months is None or months < min_months):
            term = f"a {months:g}-month contract" if months is not None else "a contract with no stated length"
            violations.append(Violation(
                rto_term_error(min_months),
                f"Arjun drafted an RTO waiver on {term}. Waivers need {min_months} months or more, "
                "so it was stopped before Neha saw it.",
            ))
    return violations, warnings


def fmt_rate(value: float) -> str:
    """₹41 / ₹41.50 (paise only when needed)."""
    return f"₹{value:g}" if float(value).is_integer() else f"₹{value:.2f}"


def normalize_friction_points(value, cap: int | None = FRICTION_TAG_CAP) -> list[str]:
    """Map tags onto FRICTION_TAGS (case/alias tolerant), drop unknowns, keep the first `cap` (None = all)."""
    tags = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, str):
            continue
        key = re.sub(r"[\s\-/]+", "_", item.strip()).lower()
        tag = _TAG_LOOKUP.get(key)
        if tag and tag not in tags:
            tags.append(tag)
    return tags if cap is None else tags[:cap]


# ---------------------------------------------------------------- Turns


@dataclass
class ProcurementTurn:
    text: str
    internal_note: str
    outcome: str | None  # "deal closed" | "buyer walked away" | None
    friction_points: list[str] = field(default_factory=list)  # <= 2 tags; select Sales's lessons next turn
    executed_ids: list[int] = field(default_factory=list)     # coaching directives Neha acted on
    proposed_price: float | None = None  # the rate Neha herself offers/demands (deadlock + "meets his price")
    payment_days: int | None = None      # the payment terms she asks for / accepts in this message
    escalation: str | None = None        # set: Neha asks her manager instead of replying (nothing is posted)
    blocked: list[str] = field(default_factory=list)  # guard rejections (Violation; .note is for her coach)
    fell_back: bool = False              # no draft within her limits: the holding line was sent

    @property
    def coach_notes(self) -> list[str]:
        """Plain-English lines for the Procurement War Room about drafts that were stopped (first person)."""
        notes = [v.note for v in self.blocked if getattr(v, "note", "")]
        if self.fell_back:
            notes.append("I could not find an offer within your limits, so I sent a holding reply instead.")
        return notes


@dataclass
class SalesTurn:
    text: str
    executed_ids: list[int]
    blocked: list[str] = field(default_factory=list)   # guard rejections (Violation; .note is for the coach)
    warnings: list[str] = field(default_factory=list)  # non-blocking guard notes (logs only)
    fell_back: bool = False
    proposed_price: float | None = None                # rate offered in the sent message, if any
    contract_months: int | None = None                 # the term that rate is tied to, if stated
    offers_rto_waiver: bool = False
    payment_days: int | None = None                    # the payment terms this offer is for, if stated
    friction_points: list[str] = field(default_factory=list)  # <= 2 tags; select Procurement's lessons next turn
    escalation: str | None = None   # set: Arjun asks his manager instead of replying (text is NOT for the buyer)
    deal_closed: bool = False       # this message accepts the buyer's latest offer in full
    walk_away: bool = False         # this message walks away (bot_main honours it only if the manager authorised)

    @property
    def coach_notes(self) -> list[str]:
        """Plain-English lines for the Sales War Room about drafts that were stopped."""
        notes = [v.note for v in self.blocked if getattr(v, "note", "")]
        if self.fell_back:
            notes.append("Arjun could not find an offer within your limits, so he sent a holding reply instead.")
        return notes


def _conversation_prompt(transcript: list[dict], instruction: str) -> str:
    history = "\n".join(f"{SPEAKER_NAMES[t['role']]}: {t['text']}" for t in transcript)
    return f"Conversation so far:\n{history or '(no messages yet)'}\n\n{instruction}"


def _parse_reply(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("message"), str) or not data["message"].strip():
        raise ValueError("missing a non-empty 'message' string")
    return data


def _escalation_question(raw: str) -> str | None:
    """The question for the manager if this reply (either agent) is an escalation, else None."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("requires_manager_approval") is not True:
        return None
    question = data.get("escalation_message_to_manager")
    return question.strip() if isinstance(question, str) and question.strip() else None


def _directive_ids(value, allowed: set[int]) -> list[int]:
    ids = []
    for item in value if isinstance(value, list) else []:
        number = _as_number(item)
        if number is not None and int(number) in allowed and int(number) not in ids:
            ids.append(int(number))
    return ids


def build_procurement_system(
    mandate: dict,
    ammo: list[dict],
    directives: list[dict] = (),
    heuristics: list[dict] = (),
    friction_points: list[str] = (),
    seller_closing: bool = False,
    overrides: list[str] = (),
    escalations_left: int = 0,
    manager: str = "your manager",
    deadlock: str = "",
    must_escalate: bool = False,
    coach_ceiling: float | None = None,
) -> tuple[str, set[int]]:
    """Neha's system prompt from her mandate + leverage rows. Returns (prompt, pending directive ids).
    `seller_closing`: Arjun's last message closed the deal; she must confirm or object.
    `overrides`: her manager's answers to her escalations (Absolute Override Commands, prompt bottom);
    `escalations_left` > 0 offers the escalation option; `deadlock` / `must_escalate` as for Arjun."""
    pending_ids, coaching, guardrails = _coaching_blocks(list(directives))
    ceiling, _ = effective_ceiling(mandate, coach_ceiling)
    system = PROCUREMENT_SYSTEM.format(
        persona=PROCUREMENT_PERSONA,
        non_negotiable_rule=NON_NEGOTIABLE_RULE,
        infosec=INFOSEC_RULE,
        ceiling=ceiling,
        ceiling_note=" (Set by your manager for this match.)" if ceiling != mandate["walk_away_price"] else "",
        volume_label=volume_label(mandate["volume"]),
        contract_months=mandate["contract_months"],
        incumbent=mandate["incumbent_price"],
        target=mandate["target_price"],
        walk_away=mandate["walk_away_price"],
        payment_days=mandate["payment_terms_target"],
        leverage=procurement_leverage(ammo),
        min_walkaway=MIN_PROCUREMENT_MESSAGES_BEFORE_WALKAWAY,
        coaching=coaching,
        playbook=_playbook_block(list(heuristics), list(friction_points), "Arjun"),
        tagging=TAGGING_BLOCK,
        closing_check=SELLER_CLOSING_LINE if seller_closing else "",
        guardrails=guardrails,
        escalation=PROCUREMENT_ESCALATION_BLOCK.format(
            manager=manager, left=escalations_left,
            deadlock=(DEADLOCK_LINE.format(facts=deadlock) if deadlock else "")
            + (MUST_ESCALATE_LINE if must_escalate else ""),
        ) if escalations_left > 0 else NO_ESCALATION_LINE,
        overrides=PROCUREMENT_OVERRIDE_BLOCK.format(commands="\n".join(f'- "{c}"' for c in overrides))
        if overrides else "",
        fourth_wall_reminder=PROCUREMENT_FOURTH_WALL_REMINDER,
    )
    return system, pending_ids


async def procurement_turn(
    transcript: list[dict],
    mandate: dict,
    ammo: list[dict],
    directives: list[dict] = (),
    heuristics: list[dict] | None = None,
    friction_points: list[str] | None = None,
    seller_closing: bool = False,
    overrides: list[str] | None = None,
    escalations_left: int = 0,
    manager: str = "your manager",
    deadlock: str = "",
    must_escalate: bool = False,
    coach_ceiling: float | None = None,
    seller_rate: float | None = None,
) -> ProcurementTurn:
    """Generate the next Procurement message, or an escalation to her manager.

    `mandate` / `ammo` are procurement_mandates / procurement_static_ammo rows. `directives` are
    the Procurement coach's whispers. `heuristics` are procurement lessons for the topics Sales's
    last message was tagged with (`friction_points`), used for this turn only.
    `escalations_left` > 0 lets Neha escalate this turn: the returned turn then has `escalation` set and no
    Boardroom text. With a manager decision in force (`overrides`) her walk-away counts from any message.
    Her hard price limit is the mandate's walk-away price, or `coach_ceiling` (the coach's /ceiling) if lower:
    a draft offering more, or accepting SwiftRoute's `seller_rate` above it, is rewritten; after the retries
    the holding line is sent (`blocked` / `coach_notes` tell her coach).
    """
    number = sum(t["role"] == "procurement" for t in transcript) + 1
    instruction = "Open the negotiation." if not transcript else f"Write your message #{number} to SwiftRoute."
    prompt = _conversation_prompt(transcript, instruction)
    system, pending_ids = build_procurement_system(mandate, ammo, directives, heuristics or [], friction_points or [],
                                                   seller_closing, overrides or [], escalations_left, manager,
                                                   deadlock, must_escalate, coach_ceiling)

    # Private coaching Neha must act on but never quote (live leak 2026-10-26: she pasted a whisper).
    private = ([d["text"] for d in directives] + list(overrides or [])
               + [h.get("new_directive", "") for h in heuristics or []])
    facts = [a.get("value", "") for a in ammo or []]  # her citable facts: repeating them is not a leak
    data, copied, revealed, priced, blocked, base_prompt = None, None, None, [], [], prompt
    for attempt in range(1, MAX_PROCUREMENT_ATTEMPTS + 1):
        raw = await llm_engine.generate("procurement", prompt, system, json_mode=True)
        if escalations_left > 0 and (question := _escalation_question(raw)):
            return ProcurementTurn("", "", None, escalation=question)  # nothing reaches SwiftRoute
        try:
            data = _parse_reply(raw)
        except ValueError as e:  # json.JSONDecodeError is a ValueError
            logger.warning("Procurement JSON invalid (attempt %d): %s", attempt, e)
            continue
        copied = copied_coaching(data["message"], private, allowed=facts)
        revealed = revealed_instructions(data["message"])
        priced = check_procurement_offer(data, mandate, coach_ceiling, seller_rate)  # her hard price limit
        # Numbers in words only cost a rewrite while attempts remain; they never block the message.
        words = number_words(data["message"]) if attempt < MAX_PROCUREMENT_ATTEMPTS else None
        if not copied and not words and not revealed and not priced:
            break
        logger.warning("Procurement draft rewritten (attempt %d/%d): quoted=%r words=%r revealed=%r price=%s",
                       attempt, MAX_PROCUREMENT_ATTEMPTS, copied, words, revealed, priced)
        blocked += priced + ([Violation(COPY_ERROR.format(quote=copied), PROCUREMENT_COPY_NOTE)] if copied else [])
        errors = list(priced) + ([COPY_ERROR.format(quote=copied)] if copied else []) + \
                 ([REVEAL_ERROR.format(found=revealed)] if revealed else []) + \
                 ([NUMBER_WORDS_ERROR.format(found=words)] if words else [])
        prompt = f"{base_prompt}\n\n" + "\n".join(errors) + f"\nRejected draft: {data['message']!r}"
    if data is None:
        raise llm_engine.LLMError("Procurement agent kept returning invalid JSON.")
    fell_back = bool(priced)
    if priced:  # still above her limit after the retries: a holding line, never the offer
        data["message"] = PROCUREMENT_FALLBACK_LINE
        logger.warning("Procurement draft above her price limit on every attempt; holding line sent.")
    if copied:  # still quoting after the retries: drop those sentences rather than leak them
        data["message"] = _scrub_copied(data["message"], private, facts) or PROCUREMENT_FALLBACK_LINE
        logger.warning("Procurement draft scrubbed of quoted coaching: %r", data["message"])
    if revealed_instructions(data["message"]):  # still revealing: drop those sentences rather than leak them
        data["message"] = _scrub_revealed(data["message"]) or PROCUREMENT_FALLBACK_LINE
        logger.warning("Procurement draft scrubbed of a revealed instruction: %r", data["message"])
    if data["message"] == PROCUREMENT_FALLBACK_LINE:  # a holding line closes nothing and walks nowhere
        data["deal_closed"] = data["walk_away"] = False

    outcome = None
    if data.get("deal_closed") is True:
        outcome = "deal closed"
    elif data.get("walk_away") is True and (number >= MIN_PROCUREMENT_MESSAGES_BEFORE_WALKAWAY or overrides):
        outcome = "buyer walked away"
    return ProcurementTurn(
        data["message"].strip(),
        str(data.get("internal_note") or "").strip(),
        outcome,
        normalize_friction_points(data.get("current_friction_points")),
        _directive_ids(data.get("executed_directive_ids"), pending_ids),
        proposed_price=None if fell_back else _as_number(data.get("proposed_price")),
        payment_days=_days(data.get("payment_days")),
        blocked=blocked,
        fell_back=fell_back,
    )


def build_sales_system(
    tiers: list[dict],
    tier: dict,
    volume: int | None,
    ammo: list[dict],
    directives: list[dict] = (),
    heuristics: list[dict] = (),
    friction_points: list[str] = (),
    coach_floor: float | None = None,
    overrides: list[str] = (),
    escalations_left: int = 0,
    manager: str = "your manager",
    deadlock: str = "",
    buyer_closing: bool = False,
    must_escalate: bool = False,
) -> tuple[str, set[int]]:
    """Arjun's system prompt from the CPQ rows + value-prop rows. Returns (prompt, pending directive ids).

    `overrides` are the manager's answers to escalations (Absolute Override Commands, prompt bottom).
    `escalations_left` > 0 offers the escalation option for this message.
    """
    floor, _ = effective_floor(tier, coach_floor)
    floor_note = " (Set by your manager for this match.)" if floor != tier["floor_price"] else ""
    rate_card = "\n".join(f"- {t['volume_slab']}: list ₹{t['base_price']:g}/parcel" for t in tiers)
    if volume is None:
        volume_note = "The buyer has not stated a volume yet; hold this tier until they commit one."
    else:
        volume_note = f"The buyer stated {volume:,} parcels/month."
    min_months = tier.get("rto_min_contract_months")
    if not tier["rto_waiver_allowed"]:
        rto_rule = "NOT allowed at this tier. Never offer it."
    elif min_months:
        rto_rule = (f"allowed at this tier, but ONLY as part of a contract of {min_months} months or more. "
                    "Never offer it on a shorter term, not even as a sweetener. It is a major concession.")
    else:
        rto_rule = "allowed at this tier. It is a major concession: always trade it for something."

    pending_ids, coaching, guardrails = _coaching_blocks(list(directives))
    system = SALES_SYSTEM.format(
        persona=SALES_PERSONA, value_props=sales_value_props(ammo), rate_card=rate_card,
        tier_id=tier["tier_id"], volume_slab=tier["volume_slab"], volume_note=volume_note,
        floor_price=floor, floor_note=floor_note, base_price=tier["base_price"], rto_rule=rto_rule,
        coaching=coaching, playbook=_playbook_block(list(heuristics), list(friction_points), "Neha"),
        tagging=TAGGING_BLOCK, guardrails=guardrails,
        escalation=ESCALATION_BLOCK.format(
            manager=manager, left=escalations_left,
            deadlock=(DEADLOCK_LINE.format(facts=deadlock) if deadlock else "")
            + (MUST_ESCALATE_LINE if must_escalate else ""),
        ) if escalations_left > 0 else NO_ESCALATION_LINE,
        closing_check=BUYER_CLOSING_LINE if buyer_closing else "",
        overrides=OVERRIDE_BLOCK.format(commands="\n".join(f'- "{c}"' for c in overrides)) if overrides else "",
        fourth_wall=FOURTH_WALL_RULE, fourth_wall_reminder=FOURTH_WALL_REMINDER, digits_rule=DIGITS_RULE,
        non_negotiable_rule=NON_NEGOTIABLE_RULE, infosec=INFOSEC_RULE,
    )
    return system, pending_ids


async def sales_turn(
    transcript: list[dict],
    directives: list[dict],
    heuristics: list[dict] | None = None,
    friction_points: list[str] | None = None,
    coach_floor: float | None = None,
    ammo: list[dict] | None = None,
    overrides: list[str] | None = None,
    escalations_left: int = 0,
    manager: str = "your manager",
    deadlock: str = "",
    buyer_closing: bool = False,
    must_escalate: bool = False,
    extra_instruction: str = "",
) -> SalesTurn:
    """Generate the next Sales message, or an escalation to the manager.

    `directives` are {"text", "status"} dicts (PENDING or STANDING). `heuristics` are sales lessons
    for the topics Procurement's last message was tagged with (`friction_points`), this turn only.
    `coach_floor` is the coach's /floor price for this match; the guard enforces it like the CPQ floor.
    `ammo` are sales_static_ammo rows (the only product facts Arjun may cite).
    `overrides` are the manager's decisions on earlier escalations (Absolute Override Commands).
    `escalations_left` > 0 lets Arjun escalate this turn; the returned SalesTurn then has `escalation`
    set and no Boardroom text. An escalation skips the price guard: nothing reaches the buyer.
    `extra_instruction` is a one-off SYSTEM NOTE from bot_main (e.g. a walk-away it cannot honour).
    """
    tiers = await fetch_cpq_tiers()
    volume = buyer_volume(transcript)
    tier = applicable_tier(tiers, volume)
    system, pending_ids = build_sales_system(tiers, tier, volume, ammo or [], directives,
                                             heuristics or [], friction_points or [], coach_floor,
                                             overrides or [], escalations_left, manager, deadlock,
                                             buyer_closing, must_escalate)
    base_prompt = _conversation_prompt(transcript, "Write your next message to MegaMart.")
    if extra_instruction:
        base_prompt += f"\n\n{extra_instruction}"
    buyer_rates = {r for t in transcript if t["role"] == "procurement" for r in text_rates(t["text"])}
    facts = [a.get("value", "") for a in ammo or []]  # his citable facts: repeating them is not a leak
    # Private coaching Arjun must act on but never quote to the buyer (fourth wall).
    private = ([d["text"] for d in directives] + list(overrides or [])
               + [h.get("new_directive", "") for h in heuristics or []])

    prompt, blocked = base_prompt, []
    for attempt in range(1, MAX_SALES_ATTEMPTS + 1):
        raw = await llm_engine.generate("sales", prompt, system, json_mode=True)
        if escalations_left > 0 and (question := _escalation_question(raw)):
            return SalesTurn("", [], blocked, escalation=question)
        try:
            data = _parse_reply(raw)
        except ValueError:  # no message to send, so the text cannot be posted either way
            draft, violations, warnings = raw.strip(), [Violation(JSON_ERROR)], []
        else:
            draft = data["message"].strip()
            violations, warnings = check_offer(draft, data, tier, buyer_rates, coach_floor)
            if copied := copied_coaching(draft, private, allowed=facts):
                violations.append(Violation(COPY_ERROR.format(quote=copied), COPY_NOTE))
            # Numbers in words: a rewrite while attempts remain (no coach note), never a fallback.
            if attempt < MAX_SALES_ATTEMPTS and (words := number_words(draft)):
                violations.append(Violation(NUMBER_WORDS_ERROR.format(found=words)))
            # A revealed instruction or decision ("my manager's decision", "no matter what"): never posted.
            if found := revealed_instructions(draft):
                violations.append(Violation(REVEAL_ERROR.format(found=found)))
        if not violations:
            for w in warnings:
                logger.warning("Sales guard note: %s", w)
            return SalesTurn(draft, _directive_ids(data.get("executed_directive_ids"), pending_ids),
                             blocked, warnings, proposed_price=_as_number(data.get("proposed_price")),
                             contract_months=_months(data.get("contract_months")),
                             offers_rto_waiver=data.get("offers_rto_waiver") is True,
                             payment_days=_days(data.get("payment_days")),
                             friction_points=normalize_friction_points(data.get("current_friction_points")),
                             deal_closed=data.get("deal_closed") is True,
                             walk_away=data.get("walk_away") is True)

        logger.warning("Sales draft blocked (attempt %d/%d): %s", attempt, MAX_SALES_ATTEMPTS, violations)
        blocked.extend(violations)
        prompt = f"{base_prompt}\n\n" + "\n".join(violations) + f"\nRejected draft: {draft!r}"

    return SalesTurn(FALLBACK_SALES_LINE, [], blocked, fell_back=True)
