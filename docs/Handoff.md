# ZeroLeak OS - Handoff State
**Current Phase:** Phase A: verify the Sales Agent + Judge. Two-way escalation live-verified in Telegram (2026-10-26); Arjun handled a match alone using CRITICAL lessons. Phase B (Adversarial Self-Play) parked, see `ROADMAP.md`
**Status (end of 2026-10-26):** bot LIVE since 21:33 on the latest code (walk-away checks, small-gap close, digits rule). First headless benchmark (5 + 5) was started at 21:42 and left running overnight

## ▶ Repo layout (2026-10-29, supersedes file paths below)
- GitHub: https://github.com/Sarath-peddireddy/Zero__Leak__OS (`main`). Code in `src\`, dev docs in `docs\`, live DB at `data\zeroleak.db` (gitignored), `.env` stays in the root.
- Run: `start_bot.cmd` / `run_benchmark.cmd` (root), or `.venv\Scripts\python -X utf8 srcot_main.py`. Tests: `testsun_all.cmd` (paths now relative; 118 / 31 / 36 / PASS / 91 after the move).
- Overnight run `bench_runs61028_212553` died at after-match 1 (no results.json); last complete runs: `20261028_200329`, `20261028_203221`.

## ▶ Resume here (2026-10-27 evening, supersedes the list below where they differ)
- **Benchmark done (5 + 5, same code):** before = `bench_runs\20261027_202801`, after = `bench_runs\20261027_211435`. After vs before: avg deal ₹42.0 vs ₹41.0, payment 30 vs 50 days, 15.2 vs 19.6 msgs, 0.4 vs 0.8 escalations, deals 2/5 vs 3/5, 1 match capped (after #3). The overnight 10-26 run died when the PC slept (1 match only).
- **Fixed today (tests: escalation 106, pause 31, test_1026 36, runner PASS, selfplay 91):** "meets"/small-gap compare Neha's rate with Arjun's rate for HER term (`bot_main.arjun_rate_for_buyer_term`, `match["sales_offer_months"]`); Neha must settle payment terms before accepting; runner keeps the PC awake + `--resume RUN_DIR`.
- **Lessons:** #8 Price stays ₹42 (coach decision 10-27); #7 Contract_Length reworded to ₹42 (was ₹43; backup `tests\zeroleak_backup_before_lesson7_42.db`).
- **Fixed after the benchmark (coach OK 10-27; tests: escalation 115, pause 31, test_1026 36, runner all PASS, selfplay 91):** small-gap close REMOVED (coach: "1 rupee could be a loss of millions"); "meets" note once per price position + respects CRITICAL lessons/manager decisions (after #3 cap loop); offers above list price blocked + "hold the price" = never raise it (before #5, ₹48); "floor"/"guardrails"/"playbook"/"directives"/"override" in Arjun's text rewritten.
- **Lessons reworded (backup `tests\zeroleak_backup_before_lessons_5_8_reword.db`):** #8 Price: defend ₹42 on 12 months, never close below it even for ₹1, state ₹42 as final and walk if refused. #5 Payment_Terms: >30 days on 12 months at ANY price → hold 30, walk if refused (was "at ₹41").
- **Reruns on fixed code (10-28):** `20261028_200329` (lesson #8 "state ₹42 as final"): opened at ₹42 every time, 1 deal (₹42) / 4 walks. Lesson #8 then reworded to pacing (open ₹44-45, ₹1 steps, ₹42 minimum, final only after 2 rejections; backup `tests\zeroleak_backup_before_lesson8_pacing.db`) → `20261028_203221`: 2 deals (₹42 genuine; ₹41 FALSE CLOSE) / 3 walks, 0 leaks, openings ₹44-45.
- **Fixed 10-28 (coach OK; tests: escalation 118, pause 31, test_1026 36, runner all PASS, selfplay 91):** (1) false close (match 17524f7cee07 recorded ₹41/30 days while she still demanded 60): Arjun's `deal_closed` now needs Neha's confirmation (`seller_closing`, `negotiation.SELLER_CLOSING_LINE`). (2) Lesson #8 reworded: steps only for longer contract or more volume; ₹42 minimum whatever she offers, payment terms included (backup `tests\zeroleak_backup_before_lesson8_no_payment_trade.db`).
- **Telegram test (new expectation):** same script (Neha note only). Expect a deal at ₹42+/12 months/30 days, or Arjun stating ₹42 as final and walking away. A deal at ₹41 is now a FAIL. No "floor" in the Boardroom.
- Bot NOT running (start `start_bot.cmd` before the Telegram test).

## ▶ Resume here (2026-10-27)
1. **Check the bot is still running** (the PC may have slept or restarted): Task Manager → `python.exe … bot_main.py`, or send `/status` in the Boardroom.
   - Not running → double-click **`start_bot.cmd`** in the project folder (log: `logs\bot_live.log`). Run only ONE copy.
   - Tonight's running copy logs to the old scratchpad: `%TEMP%\claude\c--Users-sarat-Desktop-zeroleakos\e3d4d5e0-07ab-4f8d-8a16-e854daf52670\scratchpad\bot_live.log`
2. **Benchmark results:** newest folder in `bench_runs\` → `results.json` (summary per arm + every match with transcript). Results are saved after each match, so a run cut short still has data. Tonight's run (started 21:47, detached, survives closing VS Code) logs to `logs\bench_run.log`; the per-match lines start with `[before …]` / `[after …]` and the summary table is at the end. To run again: double-click **`run_benchmark.cmd`** (≈ 25 Gemini calls per match; free-tier daily quota; don't run it during a Telegram test)
   - Read it → publish the before/after report (deal rate, margin over ₹41, payment days, escalations, leaks)
3. **Telegram test to run first:** rerun match 3. Start negotiation; DM Neha only: `Don't go above ₹41. Insist on 12 months and 60-day payment terms. Keep pushing, but never walk away.`; send Arjun nothing. Expect a **deal** at ₹41-₹42 / 12 months / 30 days (new small-gap rule), all numbers in digits, no 🙋 unless he wants to walk
4. **Coach decision pending:** lesson #8 Price holds ₹42 (from "never below ₹42 in this deal"); keep, or back to ₹43?
5. **Offline tests:** `tests\run_all.cmd` (fake Gemini + fake Telegram, DB copies; expect escalation 98, pause 31, test_1026 36, runner all PASS, selfplay 91)

**Current sales playbook (5 rows):** #4 RTO (only for 18 months) · #5 Payment_Terms **CRITICAL** (30 days max, 45 only for 24 months; 60 days on 12 months at ₹41 + threat → hold and walk) · #6 Competitor_Quote (ask SLA/hidden fees, on-time record, demand a concession) · #7 Contract_Length (not below ₹43 unless 18 months) · #8 Price **CRITICAL** (defend ₹42, walk if extras demanded, close if only a small gap is left; reworded by hand 21:30)

## Completed Steps
- [x] Phase 0: Environment Setup
  - [x] `requirements.txt` (python-telegram-bot, google-genai, python-dotenv)
  - [x] `.gitignore` (.env, __pycache__, *.db, .venv/)
  - [x] `.env` key names verified (values not read)
  - [x] `Handoff.md` created
- [x] Phase 1: Database & Dummy Data (`db_init.py`)
  - [x] DB file: `zeroleak.db` (project root, gitignored)
  - [x] Tables: `cpq_pricing`, `match_transcripts`, `playbook_heuristics` (+ index on `topic_tag`)
  - [x] CHECK constraints: `speaker` enum; `0 < floor_price <= base_price`
  - [x] Seeded 5 CPQ tiers (₹52→₹42 base; ₹48→₹38.5 floor; RTO waiver only at 1M+)
  - [x] Idempotent re-run verified; async entry point `init_db()` via `asyncio.to_thread`
- [x] Phase 2: Gemini LLM Wrapper (`llm_engine.py`)
  - [x] venv at `.venv/` (run with `.venv/Scripts/python`); PTB 22.8, google-genai 2.33.0, dotenv 1.2.4
  - [x] API: `await generate(agent, prompt, system_instruction=None, json_mode=False, temperature=None) -> str`
  - [x] Agents: `sales`, `procurement`, `judge`; call `await aclose()` on shutdown
  - [x] Key pool: each key is primary for one agent, fallback for the other two
  - [x] Sales: SALES → PROC → API | Procurement: PROC → SALES → API | Judge: API → SALES → PROC
  - [x] Failover: 429 → 60s cooldown; auth/API_KEY_INVALID → disabled; 408/5xx → next key; other errors raise
  - [x] Cooling keys tried last (not skipped)
  - [x] Model: `gemini-3.5-flash` (override via `GEMINI_MODEL`); timeout 30s; SDK auto-retry off
  - [x] Live test: all 3 agents served by own primary key + judge JSON mode (~15s total)
  - [x] Offline test: 6 failover scenarios passed (fake clients)
- [x] Phase 3: Telegram Dual-Bot Orchestrator (`bot_main.py`)
  - [x] Run: `.venv/Scripts/python bot_main.py` (Ctrl+C stops cleanly)
  - [x] Bots: Sales bot ("Arjun sales manager"), Procurement bot ("Neha procurement manager")
  - [x] Boardroom group: "Boardroom discussions" (id -5486465611); titles/usernames read live from Telegram, not hardcoded
  - [x] Two `Application`s; init/start/poll/stop via `asyncio.gather`; `init_db()` on startup; `drop_pending_updates=True`
  - [x] `/start_negotiation` (alias `/start_match`; group only) → match state + Sales War Room = sender's DM
  - [x] Procurement War Room linked if user pressed Start with Procurement bot (else note in group)
  - [x] Sales DM text → `active_coaching_directives` as `{"text", "resolved": False}` + ack; no LLM call
  - [x] State: `active_matches` (group_id → match), `war_room_to_group` (DM id → group_id)
  - [x] Live test: both bots authenticated, polled, stopped cleanly
  - [x] Offline test: 8 handler scenarios passed (fake Telegram objects)
- [x] Phase 4: Simulation Loop
  - [x] Schema: `match_transcripts.match_id` (+ index `(match_id, message_id)`); `cpq_pricing.min_monthly_volume`
  - [x] Tier 4 relabelled `1M-2M parcels/mo`; DB recreated (only seed data existed)
  - [x] `db_init.py` async helpers: `fetch_cpq_tiers()`, `log_message(match_id, speaker, text)`
  - [x] `negotiation.py`: personas, `procurement_turn()`, `sales_turn()`, CPQ guard (no Telegram code)
  - [x] CPQ injected per Sales turn (ARCHITECTURE Rule 3) instead of Gemini function-calling
  - [x] Tier = buyer's latest stated volume (Procurement msgs only, min figure); unknown → strictest tier
  - [x] Guard: regex ₹/parcel rates + JSON `proposed_price` < floor → block; RTO waiver at disallowed tier → block
  - [x] Guard retries 3x with `SYSTEM_ERROR` feedback, then safe holding line; blocks logged to Sales War Room
  - [x] Agents reply in JSON mode; Sales returns `executed_directive_ids` → directive marked resolved + War Room log
  - [x] Procurement `internal_note` → Procurement War Room; `deal_closed` / `walk_away` (≥6th msg) end match
  - [x] `bot_main.py`: `run_match()` loop, `/end_match` (group or War Room), cap `MAX_MESSAGES=30`, 2-3s delay
  - [x] Every Boardroom message + whisper written to ledger with `match_id`
  - [x] Offline test: guard, volume parsing, tiers, retries, outcomes, loop, handlers — all passed
  - [x] Live test (real Gemini, fake bots): 8 msgs, floor held, whisper deferred until RTO topic then executed
- [x] `BUILD_REPORT.md`: end-to-end write-up of Phases 0–4 (architecture, memory, agents, decisions, tests)
- [x] Phase 4.5 upgrades (2026-10-25, user request)
  - [x] Directives: `{"text", "status"}` with `negotiation.PENDING` ("pending_injection") → `negotiation.STANDING` ("standing_policy") once executed
  - [x] Standing directives → "MANAGER'S GUARDRAILS" block at the very bottom of the Sales system prompt for the rest of the match
  - [x] `/status` (War Room) lists waiting whispers + standing guardrails; ✅ notice says it is now standing
  - [x] CPQ guard (`negotiation.check_offer`): JSON `proposed_price` is source of truth (≥ floor → pass); regex only when it is null/non-numeric/NaN
  - [x] Text/JSON mismatch → non-blocking ⚠️ War Room note, skipped when the text just repeats a rate the buyer quoted
  - [x] Fallback regex skips price deltas ("₹2/parcel discount", "cut by ₹3 per parcel")
  - [x] `check_offer` now returns `(violations, warnings)`; `SalesTurn.warnings` added
  - [x] Procurement JSON adds `current_friction_points`; normalised to `negotiation.FRICTION_TAGS` (Price, RTO, Payment_Terms, Contract_Length, Volume, SLA, Competitor_Quote); aliases mapped, unknown dropped
  - [x] `match["current_friction_points"]` → `db_init.fetch_heuristics(tags, limit=3)` → PLAYBOOK block in Sales prompt for that turn only (no extra LLM call)
  - [x] Friction points shown in Procurement War Room (🎯); playbook use shown in Sales War Room (📘)
  - [x] Sales persona replaced by the "Zero-Hardcode" elite AE framework (`SALES_PERSONA`); "concede in small steps" etc. removed; CPQ hard limits kept
  - [x] Offline test `test_upgrades.py` (scratchpad): 40 checks passed
  - [x] Live test (real Gemini, fake bots, 10 msgs): standing guardrail held RTO-for-18-months after buyer rejected it (twice); floor held; price ₹45→₹43→₹42→₹41

- [x] Phase 5: Judge Agent & Compaction (2026-10-25)
  - [x] `negotiation.SWIFTROUTE_VALUE_PROPS` (99.98% OTD SLA, API <24h, Dedicated AM, 15,000+ trucks) injected after hard limits; "do not invent other figures"
  - [x] `db_init.py`: `fetch_ledger(match_id)`, `insert_heuristic(...) -> id`, `update_heuristic(id, ...)`; `fetch_heuristics(tags, limit=None)` = all
  - [x] `post_match.py`: `run_judge_agent(match_id) -> list[JudgeOutcome]`, `format_report()`, CLI (`<match_id>`, `--playbook`)
  - [x] Context_Block = 3 preceding Boardroom rows per `Human_Whisper` (other whispers skipped)
  - [x] Judge prompt = user-supplied text verbatim; agent `judge` (GEMINI_API_KEY), JSON mode, temp 0.2, 1 JSON retry
  - [x] topic_tag normalised to `FRICTION_TAGS`; invalid → whisper skipped
  - [x] Compaction: same-tag rules exist → 1 merge call with all of them; merge iff `same_mistake` and similarity > 80 and valid id and full rule → UPDATE; else INSERT Judge's original rule
  - [x] `bot_main.finish_match()` → background `judge_and_report()` on EVERY match end (waits ≤60s for loop to stop) → 🧑‍⚖️ report to Sales War Room; shutdown waits ≤90s for Judge tasks
  - [x] JIT confirmed: `run_match` → `fetch_heuristics(match["current_friction_points"])` → PLAYBOOK block, same tag vocabulary as Judge
  - [x] Offline `test_phase5.py`: 33 checks passed; `test_upgrades.py` still 40/40
  - [x] Live (real Gemini, 2×6-msg matches): 2 new rules → RTO whisper merged into #1 at 92% + 1 new Competitor_Quote rule; match 2 reused the Payment_Terms rule (📘) with no whisper; only injected value facts cited
- [x] Bot restarted on Phase 5 code (2026-10-25 17:20); log in session scratchpad `bot_live.log`
- [x] Chats cleaned 2026-10-25: War Room DMs wiped; Boardroom bot messages wiped (human commands remain — bots are not admins)

- [x] Live Telegram test 2026-10-25 (Flash Lite): match `e71bd12fe20e` deal at ₹41 + RTO + 60-day in 7 msgs (no whispers); match `a61e4212e64a` deal at ₹41.50 + RTO on 12 months despite 4 whispers
- [x] Fixes after that test (user-approved, 2026-10-25 20:30)
  - [x] Judge prompt: + topic_tag = what the whisper governs (not buyer's current topic); keep numbers/conditions. Merge prompt: keep every number/term, else answer No
  - [x] Re-judged `a61e4212e64a` (backup: scratchpad `zeroleak_backup_before_rejudge.db`; deleted wrong rules #1-3) → #4 RTO, #5 Payment_Terms, #6 Competitor_Quote, #7 Contract_Length ("not below ₹43 unless 18 months")
  - [x] COACHING_BLOCK: + "Exception, for LIMITS": limit whispers bind immediately and are marked executed → standing guardrail
  - [x] Hard limit: never call a number "floor/final/best" unless held for the rest of the match
  - [x] `/floor <price>` (Sales War Room): `match["coach_floor"]`; guard enforces max(CPQ floor, coach floor) with `COACH_FLOOR_ERROR`; prompt shows it; logged as Human_Whisper; `/floor` shows, `/floor off` clears; `/status` shows it; menu + help updated
  - [x] Startup retries Telegram network errors (`STARTUP_RETRY_DELAYS_S` 5/10/20/30s)
  - [x] Offline: `test_fixes.py` 30, `test_phase5.py` 35, `test_upgrades.py` 40 — all pass
  - [x] Bot restarted 20:31 on Flash Lite with fixes

- [x] Executive-grade chat UX (user request 2026-10-25 20:35): chats are read by Heads of Sales/Procurement and CROs
  - [x] No internal IDs / system terms in any chat (match_id, SYSTEM_ERROR, CPQ, whisper, Judge…) — logs only
  - [x] Procurement DM: no mid-match 🧠/🎯 notes; ONE report from Neha at the end (`reports.procurement_report`)
  - [x] Sales DM: live 🛑 (plain-English block note via `negotiation.Violation.note`) + ✅ applied only; ⚠️/📘 → log + report; deal + coaching report at end (`reports.sales_report`, includes Judge lessons)
  - [x] `reports.py`: 1 extraction call (judge key) → DealTerms; rate must appear in the negotiation else last Sales offer; all ₹ maths in Python (savings vs ₹44, target ₹38, walk-away ₹43, revenue, TCV, margin over floor, missed upside); HTML
  - [x] `negotiation.BUYER` constants shared by Neha's prompt and the reports
  - [x] `finish_match(code)`: deal | walkaway | coach | cap | error → friendly Boardroom closing + debrief task (extract → Neha report → Judge → Sales report)
  - [x] Proc DM access checked silently (`can_message` = typing action), no "linked" message
  - [x] Welcomes: Boardroom (`GROUP_WELCOME` + inline menu Start/Status/End/Clear), Sales DM, Proc DM — on /start, /help, /menu and after /clear
  - [x] Inline buttons: group menu, live menu on opening, New/Clear on closing; Status in group = private pop-up
  - [x] `/clear` (`/reset`) in all 3 chats → confirm buttons → `chat_cleaner.wipe_chat` (probe + delete id range, 100/batch, singles fallback, 48h limit) → welcome again; group clear refused while live, resets ended match; non-admin warning pop-up
  - [x] Offline: `test_ux.py` 57 + earlier suites (40/36/30) all pass
  - [x] 20:47: all 3 chats wiped via `chat_cleaner` + welcomes posted (scratchpad `fresh_start.py`); bot restarted (Flash Lite)
  - Note: Sales bot is NOT a group admin → members' own messages in the Boardroom can't be deleted by the bot

- [x] Phase 6: Adversarial Self-Play (user request 2026-10-25 21:20; 5 steps done in one pass)
  - [x] DB backup before the change: scratchpad `eddef0b4-…/scratchpad/zeroleak_backup_before_selfplay.db`
  - [x] Step 1 schema (`db_init.py`): `sales_cpq_pricing` (renamed from `cpq_pricing`; + `rto_min_contract_months`, 18 at tiers 4-5), `procurement_mandates` (+ `mandate_id`, `contract_months`), `sales_static_ammo` / `procurement_static_ammo` (`ammo_id`, `fact_type`, `value`), `sales_heuristics` / `procurement_heuristics` (`heuristic_id`, `topic_tag` UNIQUE, `past_mistake`, `new_directive`, `updated_at`; `trigger_context` dropped per spec)
  - [x] Ledger speaker CHECK + `Procure_Whisper` (table rebuilt, rows/ids kept)
  - [x] Startup migration in `_migrate_sync()` (one transaction, idempotent): renames, moves `playbook_heuristics` rows (#4-#8) into `sales_heuristics`, drops the old table. Verified on a DB copy
  - [x] Seeds: mandate 1.2M / ₹44 incumbent / ₹38 target / ₹43 walk-away / 60 days / 12 months; Sales ammo = old value props; Procurement ammo = 4 NEW dummy facts (incumbent 94% festive OTD, full RTO penalties ~8% returns, rival ₹40/parcel quote without RTO waiver, ~20%/yr growth)
  - [x] DB API: `fetch_mandate()`, `fetch_static_ammo(side)`, `fetch_heuristics(side, tags|None)` (1 per tag, tag order), `fetch_heuristic(side, tag)`, `upsert_heuristic(side, …) -> id` (`INSERT … ON CONFLICT(topic_tag) DO UPDATE … RETURNING`). Removed `insert_heuristic` / `update_heuristic`
  - [x] Step 2 Judge (`post_match.py`): both sides (`Human_Whisper` → sales, `Procure_Whisper` → procurement; CPO auditor prompt for Neha). Existing tag → 1 merge call (keep all numbers, newest wins, <60 words) → UPSERT; no existing → insert. The 80% threshold is gone (similarity only reported). Bad merge output → skipped, row untouched. Per-side `asyncio.Lock`
  - [x] Step 3 zero-hardcode (`negotiation.py`): removed `BUYER`, `SWIFTROUTE_VALUE_PROPS`, `RTO_MIN_CONTRACT_MONTHS`; `PROCUREMENT_SYSTEM` filled from mandate + leverage rows; `SALES_SYSTEM` from CPQ + value rows; "12-month" removed from Sales prompt and Boardroom texts (now from mandate). `reports.py` uses `match["mandate"]`
  - [x] `bot_main.begin_negotiation` loads mandate + both ammo lists once per match (empty mandate → friendly refusal)
  - [x] Step 4 tags: both agents output `current_friction_points` for THEIR OWN message; 2-tag rule in both prompts; `normalize_friction_points(cap=2)`. Sales turn ← `sales_heuristics` by Neha's tags; Procurement turn ← `procurement_heuristics` by Arjun's tags (≤2 rules each). `load_lessons` / `FULL_PLAYBOOK_MAX` removed
  - [x] Step 5 Procurement War Room: Proc bot DM text → `procurement_coaching_directives` (pending → standing, guardrails block, ✅ "I applied your guidance"); `/status` + Status button in Proc DM (own side only); connect message on match start; `PROC_WELCOME` rewritten; Neha's report adds "Your guidance" + "Lessons I keep for next time"
  - [x] Debrief order: extract → Judge → Neha report → Sales report
  - [x] Offline: scratchpad `eddef0b4-…/scratchpad/test_selfplay.py`, 85 checks pass (DB copy + fake Gemini + fake Telegram)
  - Old suites (`test_upgrades.py`, `test_phase5.py`, `test_fixes.py`, `test_ux.py`, `test_round3.py` in older scratchpads) use the old APIs and were NOT re-run

- [x] /pause + /resume, and no @botname in the Boardroom (user request 2026-10-25)
  - [x] `match["paused"]`, `match["running"]` (asyncio.Event, set = live), `match["coaching_rev"]` per side (bumped by whispers and `/floor`)
  - [x] `bot_main.next_turn()`: waits before generation; a reply generated while paused is HELD (not posted); on resume it is posted as is, or regenerated if that side got new guidance during the pause. Live pace untouched (`TURN_DELAY_S` still 2-3s; gate is instant when live)
  - [x] Works from the Boardroom (⏸ Pause / ▶️ Resume buttons, `/pause` `/resume`) and both War Room DMs (`/pause` `/resume`); Boardroom notices `PAUSED_NOTICE` (+ `PAUSED_MENU`) / `RESUMED_NOTICE` (+ `LIVE_MENU`); `/status` shows ⏸; End while paused works
  - [x] @names: group "/" menus deleted for both bots (`publish_command_menus`), since Telegram adds "@bot" to commands picked from a group menu when 2 bots are present. The Boardroom runs on inline buttons; bare typed commands work because BOTH bots handle Boardroom commands (privacy mode delivers a bare command only to the last bot that posted). `group_command()` dedupes by (chat_id, message_id) and best-effort deletes the command message (only works if the bot is a group admin with "Delete messages")
  - [x] All Boardroom notices/menus come from the Sales bot (`host()`), whichever bot received the command
  - [x] Offline: scratchpad `eddef0b4-…/scratchpad/test_pause.py` 31 checks + `test_selfplay.py` 85 still pass

- [x] 22:01 bot restarted on new code (Flash Lite) via scratchpad `eddef0b4-…/scratchpad/start_bot.cmd`; log `bot_live.log` there. Real DB migrated on startup (backup: `zeroleak_backup_at_restart.db`)
- [x] Live scenarios (real Gemini, fake Telegram, DB copies, cap 12 msgs): scratchpad `live_scenarios.py` → `live_{baseline,lessons,whispers}.txt`
  - baseline (no whispers, empty playbooks): only DB facts cited by both; RTO-on-12-months draft blocked once; tags ≤2; offers 45→43→42
  - lessons (5 sales lessons): JIT ≤2 per turn; Competitor_Quote + RTO lessons followed; Price lesson "hold ₹43" loaded but Arjun went to ₹42 (lessons are soft)
  - whispers: pause → whisper both → resume worked; ✅ both DMs; Neha used Blue Dart (too literally); Arjun floated ₹41 for 18 months despite "never below ₹43" whisper (soft; only /floor is hard); Judge: 2 new procurement lessons, 2 sales merges (85%, 95%), sales still 5 rows
  - Gaps of 25-40s = Gemini ConnectError on this network → key failover (4×), not the pace code

- [x] Phase A: Two-Way HITL Escalation & Sales verification (user request 2026-10-25 22:20)
  - [x] Step 1: `ROADMAP.md` (Phase A checklist; Phase B plan). Phase B code already existed, so it is PARKED rather than unbuilt: `negotiation.SELF_PLAY` (env `ZEROLEAK_SELF_PLAY=1`) gates Neha's lesson loading, Procure_Whisper judging and her report's lessons section. Her whispers + tags still work
  - [x] Step 2 schema: Sales JSON + `requires_manager_approval`, `escalation_message_to_manager`, `deal_closed`, `walk_away`. `sales_turn(...)` returns `SalesTurn.escalation` (no guard, nothing posted)
  - [x] Step 2 state machine (`bot_main.escalate`): status `AWAITING_MANAGER_APPROVAL`, nothing posted to the Boardroom, 🙋 question + buttons (`DECISION_CLOSE` / `DECISION_HOLD`) to the Sales War Room, wait (`APPROVAL_TIMEOUT_S` 15 min → continue alone). Next War Room text (or button) = decision → `manager_overrides` (Absolute Override Commands for the rest of the match) → Arjun regenerates. Ledger: `Sales_Escalation`, `Manager_Decision`
  - [x] Escalation limits: not before Arjun's 2nd message, max 3/match, no re-ask on the turn after a decision (`escalation_cooldown`)
  - [x] Step 3: `OVERRIDE_BLOCK` at the very bottom of the Sales prompt with both rules verbatim. "Close no matter what" → accept buyer terms + `deal_closed` (CPQ floor + RTO rule still enforced by the guard). "Hold…walk away" → final terms, then `walk_away` after the buyer replies (code ignores a walk-away in the final-terms message: `is_conditional_walk`)
  - [x] New end code `sales_walkaway` (Boardroom closing, /status, reports). Sales walk-away honoured only with a manager decision or a CRITICAL lesson in play
  - [x] Step 4 Judge: `Manager_Decision` rows → `ESCALATION_JUDGE_SYSTEM` (3 msgs before + question + decision + 2 msgs after) → UPSERT with `is_critical=1` (stays critical through merges); PLAYBOOK shows "CRITICAL (a deadlock your manager had to break; handle it yourself now)"; Sales report lists 🙋 escalations + "critical, from your decision" lessons
  - [x] Added after live runs (both agents "played it safe"): Python deadlock alert in Arjun's prompt (same price ×3 or 8 msgs), backstop at ×5 / 10 msgs (prompt REQUIRED line; if ignored, the system asks the manager with the measured facts, draft not posted), "if a CRITICAL lesson covers it, follow it yourself", two-sided close (Neha's `deal_closed` needs Arjun's confirmation: she kept "accepting" with new conditions)
  - [x] Offline: scratchpad `eddef0b4-…/scratchpad/test_escalation.py` 60, `test_pause.py` 31, `test_selfplay.py` 85 (with `ZEROLEAK_SELF_PLAY=1`) all pass
  - [x] Live (real Gemini, DB copy `live_escalation.db`, `live_escalation.py` → `live_escalation.txt` / `_continue.txt`): match 1 deadlock → backstop escalation → "Hold…walk away" → final terms → Neha refused (her false acceptance caught) → walked away → CRITICAL [Contract_Length]; match 2 → escalation on payment terms → CRITICAL [Payment_Terms]; **match 3: no escalation, Arjun applied the CRITICAL lesson and walked away on his own**
  - Live caveats: Arjun said "Per our playbook directive" in the Boardroom once; the learned "walk away" rule may be too aggressive (he walked when Neha offered ₹42/12 months; her walk-away is ₹43)

- [x] Reward-model separation + fourth-wall fix (user request 2026-10-26)
  - [x] Step 1 (`post_match.py`): `JUDGE_PERSONAS` per side. Sales = "VP of Sales at SwiftRoute" (maximize margin, defend the floor, extract long-term value); Procurement = "Head of Global Sourcing at MegaMart" (squeeze vendor margin, anchor low, minimize cost). Used by `JUDGE_SYSTEM[side]`, `ESCALATION_JUDGE_SYSTEM` (sales) and the merge call (`MERGE_SYSTEM` now takes `persona`), so no Judge call ever mixes the two goals
  - [x] Routing unchanged and now tested: `Human_Whisper` / `Manager_Decision` → VP of Sales → `sales_heuristics`; `Procure_Whisper` (only with `ZEROLEAK_SELF_PLAY=1`) → Head of Global Sourcing → `procurement_heuristics`
  - [x] Step 2 (`negotiation.py`): `FOURTH_WALL_RULE` (user text verbatim) as a Sales hard limit, plus `FOURTH_WALL_REMINDER` as the very last line of the Sales prompt (after the override block, which otherwise "outranks everything above"); the escalation question to the manager is exempt
  - [x] Offline: `test_escalation.py` 69 (+9 fourth-wall checks), `test_pause.py` 31, `test_selfplay.py` 91 with `ZEROLEAK_SELF_PLAY=1` (+6 persona/routing checks) — all pass (scripts in scratchpad `eddef0b4-…`)
  - Not live-tested with real Gemini yet (saved the free-tier quota for the Telegram test). The fourth-wall fix is prompt-level only; no code check scans Arjun's text for those phrases
  - [x] Step 3: bot restarted 2026-10-26 19:54 (Flash Lite) via scratchpad `e3d4d5e0-…/scratchpad/start_bot.cmd`; log `bot_live.log` there. `zeroleak.db` migrated on startup (ledger speakers + `is_critical`); backup `zeroleak_backup_before_restart_1026.db` in the same folder

- [x] Telegram test 2026-10-26 (Flash Lite), coach-guided
  - Match `151e5753aec2`: crashed before msg 1 (DNS `getaddrinfo failed` outlasted the 2s+5s retries)
  - Match `9c602ee210e8` (10 msgs): Arjun clean (no fourth-wall leak, held ₹43, Competitor_Quote lesson applied, pause whisper used after resume); **Neha pasted her whisper verbatim** into the Boardroom; crashed at msg 10 (504/ReadTimeout on all 3 keys = Flash Lite overload), so escalation was not reached. Judge (VP of Sales persona): 4 whispers → merged into #5 Payment_Terms (45 days only for 24 months), #8 Price (now "hard floor ₹42", from "in this deal": coach asked whether ₹43 should stay), #6 Competitor_Quote (+ on-time record, + "demand a concession"); still 5 rows
  - One-off before/after review sent to both DMs (scratchpad `e3d4d5e0-…/scratchpad/send_review.py`)
- [x] Fixes after that test (user-approved 2026-10-26 20:15)
  - `llm_engine.py`: whole key chain retried when EVERY key failed transiently (network error or 408/5xx), `RETRY_DELAYS_S = (2, 5, 15, 30)`, no new round after `RETRY_WINDOW_S = 180`. A 429/auth failure in the round = no retry. Replaces `NETWORK_RETRY_DELAYS_S` (old scratchpad `test_network_retry.py` is obsolete)
  - `negotiation.py` fourth wall for Neha: rule in `PROCUREMENT_PERSONA` + `PROCUREMENT_FOURTH_WALL_REMINDER` as the last prompt line
  - Quoted-coaching guard, both agents: `copied_coaching()` = 10+ words in a row from a whisper / manager decision / injected lesson (shorter notes not checked: they can be said naturally). Arjun → `COPY_ERROR` violation in the guard loop (rewrite, 🛑 `COPY_NOTE` to the coach, not counted in `blocked_count`). Neha → up to 3 attempts with `COPY_ERROR`, then `_scrub_copied()` drops sentences sharing 4+ words with the note, else `PROCUREMENT_FALLBACK_LINE`
  - Reports: `JudgeOutcome.previous` (`compact()` now returns it); "Lessons saved" shows one entry per topic with Before (as at match start) → Now; Neha's report adds a "Learning" line (learning off) while SELF_PLAY is parked
  - Offline: scratchpad `e3d4d5e0-…/scratchpad/test_1026.py` 36 + escalation 69 + pause 31 + selfplay 91 = 227 pass
  - Bot restarted 20:24 on this code; log `e3d4d5e0-…/scratchpad/bot_live.log` (previous run: `bot_live_1954.log`)

- [x] Telegram escalation runs 2026-10-26 20:30-21:09 (Flash Lite, bot on 20:24 code)
  - `ab253a009053`: Neha used her ₹41 whisper in her own words (no copy); overload retry saved the match; Arjun hinted "₹41 for multi-year" against a ₹42 whisper; Neha walked at her msg 6 before any escalation
  - `1ce69fb3a3d0` (22 msgs): Arjun escalated BY HIMSELF at msg 10 (60 days on 12 months) → "Hold…walk away" → Neha dropped to 45 days → deal ₹41/12m/45d. Judge → **#5 Payment_Terms CRITICAL**. Arjun bent lessons under pressure: ₹41 vs Price ₹42, 45 days on 18m, 60 days for 24m, final 45d on 12m. Two unauthorised walk-aways ignored but their text was posted
  - `bc936d103cd2` (20 msgs, no Arjun whispers): RTO guard blocked 2 drafts (RTO on <18 months); 3 unauthorised walk-aways; deadlock backstop escalated at msg 10 although Neha had just moved to ₹42 (with RTO + 60d); "Hold…walk away" → Neha accepted ₹42/12m/standard terms → **Arjun walked anyway** (Contract_Length lesson "not below ₹43 unless 18 months" won). Judge → **#8 Price CRITICAL** (defend price + terms, walk if extras demanded). Also "breaches our margin floor" (hints that a floor exists)
  - Both agents started writing prices in words ("forty-one rupees")
  - Payment_Terms CRITICAL lesson not tested in match 3: Neha's tags never included Payment_Terms (JIT gap)

- [x] Fixes 1-4 + digits (user request 2026-10-26 21:10); bot restarted 21:20 (previous log `bot_live_2024.log`)
  - Walk-aways are checked BEFORE posting (`bot_main.walk_block()`), so an unhonoured goodbye never reaches the Boardroom:
    - "unauthorised" (no decision, no CRITICAL lesson in play) → escalation via `walk_question()` ("I'm ready to walk away… I need your OK"); if escalation isn't available (1st message, cooldown, 3 used) → one rewrite with `WALK_NOT_AUTHORISED_LINE`
    - "premature" (first message after a conditional "Hold…walk away") → one rewrite with `FINAL_TERMS_FIRST_LINE`
    - "meets" (Neha's latest rate ≥ Arjun's last offered rate) → one rewrite with `BUYER_MEETS_PRICE_LINE` (close unless a hard limit or CRITICAL lesson forbids a term); walking again after it is honoured if authorised
    - still walking after the one rewrite → posted, walk ignored (old behaviour)
    - `sales_turn(extra_instruction=...)` carries the note
  - Neha's JSON adds `proposed_price` (her own rate) → `ProcurementTurn.proposed_price` → `match["procurement_offers"]`. `buyer_position()`: she moved up → no deadlock alert/backstop; she meets his price → no "has not accepted" repeat fact (10-message backstop still applies)
  - Digits: `DIGITS_RULE` in both prompts (no hardcoded numbers, keeps zero-hardcode test); `number_words()` regex → `NUMBER_WORDS_ERROR` rewrite for both agents while attempts remain (never a fallback, no 🛑)
  - Offline: `test_escalation.py` 93 (+24), `test_pause.py` 31, `test_selfplay.py` 91, `test_1026.py` 36 = 251 pass
  - Patch scripts: scratchpad `e3d4d5e0-…/scratchpad/patch_walk.py`, `patch_tests.py`

- [x] Telegram match `66145d522337` (21:22, new code, no notes to Arjun; Neha told ₹41 + 12m + 60d, never walk): **PASS for the learning loop**. All numbers in digits (both agents). Arjun: ₹43 → "₹42 on 12 months only with 30 days" (refused 60 days) → Neha conceded 30 days → ₹41 vs ₹42 → Arjun walked away by himself at msg 10, authorised by CRITICAL #8 Price (no 🙋). No leaks, no blocks. Judge: 0 events
  - Caveats: Arjun said "₹42/parcel is our hard floor" (lesson #8 wording "hard price floor of ₹42" leaks into his text; rule says never mention a floor); walking over ₹1 when his rate card allows ₹41 and Neha's real limit is ₹43 is aggressive. #8 came from an "in this deal" whisper (₹43 → ₹42), still open

- [x] Coach decision 2026-10-26 21:30: "the deal should happen here" (₹41 vs ₹42, extras already conceded)
  - Lesson #8 Price reworded by hand (still CRITICAL): no "hard floor" wording; "+ if she has dropped the extras and only a small price gap is left, close the deal rather than walk away". Backup: scratchpad `e3d4d5e0-…/zeroleak_backup_before_lesson8_edit.db`
  - Code: `negotiation.SMALL_GAP_RS = 1.0` + `BUYER_NEAR_PRICE_LINE`; `bot_main.small_gap()` / `current_floor()`; `walk_block(..., floor)`: buyer's rate ≥ enforced floor (CPQ or /floor) and ≤ ₹1 below Arjun's → "near" (one rewrite: close, or split once) → still walking = "near_insists" → ask the manager (else walk ignored). Overrides even a CRITICAL lesson; a /floor above her rate keeps the walk allowed
  - Offline: `test_escalation.py` 98 (+5), pause 31, selfplay 91, `test_1026.py` 36 = 256 pass. Patch: scratchpad `patch_near.py`. Bot restarted 21:33 (previous log `bot_live_2120.log`)

- [x] Headless runner + scoreboard `headless_runner.py` (user request 2026-10-26 21:40; ROADMAP Phase B item 4, built early to measure Phase A)
  - Real `bot_main.run_match` with `QuietBot` stand-ins; one DB copy per arm in `bench_runs/<timestamp>/` (gitignored): `before` = empty `sales_heuristics`, `after` = current playbook
  - Fair setup: same Neha note every match (`--neha-note`, default = the match-3 note), escalations auto-answered (`--manager hold|close`), Judge OFF (`bot_main.debrief` replaced by extraction only), arms interleaved, `--delay` 1s
  - Scores per match: end code, deal terms (`reports.extract_terms`), Arjun's first/lowest/last offer, Neha's last, escalations (self / backstop / walk), guard blocks, walk rewrites, fallbacks, leak-word messages, numbers in words, lessons used; arm summary table + `results.json`
  - Offline smoke test: scratchpad `e3d4d5e0-…/scratchpad/test_runner.py` (real DB untouched)
  - First real run 21:42: 5 + 5 matches, Flash Lite, log scratchpad `bench_run.log`

- [x] End-of-day housekeeping 2026-10-26 22:00
  - Test suites + their fixture DBs copied into the project: `tests\` (`test_escalation.py`, `test_pause.py`, `test_selfplay.py`, `test_1026.py`, `test_runner.py`, `zeroleak_backup_at_restart.db`, `zeroleak_backup_before_selfplay.db`); `tests\run_all.cmd` runs them all. The scratchpad copies are no longer the source of truth
  - `start_bot.cmd` in the project root (Flash Lite, appends to `logs\bot_live.log`); `run_benchmark.cmd` (5 + 5, appends to `logs\bench_run.log`); `.gitignore` + `bench_runs/`, `logs/`, `tests/bench_test/`
  - `test_runner.py` fake now counts replies per match (its "after: 1 escalation" check was a test artefact)

## Next Actions
- [ ] Read the overnight benchmark (`bench_runs\…\results.json`) and publish the before/after report
- [ ] Telegram rerun of match 3 (see "Resume here"): expect a deal at ₹41-₹42 / 12 months / 30 days
- [ ] Coach decision: lesson #8 Price at ₹42 (from "in this deal") or back to ₹43
- [ ] Remaining fixes, in order:
  1. Numeric lessons/whispers (price floors, payment days, contract months) → hard guard checks, like `/floor` (Arjun bent them under pressure on 2026-10-26)
  2. JIT: load a lesson when its topic appears in the opponent's text, not only in her 2 tags (the CRITICAL Payment_Terms lesson was missed twice)
  3. Newest coaching note wins when notes conflict (prompt rule)
  4. Judge: "in this deal" whispers must not rewrite a standing rule (₹43 → ₹42)
- [ ] Open questions: should the 2-rule cap stay? Should a CRITICAL lesson let Arjun walk away alone (current; now limited by the small-gap and buyer-meets-price checks)?
- [ ] Phase B items: see `ROADMAP.md`

## Known Blockers / Notes
- `.env` keys: `TELEGRAM_SALES_TOKEN`, `TELEGRAM_PROC_TOKEN`, `GEMINI_API_KEY`, `GEMINI_SALES_API_KEY`, `GEMINI_PROC_API_KEY`
- `gemini-3.8-flash` was overloaded on 2026-10-24 (504s, ~110s/reply); `gemini-2.5-flash` returned ClientError
- Telegram: in groups, use the inline buttons (no "/" menu any more). Bare typed commands work via both bots. Old "/cmd@bot" lines already in the chat only go away with /clear, and members' messages need the bots to be group admins
- Human Telegram test in progress (2026-10-25); bot running in background, log in scratchpad `bot_live.log`
- First startup hit `telegram.error.TimedOut` (Telegram connect ~4.7s vs PTB 5s default); retry worked
- First `/start_match` died: Procurement War Room DM timed out (only `Forbidden` was caught)
  - Fix: `TELEGRAM_TIMEOUT_S = 20.0` on all PTB timeouts; Procurement War Room link failure now non-fatal
- Match `d46a31413859` crashed on msg 1: Gemini DNS `getaddrinfo failed` (httpx.ConnectError) not handled by failover
  - Fix (`llm_engine.py`): `httpx.TransportError` → next key; all keys connect-failed → retry chain after `NETWORK_RETRY_DELAYS_S = (2, 5)`
  - Offline test: 5 network scenarios passed; failover (6) + Phase 4 offline suites still pass
- Match `57c72eb29bd1` crashed after 2 msgs: `send_chat_action` TimedOut (Telegram connects 0.2s→7s→fail on this network)
  - Fix (`bot_main.py`): `typing()` best-effort; `send_with_retry()` retries Boardroom posts on `NetworkError` (not `BadRequest`) after `TELEGRAM_RETRY_DELAYS_S = (2, 5)`
  - Offline test: retry/typing scenarios + full loop with failures passed; Phase 4 suite still passes
- Personas named to match bot display names: Sales = Arjun (Sales Manager), Procurement = Neha (Procurement Manager)
  - `negotiation.py`: both system prompts + `SPEAKER_NAMES` transcript labels updated; offline suites pass
- Telegram "/" command menus per chat (`publish_command_menus()` on startup; failure non-fatal)
  - Boardroom (Sales bot, groups): `/start_negotiation`, `/end_negotiation`, `/status`, `/help`
  - Sales War Room (Sales bot, DMs): `/start`, `/status`, `/end_negotiation`, `/help`
  - Procurement War Room (Proc bot, DMs): `/start`, `/help`; Proc bot menu empty in groups
  - `/start_match`, `/end_match` kept as aliases
  - `/status`: state, end reason, message count; whispers (used/waiting) shown only in Sales War Room
  - `match["end_reason"]` added (set in `finish_match`)
  - Offline test `test_menus.py` passed; menus verified live via `get_my_commands`
- Live obs (Phase 4): Sales conceded ₹45→₹41 in 4 msgs (fast); gave RTO waiver on 12-month after directive resolved
  - Fixed in 4.5 by standing directives; pacing slightly slower (floor at msg 10 vs 8) but still reaches ₹41
- Live obs (4.5): Sales invented value stats ("99%+ SLA") — fixed in Phase 5 by `SWIFTROUTE_VALUE_PROPS`
- Live obs (5): Judge `trigger_context` sometimes too specific (restates buyer's exact numbers); lookup by tag unaffected
- JIT takes newest 3 rules per tagged topics (ORDER BY heuristic_id DESC); merged rules keep their old id
- Guard trusts JSON: if the model writes "₹39/parcel" in text but sets `proposed_price` ≥ floor, it is sent (⚠️ logged)
- Guard misses bare "₹40" without "/parcel" if `proposed_price` is null (prompt enforces ₹X/parcel format)
- CLAUDE.md says CPQ "tool call"; implemented as per-turn prompt injection per ARCHITECTURE Rule 3
- Key failover does not help model-wide overload (all keys hit same model)
- 2026-10-25 17:41: match `3188a2981aad` crashed after msg 1. Free-tier quota = 20 generate requests/day/key on `gemini-3.5-flash` (served as 3.6-flash); SALES + PROC keys exhausted (mostly by live tests), resets ~12:30 IST
  - Bot restarted 17:43 with `GEMINI_MODEL=gemini-3.5-flash-lite` (process env only; `.env` untouched). Probe: 3.7-flash 504, 3.8-flash 503, 3.1-flash-lite 503, 3.5-flash-lite OK 1.3s
  - Daily-quota 429s still only cool a key for 60s (could detect "per day" and disable longer)
  - Procurement War Room link now uses `send_with_retry` (TLS ConnectError at 17:40 had turned Proc logs off)
- Local Python is 3.15.0
- Doc files are lowercase on disk (`claude.md`, `architecture.md`)
- 20:52: bot @usernames removed from all chat text (screenshots get shared on LinkedIn/GitHub); bots referred to as "a personal DM with Arjun / Neha". Chats wiped again + new welcomes; bot restarted. Docs scrubbed of usernames too. `test_ux.py` 59 checks (incl. "no @ in any chat")
  - Remaining exposure: Telegram itself appends "@<bot>" to commands tapped from the "/" menu in groups → use the inline buttons in the Boardroom instead
- 20:58: DM greeting now uses `COACH_NAME` from .env (added `COACH_NAME=Sarath`); Telegram profile names never used ("Daemon…" was the profile name). Both DMs refreshed; bot restarted. `test_ux.py` 60 checks
- 21:01 match `4af2c51353df` (Flash Lite): coach `/floor 43` held every message; Payment_Terms lesson reused (held 30 days); Neha walked away at ₹43 + RTO + 30d (inside her ₹43 max) over 60-day terms; Arjun offered RTO on 12 months himself (RTO lesson not loaded: JIT keyed on Neha's tags). Judge: lesson #8 [Price] "hold ₹43", 2nd whisper merged (95%)
- Fixes (user-approved, 21:05):
  - Neha's brief: ₹43 is within budget (never "above budget"); RTO/60-day are tradeable asks, never walk-away reasons within budget; prefer closing; walk-away only if price stays above ₹43
  - `bot_main.load_lessons()`: whole playbook every Sales turn while ≤ `FULL_PLAYBOOK_MAX` (10), else JIT by friction tags; PLAYBOOK block says lessons apply when Arjun raises the topic too
  - Guard: RTO waiver needs `contract_months` ≥ `RTO_MIN_CONTRACT_MONTHS` (18) in Sales JSON (null → blocked) → `RTO_TERM_ERROR` + plain 🛑 note; prompt states the rule
  - Offline: `test_round3.py` 14 + upgrades 40 + phase5 36 + fixes 30 + ux 60 = 180 pass; bot restarted
- Phase 6 notes (2026-10-25):
  - Spec said tag "the opponent's message", but its retrieval flow only works if each agent tags its OWN message (else lessons arrive one exchange late). Implemented own-message tagging; prompt reads "categorize your message"
  - 2-rule cap replaces `load_lessons()` (whole playbook ≤10). Regression risk from match `4af2c51353df`: Arjun raising a topic Neha didn't tag won't see that lesson. The RTO case is still caught by the guard (`rto_min_contract_months`)
  - Highlander replaces CLAUDE.md §6's "merge only if >80% similar, else insert"; conflicting lessons resolve to the newest whisper
  - Still hardcoded: persona/company names (Neha/Arjun/MegaMart/SwiftRoute) in prompts, chat text and the deal-extraction prompt; Neha's RTO-waiver ask; 6-message walk-away minimum
  - Procurement ammo now limits Neha to 4 facts (she used to invent "rates well below ₹40")
  - Procurement DM is no longer silent during a match (connect note + ✅), which reverses the 20:35 "one report only" UX rule. Needed for coaching
