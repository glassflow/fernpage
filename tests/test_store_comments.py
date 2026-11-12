import sqlite3

import pytest

from app.store import Store

THREAD_KEYS = {
    "id", "page_id", "author", "body", "created_at", "resolved", "resolved_at", "replies",
}
REPLY_KEYS = {"id", "page_id", "parent_id", "author", "body", "created_at"}


@pytest.fixture
def store():
    return Store()


@pytest.fixture
def page(store):
    return store.create(title="Notes")


def test_thread_with_replies_in_order(store, page):
    first = store.add_comment(page["id"], "first", "Ann")
    second = store.add_comment(page["id"], "second", "Bo")
    r1 = store.add_reply(first["id"], "reply one", "Bo")
    r2 = store.add_reply(first["id"], "reply two", "Ann")

    threads = store.comments(page["id"])
    assert [t["id"] for t in threads] == [first["id"], second["id"]]
    assert [r["id"] for r in threads[0]["replies"]] == [r1["id"], r2["id"]]
    assert threads[1]["replies"] == []
    for t in threads:
        assert set(t) == THREAD_KEYS
        for r in t["replies"]:
            assert set(r) == REPLY_KEYS
    assert set(first) == THREAD_KEYS
    assert set(r1) == REPLY_KEYS
    assert r1["parent_id"] == first["id"]
    assert r1["page_id"] == page["id"]
    assert threads[0]["resolved"] is False
    assert threads[0]["resolved_at"] is None
    assert store.thread(first["id"]) == threads[0]
    assert store.thread(r1["id"]) is None
    assert store.thread(9999) is None


def test_blank_author_is_anonymous(store, page):
    assert store.add_comment(page["id"], "hi", "   ")["author"] == "Anonymous"
    assert store.add_comment(page["id"], "hi")["author"] == "Anonymous"


def test_author_is_stripped_and_cut(store, page):
    assert store.add_comment(page["id"], "hi", "  " + "a" * 100)["author"] == "a" * 80


def test_empty_body_is_refused(store, page):
    with pytest.raises(ValueError):
        store.add_comment(page["id"], "  \n")
    thread = store.add_comment(page["id"], "ok")
    with pytest.raises(ValueError):
        store.add_reply(thread["id"], "  \n")


def test_too_long_body_is_refused(store, page):
    with pytest.raises(ValueError):
        store.add_comment(page["id"], "x" * 10001)
    assert store.add_comment(page["id"], "x" * 10000)["body"] == "x" * 10000


def test_comment_on_missing_page(store):
    with pytest.raises(KeyError):
        store.add_comment(9999, "hello")


def test_reply_to_reply_is_refused(store, page):
    thread = store.add_comment(page["id"], "hello")
    reply = store.add_reply(thread["id"], "hi")
    with pytest.raises(ValueError):
        store.add_reply(reply["id"], "too deep")


def test_reply_to_missing_comment(store):
    with pytest.raises(KeyError):
        store.add_reply(9999, "hello")


def test_resolve_and_reopen(store, page, monkeypatch):
    thread = store.add_comment(page["id"], "hello")
    monkeypatch.setattr("app.store._now", lambda: "2026-01-01T00:00:01+00:00")
    done = store.set_resolved(thread["id"], True)
    assert done["resolved"] is True
    assert done["resolved_at"] == "2026-01-01T00:00:01+00:00"
    monkeypatch.setattr("app.store._now", lambda: "2026-01-01T00:00:09+00:00")
    again = store.set_resolved(thread["id"], True)
    assert again["resolved_at"] == done["resolved_at"]
    reopened = store.set_resolved(thread["id"], False)
    assert reopened["resolved"] is False
    assert reopened["resolved_at"] is None
    assert store.set_resolved(9999, True) is None


def test_resolving_a_reply_is_refused(store, page):
    thread = store.add_comment(page["id"], "hello")
    reply = store.add_reply(thread["id"], "hi")
    with pytest.raises(ValueError):
        store.set_resolved(reply["id"], True)


def test_delete_thread_deletes_replies(store, page):
    thread = store.add_comment(page["id"], "hello")
    reply = store.add_reply(thread["id"], "hi")
    assert store.delete_comment(thread["id"]) is True
    assert store.get_comment(thread["id"]) is None
    assert store.get_comment(reply["id"]) is None
    assert store.delete_comment(thread["id"]) is False


def test_delete_page_deletes_comments(store, page):
    thread = store.add_comment(page["id"], "hello")
    reply = store.add_reply(thread["id"], "hi")
    assert store.delete(page["id"]) is True
    assert store.get_comment(thread["id"]) is None
    assert store.get_comment(reply["id"]) is None


def test_open_count_ignores_resolved_and_replies(store, page):
    a = store.add_comment(page["id"], "one")
    b = store.add_comment(page["id"], "two")
    store.add_reply(a["id"], "a reply")
    store.set_resolved(b["id"], True)
    assert store.open_comment_count(page["id"]) == 1
    assert store.get(page["id"])["open_comments"] == 1


def test_old_database_gets_comments_table(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE pages (
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
        CREATE INDEX pages_parent ON pages(parent_id);
        """
    )
    old.execute(
        "INSERT INTO pages (title, created_at, updated_at) VALUES ('Old', 'x', 'x')"
    )
    old.commit()
    old.close()

    store = Store(str(path))
    page_id = store.get(1)["id"]
    thread = store.add_comment(page_id, "still works")
    assert store.get_comment(thread["id"]) is not None
    assert store.delete(page_id) is True
    assert store.get_comment(thread["id"]) is None
    assert store._db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
