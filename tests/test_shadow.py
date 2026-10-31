"""Offline tests for the 2026-10-31 memory pipeline hardening (no Gemini, no Telegram, DB copies only):
  1. staging gate table: migration of the 10-30 pending_lessons table, superseding, sent tracking;
  2. shadow regression: snapshot + proposal copy, the child-process runner (a stand-in script), timeouts,
     the delta text in the approval request;
  3. review_proposals: shadow result -> stored -> approval request with the delta (and reused after a restart);
  4. bot wiring: debrief stores the War Room and runs the review; startup resumes unsent requests.
"""

import asyncio
import json
import shutil
import sqlite3
import sys
import textwrap
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))
import os  # noqa: E402
# .env may hold dev settings: a test never starts real shadow matches (Gemini), and pins self-play.
os.environ.setdefault("ZEROLEAK_SHADOW_MATCHES", "0")
os.environ.setdefault("ZEROLEAK_SELF_PLAY", "0")

import db_init  # noqa: E402

TEST_DB = HERE / "test_shadow.db"
shutil.copy(HERE / "zeroleak_backup_before_1031_neha_tests.db", TEST_DB)  # 5 sales lessons, 10-30 pending table
# a 10-30 style proposal, already announced to the coach at the time
with sqlite3.connect(TEST_DB) as c:
    c.execute("INSERT INTO pending_lessons (side, topic_tag, past_mistake, new_directive, previous_directive, reason) "
              "VALUES ('sales', 'Volume', 'm', 'old proposal', '', 'r')")
db_init.DB_PATH = TEST_DB

import llm_engine  # noqa: E402
import post_match as P  # noqa: E402
import shadow_test as S  # noqa: E402
import bot_main as B  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))


async def no_llm(*a, **k):
    raise AssertionError("no LLM call expected")

llm_engine.generate = no_llm
run = asyncio.run
run(db_init.init_db())

# ================================================================ 1. staging table migration
with sqlite3.connect(TEST_DB) as c:
    sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'pending_lessons'").fetchone()[0]
    cols = {r[1] for r in c.execute("PRAGMA table_info(pending_lessons)")}
    old = c.execute("SELECT new_directive, status, sent_at FROM pending_lessons WHERE pending_id = 1").fetchone()
check("migration: 'superseded' status + new columns", "'superseded'" in sql
      and {"source_note", "shadow_json", "war_room_chat_id", "sent_at"} <= cols, (sql, cols))
check("migration: old proposal kept and marked as already sent (never re-sent)",
      old[0] == "old proposal" and old[1] == "pending" and old[2] is not None, old)
run(db_init.init_db())
check("migration is idempotent", run(db_init.fetch_pending(1))["new_directive"] == "old proposal")
check("old proposal not in the unsent list", all(r["pending_id"] != 1 for r in run(db_init.fetch_unsent_pending())))
run(db_init.resolve_pending(1, approve=False))
try:
    run(db_init.update_pending(1, status="approved"))
    check("update_pending refuses other fields", False)
except ValueError:
    check("update_pending refuses other fields", True)

# ================================================================ 2a. shadow copies
PRICE = run(db_init.fetch_heuristic("sales", "Price"))
pid = run(db_init.save_pending("sales", "Price", "m", "Hold ₹43 on 12 months. TEST-BETTER", True,
                               previous=PRICE["new_directive"], reason="", note="Hold ₹43."))
row = run(db_init.fetch_pending(pid))
work = HERE / "shadow_test_tmp"
shutil.rmtree(work, ignore_errors=True)
work.mkdir()
run(db_init.snapshot_db(work / "snap.db"))
S._copy_with_proposal(work / "snap.db", work / "prop.db", row)
with sqlite3.connect(work / "prop.db") as c:
    copied = c.execute("SELECT new_directive, is_critical FROM sales_heuristics WHERE topic_tag = 'Price'").fetchone()
    n = c.execute("SELECT count(*) FROM sales_heuristics").fetchone()[0]
check("proposal written into the copy (same UPSERT, stays critical)", copied == (row["new_directive"], 1), copied)
check("copy keeps the rest of the playbook", n == 5, n)
check("live playbook untouched", run(db_init.fetch_heuristic("sales", "Price"))["new_directive"] == PRICE["new_directive"])

