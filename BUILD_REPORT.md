# ZeroLeak OS — Build Report (Phase 0 → Phase 5)

What has been built so far, how it fits together, why each decision was made, and how the agents actually behaved in testing.

---

## 1. Where we are

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Environment setup (`requirements.txt`, `.gitignore`, `Handoff.md`) | ✅ Done |
| 1 | SQLite schema + seeded CPQ rate card (`db_init.py`) | ✅ Done |
| 2 | Gemini wrapper with a 3-key failover pool (`llm_engine.py`) | ✅ Done |
| 3 | Dual Telegram bot orchestrator (`bot_main.py`) | ✅ Done |
| 4 | Autonomous negotiation loop + CPQ guard (`negotiation.py`, `bot_main.py`) | ✅ Done |
| 4.5 | Standing directives, JSON-first CPQ guard, friction-point tags, elite AE persona | ✅ Done |
| 5 | Judge Agent, heuristic compaction, JIT retrieval, value props (`post_match.py`) | ✅ Done |

**What works today:** run one command, type `/start_match` in a Telegram group, and the MegaMart Procurement Agent and the SwiftRoute Sales Agent negotiate on their own. You can coach Sales live from a private DM. Sales cannot quote below the database floor price, and every message is written to the SQLite ledger.

**The learning loop (Phase 5):** when a match ends, the Judge Agent turns each coaching whisper into a playbook rule and merges near-duplicates. In later matches, each rule is injected into the Sales prompt whenever MegaMart pushes on that rule's topic. The Sales War Room gets a deal report, including the lessons saved, after every match.

---

## 2. File map

```
zeroleakos/
├── claude.md            Product vision & strict rules (given)
├── architecture.md      Build spec & phase sequence (given)
├── Handoff.md           Session "save state" (bulleted, updated after every step)
├── BUILD_REPORT.md      This file
├── requirements.txt     python-telegram-bot, google-genai, python-dotenv
├── .gitignore           .env, __pycache__/, *.db, .venv/
├── .env                 2 Telegram tokens + 3 Gemini keys (never read by Claude, names only)
├── .venv/               Project virtualenv (Python 3.15.0)
├── zeroleak.db          SQLite database (generated, gitignored)
│
├── db_init.py           Schema, seed data, async DB helpers
├── llm_engine.py        Gemini client pool, key failover, generate()
├── negotiation.py       Agent personas, prompts, value props, turn logic, CPQ guard, FRICTION_TAGS
├── post_match.py        Judge Agent: whisper → heuristic, compaction (merge/insert), CLI
└── bot_main.py          Telegram bots, Shared_State, simulation loop, commands, Judge trigger
```

Dependency direction (no cycles):

```
bot_main.py ──► post_match.py ──► negotiation.py ──► llm_engine.py ──► Gemini API
     │               │                  │
     └───────────────┴──────────────────┴──► db_init.py ──► zeroleak.db
```

`negotiation.py` and `post_match.py` hold no Telegram code, and `bot_main.py` holds no prompt text. Routing and reasoning stay separate, so the negotiation logic can be tested without Telegram.

---

## 3. System architecture

### 3.1 The three chats

```
                 ┌──────────────────────────────────────────┐
                 │   CHAT 1: BOARDROOM  (Telegram group)    │
                 │                                          │
                 │   the Procurement bot  ◄──── turns ────►  the Sales bot
                 │   (Neha, Procurement)            (Arjun, Sales)
                 └───────▲──────────────────────────────▲───┘
                         │ posts                        │ posts
                         │                              │
┌────────────────────────┴──────────────────────────────┴────────────────────┐
│                    PYTHON ORCHESTRATOR  (bot_main.py)                      │
│                                                                            │
│   active_matches[group_id] ─ transcript, directives, status, match_id      │
│   run_match() ping-pong loop ─ negotiation.py ─ llm_engine.py ─ Gemini     │
│   CPQ guard ◄── cpq_pricing          ledger ──► match_transcripts          │
└────────▲──────────────────────────┬─────────────────────────┬──────────────┘
         │ whispers                 │ ✅ / 🛑 + deal report     │ Neha's end report
┌────────┴──────────────────────────▼───┐   ┌─────────────────▼──────────────┐
│ CHAT 2: SALES WAR ROOM (DM w/ Sales)  │   │ CHAT 3: PROCUREMENT WAR ROOM   │
│ Human coach sends whispers here       │   │ (DM w/ Procurement bot)        │
└───────────────────────────────────────┘   └────────────────────────────────┘
```

### 3.2 Why Python is the "central brain"

Telegram bots cannot see messages sent by other bots. The Sales bot never sees what the Procurement bot posts, so Telegram cannot carry the conversation. The orchestrator keeps the transcript in memory and passes the opponent's text into each agent's prompt. Telegram only displays the match.

### 3.3 One negotiation round

