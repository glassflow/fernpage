import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.store
from app.main import create_app
from app.store import Store

PRIVATE = {
    "cache-control": "no-store",
    "x-robots-tag": "noindex",
    "referrer-policy": "no-referrer",
}


@pytest.fixture
def client():
    return TestClient(create_app(Store()))


def make(client, **body):
    res = client.post("/api/pages", json=body)
    assert res.status_code == 201
    return res.json()


def share(client, page_id):
    res = client.post(f"/api/pages/{page_id}/share")
    assert res.status_code == 200
    return res.json()["token"]


def test_share_returns_token_and_url(client):
    page = make(client, title="Ideas")
    res = client.post(f"/api/pages/{page['id']}/share")
    assert res.status_code == 200
    data = res.json()
    assert len(data["token"]) >= 20
    assert data["url"] == "/s/" + data["token"]


def test_sharing_twice_returns_the_same_token(client):
    page = make(client, title="Ideas")
    assert share(client, page["id"]) == share(client, page["id"])


def test_shared_page_is_public_and_minimal(client):
    page = make(client, title="Ideas", icon="x", body="# Hi")
    token = share(client, page["id"])
    res = client.get(f"/api/shared/{token}")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Ideas"
    assert data["icon"] == "x"
    assert data["body"] == "# Hi"
    assert data["updated_at"] == page["updated_at"]
    for key in ("id", "parent_id", "share_token"):
        assert key not in data
    for name, value in PRIVATE.items():
        assert res.headers[name] == value


def test_page_shows_the_same_token(client):
    page = make(client, title="Ideas")
    assert "share_token" in page and page["share_token"] is None
    token = share(client, page["id"])
    assert client.get(f"/api/pages/{page['id']}").json()["share_token"] == token


def test_sharing_does_not_change_updated_at(client, monkeypatch):
    page = make(client, title="Ideas")
    monkeypatch.setattr(app.store, "_now", lambda: "2999-01-01T00:00:00+00:00")
    token = share(client, page["id"])
    assert client.get(f"/api/pages/{page['id']}").json()["updated_at"] == page["updated_at"]
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204
    assert client.get(f"/api/pages/{page['id']}").json()["updated_at"] == page["updated_at"]
    assert token


def test_unshare_revokes_and_a_new_share_gets_a_new_token(client):
    page = make(client, title="Ideas")
    old = share(client, page["id"])
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204
    assert client.get(f"/api/shared/{old}").status_code == 404
    assert client.get(f"/api/pages/{page['id']}").json()["share_token"] is None
    new = share(client, page["id"])
    assert new != old
    assert client.get(f"/api/shared/{old}").status_code == 404
    assert client.get(f"/api/shared/{new}").status_code == 200


def test_unsharing_a_page_that_was_never_shared_is_204(client):
    page = make(client, title="Ideas")
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204


def test_missing_pages_and_tokens_are_404(client):
    assert client.post("/api/pages/999/share").status_code == 404
    assert client.delete("/api/pages/999/share").status_code == 404
    res = client.get("/api/shared/nope")
    assert res.status_code == 404
    for name, value in PRIVATE.items():
        assert res.headers[name] == value


def test_deleting_a_page_kills_its_token(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    assert client.delete(f"/api/pages/{page['id']}").status_code == 204
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_deleting_the_parent_kills_the_childs_token(client):
    parent = make(client, title="Product")
    child = make(client, title="Roadmap", parent_id=parent["id"])
    token = share(client, child["id"])
    assert client.delete(f"/api/pages/{parent['id']}").status_code == 204
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_patch_cannot_set_the_share_token(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    res = client.patch(f"/api/pages/{page['id']}", json={"share_token": "x"})
    assert res.status_code == 200
    assert res.json()["share_token"] == token
    assert client.get("/api/shared/x").status_code == 404


def test_store_update_ignores_the_share_token():
    store = Store()
    page = store.create(title="Ideas")
    token = store.share(page["id"])
    store.update(page["id"], share_token="x")
    assert store.get(page["id"])["share_token"] == token


def test_old_database_is_migrated(tmp_path):
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
        """
    )
    old.execute(
        "INSERT INTO pages (title, body, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("Old", "kept", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
    )
    old.commit()
    old.close()

    store = Store(str(path))
    page = store.get(1)
    assert page is not None and page["title"] == "Old" and page["share_token"] is None
    token = store.share(1)
    assert token

    again = Store(str(path))
    assert again.get(1)["title"] == "Old"
    assert again.share(1) == token
    assert again.get_shared(token)["body"] == "kept"
