"""
ZeroLeak OS - Shadow regression test: evidence that a proposed playbook change helps before it goes live.

Every change the Judge stages in pending_lessons is played headless (AI vs AI) before the human manager is
asked to approve it:

    control   SHADOW_MATCHES matches on a snapshot of the live DB (today's live playbook)
    p<id>     SHADOW_MATCHES matches on the same snapshot with proposal <id> written into the playbook

headless_runner.py plays the arms interleaved (control, p12, p13, control, ...) so a slow Gemini hour hits
all of them. It runs in its OWN process: it switches db_init.DB_PATH globally, so it must never share the live
bot's process. Its Judge is off, so no shadow match changes any lesson, and nothing touches the live DB.

  * One shadow run at a time: the runs share the Gemini keys with live matches.
  * Proposals for Arjun are played against the runner's standard Neha note; proposals for Neha without a note
    (her lessons are what is being tested). Mixed sides run one after the other.
  * The runner saves results after every match, so a run that fails or times out still reports what it
    finished, and the coach always gets the approval request.

The result goes into the 🧠 approval request (post_match.proposal_alert, via shadow_lines) and is stored in
pending_lessons.shadow_json. Raw runs: bench_runs/shadow/<timestamp>_<side>_<ids>/.

Settings (env): ZEROLEAK_SHADOW_MATCHES (matches per arm, default 5; 0 = off),
                ZEROLEAK_SHADOW_TIMEOUT_S (whole run, default 10800 = 3 hours).
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from pathlib import Path

import db_init
from db_init import HEURISTICS_TABLES, SIDES

logger = logging.getLogger("zeroleak.shadow")

ROOT = Path(__file__).resolve().parent.parent
RUNNER = Path(__file__).resolve().parent / "headless_runner.py"
SHADOW_DIR = ROOT / "bench_runs" / "shadow"
SHADOW_MATCHES = int(os.getenv("ZEROLEAK_SHADOW_MATCHES", "5").strip() or 0)
SHADOW_TIMEOUT_S = float(os.getenv("ZEROLEAK_SHADOW_TIMEOUT_S", "10800").strip() or 10800)
NEHA_NOTE = {"sales": None, "procurement": ""}  # None = the runner's standard note for Neha
CONTROL = "control"

_lock = asyncio.Lock()


@dataclass
class ShadowResult:
    side: str
    matches_planned: int
    control: dict | None = None    # headless_runner summary for the live playbook
    proposed: dict | None = None   # ... and with the proposal applied
    volume: int | None = None      # the mandate's parcels/month, to price a ₹/parcel change
    run_dir: str = ""
    error: str = ""                # why the run stopped early ('' = finished)

    @property
    def ok(self) -> bool:
        return bool(self.control and self.proposed and self.control.get("matches") and self.proposed.get("matches"))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str | None) -> "ShadowResult | None":
        return cls(**json.loads(text)) if text else None


# ------------------------------------------------------------------ running


def _copy_with_proposal(base: Path, dest: Path, proposal: dict) -> None:
    """`base` + the proposed rule written into its side's playbook (the same UPSERT approval would do)."""
    src, dst = sqlite3.connect(base), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        src.close()
    table = HEURISTICS_TABLES[proposal["side"]]
    try:
        with dst:
            dst.execute(
                f"INSERT INTO {table} (topic_tag, past_mistake, new_directive, is_critical) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(topic_tag) DO UPDATE SET past_mistake = excluded.past_mistake, "
                f"new_directive = excluded.new_directive, is_critical = MAX({table}.is_critical, excluded.is_critical)",
                (proposal["topic_tag"], proposal["past_mistake"], proposal["new_directive"], proposal["is_critical"]))
    finally:
        dst.close()


