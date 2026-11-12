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
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    author TEXT NOT NULL DEFAULT 'Anonymous',
    body TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_page ON comments(page_id);
CREATE INDEX IF NOT EXISTS comments_parent ON comments(parent_id);
"""

FIELDS = ("title", "icon", "body", "favorite", "parent_id")
MAX_COMMENT = 10000
MAX_AUTHOR = 80


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clean(body: str, author: str) -> tuple[str, str]:
    if body.strip() == "":
        raise ValueError("a comment needs some text")
    if len(body) > MAX_COMMENT:
        raise ValueError(f"a comment can be at most {MAX_COMMENT} characters")
    return body, author.strip()[:MAX_AUTHOR] or "Anonymous"


def _reply(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "page_id": row["page_id"],
        "parent_id": row["parent_id"],
        "author": row["author"],
        "body": row["body"],
        "created_at": row["created_at"],
    }


def _thread(row: sqlite3.Row, replies: list[dict]) -> dict:
    return {
        "id": row["id"],
        "page_id": row["page_id"],
        "author": row["author"],
        "body": row["body"],
        "created_at": row["created_at"],
        "resolved": row["resolved_at"] is not None,
        "resolved_at": row["resolved_at"],
        "replies": replies,
    }


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
        page = self._row(row)
        if page is not None:
            page["open_comments"] = self.open_comment_count(page_id)
        return page

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

    def get_comment(self, comment_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
        return dict(row) if row else None

    def comments(self, page_id: int) -> list[dict]:
        threads = self._db.execute(
            "SELECT * FROM comments WHERE page_id = ? AND parent_id IS NULL"
            " ORDER BY created_at, id",
            (page_id,),
        ).fetchall()
        replies = self._db.execute(
            "SELECT * FROM comments WHERE page_id = ? AND parent_id IS NOT NULL"
            " ORDER BY created_at, id",
            (page_id,),
        ).fetchall()
        by_thread: dict[int, list[dict]] = {}
        for r in replies:
            by_thread.setdefault(r["parent_id"], []).append(_reply(r))
        return [_thread(t, by_thread.get(t["id"], [])) for t in threads]

    def thread(self, comment_id: int) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM comments WHERE id = ? AND parent_id IS NULL", (comment_id,)
        ).fetchone()
        if row is None:
            return None
        replies = self._db.execute(
            "SELECT * FROM comments WHERE parent_id = ? ORDER BY created_at, id", (comment_id,)
        ).fetchall()
        return _thread(row, [_reply(r) for r in replies])

    def add_comment(self, page_id: int, body: str, author: str = "") -> dict:
        body, author = _clean(body, author)
        with self._lock:
            if self._db.execute("SELECT 1 FROM pages WHERE id = ?", (page_id,)).fetchone() is None:
                raise KeyError(page_id)
            try:
                cur = self._db.execute(
                    "INSERT INTO comments (page_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                    (page_id, author, body, _now()),
                )
            except sqlite3.IntegrityError as exc:
                raise KeyError(page_id) from exc
            self._db.commit()
        return self.thread(cur.lastrowid)

    def add_reply(self, comment_id: int, body: str, author: str = "") -> dict:
        body, author = _clean(body, author)
        with self._lock:
            parent = self._db.execute(
                "SELECT * FROM comments WHERE id = ?", (comment_id,)
            ).fetchone()
            if parent is None:
                raise KeyError(comment_id)
            if parent["parent_id"] is not None:
                raise ValueError("replies are one level deep")
            try:
                cur = self._db.execute(
                    "INSERT INTO comments (page_id, parent_id, author, body, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (parent["page_id"], comment_id, author, body, _now()),
                )
            except sqlite3.IntegrityError as exc:
                raise KeyError(comment_id) from exc
            self._db.commit()
            row = self._db.execute(
                "SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return _reply(row)

    def set_resolved(self, comment_id: int, resolved: bool) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT parent_id FROM comments WHERE id = ?", (comment_id,)
            ).fetchone()
            if row is None:
                return None
            if row["parent_id"] is not None:
                raise ValueError("only a thread can be resolved")
            if resolved:
                self._db.execute(
                    "UPDATE comments SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL",
                    (_now(), comment_id),
                )
            else:
                self._db.execute(
                    "UPDATE comments SET resolved_at = NULL WHERE id = ?", (comment_id,)
                )
            self._db.commit()
        return self.thread(comment_id)

    def delete_comment(self, comment_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
            self._db.commit()
        return cur.rowcount > 0

    def open_comment_count(self, page_id: int) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM comments"
            " WHERE page_id = ? AND parent_id IS NULL AND resolved_at IS NULL",
            (page_id,),
        ).fetchone()[0]

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
