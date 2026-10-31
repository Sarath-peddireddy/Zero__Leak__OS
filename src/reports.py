"""
ZeroLeak OS - End-of-negotiation executive reports.

When a match ends, one extraction call (judge key, JSON mode) reads the transcript
and records where the terms stand. Every number in the reports is then computed
here in Python from those terms, the CPQ rate card and MegaMart's brief
(the match's procurement_mandates row), so no LLM does any arithmetic. The extracted rate must also
be a rate that actually appears in the negotiation, or the last Sales offer is used.

Two reports, written for executives (no internal IDs or system jargon):
  * procurement_report() - Neha -> Head of Procurement (Procurement War Room DM)
  * sales_report()       - Head of Sales / CRO           (Sales War Room DM)
Both are Telegram HTML (send with parse_mode="HTML"); all model and coach text is escaped.
"""

import json
import logging
from dataclasses import dataclass, field
from html import escape

import llm_engine
from negotiation import SELF_PLAY, STANDING, applicable_tier, buyer_volume, fmt_rate, text_rates, volume_label
from post_match import OPEN_PROPOSAL, SKIP_REASONS as SKIP_WHY
import shadow_test

logger = logging.getLogger("zeroleak.reports")

TOPIC_LABELS = {
    "Price": "Price", "RTO": "RTO waiver", "Payment_Terms": "Payment terms",
    "Contract_Length": "Contract length", "Volume": "Volume", "SLA": "Service levels",
    "Competitor_Quote": "Competitor quotes", "Tech_Integration": "Tech / integration",
    "Communication_Tone": "Communication tone",
}

# end_code -> (Sales headline, Procurement headline)
OUTCOMES = {
    "deal": ("✅ Agreement reached", "✅ Agreement reached"),
    "walkaway": ("❌ No agreement: MegaMart walked away", "❌ No agreement: we walked away"),
    "coach": ("⏸ Closed by your team before agreement", "⏸ Closed before agreement"),
    "cap": ("⏸ No agreement within the session limit", "⏸ No agreement within the session limit"),
    "sales_walkaway": ("🛑 No agreement: we walked away, on your decision",
                       "❌ No agreement: SwiftRoute walked away"),
    "error": ("⚠️ Stopped early: the AI service was unavailable",
              "⚠️ Stopped early: the AI service was unavailable"),
}

DEAL_SYSTEM = """\
You are a commercial analyst. Read this negotiation between MegaMart India (the buyer, Neha) and \
SwiftRoute Logistics (the supplier, Arjun) for a last-mile freight contract, and record where the \
terms stand at the end. Use only what is in the transcript; never invent terms. If they agreed, \
record the agreed terms. Otherwise record SwiftRoute's latest offer that is still on the table.
Output JSON strictly in this format:
{
  "rate_per_parcel": <rupees per parcel as a number, or null if no rate was offered>,
  "rto_waiver": "included" | "not_included" | "not_discussed",
  "payment_terms_days": <days as a number, or null if not settled>,
  "contract_months": <months as a number, or null if not stated>,
  "buyer_commitments": ["<each thing MegaMart committed to, short>"],
  "open_items": ["<each point still unresolved or conditional, short>"],
  "procurement_summary": "<2 sentences for MegaMart's Head of Procurement on how it went and the result>",
  "sales_summary": "<2 sentences for SwiftRoute's CRO on how it went and the result>",
  "next_step": "<the single next action, short>"
}"""


@dataclass
class DealTerms:
    rate: float | None = None
    rto_waiver: str = "not_discussed"          # included | not_included | not_discussed
    payment_days: int | None = None
    contract_months: int | None = None
    buyer_commitments: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    procurement_summary: str = ""
    sales_summary: str = ""
    next_step: str = ""


# ------------------------------------------------------------- Extraction


def _int_in(value, low: int, high: int) -> int | None:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _strings(value, limit: int = 4) -> list[str]:
    return [s.strip() for s in value if isinstance(s, str) and s.strip()][:limit] if isinstance(value, list) else []


def _last_offer(match: dict) -> float | None:
    offers = [p for p in match.get("sales_offers", []) if p is not None]
    return offers[-1] if offers else None


def _validated_rate(value, match: dict) -> float | None:
    """The extracted rate only if it was really quoted in the negotiation; else the last Sales offer."""
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return _last_offer(match)
    quoted = {r for t in match["transcript"] for r in text_rates(t["text"])}
    quoted |= {p for p in match.get("sales_offers", []) if p is not None}
    if any(abs(rate - q) < 0.01 for q in quoted):
        return rate
    logger.warning("Extracted rate %s never appeared in the negotiation; using the last offer.", rate)
    return _last_offer(match)


