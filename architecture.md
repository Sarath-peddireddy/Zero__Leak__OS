## 1. System Overview & Constraints

**Goal:** Build "ZeroLeak OS" using a native Python async state machine, local SQLite, and the Google GenAI SDK (Gemini).
**End-goal (Phase 6): Adversarial Self-Play.** Sales and Procurement are both data-driven, both coachable, and both learn from coaching, without growing the LLM context window.
**Strict Constraints:**

* **NO heavy AI frameworks:** Do not use LangChain, CrewAI, AutoGen, or LlamaIndex. Use the official `google-genai` SDK and native Python logic.
* **API Key Mapping:** The system has 3 Gemini API keys. Each key is primary for one agent and a fallback for the other two (`llm_engine.py`).
* Key 1 ➡️ Sales Agent LLM
* Key 2 ➡️ Procurement Agent LLM
* Key 3 ➡️ Judge/Synthesizer Agent LLM (also the end-of-match deal extraction in `reports.py`)


* **Telegram Bot Blindness Fix:** Telegram bots CANNOT natively see messages sent by other bots. Therefore, the Python backend must act as the central brain. It tracks the conversation state internally and manually passes the opponent's generated text into the next agent's prompt.
* **Zero-Hardcode Prompts:** Prompt text in `negotiation.py` holds behaviour only ("be aggressive", "never give a concession for free"). Every number and fact (prices, budgets, SLA stats, pain points, RTO rules) comes from SQLite.
* **Side isolation:** Each agent only ever sees its own side's tables. The buyer's mandate never reaches the Sales prompt; the rate card never reaches the Procurement prompt.

## 2. Infrastructure & Libraries

* `python-telegram-bot` (v20+): For async Telegram polling. You must run TWO bot `Application` instances concurrently in the same `asyncio` event loop.
* `sqlite3`: Native Python library for database operations (wrapped in `asyncio.to_thread`).
* `google-genai`: Official Gemini SDK for LLM generation.
* `dotenv`: For managing the 2 Bot Tokens and 3 Gemini Keys (+ optional `COACH_NAME`, `GEMINI_MODEL`).

## 3. Symmetrical Database (`db_init.py`, file `zeroleak.db`)

| Sales side (SwiftRoute) | Procurement side (MegaMart) | Purpose |
|---|---|---|
| `sales_cpq_pricing` | `procurement_mandates` | Hard numbers (rate card & floors / budget, target, walk-away) |
| `sales_static_ammo` | `procurement_static_ammo` | Citable facts (`fact_type`, `value`) |
| `sales_heuristics` | `procurement_heuristics` | Learned lessons (`topic_tag` **UNIQUE**, `past_mistake`, `new_directive`) |

Shared: `match_transcripts` (the ledger: `match_id`, `timestamp`, `speaker`, `payload_text`).

* `sales_cpq_pricing`: `tier_id`, `volume_slab`, `min_monthly_volume`, `base_price`, `floor_price`, `rto_waiver_allowed`, `rto_min_contract_months` (RTO waiver only with a contract at least this long; NULL = no term rule).
* `procurement_mandates`: `mandate_id`, `volume`, `incumbent_price`, `target_price`, `walk_away_price`, `payment_terms_target` (days), `contract_months`. The lowest `mandate_id` is the active mandate.
* `match_transcripts.speaker`: `Sales_Agent`, `Procure_Agent`, `Human_Whisper` (coaching to Sales), `Procure_Whisper` (coaching to Procurement), `Sales_Escalation` (Arjun asks the manager), `Manager_Decision` (the answer).
* Both heuristics tables also have `is_critical` (1 = learned from a deadlock the manager had to break; never resets on merge).
* **The "Highlander" constraint:** `topic_tag` is `UNIQUE` in both heuristics tables. There can be only one master rule per topic, so the playbook never grows past one row per tag (7 tags → max 7 rows per side).
* Topic vocabulary (shared by tags and lessons): `Price, RTO, Payment_Terms, Contract_Length, Volume, SLA, Competitor_Quote` (`negotiation.FRICTION_TAGS`).
* Startup seeds dummy data idempotently (fixed primary keys + `INSERT OR IGNORE`) and migrates older databases in place: `cpq_pricing` → `sales_cpq_pricing`, `playbook_heuristics` → `sales_heuristics`, ledger CHECK widened for `Procure_Whisper`.

## 4. The Central State Machine (`Shared_State`)

Do not rely on Telegram for message history. Maintain a Python dictionary in memory to track active matches (`bot_main.new_match`).

