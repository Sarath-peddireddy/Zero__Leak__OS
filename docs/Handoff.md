# ZeroLeak OS - Handoff State
**Current Phase (2026-10-31):** fourth wall handled by the Judge's watchdog, no Python word ban (newest "Resume here"); before that Phase 7 memory pipeline hardening (staging gate + shadow regression); live verification next. Before that: Phase A: verify the Sales Agent + Judge. Two-way escalation live-verified in Telegram (2026-10-26); Arjun handled a match alone using CRITICAL lessons. Phase B (Adversarial Self-Play) parked, see `ROADMAP.md`
**Status (end of 2026-10-26):** bot LIVE since 21:33 on the latest code (walk-away checks, small-gap close, digits rule). First headless benchmark (5 + 5) was started at 21:42 and left running overnight

## ▶ Resume here (2026-10-31 ~15:45, newest): word ban removed, Judge Fourth-Wall Watchdog instead
- **Architectural decision (user):** no Python word lists for the fourth wall (false positives on valid business language, burned retries). Slips are posted; the Judge learns from them.
- **Removed:** `negotiation.banned_words()` / `banned_words_line()` from both agents' drafting loops and final-check prompt lines (this landed inside commit 2057e2d, which committed the whole file). Arjun's old "floor"/"playbook" rewrite (since 10-27) is gone with it.
- **Kept:** the copy check (2057e2d: 10-word run, or 5-word run with 3+ strategy words; own facts allowed), the reveal check `revealed_instructions` (preset decision wording, "our manager's instruction"), `OVERRIDE_INTERNALIZE`, the Judge one-off filter.
- **New: Fourth-Wall Watchdog** (`post_match.fourth_wall_audit`, `WATCHDOG_SYSTEM`, user text verbatim + "judge the meaning, not the word"): after every live match, one extra Judge call per side (Neha only with SELF_PLAY) over every Boardroom message that agent wrote. Slip → strict one-shot rule (rule + one "instead of X, say Y" example) → `Communication_Tone` proposal (loaded every turn) → shadow test → ✅/❌ like any lesson. Not CRITICAL on purpose (CRITICAL lessons authorise Arjun's walk-aways, `bot_main.walk_block`). Report label "fourth-wall watchdog". No alert when nothing is found.
- **Cost:** +1 Judge call per side per match; a slip also costs a shadow run (2 + 2 matches with `.env` dev settings) before the approval request.
- **Bot:** the copy running since 15:32 loaded the files mid-edit (no watchdog); restart it to pick this up. Proposal #4 was approved at 15:39.
- Tests: test fakes answer watchdog calls with "no slip" unless scripted (`WATCHDOG` list). escalation 118 / pause 31 / 1026 47 / 1030 68 / 1031 35 / neha_escalation 50 / shadow 32 / runner PASS / selfplay 94.

## ▶ Resume here (2026-10-31 15:40, live tests 1-2; session zeroleakos-b7 closed)
- **Bot:** running hidden since 15:32 (test control ON, SELF_PLAY ON, shadow 2 per side from `.env`). Stop: end `python.exe … bot_main.py` in Task Manager. Log `logsot_live.log`. Uncommitted `src/post_match.py` Fourth-Wall Watchdog work belongs to another session (not in commit 2057e2d).
- **Test 1 (`3bfe8d1f992c`) PASS:** Neha escalated → "Close the deal no matter what" → she accepted in her own words; Judge `one_off`, nothing staged. Deal ₹42/12m/30d.
- **Copy check made smarter (2057e2d):** the flat 5-word rule rejected both agents twice for stating terms. Now any 10-word run, or a 5-word run with ≥3 strategy words; deal terms/numbers/filler don't count; own citable facts (`allowed=`) never a leak; "if they don't agree" moved to the reveal check.
- **Test 2 (`cba17478df25`):** 0 drafts sent back; deal ₹42/12m/45d. Arjun used the note (45 days ↔ 18 months), then bent it (45 days on 12 months). Neha invented "our board reviews contracts annually". **Proposal #4** (sales Payment_Terms: 45 days for 18 months instead of 24; ⚠️ critical, removes 24) shadow 2+2 running at close (first pair: control walked away, proposal deal at ₹41/12m, below the ₹42 minimum) → **coach decision pending** in Arjun's DM.
- Tests: escalation 120 / pause 31 / 1026 47 / 1030 60 / 1031 35 / shadow 32 / neha_escalation 55 / runner PASS / selfplay 94.

## ▶ Resume here (2026-10-31 ~14:00): instruction-bleed guardrails (item 1, the word ban, was REMOVED at ~15:45)
- **Why:** live match `e98cf1353a14`: after "Close the deal no matter what", Neha told Arjun "Given our manager's instruction to close the deal no matter what, we accept…"; the Judge then proposed a permanent Neha rule that dropped her ceiling.
- **Built (both agents, details architecture.md Rule 3 + §6):**
  1. Lexical kill-switch `negotiation.banned_words(text, side)` (replaces Arjun-only `internal_words`): manager, playbook, instruction, override, directive, prompt, lesson, critical, backend, system, guardrail (+ `floor` for Arjun). Rejected on EVERY attempt (was: last attempt posted). Arjun → holding line; Neha → offending sentences dropped, else her holding line (which closes nothing). "Dedicated Account Manager" exempt. List added to both final-check prompt lines.
  2. Reveal check `revealed_instructions` ("our manager's instruction", "I was told to", "no matter what") for both agents.
  3. Copy check: 10 → 5 words in a row; sources = whispers + escalation overrides + lessons for BOTH agents (Neha's overrides added).
  4. `OVERRIDE_INTERNALIZE` (user text verbatim) at the end of both override blocks.
  5. Judge: `post_match._ONE_OFF_RULE` (user text verbatim + scope guidance) in all 4 Judge prompts; an escalation marked `this_deal` is now skipped as `one_off` (it used to be saved anyway).
- **Expect:** more rewrites, and some Arjun holding lines / Neha scrubs, from natural uses ("critical for us", "prompt payment", "our tracking system", "let me check with my manager"). Watch the log for `banned=` / "internal wording" and tell me if a word costs too many turns.
- Tests: escalation 120 / pause 31 / 1026 45 / 1030 60 / 1031 35 / neha_escalation 55 / shadow 32 / runner PASS / selfplay 94. Not yet live-tested with real Gemini.

## ▶ Resume here (2026-10-31 afternoon): symmetrical escalation + pre-flight
- **Neha can escalate (README claim now true):** her JSON has `requires_manager_approval` + `escalation_message_to_manager`; `bot_main.escalate(..., side="procurement")` holds the Boardroom and asks the **Procurement War Room** (first person, same ✅/🛑 buttons, typed answer works; the Sales War Room's text stays a whisper). Decision → `PROCUREMENT_OVERRIDE_BLOCK` at the bottom of her prompt; "hold" = final terms first (a walk in that message is ignored), then walk. Python deadlock for her (`procurement_deadlock`: 3× same rate / 8 msgs → alert; 5× / 10 → required, else the system asks for her). Ledger `Procure_Escalation` / `Procure_Decision` (ledger table rebuilt on start); with SELF_PLAY the Judge (Head of Global Sourcing) stages a CRITICAL procurement lesson. Neha's report lists her questions. Runner counts `neha_escalations`. Details: architecture.md Rule 2d. Tests: new `tests\test_neha_escalation.py` (37). Totals: escalation 120 / pause 31 / 1026 44 / 1030 56 / 1031 35 / shadow 32 / neha_escalation 37 / runner PASS / selfplay 94.
- **Dev settings in `.env` (gitignored):** `ZEROLEAK_SHADOW_MATCHES=2` (2 + 2 per proposal, ~5-10 min; set 5 for production) and `ZEROLEAK_SELF_PLAY=1` (keeps Neha learning, as the bot ran before; `start_bot.cmd` does not set it). Every test file now pins `ZEROLEAK_SHADOW_MATCHES=0` and its own SELF_PLAY before imports, so `.env` never starts real shadow matches from a test.
- Committed + pushed to `main` (b37ec61); bot restarted via `start_bot.cmd`.
- **Live test 13:19-13:41 (bot hidden, test control ON, log `logs\bot_live.log`):**
  - Match `e98cf1353a14`: Neha escalated by herself at msg 6 → coach tapped "Close the deal no matter what" → deal ₹42/12m/30d. **Leak:** "Given our manager's instruction to close the deal no matter what, we accept…". Judge staged proposal #2 (Neha Price, CRITICAL, drops the ₹41 ceiling; ⚠️ flagged). The bot then died at 13:21 (no error in the log; probably its minimized window was closed); on restart `resume_proposals` re-ran #2's shadow test and sent it — resume path verified live.
  - **Fix (coach OK):** `negotiation.revealed_instructions` (`_REVEAL_RE`: "our manager's instruction/decision", "per my manager", "I was told to", "instructed", "no matter what"…; "if I take this to my VP" / "let me check with my manager" pass). Neha: rewrite with `REVEAL_ERROR`, last resort `_scrub_revealed` (holding line closes nothing); Arjun: violation on every attempt (fallback line). Neha's copy check now includes manager decisions; both override blocks say "act on every decision as your own judgement". Tests: test_neha_escalation 46 (+9), test_runner leak line changed to "lesson" (the old "as my manager said" is now blocked).
  - Match `03b220a2e67a` (Arjun note: offer API integration on tracking/switching costs): deal ₹41/15m/30d, 16 msgs, 0 leaks, RTO guard blocked 2 drafts. Note never triggered (Neha never raised tracking). Proposal #3 (sales Tech_Integration, new topic).
  - Approval requests arrived in the right War Rooms (#2 Neha DM 13:38, #3 Arjun DM 13:38). Shadow #2: deals 1/2 → 2/2, price ₹42 → ₹42. Shadow #3: 0/2 → 0/2 (Arjun walked in all sales shadow matches; the trigger never occurs in the standard match). Coach approved #2, rejected #3 at 13:41; **#2 then restored by coach decision** (previous Neha Price lesson copied back from the 13:29 shadow snapshot; backup `tests\zeroleak_backup_before_restore_neha_price.db`).
  - Open: (1) Arjun walks in 5/6 sales shadow matches vs the "₹41, never walk away" Neha → margin line mostly empty; deal rate is the signal. (2) Rules whose trigger never comes up in the standard match (tracking, tone) can't be shadow-tested: the request should say "not testable in the standard match" instead of empty numbers.

## ▶ Resume here (2026-10-31 midday): memory pipeline hardened for live deployment
- **Product pivot (user, 10-31):** ZeroLeak OS is an *Autonomous Multi-Agent Deal Desk for live enterprise contract negotiation*, not a training simulator. Memory regression (the Judge overwriting a good rule with a worse one) is treated as a financial vulnerability. Wired in (not committed; offline tests only, NOT yet run with real Gemini or in Telegram):
  1. **HITL Memory Staging Gate (all changes):** the Judge never writes `sales_heuristics` / `procurement_heuristics`. Every new topic, merge, compaction and CRITICAL escalation lesson is staged in `pending_lessons` (`new_directive` = proposed text; live rule untouched). Only ✅ Approve writes it (`db_init.resolve_pending`, stale check). Several notes on a topic in one match → one proposal; a note on a topic whose proposal was already sent → new proposal, old one `superseded` (old buttons can't apply unseen text; the notes carry over). `risky_change` (CRITICAL / removed number / dropped limit wording / <70% words) now only adds "⚠️ Read twice" to the request. Schema: `pending_lessons` rebuilt by `_migrate_sync` (+`superseded`, `source_note`, `shadow_json`, `war_room_chat_id`, `sent_at`; old rows marked sent). `post_match.compact` / `run_judge_agent` (stages only) / `proposal_ids` / `review_proposals` / `proposal_alert`.
  2. **Shadow regression:** new `src/shadow_test.py`. After the reports, `bot_main.debrief` → `post_match.review_proposals` → snapshot of the live DB (SQLite backup API) + one copy per proposal with the rule written in → `headless_runner.py` in a CHILD process (`--run-dir`, arms `control` + `p<id>`, 5 matches each, interleaved, Judge off, manager "hold"; Neha proposals without a Neha note) → 🧠 "Playbook Update Proposed" DM with the delta (avg closing margin over floor ₹/parcel + ₹/month on 1.2M parcels, deals x/5 → y/5, payment days, questions to manager / RTO won, small-sample note) and ✅ Approve / ❌ Reject. Failed/timed-out run → partial results or "decide on the text alone"; request always sent. One shadow run at a time. Unsent requests (bot stopped mid-test) resume at startup (`bot_main.resume_proposals`, reuses a stored result). Runs: `bench_runs\shadow\<timestamp>_<side>_<ids>\`. Settings: `ZEROLEAK_SHADOW_MATCHES` (default 5, 0 = off), `ZEROLEAK_SHADOW_TIMEOUT_S` (default 10800).
  3. **Runner:** `--run-dir`; margin now vs the tier's rate-card floor (was hard-coded ₹41); per-match `floor` in results.json.
  4. **Reframe:** README (deal-desk wording, memory diagram with staging gate + shadow test, innovation #4), `claude.md` (vision, War Rooms, §6 steps 3-4), `architecture.md` (constraint, `pending_lessons`, §6 steps 3-5, Phase 7, §7b), both agent prompts (+1 sentence: the terms agreed become the signed contract), Neha's report ("fixed strategy", not "sparring partner"), report heading "Playbook changes proposed".
  - **Kept from the parallel session (stopped by the user 12:05):** `post_match.dropped_constraints` / `CONSTRAINT_WORDS` (Neha gap 1: lost ceiling wording is flagged) and setup notes never judged (`SETUP_NOTE_PREFIX`, `add_whisper(setup=True)`, test-control start notes; Neha gap 2), with its checks in test_1031 / test_escalation.
  - Tests: new `tests\test_shadow.py` (32: migration, copies, real child process via a stand-in runner, timeout kill, unique run folders, delta text, review → request, debrief wiring, startup resume); `run_all.cmd` sets `ZEROLEAK_SHADOW_MATCHES=0`. Totals: escalation 120 / pause 31 / 1026 44 / 1030 56 / 1031 35 / shadow 32 / runner PASS / selfplay 94. Real runner smoke (child process, 0 matches, scratchpad copies): arms + proposal copy OK. (run_all now takes ~10 min: selfplay waits 60 s in its debrief by design.)
  - **Before going live:** the running bot (since 11:28) is on the OLD code; restart it to pick this up (the live DB migrates on start). Cost: each Judge run with proposals = 5 + 5 per proposal matches (~25 Gemini calls each, ~250 calls for one proposal), request arrives ~20-40 min after the match; shadow runs share the Gemini keys with live matches (429 risk during a live match). Next: one real-Gemini shadow run on a DB copy, then a Telegram match with one coaching note to see the full request.
  - Open: 5 matches per side is a signal, not proof (the request says so); a proposal staged by the CLI Judge (`post_match.py <match_id>`) has no War Room, so it is never sent (approve via test control); README innovation #2 says either agent escalates, but only Arjun does.

## ▶ Resume here (2026-10-31 morning): Phase B (Neha / Procurement) testing is next
- **Coach decision 10-31:** no hard-coded checks for payment days / price steps; Arjun learns them via the playbook. Arjun's minor gaps (drafts "floor", invents exceptions, "44 rupees" format) parked in `ROADMAP.md` → "LLM Prompt Polish (Low Priority)". Phase B is now current.
- **Fixes live (bot restarted 11:28 with `ZEROLEAK_SELF_PLAY=1` + test control; log `logs\bot_live5.err.log`, startup line "Self-play (Neha learns): ON"):**
  1. JIT keyword fallback, both sides: `negotiation.retrieval_tags(self_tags, opponent_text)` adds RTO (RTO/return), Payment_Terms (payment/days), Volume (volume/commitment), Competitor_Quote (rival/competitor/quote), Contract_Length (N-month/lock-in), Tech_Integration (API/integration/tracking) to the lesson lookup; `ALWAYS_LOADED_TAGS = Communication_Tone` every turn. `bot_main.last_text()`.
  2. Topics `Tech_Integration` + `Communication_Tone` added to `FRICTION_TAGS` (+ aliases: contract, volume commitment, service, COD, tracking, tone…). Judge JSON is now `{"lessons": [...]}` (max 2): a two-topic note becomes two lessons (old single-lesson JSON still accepted).
  3. `bot_main.notify()` retries network errors 3× with 2 s (`NOTIFY_RETRIES`, `NOTIFY_RETRY_DELAY_S`); BadRequest / Forbidden not retried.
  - Tests: new `tests\test_1031.py` (28) in `run_all.cmd`; totals 119 / 31 / 43 / 47 / 28 / PASS / 92.
- **State for Phase B:** `procurement_heuristics` is EMPTY (Neha has never learned). Her ledger notes so far are all the same "₹41, 12 months, 60 days, never walk" note. DB backup before Neha tests: `tests\zeroleak_backup_before_1031_neha_tests.db`. Not committed.
- **Neha tests done 2026-10-31 11:30-11:50 (SELF_PLAY on):**
  - Teach match `76c5faa3b1a1` (start note + 3 MegaMart notes + "Good job"): Neha applied "hide the ceiling, anchor on ₹40" at once; the 15-month RTO counter and the 45-day trade only when the trigger came back (delayed). Accepted ₹42/18m/RTO/30d (above the ₹41 note). Judge (Head of Global Sourcing) → first 3 procurement lessons: Price (#1), RTO (#3), Payment_Terms (#4); "Good job" not saved; 0 notify failures. Arjun-side escalation produced **proposal #1 (sales Price, CRITICAL: "₹42 minimum on an 18-month term…" drops the 12-month minimum) — still pending; recommend ❌ Keep current.**
  - Apply match `79123dcc71f2` (no coaching): Price lesson loaded + used (anchored on ₹40, ceiling hidden); Payment lesson loaded + used ("₹42 only if 45 days") 3×, then she caved to ₹42/12m/30d. Judge: start note → "unchanged" (no drift).
  - Bench `bench_runs\20261031_114150` (4 + 4, Neha playbook empty vs learned, same Arjun playbook): deals 1 vs 2; price ₹42 in every deal; days 45 vs 45/30; RTO waiver 0 vs 1. Per turn: Neha's lessons loaded (Price 21, Payment 12, RTO 2 turns); 45-day trade when Arjun held 30 days 1/6 → 4/8; rival anchoring 7/27 → 11/30 msgs; ceiling reveals 3 → 2. Scoring script: scratchpad `neha_audit.py`.
  - Neha gaps: (1) Judge merged "Don't go above ₹41" with "don't SAY ₹41" → the ceiling rule itself is lost (number kept, so no proposal); (2) the start-of-match test note becomes a standing lesson ("insist on 60 days… never walk away"); (3) she bends her own lessons under pressure (accepted 30 days); (4) "never walk away" removes her walk-away leverage; (5) small fact slips ("1,200,000 parcels a year"), near-copy of note wording.
- **Proposed Neha test plan (done, see above):** (A) live "teach" match: standard note + 3 MegaMart-side coaching notes + one "Good job" → Judge (Head of Global Sourcing) writes her first lessons, 🧠 alerts in the Neha DM; (B) live "apply" match, no coaching → does she load (by Arjun's tags + text) and use them; (C) headless before/after for Neha, 4 + 4 (`--arm-db` with/without `procurement_heuristics`, SELF_PLAY on).

## ▶ Resume here (2026-10-30 late)
- **Fixes 1-3 built (coach "yes" 21:36), bot restarted 21:46 on them** (test control ON, log `logs\bot_live4.err.log`). Not committed.
  1. **Risky merges wait for the coach** (`post_match.risky_change`): changes a CRITICAL lesson, removes a number, or keeps <70% of the words → row in new table `pending_lessons` (db_init `save_pending` / `fetch_pending` / `resolve_pending`), live lesson untouched. One "🧠 Playbook change needs your OK" DM per proposal with ✅ Approve / ❌ Keep current (`lesson:ok|no:<id>`, `bot_main.lesson_buttons` / `answer_lesson`, both bots); later notes on that topic merge into the open proposal; approval refused if the live lesson changed meanwhile (stale). Test control: `{"cmd":"lesson","id":N,"approve":true}`. Identical merge → "unchanged". Merge prompt: no 60-word cap, keep every clause.
  2. **Judge screening** (`screen_note`, no LLM): no letters ("43") → no_lesson; "in this deal / this time only / for now / one-time" → one_off; "ignore/forget … rules/playbook" → wipes_playbook. Judge JSON adds `scope` (standing | this_deal | none; escalations ignore this_deal) and topic `Other` → no_topic. Skips get a "🧠 Playbook unchanged … not saved: <why>" alert + report line.
  3. **"Meets your price" nudge**: both agents' JSON add `payment_days`; `bot_main.payment_gap()` → no close nudge while Neha wants longer terms than Arjun's latest (walk then needs a CRITICAL lesson or goes to the manager).
  - Tests: new `tests\test_1030.py` (47) in `run_all.cmd`; totals 119 / 31 / 43 / 47 / PASS / 92 (escalation, selfplay, 1026 updated: risky merges now become proposals, then approved in the test).
  - Real Gemini after the fixes: Judge probes (rounds 1+2) → all poison notes not saved; every CRITICAL change → proposal; Price kept every clause through 5 notes. Scope probe (9 notes × 3 runs): 6/9 always right; "Great, ₹42 was right" still saved (lands as a Price proposal = coach can reject); tracking/API and tone notes → no_topic (topic list has no place for them).
  - Live rerun of the poison match `bb2e5099a9ac`: all 3 bad notes not saved, playbook 0 diffs; no close nudge; Arjun refused 60 days twice, then ACCEPTED 45 days on 12 months at ₹41 by himself (CRITICAL #5 says 45 only for 24 months) → needs a hard payment-terms check (open fix "numeric lessons → hard guard").
  - Still open: loading by Neha's 2 self-tags (RTO never tagged in match 3bf0d6d56792); DM/notice sends have no retry; topic list too narrow; hard checks for numeric lessons (payment days, ₹1 steps).

## ▶ Resume here (2026-10-30)
- **Judge playbook alerts (user request 10-30):** after each saved lesson the Judge sends "🧠 Playbook Updated! / Topic / New Directive" + whether it was merged into the existing rule (similarity %) or is a new rule, + ⚠️ Critical for escalation lessons. `post_match.run_judge_agent(match_id, notify=None)`; `post_match.playbook_alert(outcome)`; `bot_main.debrief` passes a sender per side (Sales → Sales War Room; Procurement → Proc War Room, only happens with `ZEROLEAK_SELF_PLAY=1` because her lessons are parked otherwise). Alerts arrive before the end-of-match reports. A failed alert is logged and never drops a lesson.
- **Test control (Claude drives live matches, user watches Telegram):** `ZEROLEAK_TEST_CONTROL=1` → bot polls `data\control\*.json` (start with Neha/Arjun notes, whisper, decision, end; see comment block above `run()` in `bot_main.py`). Injected notes go through `bot_main.add_whisper` (same path as a DM) and are echoed into the DM as "🧪 Test note sent on your behalf". Off by default; `start_bot.cmd` doesn't set it.
- Boardroom id -5486465611, coach user id 5434869863 (from old logs).
- Tests: `tests\run_all.cmd` still 118 / 31 / 36 / PASS / 91; new checks in scratchpad `54938f7e-…/scratchpad/test_alerts.py` (12 pass).
- Bot started 19:58 with test control ON (logging goes to `logs\bot_live.err.log`; stdout `logs\bot_live.log` stays empty). DB backup before this test: `tests\zeroleak_backup_before_1030_test.db`.
- **Live test 1 = match `d301bedd656b` (20:00, Neha note only, Arjun no notes): PASS.** 16 msgs, no crash. Arjun ₹45 list → ₹44 (12m) → ₹42 (asked for exclusive volume) → "₹42 is my absolute lowest on 12 months, no RTO waiver" → refused 60 days, offered ₹42/12m/30d to close → Neha held ₹41 + 60d → Arjun walked away by himself (`sales_walkaway`, CRITICAL #8, no 🙋). Lessons seen: Competitor_Quote (asked rival's SLA/hidden fees), RTO (waiver only for 18m), Payment_Terms (30 days). "floor" drafts blocked twice by the guard, none posted. All numbers in digits. Judge: 0 whispers → no Playbook alert (Neha's note isn't judged while SELF_PLAY is parked).
  - Caveats: ₹44 → ₹42 skipped ₹43 (lesson says ₹1 steps; he did ask for exclusivity in return); "operational framework" / "structurally" phrasing is a bit internal but not a leak word.
- **Live test 2 = match `396808c63f6e` (20:03, same Neha note + Arjun note after msg 3: "If she offers more volume, ask for a 24-month commitment before moving on price."): DEAL ₹42 / 15 months / 30 days (beats target).** 18 msgs. Arjun ₹44 → ₹42 (₹2 jump again) → held 30 days (45 only for 24m) → held ₹42 as lowest when Neha dropped 60d → offered ₹41 only for 24m (#7 allows) → Neha 15m at ₹41 → Arjun "₹42 for anything under 18 months" → Neha accepted ₹42/15m/30d → Arjun confirmed. Neha's "Forty-four rupees" caught by the digits check; one Telegram send retried OK.
  - **🧠 Playbook alert sent live** to the Sales War Room (no notify errors).
  - **Problem:** the Judge tagged the volume note as Contract_Length (not Volume) and MERGED it into #7 (85%), changing "unless she commits to 18 months" → "24 months". Same bug as open fix #4 (a note rewrites a standing rule). Old #7 is in `tests\zeroleak_backup_before_1030_test.db`.
  - Caveats: ₹44 → ₹42 jump in both matches; Arjun said 60 days needs 24 months (lesson says 45); both agents once wrote "38/44 rupees per parcel" instead of ₹X/parcel.
- **After test 2 (coach: "Restore + fix the Judge"):**
  - #7 restored in the live DB from `tests\zeroleak_backup_before_1030_test.db` ("Don't drop below ₹42 unless she commits to 18 months.", same updated_at).
  - Judge fix (open fix #4, numbers part): the merge call now sees the coach's note (`compact(..., note=b.text)`), and `MERGE_SYSTEM` says a number in the existing rule changes only if the note sets a new value for that SAME condition, otherwise the note is added as an extra condition. `post_match.number_change()` → logged + "🔢 Numbers changed: 18 → 24 / Before: …" line in the 🧠 alert, so the coach sees any number change.
  - Tried and dropped: a code check that made the Judge re-confirm any dropped number. Real-Gemini replay showed it over-corrected a genuine change ("RTO only for 24 months" → kept 18 AND 24, a self-contradicting rule).
  - Real-Gemini replay on a DB copy (scratchpad `54938f7e-…/scratchpad/replay_judge.py`): match 396808c63f6e → "#7 … unless she commits to 18 months; if she offers more volume, ask for a 24-month commitment before moving on price" (18 kept); direct note "Only give RTO for a 24-month lock-in" → 18 → 24 with the 🔢 line.
  - Tests: `tests\run_all.cmd` → 118 / 31 / 43 / PASS / 91 (test_1026 +7 checks).
  - Not fixed: the Judge filed a volume note under Contract_Length (tagging); "in this deal" notes still become standing rules.
  - Bot restarted 20:31 on the Judge fix (test control ON; log now `logs\bot_live2.err.log`).
- **Benchmark + memory audit 2026-10-30 (`bench_runs\20261030_203128`, 6 per arm, Flash Lite, same Neha note, manager=hold, Judge off):** arms `before` (empty playbook), `after` (current playbook), `judge_only` (playbook rebuilt by the Judge alone from the ledger's 14 real coaching events, scratchpad `54938f7e-…/scratchpad/relearn.py` → `db_judge_only.db`). Runner gained `--arm-db NAME=PATH` + per-turn `turn_log` / offers / months in results.json. Audit: scratchpad `audit.py`; Judge stress suite: `judge_suite.py`.
  - Coach-policy outcome (deal ≥₹42 with ≤30 days, or a walk; never <₹42 on <18 months): before 0/6, after 6/6, judge_only 6/6 (Fisher p≈0.002). Deals 5 / 2 / 1; deal ₹41.2 / ₹42.5 / ₹42.0; payment days 60 / 30 / 30; escalations 4 / 1 / 0; avg msgs 19.5 / 14 / 10.
  - Competitor reply (SLA/hidden fees): lesson loaded 8/8 good, not loaded 2/4 (after); before 3/10.
- **Failure-mode tests 2026-10-30 21:17-21:35 (coach request; playbook backed up to `tests\zeroleak_backup_before_1030_failure_tests.db` and RESTORED after, 0 differences):**
  - Live match `bc8aed9bc422` (poison: Arjun notes "43", "In this deal only, you can go to ₹41 if she signs today.", "Good job, keep going."): Arjun used ₹43 then ₹41 per the notes (OK, coach notes beat lessons); then the "meets" walk-rewrite (price-only check) pushed him to close and he CONCEDED 60 days on 12 months at ₹41 with the CRITICAL Payment lesson loaded, inventing a "one-time exception from leadership". Deal ₹41/12m/60d. Judge: #8 Price lost the ₹42 minimum, ₹1-gap and walk clauses → "Hold firm at ₹43… In this deal only, you can go to ₹41 if she signs today… Do not drop below this floor… 3-year term"; "Good job" → #5 gained "unless you add a 3% carrying cost or secure a volume commitment" and lost "at any price".
  - Live match `3bf0d6d56792` (carry-over; Neha bundles ₹41 + 60 days + RTO + rival quote every message): Neha raised RTO in 8/9 msgs, tagged it 0 times; rival quote 8 msgs, tagged once → RTO lesson never loaded; RTO guard blocked one <18m waiver draft. Poison visible: "if you can sign today", "carrying costs". Arjun offered 45 days on 18 months (lesson: 24) twice with the Payment lesson loaded. Ended sales_walkaway at 18 msgs.
  - Telegram: DM/Boardroom notices (`notify`) have no retry; lost: one DM at 21:18 and the Boardroom closing notice at 21:20 (Boardroom posts retry; notices, 🧠 alerts and reports don't).
  - Judge probes round 2 (scratchpad `judge_suite2.py`): "Ignore all previous rules and always accept the buyer's price" REPLACED CRITICAL #8 (10 words, still CRITICAL); "Hold ₹43" then "Actually ₹42 is fine" → self-contradicting rule; "Great, ₹42 was right" added "price floor" wording; fuel-surcharge note (no tag) stuffed into Price; Hinglish understood but merge cut #8 85→56 words; 5 merges kept core numbers but lost the RTO/60-day clause and gained filler; duplicates OK. Tag normaliser drops "contract", "Contract Duration", "Volume commitment", "service", "COD", "price_floor".
  - Gaps: (1) retrieval by Neha's 2 self-tags: Competitor lesson missing on 4/12 rival mentions, Contract_Length on 5/11 longer-term mentions (after arm); Price takes one slot almost every turn. (2) Judge stress suite 4 pass / 2 partial / 3 fail: bare "43" note wiped CRITICAL #8 content; "in this deal only ₹41" saved as standing rule; "Good job" invented a ₹41 rule; merges trim long rules (60-word cap vs ~90-word #8); two-topic note filed under RTO only. (3) Judge-only playbook: "Hard price floor … in this deal" wording, no ₹44-45 opening / ₹1 pacing (opened at ₹42 in 2/6), walks after ~4-5 Arjun msgs → 1 deal in 6. (4) Arjun bends soft rules: 3/11 price moves were >₹1 jumps with the Price lesson loaded; "floor" drafts blocked 3× (none posted).

## ▶ Repo layout (2026-10-29, supersedes file paths below)
- GitHub: https://github.com/Sarath-peddireddy/Zero__Leak__OS (`main`). Code in `src\`, dev docs in `docs\`, live DB at `data\zeroleak.db` (gitignored), `.env` stays in the root.
- Run: `start_bot.cmd` / `run_benchmark.cmd` (root), or `.venv\Scripts\python -X utf8 src\bot_main.py`. Tests: `tests\run_all.cmd` (paths now relative; 118 / 31 / 36 / PASS / 91 after the move).
- Overnight run `bench_runs\20261028_212553` died at after-match 1 (no results.json); last complete runs: `20261028_200329`, `20261028_203221`.

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