async def extract_terms(match: dict) -> DealTerms:
    """Final terms from the transcript. Falls back to the last Sales offer if the model is unavailable."""
    if not match["transcript"]:
        return DealTerms()
    history = "\n".join(
        f"{'Neha (MegaMart)' if t['role'] == 'procurement' else 'Arjun (SwiftRoute)'}: {t['text']}"
        for t in match["transcript"]
    )
    try:
        raw = await llm_engine.generate("judge", f"TRANSCRIPT:\n{history}", DEAL_SYSTEM,
                                        json_mode=True, temperature=0)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (ValueError, llm_engine.LLMError) as e:
        logger.warning("Deal extraction failed (%s); report uses the last Sales offer only.", e)
        return DealTerms(rate=_last_offer(match), rto_waiver="included" if match.get("rto_offered") else "not_discussed")

    rto = data.get("rto_waiver")
    return DealTerms(
        rate=_validated_rate(data.get("rate_per_parcel"), match),
        rto_waiver=rto if rto in ("included", "not_included", "not_discussed") else "not_discussed",
        payment_days=_int_in(data.get("payment_terms_days"), 0, 180),
        contract_months=_int_in(data.get("contract_months"), 1, 60),
        buyer_commitments=_strings(data.get("buyer_commitments")),
        open_items=_strings(data.get("open_items")),
        procurement_summary=str(data.get("procurement_summary") or "").strip(),
        sales_summary=str(data.get("sales_summary") or "").strip(),
        next_step=str(data.get("next_step") or "").strip(),
    )


# -------------------------------------------------------------- Formatting


def inr(amount: float) -> str:
    """Indian-style money: ₹3.60 Cr, ₹30 lakh, ₹45,000."""
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1e7:
        return f"{sign}₹{amount / 1e7:.2f} Cr"
    if amount >= 1e5:
        return f"{sign}₹{amount / 1e5:.1f}".rstrip("0").rstrip(".") + " lakh"
    return f"{sign}₹{amount:,.0f}"


def _bullets(items: list[str]) -> list[str]:
    return [f"• {escape(i)}" for i in items]


def _context(match: dict, tiers: list[dict]) -> tuple[int, dict, int]:
    mandate = match["mandate"]
    volume = buyer_volume(match["transcript"]) or mandate["volume"]
    return volume, applicable_tier(tiers, volume), mandate["contract_months"]


def _coaching_lines(directives: list[dict]) -> list[str]:
    applied = sum(d["status"] == STANDING for d in directives)
    return [f"• Your guidance: {len(directives)} sent, {applied} applied"]


def _lesson_lines(outcomes: list | None, side: str) -> list[str]:
    """"Playbook changes proposed" for one side: every change waits for the coach's approval (staging gate)."""
    if outcomes is None:
        return ["• Could not be reviewed this time (the AI service was unavailable)."]
    mine = [o for o in outcomes if o.side == side]
    if not mine:
        return ["• None: no guidance was sent and no fourth-wall slip was found."]
    # One entry per topic (one master lesson per topic): the live lesson and the proposed replacement.
    lines, by_topic = [], {}
    for o in mine:
        if o.action == "skipped":
            why = SKIP_WHY.get(o.reason)
            lines.append(f"• Not saved: “{escape(o.whisper[:80])}”" + (f" ({why})" if why else ""))
        elif o.action == "unchanged":
            covered = "the change already waiting for your OK" if o.reason == OPEN_PROPOSAL else "the current lesson"
            lines.append(f"• No change: “{escape(o.whisper[:80])}” is already covered by {covered}")
        else:
            by_topic.setdefault(o.topic_tag, []).append(o)
    for topic, outs in by_topic.items():
        last = outs[-1]  # later notes on a topic fold into the same proposal
        kinds = {getattr(o, "kind", "whisper") for o in outs}
        tag = ("critical, from your decision; " if "escalation" in kinds else "") +               ("fourth-wall watchdog; " if "watchdog" in kinds else "")
        notes = f", from {len(outs)} notes" if len(outs) > 1 else ""
        lines.append(f"• <b>{TOPIC_LABELS.get(topic, topic)}</b> ({tag}waiting for your OK{notes})")
        lines.append(f"   <i>Current:</i> {escape(last.previous) if last.previous else 'none (first lesson on this topic)'}")
        lines.append(f"   <i>Proposed:</i> {escape(last.directive)}")
        if last.reason:
            lines.append(f"   ⚠️ {escape(last.reason)}")
    if by_topic:
        follow = ("A shadow test is running now; the approval request follows with its results."
                  if shadow_test.SHADOW_MATCHES > 0 else "The approval request follows.")
        lines.append(f"<i>Live lessons stay as they are until you approve. {follow}</i>")
    return lines