```python
active_matches = {
    group_chat_id: {
        "match_id": "e71bd12fe20e",
        "status": "AWAITING_PROCUREMENT" | "AWAITING_SALES" | "ENDED",
        "paused": False, "running": asyncio.Event(),      # /pause gate (set = live)
        "coaching_rev": {"sales": 0, "procurement": 0},  # new guidance since a reply was held?
        "transcript": [],                       # {"role": "sales|procurement", "text": "..."}
        # Loaded from SQLite once, at match start (zero-hardcode):
        "mandate": {...}, "sales_ammo": [...], "procurement_ammo": [...],
        # Whispers: {"text": str, "status": "pending_injection" | "standing_policy"}
        "active_coaching_directives": [],       # Sales coach -> Arjun
        "procurement_coaching_directives": [],  # Procurement coach -> Neha
        # Each agent's tags for its latest message (max 2) -> select the OPPONENT's lessons
        "procurement_friction_points": [], "sales_friction_points": [],
        "coach_floor": None,                    # /floor price from the Sales War Room
        "sales_war_room_chat_id": 123456789,
        "procurement_war_room_chat_id": 123456789,  # DM with the Procurement bot (None if not started)
        ...                                     # report facts: sales_offers, rto_offered, blocked_count, end_code
    }
}
war_room_to_group = {}       # Sales War Room DM id -> group id
proc_war_room_to_group = {}  # Procurement War Room DM id -> group id
```

## 5. Architectural Rules & Data Flow

### Rule 1: The Negotiation Loop (The Boardroom)

1. **Match start:** `/start_negotiation` loads `procurement_mandates`, `sales_static_ammo` and `procurement_static_ammo` into the match.
2. **Procurement Turn:** Python fetches `procurement_heuristics` for Sales's last tags (max 2 rows), then calls Gemini Key 2 with the mandate, leverage facts, Neha's coaching and those lessons.
3. **Broadcast:** Python uses `Procurement_Bot_Token` to send the text to the Telegram Group (Boardroom).
4. **Internal Sync:** Python appends text to the transcript and the ledger; stores Neha's tags in `procurement_friction_points`.
5. **Token Pass:** Python switches status to `AWAITING_SALES`.
6. **Sales Turn:** Python fetches `sales_heuristics` for Procurement's tags (max 2 rows) and the CPQ tier, then calls Gemini Key 1 with the transcript, rate card, value facts, Arjun's coaching and those lessons. The CPQ guard checks the draft.
7. **Broadcast:** Python uses `Sales_Bot_Token` to send the text to the Telegram Group; stores Arjun's tags in `sales_friction_points`.

### Rule 2: The Whisper Interrupt (Symmetrical War Rooms)

1. Human sends a DM to the **Sales bot** (Sales War Room) or to the **Procurement bot** (Procurement War Room).
2. The Telegram `MessageHandler` of that bot intercepts this DM.
3. It does NOT trigger an LLM immediately. It appends `{"text", "status": "pending_injection"}` to that side's directives and logs it to the ledger (`Human_Whisper` / `Procure_Whisper`).
4. The system confirms receipt to the human in plain language ("Noted. … Limits apply straight away.").
5. The agent weaves a pending directive in when the topic fits (limits bind immediately) and reports it in `executed_directive_ids`. It then becomes `standing_policy`: listed in "MANAGER'S GUARDRAILS" at the bottom of that agent's prompt for the rest of the match, and the coach gets a ✅.

### Rule 2b: Pause / Resume

* `/pause` / `/resume` (Boardroom buttons ⏸ / ▶️, or typed in the Boardroom or either War Room DM) toggle `match["running"]` (an `asyncio.Event`).
* `bot_main.next_turn()` checks it at two safe points: **before** an agent starts generating, and **after** a reply is generated but **before** it is posted. A reply that was mid-generation when the coach paused is held, so nothing appears after the pause notice.
* On resume, the held reply is posted unchanged (no extra LLM call), unless that side received new guidance during the pause (`match["coaching_rev"]`). Then it is regenerated so the whisper applies immediately.
* While live, the gate costs nothing; the 2-3s pace between messages is unchanged.
* The Boardroom has no "/" command menu (two bots in a group make Telegram post "/cmd@botname"). Both bots handle bare Boardroom commands; each command message is handled once and deleted if the bot has admin rights.

### Rule 2c: Two-Way Escalation (Ask the Manager)