# ================================================================ 2b. child-process runner (stand-in script)
FAKE = work / "fake_runner.py"
FAKE.write_text(textwrap.dedent('''
    import argparse, json, sqlite3, sys, time
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int); ap.add_argument("--arms"); ap.add_argument("--run-dir")
    ap.add_argument("--arm-db", action="append", default=[]); ap.add_argument("--neha-note")
    a = ap.parse_args()
    run_dir = Path(a.run_dir)
    (run_dir / "argv.json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
    if a.neha_note == "SLEEP":
        time.sleep(30)
    dbs = dict(s.split("=", 1) for s in a.arm_db)
    summary = {}
    for arm in a.arms.split(","):
        with sqlite3.connect(dbs[arm]) as c:
            better = any("TEST-BETTER" in r[0] for r in c.execute("select new_directive from sales_heuristics"))
        summary[arm] = {"matches": a.matches, "deals": 4 if better else 3, "avg_deal_rate": 42.5 if better else 42.0,
                        "avg_margin_over_floor": 1.5 if better else 1.0, "avg_payment_days": 30 if better else 45,
                        "avg_escalations": 0.2 if better else 0.6, "leaks": 0, "rto_given_in_deals": 0}
    (run_dir / "results.json").write_text(json.dumps({"summary": summary}), encoding="utf-8")
    sys.exit(3 if a.neha_note == "FAIL" else 0)
'''), encoding="utf-8")
S.RUNNER, S.SHADOW_DIR, S.SHADOW_MATCHES = FAKE, work / "runs", 5

results = run(S.run_shadow([row]))
r = results.get(pid)
check("run_shadow: one result per proposal, both arms read", r is not None and r.ok and r.error == ""
      and r.control["avg_margin_over_floor"] == 1.0 and r.proposed["avg_margin_over_floor"] == 1.5, r)
argv = json.loads((Path(r.run_dir) / "argv.json").read_text(encoding="utf-8"))
check("runner args: 5 matches, control + proposal arms, own run dir, standard Neha note for a sales proposal",
      argv[argv.index("--matches") + 1] == "5" and argv[argv.index("--arms") + 1] == f"control,p{pid}"
      and argv[argv.index("--run-dir") + 1] == r.run_dir and "--neha-note" not in argv, argv)
check("snapshot + proposal copy are in the run folder", (Path(r.run_dir) / "snapshot.db").exists()
      and (Path(r.run_dir) / f"proposal_{pid}.db").exists())
check("mandate volume priced in", r.volume == 1_200_000, r.volume)

proc_row = dict(row, pending_id=999, side="procurement", topic_tag="Price")
S.NEHA_NOTE["procurement"] = "FAIL"   # the stand-in exits with code 3 after writing results
r2 = run(S.run_shadow([proc_row]))[999]
check("runner error kept (plain words), finished results still used", r2.ok and "code 3" in r2.error
      and "runner.log" not in r2.error, r2)
S.NEHA_NOTE["procurement"] = "SLEEP"
S.SHADOW_TIMEOUT_S = 1.0
r3 = run(S.run_shadow([proc_row]))[999]  # same proposal ids, same second: must not reuse r2's folder
check("every run gets its own folder (never another run's results)", r3.run_dir != r2.run_dir, (r2.run_dir, r3.run_dir))
check("timeout -> child killed, error reported, nothing to compare", not r3.ok and "timed out after 1s" in r3.error, r3)
S.SHADOW_TIMEOUT_S, S.NEHA_NOTE["procurement"] = 600.0, ""
S.SHADOW_MATCHES = 0
check("switched off -> no run at all", run(S.run_shadow([row])) == {})
S.SHADOW_MATCHES = 5

# ================================================================ 2c. the delta text
text = S.shadow_lines(r)
check("sales delta: margin, ₹/month, deals, payment days, questions, small-sample note",
      all(k in text for k in ("₹1 → ₹1.5/parcel", "<b>+₹0.5/parcel</b>", "+₹600,000/month", "Deals: 3/5 → 4/5",
                              "45 → 30 days", "0.6 → 0.2", "small sample")), text)
pr = S.ShadowResult("procurement", 5, {"matches": 5, "deals": 2, "avg_deal_rate": 42.0, "avg_payment_days": 30,
                                      "rto_given_in_deals": 0},
                    {"matches": 3, "deals": 3, "avg_deal_rate": 41.5, "avg_payment_days": 45, "rto_given_in_deals": 1},
                    1_200_000, "", "timed out after 180 minutes")
text = S.shadow_lines(pr)
check("procurement delta: price down = saving, RTO won, partial run flagged",
      all(k in text for k in ("₹42 → ₹41.5/parcel", "<b>−₹0.5/parcel</b>", "₹600,000/month saved",
                              "RTO waiver won: 0/2 → 1/3", "Only 3 of 5 matches")), text)
nodeal = S.ShadowResult("sales", 5, {"matches": 5, "deals": 0, "avg_margin_over_floor": None},
                        {"matches": 5, "deals": 2, "avg_margin_over_floor": 1.0})
check("no deals in one arm -> no like-for-like claim", "no deals → ₹1/parcel" in S.shadow_lines(nodeal),
      S.shadow_lines(nodeal))