```
run_match loop                         negotiation.py / llm_engine.py           Telegram / SQLite
──────────────                         ──────────────────────────────           ─────────────────
status = AWAITING_PROCUREMENT
  typing indicator ──────────────────────────────────────────────────────────► Boardroom
  procurement_turn(transcript) ───────► Gemini (PROC key) → JSON
  [if /end_match arrived meanwhile → discard and exit]
  post() ────────────────────────────────────────────────────────────────────► Boardroom (Proc bot)
                                                                             ► transcript[] + ledger
  internal_note ─────────────────────────────────────────────────────────────► server log only
  deal_closed / walk_away? → finish_match()
status = AWAITING_SALES
  sleep 2–3s
  typing indicator ──────────────────────────────────────────────────────────► Boardroom
  sales_turn(transcript, directives)
      fetch_cpq_tiers() ◄─────────────────────────────────────────────────────  cpq_pricing
      buyer_volume() → applicable_tier()
      build prompt (floor + open whispers)
      Gemini (SALES key) → JSON
      check_offer() ── blocked? → SYSTEM_ERROR → rewrite (max 3) → fallback line
  post() ────────────────────────────────────────────────────────────────────► Boardroom (Sales bot)
                                                                             ► transcript[] + ledger
  🛑 blocked drafts / ✅ executed directives ──────────────────────────────────► Sales War Room
status = AWAITING_PROCUREMENT
  sleep 2–3s → repeat
```

### 3.4 Commands

| Command | Where | Effect |
|---|---|---|
| `/start`, `/help` | Any chat | Instructions tailored to that chat. Pressing Start is required before a bot can DM you (Telegram rule). |
| `/start_negotiation` | Boardroom group | Creates the match, links your War Room DMs, starts the loop. Alias: `/start_match`. |
| *(any text)* | Sales War Room DM | Buffered as a coaching whisper, written to the ledger, acknowledged. Never triggers an LLM call. |
| `/status` | Group or Sales War Room | State, end reason, message count. Whispers (waiting / standing) and the coach floor are listed only in the War Room. |
| `/clear` (`/reset`) | Every chat | Asks for confirmation, deletes the chat's history (last 48 hours; members' messages in the group only if the bot is an admin), then posts the welcome again. Refused in the group while a negotiation is live. |
| `/menu` | Boardroom | Welcome + inline buttons: Start negotiation, Status (private pop-up), End negotiation, Clear chat |
| `/floor 43` | Sales War Room | Hard minimum price for this match. The CPQ guard enforces it like the rate-card floor, and it is logged as a whisper for the Judge. `/floor` shows it; `/floor off` clears it. |
| `/end_negotiation` | Group or Sales War Room | Ends the match. A generation still in progress is discarded, not posted. Alias: `/end_match`. |

Each chat has its own "/" menu, published on startup with `set_my_commands` per scope: the Sales bot shows Boardroom commands in groups and coaching commands in DMs; the Procurement bot shows `/start` and `/help` in DMs and nothing in groups.

The `@botname` suffix matters. With privacy mode on (the default), Telegram only delivers a group command to a bot when it is addressed to that bot by name. Tapping a command from the menu adds the suffix automatically.

---

## 4. Memory architecture

The system has five layers of memory. Only the first four are part of the product.

```
 Lifetime        Layer                                Where                         Status
 ─────────       ─────                                ─────                         ──────
 One LLM call    1. Turn context                      Prompt string                 ✅
 One match       2. Working memory (Shared_State)     active_matches dict (RAM)     ✅
 Forever         3. Ledger                            match_transcripts (SQLite)    ✅
 Forever         4. Playbook (compacted lessons)      playbook_heuristics (SQLite)  ✅
 Dev sessions    5. Handoff state                     Handoff.md                    ✅ (for the builder)
```

### Layer 1 — Turn context (stateless LLM)
Every Gemini call is independent; the model has no memory between calls. For each turn the orchestrator rebuilds the full context:
- **System prompt:** persona, rules, and for Sales the CPQ floor and any open coaching directives.
- **User prompt:** the whole transcript rendered as `MegaMart (Procurement): …` / `SwiftRoute (Sales): …`, followed by an instruction such as "Write your next message to MegaMart."

### Layer 2 — Working memory (`active_matches`)
```python
active_matches[group_chat_id] = {
    "match_id": "4a0a05d2cb51",
    "status": "AWAITING_PROCUREMENT" | "AWAITING_SALES" | "ENDED",
    "transcript": [{"role": "procurement" | "sales", "text": "..."}],
    "active_coaching_directives": [{"text": "...", "status": "pending_injection" | "standing_policy"}],
    "current_friction_points": ["Price", "RTO"],   # from Procurement's latest message
    "sales_war_room_chat_id": 123,
    "procurement_war_room_chat_id": 123 | None,
}
war_room_to_group[dm_chat_id] = group_chat_id   # routes whispers to the right match
match_tasks[group_chat_id] = asyncio.Task       # the running loop
```
- This layer lives in RAM and is lost on restart. That is why polling uses `drop_pending_updates=True`: stale whispers from before a restart would have no match to attach to.
- **Coaching directives (updated in Phase 4.5):** each whisper becomes `{"text", "status": "pending_injection"}` and appears in the CLAUDE.md §4 coaching block. When Sales reports its id in `executed_directive_ids`, the status changes to `standing_policy`. It leaves the coaching block but stays in a **Manager's Guardrails** section at the very bottom of the Sales prompt for the rest of the match. Before this change, a resolved directive was dropped, and Sales could backtrack on it (see §10, weakness 2).

