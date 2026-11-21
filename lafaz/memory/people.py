"""People Lafaz knows: name, aliases, test email. Owners and speakers heard in a run are remembered by code."""

from __future__ import annotations

import json
import sqlite3


def all_people(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT name, aliases_json, email FROM people ORDER BY name").fetchall()
    return [{"name": r["name"], "aliases": json.loads(r["aliases_json"]), "email": r["email"]} for r in rows]


def upsert(conn: sqlite3.Connection, name: str, aliases: list[str] | None = None, email: str | None = None) -> None:
    """Add a person, or update aliases and email of an existing one. Empty values never erase what is stored."""
    name = (name or "").strip()
    if not name:
        return
    row = conn.execute("SELECT aliases_json, email FROM people WHERE name=?", (name,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO people (name, aliases_json, email) VALUES (?,?,?)",
                     (name, json.dumps(aliases or [], ensure_ascii=False), email))
        return
    merged = list(dict.fromkeys(json.loads(row["aliases_json"]) + list(aliases or [])))
    conn.execute("UPDATE people SET aliases_json=?, email=? WHERE name=?",
                 (json.dumps(merged, ensure_ascii=False), email or row["email"], name))


def remember_run(conn: sqlite3.Connection, run_id: int) -> int:
    """Remember every owner and speaker of the run's accepted items. Returns how many people were new."""
    before = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    names = conn.execute(
        "SELECT owner AS name FROM items WHERE run_id=? AND status='accepted' AND owner IS NOT NULL"
        " UNION SELECT speaker FROM items WHERE run_id=? AND status='accepted' AND speaker IS NOT NULL",
        (run_id, run_id),
    ).fetchall()
    for row in names:
        conn.execute("INSERT OR IGNORE INTO people (name) VALUES (?)", (row["name"],))
    return conn.execute("SELECT COUNT(*) FROM people").fetchone()[0] - before


def in_space(conn: sqlite3.Connection, space: str) -> list[dict]:
    """People named as owner or speaker of an accepted item in a run started in `space`, with how many items."""
    rows = conn.execute(
        "SELECT p.name, p.aliases_json, p.email, COUNT(*) AS items FROM people p"
        " JOIN items i ON i.status = 'accepted' AND (i.owner = p.name OR i.speaker = p.name)"
        " JOIN runs r ON r.id = i.run_id WHERE COALESCE(r.space, 'public') = ?"
        " GROUP BY p.id ORDER BY p.name",
        (space,),
    )
    return [{"name": r["name"], "aliases": json.loads(r["aliases_json"]), "email": r["email"], "items": r["items"]}
            for r in rows]
