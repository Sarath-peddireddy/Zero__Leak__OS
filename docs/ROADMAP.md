# ZeroLeak OS - Roadmap

## Phase A (current): Verify the Sales Agent and the Judge

Goal: prove that Arjun (Sales) listens to his manager and gets better over time, against a **fixed** opponent.
Neha's learning stays off, so any change in Arjun's play comes from Arjun's own lessons.

- [x] Whispers (one-way coaching) with pending → standing guardrails
- [x] Judge turns whispers into one master lesson per topic (`sales_heuristics`, Highlander UPSERT)
- [x] Two-way escalation ("Ask Sarath"): Arjun asks for a decision when deadlocked; the Boardroom holds; the answer is an Absolute Override Command
- [x] Absolute overrides: "Close the deal no matter what" and "Hold the price, if they don't agree, walk away" (Arjun can now close or walk away)
- [x] Judge turns every answered escalation into a CRITICAL lesson so the same deadlock is handled alone next time
- [x] Deadlock alert + backstop (the model "played it safe" and never asked), two-sided close (Neha's false acceptances)
- [x] Verification runs (2026-10-25, real Gemini, DB copy): match 1 escalated → CRITICAL lesson; match 3 handled the same deadlock alone (no escalation, walked away using the lesson)
- [ ] Repeat the verification in Telegram, and over more matches (deal rate, escalations per match should fall)
- [ ] Decide: may a CRITICAL lesson authorise walking away alone, or should it only make Arjun hold and ask again?
- [x] Decided 2026-10-31: price / payment-day / step-size lessons are NOT enforced by code checks; Arjun learns them through the playbook (only CPQ floor, `/floor` and the RTO-months rule are hard)

## LLM Prompt Polish (Low Priority)

Arjun gaps parked on 2026-10-31 (coach decision: numeric limits are learned through the playbook, not hard-coded checks).
Each one is caught by an existing guard or is cosmetic; none has cost a deal yet.

- [ ] **Drafts "floor"**: Arjun keeps reaching for "our floor" / "hard floor" (blocked 3× in the 10-30 benchmark, 2× in the 10-30 live test). `INTERNAL_WORDS_ERROR` rewrites it every time, nothing is posted, but each block costs a Gemini call.
- [ ] **Invents exceptions**: "I have gone straight to leadership and secured a one-time exception" (match bc8aed9bc422). Not a fact from the system of record.
- [ ] **Rate format**: "44 rupees per parcel" instead of "₹44/parcel" (copies Neha's style, match 396808c63f6e). Digits are kept; the price guard reads the JSON price, so it is cosmetic.

## Phase B (current from 2026-10-31): Adversarial Self-Play

Goal: both agents learn, so each one's improvement pressures the other.

**Already built, switched off** (`ZEROLEAK_SELF_PLAY=1` turns it on; see `negotiation.SELF_PLAY`):
- Procurement database: `procurement_mandates`, `procurement_static_ammo`, `procurement_heuristics` (UNIQUE topic_tag)
- Procurement Judge: "Head of Global Sourcing at MegaMart" persona for `Procure_Whisper` rows, UPSERT into `procurement_heuristics` (separate reward model from the "VP of Sales at SwiftRoute" persona that audits Arjun)
- Symmetrical tagging: both agents tag their own message (max 2); the tags select the opponent's lessons
  - 2026-10-31: plus a keyword scan of the opponent's message text (`negotiation.retrieval_tags`), both sides, and Communication_Tone lessons on every turn
- Judge safety (2026-10-30, both sides): screening, scope, proposals for risky changes with coach approval
- Procurement War Room whispers (these stay live in Phase A, so the coach can steer the sparring partner)

**Still to build:**
1. **Outcome-based lessons (no human needed):** after each match the Judge scores both sides against their goals (Sales: margin over floor, concessions given cheaply; Procurement: distance to target, headroom left under walk-away) and writes lessons for whichever side lost ground.
2. **Procurement guard:** block `deal_closed` above `walk_away_price`; add `/ceiling` for the Procurement coach (mirror of `/floor`).
3. **Procurement escalation:** two-way "Ask the Head of Procurement" for Neha, with the same override rules.
4. **Headless self-play runner:** play N matches back to back without Telegram, with a scoreboard per match (deal rate, average price, messages to close). *Built early for Phase A (`headless_runner.py`, 2026-10-26): before/after playbook arms, fixed Neha note, auto manager, Judge off. For Phase B it still needs both agents learning between matches.*
5. **Persona depth parity:** give Neha a negotiation framework as rich as Arjun's.
6. **Personas in the database:** company and agent names (MegaMart / SwiftRoute / Neha / Arjun) move into SQLite, so a new buyer or seller is a data change.