check("failed run -> decide on the text alone", "could not run" in S.shadow_lines(r3) and "timed out" in S.shadow_lines(r3))
S.SHADOW_MATCHES = 0
check("off -> says so", "switched off" in S.shadow_lines(None))
S.SHADOW_MATCHES = 5
check("result survives the JSON round trip", S.ShadowResult.from_json(r.to_json()) == r)

# ================================================================ 3. review_proposals
sent = []


async def notify(side, text, pending_id=None):
    sent.append((side, text, pending_id))

calls = []
real_run_shadow = S.run_shadow


async def counting_run_shadow(rows):
    calls.append([x["pending_id"] for x in rows])
    return await real_run_shadow(rows)

S.run_shadow = counting_run_shadow
run(P.review_proposals([pid], notify))
check("review: shadow test ran once, then ONE approval request with the delta and the id",
      calls == [[pid]] and len(sent) == 1 and sent[0][2] == pid and "<b>+₹0.5/parcel</b>" in sent[0][1]
      and "Playbook Update Proposed" in sent[0][1], (calls, sent))
stored = run(db_init.fetch_pending(pid))
check("shadow result + sent time stored on the proposal", stored["shadow_json"] and stored["sent_at"])
sent.clear()
run(P.review_proposals([pid], notify))
check("a stored shadow result is reused (no second run)", calls == [[pid]] and len(sent) == 1, calls)
sent.clear()
run(db_init.resolve_pending(pid, approve=False))
run(P.review_proposals([pid], notify))
check("answered proposal -> nothing sent", sent == [], sent)

# ================================================================ 4. bot wiring
class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


async def fake_judge(match_id, notify=None):
    p = await db_init.save_pending("sales", "RTO", "m", "RTO only for 18 months. TEST-BETTER", False,
                                   previous=(await db_init.fetch_heuristic("sales", "RTO"))["new_directive"],
                                   reason="", note="RTO only for 18 months.")
    return [P.JudgeOutcome("RTO only for 18 months.", "proposed", "sales", "RTO", p, None,
                           directive="RTO only for 18 months. TEST-BETTER", previous="x")]

import reports  # noqa: E402

orig = P.run_judge_agent, reports.extract_terms, reports.procurement_report, reports.sales_report
P.run_judge_agent = fake_judge


async def no_terms(match):
    return reports.DealTerms()

reports.extract_terms = no_terms
reports.procurement_report = reports.sales_report = lambda *a, **k: "📋 report"
sb, pb = FakeBot(), FakeBot()
run(B.debrief({"match_id": "m", "sales_war_room_chat_id": 55, "procurement_war_room_chat_id": None}, sb, pb, None))
order = [t[:12] for _, t, _ in sb.sent]
req = [(c, t, m) for c, t, m in sb.sent if "Playbook Update Proposed" in t]
check("debrief: reports first, then the approval request", order[-1].startswith("🧠") and order[0] == "📋 report", order)
check("debrief: request in the Sales War Room with ✅ Approve / ❌ Reject",
      req and req[0][0] == 55 and [b.callback_data.split(":")[1] for b in req[0][2].inline_keyboard[0]] == ["ok", "no"]
      and [b.text for b in req[0][2].inline_keyboard[0]] == ["✅ Approve", "❌ Reject"], req)
new_id = int(req[0][2].inline_keyboard[0][0].callback_data.split(":")[2])
check("debrief stored the War Room on the proposal", run(db_init.fetch_pending(new_id))["war_room_chat_id"] == 55)
run(db_init.resolve_pending(new_id, approve=False))
P.run_judge_agent, reports.extract_terms, reports.procurement_report, reports.sales_report = orig

# restart: a proposal staged + War Room known, request never sent -> sent at startup
rto = run(db_init.fetch_heuristic("sales", "RTO"))["new_directive"]
lost = run(db_init.save_pending("sales", "RTO", "m", rto + " TEST-BETTER", False, previous=rto, reason="", note="n"))
run(db_init.update_pending(lost, war_room_chat_id=77))
orphan = run(db_init.save_pending("sales", "SLA", "m", "Cite SLA.", False, previous="", reason="", note="n"))  # no chat
calls.clear()
sb = FakeBot()
run(B.resume_proposals(sb, FakeBot()))
check("startup: unsent proposal shadow-tested and sent to its War Room",
      calls == [[lost]] and len(sb.sent) == 1 and sb.sent[0][0] == 77 and "Playbook Update Proposed" in sb.sent[0][1],
      (calls, sb.sent))
sb = FakeBot()
run(B.resume_proposals(sb, FakeBot()))
check("startup again: nothing left to send (the one without a War Room is skipped)", sb.sent == [], sb.sent)
check("approve after the shadow test -> live", run(B.answer_lesson(lost, True)).startswith("✅")
      and run(db_init.fetch_heuristic("sales", "RTO"))["new_directive"].endswith("TEST-BETTER"))
S.run_shadow = real_run_shadow

shutil.rmtree(work, ignore_errors=True)
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