* Sales JSON adds `requires_manager_approval`, `escalation_message_to_manager`, `deal_closed`, `walk_away`.
* When Arjun escalates, **nothing is posted to the Boardroom**. Status becomes `AWAITING_MANAGER_APPROVAL`, and the question goes to the Sales War Room with two preset answers ("Close the deal no matter what" / "Hold the price, if they don't agree, walk away") or free text.
* The manager's reply becomes an **Absolute Override Command**, the last block of every later Sales prompt in the match. Arjun then writes his Boardroom reply under it.
* Limits: not before Arjun's 2nd message, max 3 per match, no re-ask right after a decision, 15-minute timeout (then he continues alone).
* Deadlocks are measured in Python: the same price 3× in a row or 8 messages triggers an alert in the prompt. At 5× or 10 messages escalation is required; if Arjun ignores that, the system asks on his behalf.
* Closing is two-sided both ways: Neha's `deal_closed` needs Arjun's confirmation, and Arjun's `deal_closed` (when she had not just accepted) needs hers: her next prompt gets `SELLER_CLOSING_LINE`; she confirms → deal, she objects → the negotiation goes on (`match["seller_closing"]`; a close on the last allowed message still gets her reply). Added 2026-10-28 after a recorded "deal" at terms she never accepted.
* Walk-aways are checked **before** the message is posted (`bot_main.walk_block()`), so a goodbye the system cannot honour never reaches the Boardroom:
  * no manager decision and no CRITICAL lesson in play → Arjun asks the manager instead ("I'm ready to walk away… I need your OK"); if he can't escalate now, he rewrites once and keeps negotiating;
  * first message after "Hold…walk away" → rewrite as clear final terms (the walk counts only after the buyer replies);
  * Neha's latest rate meets his price → rewrite: close, unless a hard limit, a CRITICAL lesson or the manager's decision forbids one of her terms. "His price" is his latest rate for HER contract length (a rate tied to a longer term does not count; `arjun_rate_for_buyer_term`). The note is given once per price position (`match["meets_noted"]`), so an authorised walk over a non-price term (e.g. payment days) is not blocked every turn;
  * No "small gap" close (removed 2026-10-27, coach decision: ₹1/parcel is millions over a contract). A gap of any size is handled like any other walk-away.
