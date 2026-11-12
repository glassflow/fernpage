"""Pages in SQLite. A page has a title, a markdown body, an optional parent and a favourite flag."""

import sqlite3
import threading
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    favorite INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pages_parent ON pages(parent_id);
"""

FIELDS = ("title", "icon", "body", "favorite", "parent_id")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        page = dict(row)
        page["favorite"] = bool(page["favorite"])
        return page

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def get(self, page_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone()
        return self._row(row)

    def create(self, title: str = "", body: str = "", icon: str = "",
               parent_id: int | None = None) -> dict:
        if parent_id is not None and self.get(parent_id) is None:
            raise KeyError(parent_id)
        now = _now()
        with self._lock:
            position = self._db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM pages WHERE parent_id IS ?",
                (parent_id,),
            ).fetchone()[0]
            cur = self._db.execute(
                "INSERT INTO pages (parent_id, title, icon, body, position, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (parent_id, title, icon, body, position, now, now),
            )
            self._db.commit()
        return self.get(cur.lastrowid)

    def update(self, page_id: int, **changes) -> dict | None:
        changes = {k: v for k, v in changes.items() if k in FIELDS}
        if self.get(page_id) is None:
            return None
        if "parent_id" in changes:
            self._check_parent(page_id, changes["parent_id"])
        if "favorite" in changes:
            changes["favorite"] = int(bool(changes["favorite"]))
        if changes:
            changes["updated_at"] = _now()
            cols = ", ".join(f"{k} = ?" for k in changes)
            with self._lock:
                self._db.execute(f"UPDATE pages SET {cols} WHERE id = ?",
                                 (*changes.values(), page_id))
                self._db.commit()
        return self.get(page_id)

    def _check_parent(self, page_id: int, parent_id: int | None) -> None:
        """A page can't move under itself or under one of its own children."""
        while parent_id is not None:
            if parent_id == page_id:
                raise ValueError("a page can't be moved inside itself")
            parent = self.get(parent_id)
            if parent is None:
                raise KeyError(parent_id)
            parent_id = parent["parent_id"]

    def delete(self, page_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM pages WHERE id = ?", (page_id,))
            self._db.commit()
        return cur.rowcount > 0

    def tree(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, parent_id, title, icon, favorite FROM pages ORDER BY position, id"
        ).fetchall()
        nodes = {r["id"]: {**self._row(r), "children": []} for r in rows}
        roots = []
        for node in nodes.values():
            parent = nodes.get(node["parent_id"])
            (parent["children"] if parent else roots).append(node)
        return roots

    def favorites(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, title, icon FROM pages WHERE favorite = 1 ORDER BY title"
        ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> list[dict]:
        like = f"%{query.strip()}%"
        rows = self._db.execute(
            "SELECT id, title, icon, body FROM pages WHERE title LIKE ? OR body LIKE ?"
            " ORDER BY (title LIKE ?) DESC, updated_at DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        return [{"id": r["id"], "title": r["title"], "icon": r["icon"],
                 "snippet": _snippet(r["body"], query)} for r in rows]


def _snippet(body: str, query: str, width: int = 80) -> str:
    at = body.lower().find(query.strip().lower())
    if at < 0:
        return body[:width].replace("\n", " ")
    start = max(0, at - width // 2)
    text = body[start:start + width].replace("\n", " ")
    return ("…" if start else "") + text