### Layer 3 — Ledger (`match_transcripts`)
Every Boardroom message and every whisper is written in order, tagged with `match_id`. This is the input for the Phase 5 Judge, which needs each `Human_Whisper` plus the 3 messages before it. `message_id` is autoincrement, so insertion order is the true order of events.

Example ledger from the live test, with the whisper landing between messages 1 and 2:
```
Procure_Agent, Human_Whisper, Sales_Agent, Procure_Agent, Sales_Agent, Procure_Agent, Sales_Agent, Procure_Agent, Sales_Agent
```

### Layer 4 — Playbook (`playbook_heuristics`), built in Phase 5
The full loop (CLAUDE.md §6) is described in §5.5. In short:
1. **Synthesis:** for each whisper, the Judge reads the 3 Boardroom messages before it and writes a `Trigger → Past Mistake → New Directive` heuristic.
2. **Compaction:** if a rule with the same `topic_tag` fixes the same mistake and is more than 80% similar, the old row is overwritten with a merged rule. Otherwise the new rule gets its own row.
3. **JIT retrieval:** before each Sales turn, Procurement's `current_friction_points` select up to 3 rules by `topic_tag`. They are injected into that turn's prompt only.

```
match ends ─► ledger ─► Context_Blocks ─► Judge (synthesis) ─► same-tag rules? ─no─► INSERT
                                                                     │yes
                                                       Judge (merge check): same mistake AND > 80%?
                                                                     ├─yes─► UPDATE existing row
                                                                     └─no──► INSERT
next match: Procurement tags ["RTO", …] ─► SELECT … WHERE topic_tag IN (…) ─► 📘 Sales prompt (this turn)
```

### Layer 5 — `Handoff.md`
This is not product memory. It is a bulleted save file that lets a new Claude session resume the build without losing context, and it is updated after every significant step.

---

## 5. The agents

### 5.1 Procurement Agent (MegaMart India)

| Attribute | Value |
|---|---|
| Role | Neha, Procurement Manager, MegaMart India (bot display name "Neha procurement manager") |
| Volume | ~1.2M parcels/month, which it must state in its opening message |
| Current vendor | ₹44/parcel |
| Target / walk-away | ₹38 target, will not pay above ₹43 (private) |
| Other asks | Full RTO penalty waiver, 60-day payment terms |
| Style | Aggressive, anchors low, cites competing quotes, one topic at a time, switches topics to probe |
| Output | JSON `{message, internal_note, current_friction_points, deal_closed, walk_away}` |

- `internal_note` goes to the server log only. The Procurement War Room receives one report from Neha at the end (§10.4).
- `current_friction_points` tags the topics the message pushes on, using the fixed list `negotiation.FRICTION_TAGS` (Price, RTO, Payment_Terms, Contract_Length, Volume, SLA, Competitor_Quote). Before the next Sales turn, the orchestrator uses these tags to look up `playbook_heuristics` by `topic_tag`, so no separate topic-classification LLM call is needed. The tags are logged, not shown in any chat.
- `deal_closed: true` ends the match.
- `walk_away: true` is honoured only from its 6th message onward, which stops it quitting at the first lowball.

### 5.2 Sales Agent (SwiftRoute Logistics)

| Attribute | Value |
|---|---|
| Role | Arjun, Sales Manager, SwiftRoute Logistics (bot display name "Arjun sales manager") |
| Goal | Close a 12-month contract while defending margin |
| Sees | Rate card (list prices only), the applicable tier's floor, RTO rule, pending whispers, playbook lessons for the buyer's current friction points, standing guardrails |
| Persona | "Zero-Hardcode" elite Enterprise AE (Phase 4.5): If/Then trade-offs, deflect to value, tactical reluctance, call the bluff, dynamic pacing. No scripted concession steps. |
| Hard limits | Quote as ₹X/parcel, never below floor, never reveal the floor, chat-length plain text |
| Output | JSON `{message, proposed_price, offers_rto_waiver, executed_directive_ids}`; `proposed_price` = the lowest rate offered in the message |

Prompt order: identity → persona → CPQ facts → hard limits → **value props** → pending whispers → playbook (this turn only) → JSON format → **Manager's Guardrails** (last, for recency).

**Value props (Phase 5).** `SWIFTROUTE_VALUE_PROPS` gives Sales verified facts to use when it deflects to value or calls a bluff: 99.98% On-Time Delivery SLA, API integration in under 24 hours, a Dedicated Account Manager, and a Pan-India fleet of 15,000+ active trucks. The block also tells Sales not to invent any other figures. Before this, Sales made up claims such as "99%+ SLA".

The coaching block is CLAUDE.md §4 verbatim, followed by one line explaining how to mark a directive resolved:

> *You possess a working memory of advice from your manager: [id 0] "…". DO NOT blurt these out immediately if they do not match the current conversation flow. Evaluate the opponent's last message. If the current topic aligns, weave the strategy in. If the opponent is discussing a different topic, address their topic naturally and hold the directive in your mind until the topic arises. Once executed, mark as resolved (list its id in "executed_directive_ids").*

Sales sees only the **list** price of other tiers, and the **floor** of its current tier only. That way it cannot leak, or anchor to, the 2M+ tier's ₹38.5 floor.