def procurement_report(match: dict, terms: DealTerms, tiers: list[dict], judge_outcomes: list | None = None) -> str:
    """Neha's report to MegaMart's Head of Procurement."""
    volume, _, default_months = _context(match, tiers)
    months = terms.contract_months or default_months
    agreed = match["end_code"] == "deal"
    lines = [
        "<b>📋 Negotiation report: SwiftRoute Logistics</b>",
        f"Last-mile freight · {volume_label(volume)} parcels/month",
        f"<b>Outcome:</b> {OUTCOMES[match['end_code']][1]}",
        "",
        f"<b>{'Agreed terms' if agreed else 'Last offer from SwiftRoute'}</b>",
    ]
    rto = {"included": "Secured ✅", "not_included": "Not secured ❌", "not_discussed": "Not discussed"}
    mandate = match["mandate"]
    target_days = mandate["payment_terms_target"]
    if terms.payment_days is None:
        pay = "Not settled"
    else:
        pay = f"{terms.payment_days} days" + ("" if terms.payment_days >= target_days else f" (we asked for {target_days})")
    lines += [
        f"• Rate: {fmt_rate(terms.rate)}/parcel" if terms.rate is not None else "• Rate: not settled",
        f"• RTO penalty waiver: {rto[terms.rto_waiver]}",
        f"• Payment terms: {pay}",
        f"• Contract length: {months} months",
    ]

    if terms.rate is not None:
        incumbent, target, walkaway = (mandate["incumbent_price"], mandate["target_price"],
                                      mandate["walk_away_price"])
        saving = incumbent - terms.rate
        lines += ["", f"<b>{'Savings' if agreed else 'Savings if accepted'} vs current vendor ({fmt_rate(incumbent)}/parcel)</b>"]
        if saving > 0:
            lines += [
                f"• {fmt_rate(saving)}/parcel ({saving / incumbent:.1%} lower)",
                f"• {inr(saving * volume)} per month · {inr(saving * volume * months)} over {months} months",
            ]
        else:
            lines.append(f"• No saving: {fmt_rate(-saving)}/parcel above our current vendor")
        lines += ["", "<b>Against our mandate</b>"]
        over_target = terms.rate - target
        lines.append(f"• Target {fmt_rate(target)}: " + (
            "met ✅" if over_target <= 0 else f"{fmt_rate(over_target)} above target"))
        lines.append(f"• Walk-away {fmt_rate(walkaway)}: " + (
            f"within limit ✅ ({fmt_rate(walkaway - terms.rate)} headroom)" if terms.rate <= walkaway
            else f"exceeded ❌ by {fmt_rate(terms.rate - walkaway)}"))
        offers = [p for p in match.get("sales_offers", []) if p is not None]
        if offers and offers[0] > terms.rate:
            moved = offers[0] - terms.rate
            lines.append(f"• SwiftRoute opened at {fmt_rate(offers[0])} and moved {fmt_rate(moved)} "
                         f"({moved / offers[0]:.1%})")

    if terms.buyer_commitments:
        lines += ["", "<b>What we committed to</b>", *_bullets(terms.buyer_commitments)]
    if terms.open_items:
        lines += ["", "<b>Open items</b>", *_bullets(terms.open_items)]
    if terms.procurement_summary:
        lines += ["", "<b>Summary</b>", escape(terms.procurement_summary)]
    if terms.next_step:
        lines += ["", f"<b>Next step:</b> {escape(terms.next_step)}"]
    directives = match.get("procurement_coaching_directives", [])
    asked = match.get("procurement_escalations", [])  # Neha's questions to the Head of Procurement
    if directives or asked:
        lines += ["", "<b>Your guidance</b>", *(_coaching_lines(directives) if directives else [])]
    for e in asked:
        answer = f"you decided “{escape(e['decision'])}”" if e["decision"] else "no decision in time"
        lines.append(f"• 🙋 I asked you: “{escape(e['question'])}”: {answer}")
    if SELF_PLAY and (directives or judge_outcomes):  # Neha's learning is parked until Phase B
        lines += ["", "<b>Playbook changes proposed</b>", *_lesson_lines(judge_outcomes, "procurement")]
    elif directives:
        lines += ["", "<b>Learning</b>", "• I used your guidance in this negotiation only. My learning is "
                  "switched off for now, so I keep a fixed strategy while SwiftRoute's agent is measured."]
    lines += ["", "— Neha, Procurement Manager"]
    return "\n".join(lines)


