"""
ZeroLeak OS - Database layer (symmetrical self-play schema).

Every fact either agent may use lives here, not in prompt code:

  Sales side (SwiftRoute)            Procurement side (MegaMart)
  -----------------------            ---------------------------
  sales_cpq_pricing  (rate card)     procurement_mandates   (budget / targets)
  sales_static_ammo  (value facts)   procurement_static_ammo (leverage facts)
  sales_heuristics   (lessons)       procurement_heuristics  (lessons)

Plus the shared ledger, match_transcripts.

"Highlander" rule: topic_tag is UNIQUE in both heuristics tables, so there is
exactly one master lesson per topic. The Judge merges new lessons into it with
an UPSERT (see post_match.py) instead of adding rows, so the playbook stays at
one row per topic however many matches are played.

Each side's tables are private to that side: the orchestrator never puts the
buyer's mandate into the Sales prompt, or the rate card into the Procurement prompt.

Older databases are migrated in place on startup (cpq_pricing is renamed,
playbook_heuristics rows move to sales_heuristics, the ledger gains the
Procure_Whisper / Sales_Escalation / Manager_Decision speakers, lessons gain is_critical). sqlite3 is blocking, so every public helper runs in a
worker thread via asyncio.to_thread to keep the Telegram event loop free.
"""

import asyncio
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("zeroleak.db")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "zeroleak.db"

SIDES = ("sales", "procurement")
# Table names come only from these maps (never from user input), so f-string SQL is safe.
HEURISTICS_TABLES = {"sales": "sales_heuristics", "procurement": "procurement_heuristics"}
AMMO_TABLES = {"sales": "sales_static_ammo", "procurement": "procurement_static_ammo"}

# Ledger speakers:
#   Sales_Agent / Procure_Agent   Boardroom messages
#   Human_Whisper                 coaching sent to Sales;  Procure_Whisper: coaching sent to Procurement
#   Sales_Escalation              Arjun asked his manager for a decision (two-way escalation)
#   Manager_Decision              the manager's answer, obeyed as an Absolute Override Command
LEDGER_SPEAKERS = ("Sales_Agent", "Procure_Agent", "Human_Whisper", "Procure_Whisper",
                   "Sales_Escalation", "Manager_Decision")

TRANSCRIPTS_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    message_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id     TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    speaker      TEXT    NOT NULL
                 CHECK (speaker IN (""" + ", ".join(f"'{s}'" for s in LEDGER_SPEAKERS) + """)),
    payload_text TEXT    NOT NULL
);
"""

HEURISTICS_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    heuristic_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_tag     TEXT NOT NULL UNIQUE,   -- Highlander: one master rule per topic
    past_mistake  TEXT NOT NULL,
    new_directive TEXT NOT NULL,
    is_critical   INTEGER NOT NULL DEFAULT 0 CHECK (is_critical IN (0, 1)),  -- 1 = learned from a deadlock escalation
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

AMMO_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    ammo_id   INTEGER PRIMARY KEY,
    fact_type TEXT NOT NULL,
    value     TEXT NOT NULL,
    UNIQUE (fact_type, value)
);
"""

SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS sales_cpq_pricing (
    tier_id                 INTEGER PRIMARY KEY,
    volume_slab             TEXT    NOT NULL UNIQUE,
    min_monthly_volume      INTEGER NOT NULL UNIQUE,  -- lower bound of the slab, used to pick the tier
    base_price              REAL    NOT NULL,
    floor_price             REAL    NOT NULL,
    rto_waiver_allowed      INTEGER NOT NULL CHECK (rto_waiver_allowed IN (0, 1)),
    rto_min_contract_months INTEGER CHECK (rto_min_contract_months IS NULL OR rto_min_contract_months > 0),
    CHECK (floor_price > 0 AND floor_price <= base_price)
);

CREATE TABLE IF NOT EXISTS procurement_mandates (
    mandate_id           INTEGER PRIMARY KEY,
    volume               INTEGER NOT NULL CHECK (volume > 0),     -- parcels per month
    incumbent_price      REAL    NOT NULL CHECK (incumbent_price > 0),
    target_price         REAL    NOT NULL,
    walk_away_price      REAL    NOT NULL,                        -- private ceiling
    payment_terms_target INTEGER NOT NULL CHECK (payment_terms_target >= 0),  -- days
    contract_months      INTEGER NOT NULL CHECK (contract_months > 0),
    CHECK (target_price > 0 AND target_price <= walk_away_price)
);
"""
    + TRANSCRIPTS_DDL.format(name="match_transcripts")
    + """