* Sales guard extras: an offer above the tier's list price is blocked (coach note); after "Hold the price…" he keeps his last price and never raises it; internal words ("floor", "guardrails", "playbook", "directives", "override") are rewritten while attempts remain (`negotiation.internal_words()`).
* Neha must settle payment terms before she accepts (a deal needs price, contract length and payment terms).
* Neha's JSON includes her own `proposed_price`, so the deadlock measure sees the buyer: no deadlock alert while she is moving up, and no "has not accepted" when she meets his price.
* Ledger speakers `Sales_Escalation` and `Manager_Decision` feed the Judge, which stores each answered escalation as a **CRITICAL** lesson (`is_critical = 1`) so Arjun can handle that deadlock alone next time.
* Phase B (Neha's learning) is parked behind `ZEROLEAK_SELF_PLAY=1`, so she stays a fixed opponent while Arjun's learning is measured.

### Rule 3: Database Integration (Zero Hallucination)

Before Gemini Key 1 (Sales Agent) generates a response, the Python orchestrator must:

1. Query `sqlite3` table `sales_cpq_pricing`.
2. Format the pricing rules as a strict string (e.g., *"Floor price is 41. Do not go below."*), plus the tier's RTO rule.
3. Inject this dynamically into the Gemini System Prompt for that specific turn.

Both agents may only cite the facts in their own `*_static_ammo` table ("do not invent any other figures, quotes or claims").

**Digits:** both prompts require numbers in digits (₹X/parcel, N months, N days, N%); a draft with a price or term in words ("forty-one rupees") is rewritten while attempts remain (`negotiation.number_words()`).

**Quoted coaching:** a draft that repeats 10+ words in a row from a whisper, manager decision or lesson is rewritten (both agents); Neha's is scrubbed as a last resort.

**Fourth wall:** Arjun's prompt forbids mentioning the system to the buyer ("per our playbook", "according to my manager", "my directives", "critical lesson"): a hard limit, repeated as the last line of the prompt so it also holds under manager overrides (`negotiation.FOURTH_WALL_RULE` / `FOURTH_WALL_REMINDER`).

### Rule 4: Symmetrical JIT Retrieval & the 2-Tag Cap

* Both agents' JSON output includes `"current_friction_points": []`, tagging **the message they are writing** (the one the opponent replies to).
* Both prompts contain: *"You must categorize your message into strict topics. You are limited to a MAXIMUM of 2 tags per message. Select only the primary and secondary driving factors."* Python also truncates to 2 (`FRICTION_TAG_CAP`).
* Before Procurement's turn: `procurement_heuristics` by Sales's tags. Before Sales's turn: `sales_heuristics` by Procurement's tags. Because `topic_tag` is UNIQUE, that is at most 2 rules per turn, injected for that turn only. This avoids "Lost in the Middle" confusion.

## 6. The Judge Agent & Memory Compaction (`post_match.py`)

Runs in the background after every match (`bot_main.debrief`), before the two reports are sent.

1. **Data prep:** For every `Human_Whisper` / `Procure_Whisper` in the ledger, take the 3 preceding Boardroom messages.
2. **Synthesis:** Gemini Key 3, JSON mode → `{topic_tag, past_mistake, new_directive}`. **Reward-model separation:** each side is audited by its own boss (`post_match.JUDGE_PERSONAS`), used for the synthesis, escalation and merge calls of that side only:
   * Arjun (`Human_Whisper`, `Manager_Decision`) → "VP of Sales at SwiftRoute": maximize margin, defend the floor, extract long-term value → `sales_heuristics`.
   * Neha (`Procure_Whisper`, only with `ZEROLEAK_SELF_PLAY=1`) → "Head of Global Sourcing at MegaMart": squeeze vendor margin, anchor low, minimize cost → `procurement_heuristics`.
3. **Highlander UPSERT:** Under a per-side lock, fetch the master rule for `topic_tag`.
   * None → `INSERT`.
   * Exists → one fast merge call folds the new lesson into it (keep every number and condition; **the newest coaching wins on conflicts**; each field under 60 words), then `INSERT … ON CONFLICT(topic_tag) DO UPDATE`. The reported similarity (0-100) is informational only.
   * Unusable merge output → whisper skipped and the existing rule is left untouched (never overwritten unmerged).
4. Lessons appear in the reports: Sales lessons in the Sales report, Procurement lessons in Neha's report.

## 7. Step-by-Step Build Sequence

* **Phase 1: Database & Dummy Data** (`db_init.py`) ✅
* **Phase 2: Gemini LLM Wrapper** (`llm_engine.py`) ✅
* **Phase 3: The Telegram Dual-Bot Orchestrator** (`bot_main.py`) ✅
* **Phase 4: The Simulation Loop** (`negotiation.py` + `bot_main.py`) ✅
* **Phase 5: The Judge Agent & Compaction** (`post_match.py`) ✅
* **Phase 6: Adversarial Self-Play** ✅ (2026-10-25)
  1. Symmetrical schema + Highlander `UNIQUE(topic_tag)`
  2. Judge UPSERT compaction (both sides)
  3. Zero-hardcode prompts (mandate + static ammo from SQLite)
  4. Symmetrical JIT retrieval with the 2-tag cap
  5. Symmetrical War Rooms (Procurement whispers)

## 7b. Measuring: the headless runner (`headless_runner.py`)

Plays matches without Telegram through the real `bot_main.run_match` (stand-in bots), on database copies in `bench_runs/<timestamp>/`. Arms: `before` (empty sales playbook) vs `after` (current playbook), interleaved; same Neha note every match; escalations answered by a fixed policy; Judge off. Scores deal rate, terms, offers, escalations, guard blocks, walk-away rewrites, leaks and numbers-in-words into `results.json`. Offline tests: `tests\run_all.cmd`.

## 8. Error Handling

* **LLM Hallucination:** If the Sales LLM outputs a price below the floor (CPQ, or the coach's `/floor` if higher), it is caught before it reaches Telegram. The JSON `proposed_price` is checked first, with a regex fallback. The LLM is forced to regenerate with `"SYSTEM_ERROR: Proposed price below CPQ limit. Rewrite."` An RTO waiver at a disallowed tier, or on a contract shorter than `rto_min_contract_months`, is blocked the same way. After 3 failed attempts a safe holding line is sent.
* **Telegram Rate Limits:** Implement a 2-to-3 second `asyncio.sleep()` between agent messages to prevent Telegram from throttling the bots and to simulate "typing" time.
* **Network / LLM failures:** Key failover in `llm_engine.py`; when every key fails with a network error or 408/5xx (DNS blip, model overload), the whole chain is retried after 2/5/15/30s, for up to 3 minutes; Boardroom posts retried on network errors; a crashed match ends with a friendly closing line and still gets a debrief.