def sales_report(match: dict, terms: DealTerms, tiers: list[dict], judge_outcomes: list | None) -> str:
    """Deal and coaching report for SwiftRoute's Head of Sales / CRO."""
    volume, tier, default_months = _context(match, tiers)
    months = terms.contract_months or default_months
    agreed = match["end_code"] == "deal"
    list_price, floor = tier["base_price"], tier["floor_price"]
    lines = [
        "<b>📊 Deal report: MegaMart India</b>",
        f"Last-mile freight · {volume_label(volume)} parcels/month · {len(match['transcript'])} messages",
        f"<b>Outcome:</b> {OUTCOMES[match['end_code']][0]}",
        "",
        f"<b>{'Agreed terms' if agreed else 'Our last offer'}</b>",
    ]
    rto = {"included": "Given", "not_included": "Not given", "not_discussed": "Not discussed"}
    if terms.rate is not None:
        discount = list_price - terms.rate
        rate_line = f"• Rate: {fmt_rate(terms.rate)}/parcel (list {fmt_rate(list_price)}"
        rate_line += f", {discount / list_price:.1%} discount)" if discount > 0 else ")"
        lines.append(rate_line)
    else:
        lines.append("• Rate: not settled")
    lines += [
        f"• RTO waiver: {rto[terms.rto_waiver]}",
        f"• Payment terms: {f'{terms.payment_days} days' if terms.payment_days is not None else 'Not settled'}",
        f"• Contract length: {months} months",
    ]

    if terms.rate is not None:
        monthly = terms.rate * volume
        margin = terms.rate - floor
        lines += ["", f"<b>Commercials{'' if agreed else ' (if accepted)'}</b>",
                  f"• Revenue: {inr(monthly)}/month · {inr(monthly * months)} contract value",
                  f"• Above our floor: {fmt_rate(margin)}/parcel ({inr(margin * volume)}/month)"
                  if margin > 0 else "• At our floor price: no margin above floor"]
        if list_price > terms.rate:
            lines.append(f"• Discount from list: {fmt_rate(list_price - terms.rate)}/parcel "
                         f"({inr((list_price - terms.rate) * volume)}/month)")
        walkaway = match["mandate"]["walk_away_price"]
        if agreed and terms.rate < walkaway:
            gap = walkaway - terms.rate
            lines += ["", "<b>Missed upside</b>",
                      f"• MegaMart would have paid up to {fmt_rate(walkaway)}/parcel: {fmt_rate(gap)}/parcel "
                      f"left on the table ({inr(gap * volume)}/month · {inr(gap * volume * months)} over the contract)"]

    lines += ["", "<b>Coaching</b>", *_coaching_lines(match["active_coaching_directives"])]
    for e in match.get("escalations", []):  # Arjun's questions to the Head of Sales
        answer = f"you decided “{escape(e['decision'])}”" if e["decision"] else "no decision in time"
        lines.append(f"• 🙋 Arjun asked: “{escape(e['question'])}”: {answer}")
    if match.get("coach_floor") is not None:
        lines.append(f"• Your floor: {fmt_rate(match['coach_floor'])}/parcel")
    if match.get("blocked_count"):
        lines.append(f"• Offers stopped before Neha saw them: {match['blocked_count']}")
    if match.get("playbook_topics"):
        used = ", ".join(TOPIC_LABELS.get(t, t) for t in sorted(match["playbook_topics"]))
        lines.append(f"• Lessons from past negotiations in play: {used}")

    lines += ["", "<b>Playbook changes proposed</b>", *_lesson_lines(judge_outcomes, "sales")]

    if terms.sales_summary:
        lines += ["", "<b>Summary</b>", escape(terms.sales_summary)]
    if terms.next_step:
        lines += ["", f"<b>Next step:</b> {escape(terms.next_step)}"]
    return "\n".join(lines)