-- The Judge reads one match at a time, in message order.
CREATE INDEX IF NOT EXISTS idx_transcripts_match ON match_transcripts (match_id, message_id);
"""
    + "".join(AMMO_DDL.format(name=t) for t in AMMO_TABLES.values())
    + "".join(HEURISTICS_DDL.format(name=t) for t in HEURISTICS_TABLES.values())
)

# ------------------------------------------------------------ Seed data (dummy MVP)
# Fixed primary keys keep seeding idempotent: INSERT OR IGNORE never duplicates or overwrites.

# SwiftRoute Logistics rate card (INR per parcel).
# (tier_id, volume_slab, min_monthly_volume, base_price, floor_price, rto_waiver_allowed, rto_min_contract_months)
CPQ_SEED = [
    (1, "Up to 250K parcels/mo", 0,         52.0, 48.0, 0, None),
    (2, "250K-500K parcels/mo",  250_000,   49.0, 45.0, 0, None),
    (3, "500K-1M parcels/mo",    500_000,   47.0, 43.0, 0, None),
    (4, "1M-2M parcels/mo",      1_000_000, 45.0, 41.0, 1, 18),
    (5, "2M+ parcels/mo",        2_000_000, 42.0, 38.5, 1, 18),
]
CPQ_COLUMNS = ("tier_id, volume_slab, min_monthly_volume, base_price, floor_price, "
               "rto_waiver_allowed, rto_min_contract_months")

# MegaMart India's brief for this contract.
# (mandate_id, volume, incumbent_price, target_price, walk_away_price, payment_terms_target, contract_months)
MANDATE_SEED = [(1, 1_200_000, 44.0, 38.0, 43.0, 60, 12)]
MANDATE_COLUMNS = ("mandate_id, volume, incumbent_price, target_price, walk_away_price, "
                   "payment_terms_target, contract_months")

# Facts each side may cite. Agents are told never to invent figures beyond these.
AMMO_SEED = {
    "sales": [
        (1, "SLA", "99.98% On-Time Delivery SLA"),
        (2, "Integration", "API integration in under 24 hours"),
        (3, "Account_Management", "Dedicated Account Manager"),
        (4, "Fleet", "Pan-India fleet of 15,000+ active trucks"),
    ],
    "procurement": [
        (1, "Incumbent_Pain_Point", "Our current vendor's on-time delivery fell to about 94% in the last festive peak"),
        (2, "Incumbent_Pain_Point", "Our current vendor charges full RTO penalties, and about 8% of our parcels come back"),
        (3, "Competitor_Quote", "A rival national carrier has quoted ₹40/parcel for this volume, without an RTO waiver"),
        (4, "Leverage", "Our parcel volume is growing about 20% a year, so this account gets bigger"),
    ],
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------ Migration


def _table_sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row[0] if row else None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_sync() -> None:
    """Bring a pre-self-play database up to the current schema. Safe to run every startup."""
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # explicit BEGIN/COMMIT: DDL included
    try:
        conn.execute("BEGIN IMMEDIATE")

        # 1. cpq_pricing -> sales_cpq_pricing (+ the RTO contract-length rule moves from code into the table).
        if _table_sql(conn, "cpq_pricing") and not _table_sql(conn, "sales_cpq_pricing"):
            conn.execute("ALTER TABLE cpq_pricing RENAME TO sales_cpq_pricing")
            logger.info("Migrated: cpq_pricing renamed to sales_cpq_pricing")
        if _table_sql(conn, "sales_cpq_pricing") and "rto_min_contract_months" not in _columns(conn, "sales_cpq_pricing"):
            conn.execute("ALTER TABLE sales_cpq_pricing ADD COLUMN rto_min_contract_months INTEGER "
                         "CHECK (rto_min_contract_months IS NULL OR rto_min_contract_months > 0)")
            for tier_id, *_, months in CPQ_SEED:  # same values the old code hardcoded
                conn.execute("UPDATE sales_cpq_pricing SET rto_min_contract_months = ? "
                             "WHERE tier_id = ? AND rto_waiver_allowed = 1", (months, tier_id))
            logger.info("Migrated: sales_cpq_pricing.rto_min_contract_months added")

        # 2. Ledger: widen the speaker CHECK to every LEDGER_SPEAKERS value (SQLite needs a table rebuild).
        sql = _table_sql(conn, "match_transcripts")
        if sql and any(f"'{s}'" not in sql for s in LEDGER_SPEAKERS):
            conn.execute("DROP INDEX IF EXISTS idx_transcripts_match")
            conn.execute(TRANSCRIPTS_DDL.format(name="match_transcripts_new"))
            conn.execute("INSERT INTO match_transcripts_new (message_id, match_id, timestamp, speaker, payload_text) "
                         "SELECT message_id, match_id, timestamp, speaker, payload_text FROM match_transcripts")
            conn.execute("DROP TABLE match_transcripts")
            conn.execute("ALTER TABLE match_transcripts_new RENAME TO match_transcripts")
            logger.info("Migrated: match_transcripts speakers now %s", ", ".join(LEDGER_SPEAKERS))

        # 2b. Heuristics tables from before escalations: add is_critical.
        for table in HEURISTICS_TABLES.values():
            if _table_sql(conn, table) and "is_critical" not in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN is_critical INTEGER NOT NULL DEFAULT 0 "
                             "CHECK (is_critical IN (0, 1))")
                logger.info("Migrated: %s.is_critical added", table)

        # 3. playbook_heuristics -> sales_heuristics (one row per topic; newest wins on a duplicate tag).
        if _table_sql(conn, "playbook_heuristics"):
            conn.execute(HEURISTICS_DDL.format(name="sales_heuristics"))
            moved = conn.execute(
                "INSERT OR IGNORE INTO sales_heuristics (heuristic_id, topic_tag, past_mistake, new_directive) "
                "SELECT heuristic_id, topic_tag, past_mistake, new_directive FROM playbook_heuristics "
                "ORDER BY heuristic_id DESC"
            ).rowcount
            conn.execute("DROP TABLE playbook_heuristics")
            logger.info("Migrated: %d playbook rule(s) moved to sales_heuristics", moved)

        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _init_db_sync() -> list[dict]:
    _migrate_sync()
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conn.executemany(f"INSERT OR IGNORE INTO sales_cpq_pricing ({CPQ_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         CPQ_SEED)
        conn.executemany(f"INSERT OR IGNORE INTO procurement_mandates ({MANDATE_COLUMNS}) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", MANDATE_SEED)
        for side, rows in AMMO_SEED.items():
            conn.executemany(f"INSERT OR IGNORE INTO {AMMO_TABLES[side]} (ammo_id, fact_type, value) "
                             "VALUES (?, ?, ?)", rows)
    return _fetch_cpq_tiers_sync()


# ------------------------------------------------------------ Reads


def _fetch_cpq_tiers_sync() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(f"SELECT {CPQ_COLUMNS} FROM sales_cpq_pricing ORDER BY min_monthly_volume")
        return [dict(row) for row in rows]


def _fetch_mandate_sync() -> dict | None:
    with _connect() as conn:
        row = conn.execute(f"SELECT {MANDATE_COLUMNS} FROM procurement_mandates ORDER BY mandate_id LIMIT 1").fetchone()
        return dict(row) if row else None


def _fetch_static_ammo_sync(side: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(f"SELECT ammo_id, fact_type, value FROM {AMMO_TABLES[side]} ORDER BY ammo_id")
        return [dict(row) for row in rows]


def _fetch_heuristics_sync(side: str, topic_tags: list[str] | None) -> list[dict]:
    table = HEURISTICS_TABLES[side]
    cols = "heuristic_id, topic_tag, past_mistake, new_directive, is_critical, updated_at"
    with _connect() as conn:
        if topic_tags is None:
            rows = conn.execute(f"SELECT {cols} FROM {table} ORDER BY topic_tag")
            return [dict(row) for row in rows]
        placeholders = ", ".join("?" for _ in topic_tags)
        rows = [dict(r) for r in conn.execute(
            f"SELECT {cols} FROM {table} WHERE topic_tag IN ({placeholders})", topic_tags)]
    order = {tag: i for i, tag in enumerate(topic_tags)}
    return sorted(rows, key=lambda h: order[h["topic_tag"]])  # primary tag's rule first


def _upsert_heuristic_sync(side: str, topic_tag: str, past_mistake: str, new_directive: str,
                           critical: bool) -> int:
    table = HEURISTICS_TABLES[side]
    with _connect() as conn:
        row = conn.execute(
            f"INSERT INTO {table} (topic_tag, past_mistake, new_directive, is_critical) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(topic_tag) DO UPDATE SET past_mistake = excluded.past_mistake, "
            "new_directive = excluded.new_directive, "
            f"is_critical = MAX({table}.is_critical, excluded.is_critical), "  # once critical, stays critical
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "RETURNING heuristic_id",
            (topic_tag, past_mistake, new_directive, int(critical)),
        ).fetchone()
        return row[0]


def _log_message_sync(match_id: str, speaker: str, payload_text: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO match_transcripts (match_id, speaker, payload_text) VALUES (?, ?, ?)",
            (match_id, speaker, payload_text),
        )


def _fetch_ledger_sync(match_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT message_id, timestamp, speaker, payload_text FROM match_transcripts "
            "WHERE match_id = ? ORDER BY message_id",
            (match_id,),
        )
        return [dict(row) for row in rows]


# ------------------------------------------------------------ Async API


async def init_db() -> list[dict]:
    """Migrate an older database if needed, create tables, seed dummy data, return the CPQ tiers."""
    return await asyncio.to_thread(_init_db_sync)


async def fetch_cpq_tiers() -> list[dict]:
    """Sales rate card, lowest volume slab first."""
    return await asyncio.to_thread(_fetch_cpq_tiers_sync)


async def fetch_mandate() -> dict | None:
    """The buyer's active mandate (lowest mandate_id), or None if the table is empty."""
    return await asyncio.to_thread(_fetch_mandate_sync)