async def _run_runner(arms: dict[str, Path], run_dir: Path, neha_note: str | None) -> str:
    """Play the arms in a child process; returns '' or why it stopped early."""
    cmd = [sys.executable, "-X", "utf8", str(RUNNER), "--matches", str(SHADOW_MATCHES),
           "--arms", ",".join(arms), "--run-dir", str(run_dir)]
    for name, path in arms.items():
        cmd += ["--arm-db", f"{name}={path}"]
    if neha_note is not None:
        cmd += ["--neha-note", neha_note]
    env = {**os.environ, "ZEROLEAK_SHADOW_MATCHES": "0", "ZEROLEAK_TEST_CONTROL": ""}
    with open(run_dir / "runner.log", "wb") as log:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=ROOT, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=log, stderr=asyncio.subprocess.STDOUT)
        try:
            code = await asyncio.wait_for(proc.wait(), SHADOW_TIMEOUT_S)
        except (TimeoutError, asyncio.CancelledError) as e:
            proc.kill()
            await proc.wait()
            if isinstance(e, asyncio.CancelledError):  # the bot is shutting down
                raise
            limit = f"{SHADOW_TIMEOUT_S / 60:.0f} minutes" if SHADOW_TIMEOUT_S >= 60 else f"{SHADOW_TIMEOUT_S:.0f}s"
            logger.warning("Shadow run timed out after %s: %s", limit, run_dir)
            return f"timed out after {limit}"
    if code:  # the coach sees a plain line; the details stay in the log
        logger.warning("Shadow runner exited with code %s; see %s", code, run_dir / "runner.log")
        return f"the test run stopped early (code {code})"
    return ""


def _read_summary(run_dir: Path) -> dict:
    path = run_dir / "results.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("summary", {})
    except (OSError, ValueError):
        return {}


async def _run_side(side: str, proposals: list[dict]) -> dict[int, ShadowResult]:
    ids = [p["pending_id"] for p in proposals]
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y%m%d_%H%M%S}_{side}_{'_'.join(map(str, ids))}"
    for n in range(1, 1000):  # a fresh folder every run: never read another run's results.json
        run_dir = SHADOW_DIR / (stem if n == 1 else f"{stem}_{n}")
        try:
            run_dir.mkdir()
            break
        except FileExistsError:
            continue
    base = run_dir / "snapshot.db"
    await db_init.snapshot_db(base)
    arms = {CONTROL: base}
    for p in proposals:
        path = run_dir / f"proposal_{p['pending_id']}.db"
        await asyncio.to_thread(_copy_with_proposal, base, path, p)
        arms[f"p{p['pending_id']}"] = path
    mandate = await db_init.fetch_mandate()
    logger.info("Shadow test: %s proposal(s) %s, %d matches per arm, in %s", side, ids, SHADOW_MATCHES, run_dir)
    error = await _run_runner(arms, run_dir, NEHA_NOTE[side])
    summary = _read_summary(run_dir)
    out = {}
    for p in proposals:
        r = ShadowResult(side, SHADOW_MATCHES, summary.get(CONTROL), summary.get(f"p{p['pending_id']}"),
                         mandate["volume"] if mandate else None, str(run_dir), error)
        if not r.ok and not r.error:
            r.error = "no match finished"
        out[p["pending_id"]] = r
        logger.info("Shadow test #%d [%s %s]: %s", p["pending_id"], side, p["topic_tag"],
                    r.error or "done")
    return out


async def run_shadow(proposals: list[dict]) -> dict[int, ShadowResult]:
    """Shadow-test proposals (pending_lessons rows). {} when switched off (SHADOW_MATCHES = 0).

    Never raises for a failed run: each proposal then gets a ShadowResult with `error` set (cancellation, at
    shutdown, is passed on after the child process is stopped)."""
    if SHADOW_MATCHES <= 0 or not proposals:
        return {}
    out: dict[int, ShadowResult] = {}
    async with _lock:
        for side in SIDES:
            mine = [p for p in proposals if p["side"] == side]
            if not mine:
                continue
            try:
                out.update(await _run_side(side, mine))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  (the approval request must still go out)
                logger.exception("Shadow test failed for %s proposals %s", side, [p["pending_id"] for p in mine])
                out.update({p["pending_id"]: ShadowResult(side, SHADOW_MATCHES, error=type(e).__name__)
                            for p in mine})
    return out