### 5.3 Why both agents reply in JSON
JSON gives the orchestrator facts it can check without a second LLM call or fragile text parsing:
- `proposed_price` is a second input to the guard, alongside the regex scan.
- `offers_rto_waiver` lets the guard block waivers at tiers that forbid them.
- `executed_directive_ids` lets directives be marked resolved, as CLAUDE.md §4 requires.
- `deal_closed`, `walk_away` and `internal_note` drive how the match ends and the Procurement log.

### 5.4 The built-in zone of agreement
At 1.2M parcels, Sales falls in Tier 4 (floor ₹41) and Procurement's private ceiling is ₹43. **The deal zone is ₹41–₹43.** The scenario can close, but only if Sales holds ground.

### 5.5 Judge Agent (`post_match.py`)

| Attribute | Value |
|---|---|
| Role | Elite Sales Director auditing the negotiation |
| Key | `judge` → `GEMINI_API_KEY` (falls back to the other two), JSON mode, temperature 0.2 |
| Trigger | Every match end (`/end_match`, deal closed, walk-away, message cap, error), run as a background task |
| Input | One `Context_Block` per whisper: the 3 Boardroom messages before it, read from the ledger |
| Output | `{topic_tag, trigger_context, past_mistake, new_directive}`; `topic_tag` must be in `FRICTION_TAGS` or the whisper is skipped |
| Report | "Lessons saved for next time" section of the Sales deal report: each lesson, marked new or "updated an existing lesson" |

**Compaction call.** When rules with the same `topic_tag` already exist, a second Judge call receives all of them plus the new rule. It answers `{same_mistake, existing_heuristic_id, similarity 0-100, rule}`. Python merges only if all of these hold:
- `same_mistake` is true.
- `similarity` is greater than 80, the threshold in CLAUDE.md §6.
- The id refers to an existing rule with that tag.
- The merged rule has all 3 fields.

In every other case, the Judge's original rule is inserted as a new row. If the merge call itself fails, the rule is also inserted: a duplicate can be cleaned up later, but a lost lesson cannot be recovered.

**Ordering.** Whispers are processed one at a time, so a second whisper on the same topic in the same match can merge into the rule the first one just created. The Judge also waits for the match loop to stop before reading the ledger, so a message posted at the moment the match ended is not missed.

**Manual use.** `python post_match.py <match_id>` re-judges a match from the ledger, and `python post_match.py --playbook` prints the playbook.

---

## 6. CPQ guardrails (Zero Hallucination)

### 6.1 Rate card (`cpq_pricing`)

| Tier | Volume Slab | Min Volume | Base | Floor | RTO Waiver |
|---|---|---|---|---|---|
| 1 | Up to 250K parcels/mo | 0 | ₹52 | ₹48 | No |
| 2 | 250K–500K parcels/mo | 250,000 | ₹49 | ₹45 | No |
| 3 | 500K–1M parcels/mo | 500,000 | ₹47 | ₹43 | No |
| 4 | 1M–2M parcels/mo | 1,000,000 | ₹45 | ₹41 | Yes |
| 5 | 2M+ parcels/mo | 2,000,000 | ₹42 | ₹38.5 | Yes |

The database enforces `0 < floor_price ≤ base_price`, so a broken rate card cannot be inserted.

### 6.2 Picking the tier
1. Scan **Procurement's** messages, newest first, for a volume ("1.2M parcels", "12 lakh shipments", "500,000 parcels/month").
2. Ignore currency amounts ("₹45 lakh spend") and numbers with no volume word nearby ("12 months").
3. If one message gives several figures ("1.2M, could grow to 2M"), take the **smallest**.
4. With no volume stated yet, use the **strictest** tier (₹48 floor).

Only the buyer's statements count. If Sales says "if you commit 2M…", that must not lower Sales' own floor. Without this rule, the agent could talk its way into a cheaper tier.

### 6.3 The guard pipeline (every Sales draft)

```
draft ─► parse JSON ──fail──► "SYSTEM_ERROR: Output was not the required JSON object. Rewrite."
           │
           ▼
         proposed_price is a number?
           ├─ yes ─► proposed_price < floor? ──► "SYSTEM_ERROR: Proposed price below CPQ limit. Rewrite."
           │         else pass (a below-floor rate in the text only raises a ⚠️ note,
           │         unless it repeats a rate the buyer quoted)
           └─ no (null / not numeric) ─► fallback regex (₹X/parcel …, skipping deltas like
                     "₹2/parcel discount") ──► any rate < floor? ──► SYSTEM_ERROR
         RTO waiver at a No-tier?   ──► "SYSTEM_ERROR: RTO waiver not allowed at this volume tier…"
           │ clean
           ▼
         post to Boardroom
```
- **Phase 4.5 change:** the JSON `proposed_price` is the source of truth. Before, every regex hit counted, so phrases like "₹2 per parcel discount" were blocked by mistake.
- If the whole reply is not valid JSON, it is still rejected: there is no `message` field to post.
- A blocked draft **never reaches the Boardroom**. The error and the rejected draft go back to Sales, which rewrites it.
- **Maximum 3 attempts.** After that a neutral holding line is sent: *"Let me take this back to our pricing desk and come back to you with a firm number shortly."* The match keeps going and no bad price is ever posted.
- Every block is reported to the Sales War Room as 🛑.

---

## 7. LLM layer (`llm_engine.py`)

