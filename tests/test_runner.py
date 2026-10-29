"""Offline smoke test for headless_runner.py (fake Gemini, 1 match per arm)."""
import asyncio
import json
import sys
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, r"C:\Users\sarat\Desktop\zeroleakos")
sys.argv = ["headless_runner.py", "--matches", "1", "--delay", "0", "--out", str(SCRATCH / "bench_test")]
import headless_runner as H  # noqa: E402

CALLS = []


def j(**kw):
    return json.dumps(kw)


async def fake(agent, prompt, system_instruction=None, json_mode=False, temperature=None):
    CALLS.append((agent, system_instruction))
    since = CALLS[max((i for i, (a, _) in enumerate(CALLS[:-1]) if a == "judge"), default=-1) + 1:]
    n = sum(a == agent for a, _ in since)  # count within the current match (a judge call ends a match)
    if agent == "procurement":
        return j(message=f"We ship 1.2M parcels/month. ₹41/parcel, 12 months ({n}).", internal_note="",
                 proposed_price=41, current_friction_points=["Price"], executed_directive_ids=[0],
                 deal_closed=n >= 4, walk_away=False)
    if agent == "sales":
        if n == 3:  # one escalation, answered by the auto manager
            return j(message="", proposed_price=None, requires_manager_approval=True,
                     escalation_message_to_manager="Close or hold?")
        # A leak the scoreboard counts but the guard does not rewrite ("playbook"/"floor" are rewritten since 10-27).
        return j(message=f"₹42/parcel, as my manager said ({n}).", proposed_price=42, offers_rto_waiver=False,
                 contract_months=12, current_friction_points=["Price"], executed_directive_ids=[],
                 requires_manager_approval=False, escalation_message_to_manager="",
                 deal_closed=n >= 5, walk_away=False)
    return j(rate_per_parcel=42, rto_waiver="not_included", payment_terms_days=30, contract_months=12,
             buyer_commitments=[], open_items=[], procurement_summary="s", sales_summary="s", next_step="n")


H.llm_engine.generate = fake
H.N.llm_engine.generate = fake
H.reports.llm_engine.generate = fake
asyncio.run(H.main())

runs = sorted((SCRATCH / "bench_test").iterdir())
data = json.loads((runs[-1] / "results.json").read_text(encoding="utf-8"))
ok = True
for arm in ("before", "after"):
    s, m = data["summary"][arm], [r for r in data["matches"] if r["arm"] == arm][0]
    checks = {"one match": s["matches"] == 1, "deal": m["deal"], "rate 42": m["rate"] == 42,
              "payment 30": m["payment_days"] == 30, "1 escalation": m["escalations"] == 1,
              "leak counted": m["leaks"] >= 1, "lowest 42": m["arjun_lowest"] == 42}
    for name, cond in checks.items():
        print(("PASS " if cond else "FAIL ") + f"{arm}: {name}")
        ok &= cond
before_db, after_db = runs[-1] / "db_before.db", runs[-1] / "db_after.db"
import sqlite3  # noqa: E402
nb = sqlite3.connect(before_db).execute("select count(*) from sales_heuristics").fetchone()[0]
na = sqlite3.connect(after_db).execute("select count(*) from sales_heuristics").fetchone()[0]
print(("PASS" if nb == 0 and na == 5 else "FAIL") + f" playbooks: before={nb} after={na}")
sales_prompts = [s for a, s in CALLS if a == "sales"]
print(("PASS" if any("PLAYBOOK" in s for s in sales_prompts) and not all("PLAYBOOK" in s for s in sales_prompts)
       else "FAIL") + " after arm sees lessons, before arm does not")
real = sqlite3.connect(r"C:\Users\sarat\Desktop\zeroleakos\zeroleak.db").execute(
    "select count(*) from match_transcripts where match_id in (%s)" % ",".join("?" * len(data["matches"])),
    [r["match_id"] for r in data["matches"]]).fetchone()[0]
print(("PASS" if real == 0 else "FAIL") + " real zeroleak.db untouched by the run")