# ------------------------------------------------------------------ reporting (Telegram HTML)


def _n(x: float) -> str:
    """42.0 -> '42', 41.5 -> '41.5', 1.25 -> '1.25'."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _signed(x: float) -> str:
    """+₹0.5/parcel, −₹1/parcel, ±₹0/parcel."""
    return ("+" if x > 0 else "−" if x < 0 else "±") + f"₹{_n(abs(x))}/parcel"


def _per_month(delta: float, volume: int | None) -> str:
    """₹/parcel change priced on the mandate's monthly volume (digits, never words)."""
    if not volume or not delta:
        return ""
    return f"₹{abs(delta) * volume:,.0f}/month"


def shadow_lines(result: "ShadowResult | None") -> str:
    """The shadow-test block of a 🧠 approval request (HTML)."""
    if SHADOW_MATCHES <= 0 and result is None:
        return "🧪 <b>Shadow test:</b> switched off, so there is no test result for this change."
    if result is None or not result.ok:
        return ("🧪 <b>Shadow test:</b> could not run this time"
                f"{f' ({escape(result.error)})' if result and result.error else ''}. Decide on the text alone.")
    c, p, n = result.control, result.proposed, result.matches_planned
    played = min(c["matches"], p["matches"])
    head = (f"🧪 <b>Shadow test</b> ({c['matches']} matches with the current lesson, {p['matches']} with the "
            f"proposed one; AI vs AI, same opponent):")
    lines = [head]
    if result.side == "sales":
        a, b = c.get("avg_margin_over_floor"), p.get("avg_margin_over_floor")
        if a is not None and b is not None:
            d = b - a
            money = _per_month(d, result.volume)
            money = f", ≈ {'+' if d > 0 else '−'}{money}" if money else ""
            lines.append(f"• Avg closing margin over the floor: ₹{_n(a)} → ₹{_n(b)}/parcel "
                         f"(<b>{_signed(d)}</b>{money})")
        else:
            lines.append(f"• Avg closing margin: {'no deals' if a is None else f'₹{_n(a)}/parcel'} → "
                         f"{'no deals' if b is None else f'₹{_n(b)}/parcel'} (no like-for-like comparison)")
    else:
        a, b = c.get("avg_deal_rate"), p.get("avg_deal_rate")
        if a is not None and b is not None:
            d = b - a
            money = _per_month(d, result.volume)
            money = f", ≈ {money} {'saved' if d < 0 else 'more'}" if money else ""
            lines.append(f"• Avg closing price: ₹{_n(a)} → ₹{_n(b)}/parcel (<b>{_signed(d)}</b>{money})")
        else:
            lines.append(f"• Avg closing price: {'no deals' if a is None else f'₹{_n(a)}/parcel'} → "
                         f"{'no deals' if b is None else f'₹{_n(b)}/parcel'} (no like-for-like comparison)")
    lines.append(f"• Deals: {c['deals']}/{c['matches']} → {p['deals']}/{p['matches']}")
    a, b = c.get("avg_payment_days"), p.get("avg_payment_days")
    if a is not None and b is not None:
        lines.append(f"• Avg payment terms in deals: {_n(a)} → {_n(b)} days")
    if result.side == "sales":
        a, b = c.get("avg_escalations"), p.get("avg_escalations")
        if a is not None and b is not None and (a or b):
            lines.append(f"• Questions to you per match: {_n(a)} → {_n(b)}")
        if c.get("leaks") or p.get("leaks"):
            lines.append(f"• Messages mentioning internal rules: {c['leaks']} → {p['leaks']}")
    else:
        lines.append(f"• RTO waiver won: {c.get('rto_given_in_deals', 0)}/{c['deals']} → "
                     f"{p.get('rto_given_in_deals', 0)}/{p['deals']} deals")
    if played < n:
        lines.append(f"<i>Only {played} of {n} matches per side finished"
                     f"{f' ({escape(result.error)})' if result.error else ''}.</i>")
    lines.append(f"<i>{played} matches per side is a small sample: read this as a signal, not proof.</i>")
    return "\n".join(lines)