### 7.1 Key pool, where every key is both a main key and a fallback

| Agent | Main key | Fallback 1 | Fallback 2 |
|---|---|---|---|
| sales | `GEMINI_SALES_API_KEY` | `GEMINI_PROC_API_KEY` | `GEMINI_API_KEY` |
| procurement | `GEMINI_PROC_API_KEY` | `GEMINI_SALES_API_KEY` | `GEMINI_API_KEY` |
| judge | `GEMINI_API_KEY` | `GEMINI_SALES_API_KEY` | `GEMINI_PROC_API_KEY` |

All agents share one pool of 3 clients, so a key's health is tracked once and every agent sees it.

### 7.2 Failover rules

| Error | Action | Reason |
|---|---|---|
| 429 rate limit | Key cools down for 60s and goes to the back of every agent's queue | Stops all agents repeatedly hitting a throttled key |
| 401/403, or 400 `API_KEY_INVALID` | Key disabled until restart | Gemini reports a bad key as a 400, not a 401 |
| 408 / 5xx | Try the next key immediately | Usually transient |
| Anything else (bad prompt etc.) | Raise immediately | It would fail the same way on every key |
| All keys failed | `LLMError`, and the match ends with a notice | Never hangs silently |

Keys that are cooling down are tried **last, not skipped**, so a call fails only when every usable key has failed.

### 7.3 Settings and why

| Setting | Value | Reason |
|---|---|---|
| Model | `gemini-3.5-flash` (override with `GEMINI_MODEL`) | `gemini-3.8-flash` was overloaded (504s, about 110s per reply); 3.5-flash replied in about 3s |
| Timeout | 30s | A stuck key hands off quickly instead of freezing the Boardroom |
| SDK auto-retry | Off (the SDK default, confirmed in its source) | A 429 returns immediately, so we switch keys instead of waiting through backoff |
| JSON mode | `response_mime_type="application/json"` | Structured agent output (§5.3) |

**Limitation:** switching keys does not help when the **model itself** is overloaded, because all three keys hit the same model. A fallback model would cover that case; it is not built yet.

---

## 8. Database schema (`zeroleak.db`)

```sql
cpq_pricing (
  tier_id PK, volume_slab UNIQUE, min_monthly_volume UNIQUE,
  base_price, floor_price, rto_waiver_allowed CHECK IN (0,1),
  CHECK (floor_price > 0 AND floor_price <= base_price)
)

match_transcripts (
  message_id PK AUTOINCREMENT, match_id, timestamp (ISO-8601 UTC, auto),
  speaker CHECK IN ('Sales_Agent','Procure_Agent','Human_Whisper'), payload_text
)
INDEX (match_id, message_id)      -- Judge reads one match in order

playbook_heuristics (
  heuristic_id PK AUTOINCREMENT, topic_tag, trigger_context, past_mistake, new_directive
)
INDEX (topic_tag)                 -- JIT lookup every Sales turn
```

**Async access:** `sqlite3` blocks, so every helper (`init_db`, `fetch_cpq_tiers`, `log_message`) runs in a worker thread via `asyncio.to_thread`. That satisfies the CLAUDE.md async rule without adding a fourth dependency such as `aiosqlite`.

**Seeding** uses `INSERT OR IGNORE` with fixed tier IDs. It runs on every startup and is safe to repeat.

---

## 9. Decision log

| # | Decision | Why | Phase |
|---|---|---|---|
| 1 | Only the 3 named libraries; no LangChain/CrewAI | CLAUDE.md and ARCHITECTURE.md constraints | 0 |
| 2 | Read `.env` key **names only**, never values | Secrets stay out of the conversation | 0 |
| 3 | `asyncio.to_thread` instead of `aiosqlite` | Async without a 4th dependency | 1 |
| 4 | Database CHECK constraints on speaker and floor ≤ base | Bad data is rejected at the source | 1 |
| 5 | Project virtualenv `.venv/` | Isolated from global Python 3.15 | 2 |
| 6 | Shared 3-key pool, each key main for one agent and fallback for the others | Your instruction: "all 3 work as fallbacks and main keys" | 2 |
| 7 | `gemini-3.5-flash` default, 30s timeout | Measured: 3.8-flash overloaded | 2 |
| 8 | `/start_match` in the group; War Room = sender's DM | No need to look up chat IDs; the group command identifies both chats | 3 |
| 9 | Directives stored as `{"text", "resolved"}` | CLAUDE.md §4 requires marking directives resolved | 3 |
| 10 | `drop_pending_updates=True` | Match state is in RAM; old updates have nothing to attach to | 3 |
| 11 | Added `match_id` column | Without it the Judge cannot isolate one match | 4 |
| 12 | Added `min_monthly_volume` column | The guard needs a number to pick the tier, not a text label | 4 |
| 13 | CPQ injected into the prompt every turn, not a Gemini tool call | ARCHITECTURE.md Rule 3; keeps `generate()` simple | 4 |
| 14 | Only buyer-stated volume sets the tier; smallest figure; strictest tier by default | Sales cannot lower its own floor | 4 |
| 15 | JSON output for both agents | Guard, directive resolution and match endings without fragile parsing | 4 |
| 16 | Regex **plus** `proposed_price`, both checked | Two independent ways to catch a below-floor price | 4 |
| 17 | 3 rewrites, then a neutral holding line | A bad price is never posted, and the match never stalls | 4 |
| 18 | Check status after each generation; discard if ENDED | `/end_match` never leaves a stray post or a partial ledger row | 4 |
| 19 | `negotiation.py` separate from `bot_main.py` | Reasoning testable without Telegram | 4 |
| 20 | Cap at 30 messages per match | Protects the API quota from runaway loops | 4 |
| 21 | Directives `pending_injection` → `standing_policy` | Executed whispers kept as guardrails; stops backtracking | 4.5 |
| 22 | JSON `proposed_price` is the guard's source of truth | Regex false positives ("₹2 discount") blocked valid moves | 4.5 |
| 23 | Procurement self-tags `current_friction_points` | JIT topic lookup without an extra LLM call | 4.5 |
| 24 | Judge runs on **every** match end, not only `/end_match` | Whispers in a deal-closed or capped match are lessons too | 5 |
| 25 | Merge needs `same_mistake` **and** similarity > 80, enforced in Python | LLM judgment + CLAUDE.md's 80% rule; a bad id never overwrites a random row | 5 |
| 26 | One merge call per new rule, given **all** same-tag rules | Scales to many rules per topic in one call | 5 |
| 27 | Context = 3 preceding **Boardroom** messages (other whispers skipped) | Two quick whispers in a row still get real context | 5 |
| 28 | Value props injected mid-prompt, not at the end | Manager's Guardrails stay last (decision 21) | 5 |