async def fetch_static_ammo(side: str) -> list[dict]:
    """Citable facts for one side ("sales" | "procurement")."""
    return await asyncio.to_thread(_fetch_static_ammo_sync, side)


async def fetch_heuristics(side: str, topic_tags: list[str] | None) -> list[dict]:
    """Master lessons for `topic_tags` (at most one per tag, in tag order); None = the whole playbook."""
    if topic_tags is not None and not topic_tags:
        return []
    return await asyncio.to_thread(_fetch_heuristics_sync, side,
                                   None if topic_tags is None else list(dict.fromkeys(topic_tags)))


async def fetch_heuristic(side: str, topic_tag: str) -> dict | None:
    """The single master lesson for one topic, or None."""
    rows = await fetch_heuristics(side, [topic_tag])
    return rows[0] if rows else None


async def upsert_heuristic(side: str, topic_tag: str, past_mistake: str, new_directive: str,
                           critical: bool = False) -> int:
    """INSERT ... ON CONFLICT(topic_tag) DO UPDATE: write the master lesson for a topic; returns its id.

    `critical` marks a lesson learned from a deadlock the manager had to break; it never resets.
    """
    return await asyncio.to_thread(_upsert_heuristic_sync, side, topic_tag, past_mistake, new_directive, critical)


async def log_message(match_id: str, speaker: str, payload_text: str) -> None:
    """Append one row to the match_transcripts ledger."""
    await asyncio.to_thread(_log_message_sync, match_id, speaker, payload_text)


