#!/usr/bin/env python3
import argparse
import re
import sqlite3
import sys
from typing import List, Optional

MIGRATION_VERSION = 20260201
MIGRATION_NAME = "20260201_fix_fk_legacy_suffixes"

BAD_SUFFIXES = ("_old", "__rebuild_old", "__rebuild")
NEW_SUFFIX = "__fixfk_new"   # table shadow créée temporairement

def fetchall(conn, sql, params=()):
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows

def fetchone(conn, sql, params=()):
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row

def ensure_migrations_table(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      version INTEGER NOT NULL,
      name TEXT NOT NULL,
      applied_at TEXT NOT NULL DEFAULT (datetime('now')),
      UNIQUE(version),
      UNIQUE(name)
    )
    """)

def migration_applied(conn) -> bool:
    ensure_migrations_table(conn)
    row = fetchone(conn,
                   "SELECT 1 FROM schema_migrations WHERE name=? OR version=? LIMIT 1",
                   (MIGRATION_NAME, MIGRATION_VERSION))
    return bool(row)

def mark_migration_applied(conn):
    ensure_migrations_table(conn)
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
                 (MIGRATION_VERSION, MIGRATION_NAME))

def normalize_sql(sql: str) -> str:
    return (sql or "").strip().rstrip(";")

def is_virtual_table(create_sql: str) -> bool:
    return bool(re.match(r"^\s*CREATE\s+VIRTUAL\s+TABLE\b", create_sql, flags=re.IGNORECASE))

def bad_ref_patterns() -> re.Pattern:
    suffix_alt = "|".join(re.escape(s) for s in sorted(BAD_SUFFIXES, key=len, reverse=True))
    return re.compile(rf"REFERENCES\s+([\"']?)([A-Za-z0-9_]+?)({suffix_alt})\1", flags=re.IGNORECASE)

def rewrite_references(sql: str) -> str:
    pat = bad_ref_patterns()
    def _sub(m: re.Match) -> str:
        quote = m.group(1) or ""
        base = m.group(2)  # drop suffix
        return f"REFERENCES {quote}{base}{quote}"
    return pat.sub(_sub, sql)

def find_bad_refs(sql: str) -> List[str]:
    pat = bad_ref_patterns()
    return sorted({m.group(2) + m.group(3) for m in pat.finditer(sql or "")})

def list_candidate_tables(conn) -> List[str]:
    likes = " OR ".join(["sql LIKE ?"] * len(BAD_SUFFIXES))
    params = [f"%{s}%" for s in BAD_SUFFIXES]
    rows = fetchall(conn, f"""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
          AND sql IS NOT NULL
          AND ({likes})
        ORDER BY name
    """, params)
    return [r[0] for r in rows]

def get_create_table_sql(conn, table: str) -> str:
    row = fetchone(conn, "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if not row or not row[0]:
        raise RuntimeError(f"Cannot read CREATE TABLE for {table}")
    return normalize_sql(str(row[0]))

def get_indexes_sql(conn, table: str) -> List[str]:
    rows = fetchall(conn, """
        SELECT sql
        FROM sqlite_master
        WHERE type='index' AND tbl_name=? AND sql IS NOT NULL
    """, (table,))
    return [r[0] for r in rows if r[0]]

def get_triggers_sql(conn, table: str) -> List[str]:
    rows = fetchall(conn, """
        SELECT sql
        FROM sqlite_master
        WHERE type='trigger' AND tbl_name=? AND sql IS NOT NULL
    """, (table,))
    return [r[0] for r in rows if r[0]]

def table_exists(conn, name: str) -> bool:
    return bool(fetchone(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)))

def rebuild_table_shadow(conn, table: str, dry_run: bool) -> bool:
    create_sql = get_create_table_sql(conn, table)
    if is_virtual_table(create_sql):
        # On évite totalement les tables virtual/FTS
        return False

    bad_refs = find_bad_refs(create_sql)
    if not bad_refs:
        return False

    fixed_create = rewrite_references(create_sql)

    # On crée une table shadow table__fixfk_new
    new_table = f"{table}{NEW_SUFFIX}"
    if table_exists(conn, new_table):
        raise RuntimeError(f"Temp shadow table already exists: {new_table}")

    # Réécrire le CREATE TABLE pour qu'il crée new_table (pas table)
    # Ça remplace uniquement le premier "CREATE TABLE <table>"
    fixed_create_new = re.sub(
        r"^\s*CREATE\s+TABLE\s+([\"']?)" + re.escape(table) + r"\1",
        f'CREATE TABLE "{new_table}"',
        fixed_create,
        flags=re.IGNORECASE
    )

    idx_sqls = get_indexes_sql(conn, table)
    trg_sqls = get_triggers_sql(conn, table)

    if dry_run:
        print(f"[DRY] {table}: refs={', '.join(bad_refs)}")
        return True

    print(f"[FIX] {table}: refs={', '.join(bad_refs)}")

    # Create shadow
    conn.execute(fixed_create_new)

    # Copy data (mêmes colonnes / même ordre)
    conn.execute(f'INSERT INTO "{new_table}" SELECT * FROM "{table}"')

    # Drop old table (les FK checks sont OFF pendant la migration)
    conn.execute(f'DROP TABLE "{table}"')

    # Rename shadow -> original name
    conn.execute(f'ALTER TABLE "{new_table}" RENAME TO "{table}"')

    # Recreate indexes / triggers (les SQL contiennent le nom de table original, c’est OK)
    for s in idx_sqls:
        conn.execute(normalize_sql(s))
    for s in trg_sqls:
        # Et on corrige au passage si un trigger contenait une vieille ref
        conn.execute(normalize_sql(rewrite_references(s)))

    return True

def apply_fix(db_path: str, dry_run: bool, max_passes: int) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")

    try:
        if migration_applied(conn):
            print("[OK] migration already applied")
            return 0

        tables = list_candidate_tables(conn)
        if not tables:
            if not dry_run:
                mark_migration_applied(conn)
            print("[OK] no bad refs found")
            return 0

        if not dry_run:
            conn.execute("PRAGMA foreign_keys=OFF;")
            conn.execute("BEGIN;")

        changed = True
        passes = 0
        while changed and passes < max_passes:
            passes += 1
            changed = False
            tables = list_candidate_tables(conn)
            if not tables:
                break
            print(f"[INFO] pass {passes} | tables={len(tables)}")
            for t in tables:
                if rebuild_table_shadow(conn, t, dry_run=dry_run):
                    changed = True
            if dry_run:
                break

        if not dry_run:
            conn.execute("COMMIT;")
            conn.execute("PRAGMA foreign_keys=ON;")

            issues = fetchall(conn, "PRAGMA foreign_key_check;")
            if issues:
                print(f"[WARN] foreign_key_check still reports {len(issues)} issue(s) (first 50):")
                for r in issues[:50]:
                    print(" ", tuple(r))
                return 2

            mark_migration_applied(conn)
            print("[OK] fixed and foreign_key_check clean")

        return 0

    except Exception as e:
        try:
            if not dry_run:
                conn.execute("ROLLBACK;")
        except Exception:
            pass
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db_path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-passes", type=int, default=30)
    args = ap.parse_args()
    raise SystemExit(apply_fix(args.db_path, dry_run=args.dry_run, max_passes=args.max_passes))

if __name__ == "__main__":
    main()