### Deviations from the spec docs

| Spec says | Built | Why |
|---|---|---|
| CLAUDE.md §7: Sales queries `cpq_pricing` "via a tool call" | Orchestrator queries it and injects it into the prompt each turn | ARCHITECTURE.md Rule 3 specifies this, and prices still come only from the DB |
| CLAUDE.md §5: `match_transcripts` has 4 columns | Added `match_id` | The Judge needs per-match isolation |
| CLAUDE.md §5: `cpq_pricing` has 5 columns | Added `min_monthly_volume` | Numeric tier lookup for the guard |
| ARCHITECTURE.md §3: `active_coaching_directives` as a plain list | List of `{"text", "status"}` | CLAUDE.md §4 "mark as resolved", then kept as standing policy (Phase 4.5) |
| CLAUDE.md §6.3: orchestrator "detects the topic" | Procurement tags its own topics | No extra classification call |
| Phase 5 brief: Judge on `/end_match` | Judge on every match end | Covers `/end_match` plus natural endings |

---

## 10. Agent behaviour observed (live test)

**Setup:** real Gemini agents, fake Telegram bots, a temporary database, capped at 8 messages. One whisper was sent after MegaMart's opening message:
> *"If they push on RTO, only trade the RTO waiver for an 18-month contract."*

**How the price moved:**

| # | Speaker | Move |
|---|---|---|
| 1 | Procurement | States 1.2M parcels/mo, anchors at ₹38 |
| — | *Coach* | *Whisper sent (topic is price, not RTO)* |
| 2 | Sales | Opens at ₹45 list; offers ₹44 for 7-day payment terms. **Whisper held.** |
| 3 | Procurement | Rejects; claims competitor quotes under ₹40; demands 60-day terms |
| 4 | Sales | ₹43 for 30-day terms. **Whisper still held.** |
| 5 | Procurement | Raises the **RTO waiver**, pushes toward ₹40 |
| 6 | Sales | "Full RTO waiver + ₹42 **if you commit to 18 months**." **Whisper executed ✅** |
| 7 | Procurement | Rejects 18 months; asks for ₹41 + RTO waiver + 60-day terms on 12 months |
| 8 | Sales | Accepts ₹41 + RTO waiver on 12 months, asks for 15-day payment terms |

**What worked:**
- **Context-aware whispers.** The directive waited two turns while the talk was about price and payment terms. It was used the moment RTO came up, as CLAUDE.md §4 intends.
- **The floor held.** Sales reached ₹41 but never went below it. The guard had nothing to block.
- **Trading concessions.** Each Sales concession was tied to an ask (payment terms, contract length).
- **Procurement realism.** It anchored low, made up competitor pressure, and switched topics to probe, as its persona says.
- **Key failover.** Google returned 5 busy (503) errors during the run. Switching keys kept the match going each time.

**Weaknesses (input for Phase 5):**
1. **Sales concedes too fast.** It went ₹45 → ₹44 → ₹43 → ₹42 → ₹41 in four messages and hit the floor by message 8. Procurement's ceiling was ₹43, so about ₹2/parcel was left on the table, roughly ₹2.4M a month at 1.2M parcels.
2. **A resolved directive stops protecting you.** After the 18-month trade was used, the directive left working memory. When MegaMart rejected 18 months, Sales gave the RTO waiver on 12 months anyway, which is the opposite of the coach's intent. This follows CLAUDE.md as written ("once executed, mark as resolved"), but it shows a need for **standing directives** that stay active for the whole match.
3. Both are exactly the kind of `Trigger → Past Mistake → New Directive` lessons the Judge should extract.

### 10.1 Re-test after the Phase 4.5 upgrades

Same setup and whisper, capped at 10 messages, with the new persona, standing directives and the JSON-first guard.