async def fetch_ledger(match_id: str) -> list[dict]:
    """Every ledger row for one match, in the order it happened."""
    return await asyncio.to_thread(_fetch_ledger_sync, match_id)


async def _main() -> None:
    rows = await init_db()
    print(f"Database ready: {DB_PATH}\n\nsales_cpq_pricing")
    print(f"{'Tier':<5}{'Volume Slab':<24}{'Min Vol':>10}{'Base':>8}{'Floor':>8}  RTO Waiver")
    for r in rows:
        rto = (f"Yes (min {r['rto_min_contract_months']} months)" if r["rto_min_contract_months"] else "Yes") \
            if r["rto_waiver_allowed"] else "No"
        print(f"{r['tier_id']:<5}{r['volume_slab']:<24}{r['min_monthly_volume']:>10,}"
              f"{r['base_price']:>8.2f}{r['floor_price']:>8.2f}  {rto}")
    print(f"\nprocurement_mandates\n{await fetch_mandate()}")
    for side in SIDES:
        print(f"\n{AMMO_TABLES[side]}")
        for a in await fetch_static_ammo(side):
            print(f"  [{a['fact_type']}] {a['value']}")
        rules = await fetch_heuristics(side, None)
        print(f"\n{HEURISTICS_TABLES[side]}: {len(rules)} rule(s)")
        for h in rules:
            print(f"  #{h['heuristic_id']} [{h['topic_tag']}] {h['new_directive']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_main())
