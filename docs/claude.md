## 1. Project Identity & Goal

**Project Name:** ZeroLeak OS
**Domain:** B2B Enterprise Logistics (Freight Pricing, Volumetric Slabs, RTO Penalties)
**Vision:** An Autonomous Multi-Agent Deal Desk for live enterprise contract negotiation, running on Telegram. A Sales Agent (Arjun, SwiftRoute Logistics) defends margin against a Procurement Agent (Neha, MegaMart India), and both negotiate real contracts: the terms they agree are the terms that get signed. The system utilizes a "Human-in-the-Loop" live whisper architecture, strict SQLite CPQ guardrails, and an RLHF (Reinforcement Learning from Human Feedback) memory loop in which no learned rule goes live without a shadow regression test and the human manager's approval.

## 2. Tech Stack & Dependencies

* **Language:** Python 3.10+
* **Orchestrator:** Native Python Async State Machine (Avoid heavy frameworks like LangChain/CrewAI).
* **Messaging Interface:** `python-telegram-bot` (v20+ async).
* **Database:** `sqlite3` (Local System of Record and CPQ Engine).
* **LLM Integration:** Gemini async clients.

## 3. The Telegram State Machine (UI/UX Routing)

The system operates across three linked Telegram chats. The orchestrator must strictly route payloads to prevent cross-contamination.

* **Chat 1: The Boardroom (Public Group):** The live negotiation channel. The Sales Agent and Procurement Agent negotiate here autonomously. The Human NEVER messages here directly.
* **Chat 2: Sales War Room (Private DM):** The Human Sales Manager monitors the Boardroom here, sends live "Whisper" instructions to the Sales Agent, answers its escalations, and approves or rejects playbook updates.
* **Chat 3: Procurement War Room (Private DM):** The same for the Procurement side (whispers, reports, playbook approvals).

## 4. Prompt Architecture: Live Context-Aware Whispers

LLMs suffer from "Topic Whiplash" if forced to immediately execute out-of-context commands.

* When a Human sends a whisper in the War Room, the webhook DOES NOT pause the Boardroom.
* The whisper is appended to a hidden array called `[ACTIVE_COACHING_DIRECTIVES]`.
* **System Prompt Injection:** Every time the Sales Agent generates a reply, the system prompt includes this block:
* *"You possess a working memory of advice from your manager: {ACTIVE_COACHING_DIRECTIVES}. DO NOT blurt these out immediately if they do not match the current conversation flow. Evaluate the opponent's last message. If the current topic aligns, weave the strategy in. If the opponent is discussing a different topic, address their topic naturally and hold the directive in your mind until the topic arises. Once executed, mark as resolved."*



## 5. Database Schema (SQLite)

The agents must not hallucinate pricing or memory.

**Table 1: `cpq_pricing` (The Mathematical Guardrails)**

* `tier_id` (PK)
* `volume_slab` (e.g., "1M parcels/mo")
* `base_price` (e.g., ₹45/parcel)
* `floor_price` (e.g., ₹41/parcel)
* `rto_waiver_allowed` (Boolean)

**Table 2: `match_transcripts` (The Ledger)**

* `message_id` (PK)
* `timestamp`
* `speaker` (Sales_Agent, Procure_Agent, Human_Whisper)
* `payload_text`

**Table 3: `playbook_heuristics` (The Compacted Memory)**

* `heuristic_id` (PK)
* `topic_tag` (e.g., "Payment_Terms")
* `trigger_context`
* `past_mistake`
* `new_directive`

## 6. The Self-Improving Memory Loop (RLHF & Compaction)

A third LLM, the **Judge Agent**, runs asynchronously post-match.

1. **Synthesis:** The Judge Agent scans `match_transcripts` for every instance where a `Human_Whisper` occurred. It analyzes the 3 preceding messages to deduce the agent's failure, and generates a structured JSON heuristic (Trigger ➡️ Past Mistake ➡️ New Directive).
2. **Memory Compaction (Deduplication):** The Judge Agent queries the existing master rule with the same `topic_tag` and MERGES the new nuance into it rather than creating a duplicate (one rule per topic, the newest coaching wins on conflicts). This ensures O(1) retrieval speed and strictly caps context bloat.
3. **HITL Memory Staging Gate:** Memory regression (a good rule overwritten by a worse one) is a direct financial risk on a live deal desk. The Judge NEVER writes a live playbook: every new rule, merge or compaction is written to the `pending_lessons` staging table, and the agents keep using the live `new_directive` until the Human Manager taps ✅ Approve in Telegram. Only then does the staged rule overwrite the live one.
4. **Shadow Regression:** Before the manager is asked, the backend plays a headless micro-benchmark (`shadow_test.py` → `headless_runner.py`, AI vs AI, on database copies): 5 matches with the current playbook and 5 with the proposed rule. The approval request carries the measured delta (avg closing margin, deal rate, payment days).
5. **Just-In-Time (JIT) Retrieval:** In future matches, the orchestrator detects the topic of the Procurement Agent's latest message, queries `playbook_heuristics` by `topic_tag`, and silently injects the exact relevant heuristic into the Sales Agent's prompt for that turn only.

## 7. Developer Directives (Strict Execution Rules)

* **Zero Hallucination:** The Sales Agent must query `cpq_pricing` via a tool call before proposing any price. If it proposes a price below `floor_price`, the system must block the message and return an internal error to the agent to rewrite it.
* **Asynchronous Processing:** Use `asyncio` for all database reads/writes and LLM network calls to prevent Telegram webhook timeouts during the live Boardroom negotiation.
* **Dummy Data Initialization:** On startup, seed the SQLite database with dummy logistic pricing metrics for SwiftRoute Logistics and MegaMart India to ensure the MVP is immediately testable.