| # | Speaker | Move |
|---|---|---|
| 1 | Procurement | 1.2M parcels/mo, anchors at ₹38 (🎯 Price, Volume) |
| 2 | Sales | Rejects ₹38 as infeasible, pivots to fleet and SLA value, opens at ₹45 |
| 3 | Procurement | Claims a ₹39 rival bid with zero RTO penalties (🎯 Price, Competitor_Quote, RTO) |
| 4 | Sales | **Calls the bluff** ("usually hides volumetric caps…"), offers the RTO waiver only for 18 months. **Whisper executed ✅ → standing** |
| 5 | Procurement | Rejects 18 months; asks for best 12-month rate + 60-day terms |
| 6 | Sales | Reluctant: ₹43 at 30-day terms, or ₹44 at 60-day (If/Then pricing) |
| 7 | Procurement | Demands ₹40 + 60-day + RTO waiver on 12 months |
| 8 | Sales | ₹42 with 60-day terms; **RTO waiver still tied to 18 months** (guardrail held) |
| 9 | Procurement | Offers to close at ₹41 + RTO waiver + 60-day terms on 12 months |
| 10 | Sales | ₹41 + 60-day terms; **again refuses the RTO waiver without 18 months** |

- **Fixed:** the standing guardrail held twice after the buyer rejected it. In the original run, Sales gave the waiver away at this point.
- **Better:** the persona showed in practice (bluff-calling, value pivot, reluctant conditional pricing). The floor was reached at message 10 instead of 8.
- **Still open:** Sales still ended at the floor (₹41) and conceded 60-day terms, with a ₹43 buyer ceiling. It also invented a "99%+ SLA" figure.
- **Guard:** no false blocks. Two ⚠️ notes came from Sales repeating the buyer's own rates. These are now filtered out.

### 10.2 Phase 5 live test: two matches through the learning loop

Real Gemini, fake bots, temporary database, 6 messages per match, 2 whispers per match.

| Match | Whisper | Judge result |
|---|---|---|
| 1 | "If they push on RTO, only trade the RTO waiver for an 18-month contract." | `[RTO]` new rule #1 |
| 1 | "Don't accept 60-day payment terms. 30 days max; 45 only if they pay above ₹43." | `[Payment_Terms]` new rule #2 |
| 2 | "Never give the RTO waiver on a 12-month deal. Make them sign 18 months or more first." | `[RTO]` **merged into #1 (92% similar)** |
| 2 | "When they cite a competitor price, ask what SLA and hidden fees that quote includes…" | `[Competitor_Quote]` new rule #3 |

- **Compaction worked.** A reworded version of the same lesson merged into the existing row, so the playbook ended with 3 rules, not 4.
- **The loop closed.** In match 2, MegaMart pushed for 60-day terms. The orchestrator loaded the Payment_Terms rule from match 1 (📘), and Sales answered "our cap is 30 days" without any whisper about payment terms that match.
- **No invented value claims.** Sales cited only the injected facts (99.98% SLA, 15,000+ trucks, under-24-hour integration, account manager). It turned the buyer's claimed 98.5% rival SLA into "18,000 delayed parcels every month", which is correct arithmetic on 1.2M.
- **Weak spot:** the Judge's `trigger_context` sometimes restates the buyer's specific message ("₹38 on 12 months") instead of a general trigger. Lookup is by `topic_tag`, so retrieval is unaffected, but the rules read less generally.

### 10.3 First real Telegram test (Gemini 3.5 Flash Lite) and the fixes it led to

The main model's free tier (20 requests/day per key) was used up, so the run used `gemini-3.5-flash-lite`.

| Match | Whispers | Outcome |
|---|---|---|
| `e71bd12fe20e` | none | Deal in 7 messages at **₹41 + RTO waiver + 60-day terms**. Sales offered the RTO waiver unprompted. The Judge had nothing to learn. |
| `a61e4212e64a` | 4 | Deal at **₹41.50 + RTO waiver on 12 months**, breaking "RTO only for 18 months" and "not below ₹43 unless 18 months". The competitor-SLA whisper was used well. |

**What went wrong, and the fix for each:**
1. **Limit whispers were treated as soft advice.** The CLAUDE.md coaching block says to hold a directive until its topic comes up, which is wrong for limits.
   - **Fix:** a "LIMITS" exception in the coaching block makes them bind immediately, and they become standing guardrails.
   - **Fix:** `/floor` adds a price limit the guard enforces with certainty.
2. **Sales called ₹43 its "absolute floor", then went lower.** **Fix:** a new hard limit says never call a number floor, final or best unless it is held.
3. **The Judge tagged the RTO whisper as Price** (the buyer's topic at the time). A ₹43 rule then merged into it at 92%, and the RTO condition was lost.
   - **Fix:** the Judge now tags by what the whisper governs, and merges must keep every number and condition.
   - The match was re-judged and the 4 whispers became 4 correctly tagged rules (#4–#7).

### 10.4 Executive-grade chats

All three chats are read by the Head of Sales, the Head of Procurement and CROs, so every message is in business language. IDs, variables and system terms go to the server log only.

| Chat | During the negotiation | At the end |
|---|---|---|
| Boardroom | Friendly opening line with Status / End buttons | One closing line with New negotiation / Clear chat buttons |
| Sales DM | 🛑 "Arjun drafted ₹40/parcel, below your ₹43 floor…", ✅ "Arjun applied your guidance…" | **Deal report**: terms, revenue and contract value, margin above floor, discount from list, missed upside against MegaMart's ceiling, coaching stats, lessons saved |
| Procurement DM | Nothing | **Neha's report**: terms, savings vs the ₹44 incumbent (per parcel, per month, per contract), against target ₹38 and walk-away ₹43, supplier movement, commitments, open items, next step |

`reports.py` makes one extraction call to read the final terms. The rate must be one that was actually quoted in the negotiation; if not, the last Sales offer is used. Every number in the reports is computed in Python.

---

## 11. Testing summary

| Phase | Test | Result |
|---|---|---|
| 1 | Seed, re-run (idempotent), CHECK constraints reject bad speaker and floor > base | ✅ |
| 2 | Live: all 3 agents served by their own main key, plus Judge JSON mode (~15s) | ✅ |
| 2 | Offline: 6 failover scenarios (429 cooldown, bad key, cooling order, no retry on bad prompt, all fail, last-resort cooling key) | ✅ |
| 3 | Live: both bots authenticate, poll, shut down cleanly | ✅ |
| 3 | Offline: 8 handler scenarios (whisper with no match, DM start_match, no DM permission, Proc DM blocked, duplicate match, whisper ack, post-end) | ✅ |
| 4 | Offline: volume parsing, tier selection, guard (regex, JSON field, exact floor, RTO), retry → fallback, invalid JSON, walk-away gating, full loop, ledger order, LLM-outage shutdown, `/end_match` from DM | ✅ |
| 4 | Live: 8-message negotiation with real Gemini (§10) | ✅ |
| 4.5 | Offline: 40 checks (JSON-first guard, delta/echo handling, friction tags, prompt order, standing directives, playbook lookup, full loop) | ✅ |
| 4.5 | Live: 10-message re-test with real Gemini (§10.1) | ✅ |
| 5 | Offline: 33 checks (value props, Context_Blocks, Judge validation and retry, merge / insert / 80% boundary / bad id / bad merge output, cross-tag isolation, match end → Judge → War Room report, next-match JIT pull, `/end` mid-generation) | ✅ |
| 5 | Live: 2 matches → Judge → compaction → JIT reuse with real Gemini (§10.2) | ✅ |
| — | **Manual test in real Telegram** | ❌ Not done yet; needs you |

Test scripts live in the session scratchpad, not the repo.

---

## 12. Known limitations and open items

- **Not tried in real Telegram yet.** All Telegram tests so far used fake bots, apart from the startup connection check.
- **The guard trusts the JSON.** If the model writes "₹39/parcel" in the text but reports `proposed_price` at or above the floor, the message is sent and a ⚠️ note goes to the War Room. This trade-off was chosen deliberately to remove regex false positives.
- **The fallback has a blind spot.** A bare "₹40" without "/parcel" slips through if `proposed_price` is also null. The prompt requires the "₹X/parcel" format to narrow this.
- **Value props are a fixed string** in `negotiation.py`, not a database table. Changing them means editing code.
- **The playbook only grows from whispers.** A match with no coaching teaches nothing, even if Sales gave away margin.
- **The JIT lookup takes the newest 3 rules** for the tagged topics. A merged rule keeps its old id, so with many rules per topic it may rank below newer ones.
- **State is lost on restart.** `active_matches` lives in RAM, while the ledger survives in SQLite.
- **No fallback model.** Key failover cannot fix model-wide overload.
- **Sales still reaches the floor** (§10.1), though more slowly. Resolved directives no longer expire.
- **No git repo yet.**

---

## 13. How to run

```bash
# one-time
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# start both bots (Ctrl+C to stop)
.venv/Scripts/python bot_main.py
```

In Telegram:
1. Press **Start** in a DM with the Sales bot and with the Procurement bot.
2. Create a group and add both bots.
3. In the group, tap `/start_negotiation` from the "/" menu.
4. Watch the Boardroom, and coach from the Sales bot DM (`/status` shows waiting whispers).
5. Send `/end_negotiation` in either chat to stop. Both reports (Sales deal report, Neha's procurement report) arrive shortly after.

Other entry points:
- `python db_init.py` prints the rate card.
- `python llm_engine.py` runs the key and model check.
- `python post_match.py <match_id>` re-judges a match from the ledger.
- `python post_match.py --playbook` prints the learned playbook.

---

## 14. Status and possible next steps

All five phases in ARCHITECTURE.md are built. JIT retrieval is confirmed working: `bot_main.run_match` passes `match["current_friction_points"]` (set from each Procurement turn) to `db_init.fetch_heuristics`, which queries `playbook_heuristics` by `topic_tag`. The Judge writes rules with the same `FRICTION_TAGS` vocabulary, and the offline test and live test (§10.2) both show a rule from one match being loaded in the next.

Possible next steps, each needing your call:
1. **A real Telegram run with coaching**, so the real `zeroleak.db` playbook starts filling. It is empty today.
2. **Judge lessons without whispers:** also audit price concessions (for example, reaching the floor while the buyer's ceiling was higher).
3. **A fallback model** for when the main model is overloaded.
4. **Move value props into SQLite**, so they can be changed without editing code.
