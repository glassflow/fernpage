import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.store
from app.main import SHARE_HEADERS, _route_path, create_app
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


def test_share_token_is_unique_in_the_database():
    store = Store()
    a = store.create(title="A")
    b = store.create(title="B")
    token = store.share(a["id"])
    with pytest.raises(sqlite3.IntegrityError):
        store._db.execute("UPDATE pages SET share_token = ? WHERE id = ?", (token, b["id"]))


def test_get_shared_with_an_empty_token_is_none():
    store = Store()
    assert store.get_shared("") is None
    page = store.create(title="A")
    store.share(page["id"])
    assert store.get_shared("") is None
    # a row that somehow holds an empty token must still never be served
    other = store.create(title="B")
    store._db.execute("UPDATE pages SET share_token = '' WHERE id = ?", (other["id"],))
    store._db.commit()
    assert store.get_shared("") is None


CSP = "default-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'"


def assert_share_headers(res):
    for name, value in SHARE_HEADERS.items():
        assert res.headers[name] == value
    for name, value in PRIVATE.items():
        assert res.headers[name] == value
    # the literal policy, so quietly weakening the constant fails here
    assert res.headers["content-security-policy"] == CSP


def test_public_page_opens_for_a_valid_token(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    res = client.get(f"/s/{token}")
    assert res.status_code == 200
    assert "share.js" in res.text
    assert_share_headers(res)


def test_public_page_for_a_bogus_token_is_404(client):
    res = client.get("/s/bogus")
    assert res.status_code == 404
    assert "doesn't work" in res.text
    assert_share_headers(res)


def test_public_page_is_404_after_unshare(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204
    res = client.get(f"/s/{token}")
    assert res.status_code == 404
    assert_share_headers(res)


def test_share_html_is_served_statically(client):
    assert client.get("/static/share.html").status_code == 200


def test_shared_api_carries_the_csp_too(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    assert_share_headers(client.get(f"/api/shared/{token}"))
    assert_share_headers(client.get("/api/shared/nope"))


def test_headers_on_the_trailing_slash_redirect(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    res = client.get(f"/s/{token}/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"].endswith(f"/s/{token}")
    assert_share_headers(res)


def test_headers_on_odd_share_paths(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    for path in (
        f"/s/{token}/x",
        "/s/a%2Fb",
        "/s/",
        "/s",
        "/api/shared",
        "/api/shared/",
        "/api/shared/nope/extra",
    ):
        res = client.get(path, follow_redirects=False)
        assert res.status_code in (307, 404), path
        assert_share_headers(res)


def test_headers_on_wrong_methods(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    for method, path in (
        ("HEAD", f"/s/{token}"),
        ("HEAD", f"/api/shared/{token}"),
        ("POST", f"/s/{token}"),
        ("DELETE", f"/api/shared/{token}"),
    ):
        res = client.request(method, path)
        assert res.status_code == 405, (method, path)
        assert_share_headers(res)


def test_handlers_do_not_duplicate_the_headers(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    for path in (f"/s/{token}", "/s/nope", f"/api/shared/{token}", "/api/shared/nope"):
        res = client.get(path)
        for name in SHARE_HEADERS:
            assert len(res.headers.get_list(name)) == 1, (path, name)


def test_other_routes_do_not_get_the_share_headers(client):
    make(client, title="Ideas")
    for path in ("/api/pages", "/", "/static/style.css", "/s2", "/api/sharedx"):
        res = client.get(path)
        for name in ("content-security-policy", "x-robots-tag", "referrer-policy"):
            assert name not in res.headers, (path, name)
        assert res.headers.get("cache-control") != "no-store", path


def test_headers_survive_a_reverse_proxy_root_path():
    # `uvicorn --root-path /prefix` puts the prefix in scope["root_path"] and (in current
    # uvicorn) in scope["path"] too, so the middleware sees "/prefix/s/<token>".
    seen = []
    app = create_app(Store())

    @app.middleware("http")
    async def spy(request, call_next):
        seen.append((request.scope["root_path"], request.url.path))
        return await call_next(request)

    client = TestClient(app, root_path="/prefix")
    page = client.post("/prefix/api/pages", json={"title": "Ideas"}).json()
    token = client.post(f"/prefix/api/pages/{page['id']}/share").json()["token"]
    for path in (f"/s/{token}", f"/api/shared/{token}", "/s/nope", "/api/shared/nope"):
        seen.clear()
        res = client.get(f"/prefix{path}")
        assert res.status_code in (200, 404), path
        assert seen == [("/prefix", f"/prefix{path}")], seen  # the prefix really is in the path
        assert_share_headers(res)
    # a server that leaves the prefix out of scope["path"] works too
    assert_share_headers(client.get(f"/s/{token}"))
    # a non-share route under the prefix gets no share headers
    res = client.get("/prefix/api/pages")
    assert res.status_code == 200
    for name in ("content-security-policy", "x-robots-tag", "referrer-policy"):
        assert name not in res.headers
    assert res.headers.get("cache-control") != "no-store"


@pytest.mark.parametrize(
    ("root_path", "path"),
    [
        ("/app", "/appx/s/x"),  # not a path-segment boundary: prefix is not stripped
        ("/app/", "/app//s/x"),  # trailing slash in root_path: only one "/" is left over
        ("/app", "/app"),  # path equals root_path (length branch)
        ("/app", "/s/x"),  # the server left the prefix out of scope["path"]
        ("/app", "/app/s/x"),
        ("", "/s/x"),
    ],
)
def test_route_path_matches_starlette(root_path, path):
    from starlette._utils import get_route_path

    scope = {"path": path, "root_path": root_path}
    assert _route_path(scope) == get_route_path(scope)


def test_headers_with_a_trailing_slash_root_path():
    # `uvicorn --root-path /app/` gives scope["path"] == "/app//s/<token>", which Starlette
    # routes as "/s/<token>"; the share headers must follow the router's view of the path.
    seen = []
    app = create_app(Store())

    @app.middleware("http")
    async def spy(request, call_next):
        seen.append((request.scope["root_path"], request.url.path))
        return await call_next(request)

    client = TestClient(app, root_path="/app/")
    page = client.post("/app//api/pages", json={"title": "Ideas"}).json()
    token = client.post(f"/app//api/pages/{page['id']}/share").json()["token"]
    for path in (f"/s/{token}", f"/api/shared/{token}"):
        seen.clear()
        res = client.get(f"/app/{path}")
        assert seen == [("/app/", f"/app/{path}")], seen  # the double slash really arrives
        assert res.status_code == 200, path
        assert_share_headers(res)


def test_unhandled_errors_carry_the_share_headers(monkeypatch):
    store = Store()
    client = TestClient(create_app(store), raise_server_exceptions=False)
    page = make(client, title="Ideas")
    token = share(client, page["id"])

    def locked(token):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "get_shared", locked)
    for path in (f"/s/{token}", f"/api/shared/{token}"):
        res = client.get(path)
        assert res.status_code == 500, path
        assert res.text == "Internal Server Error"
        assert_share_headers(res)
        for name in SHARE_HEADERS:
            assert len(res.headers.get_list(name)) == 1, (path, name)

    # a non-share route keeps the plain 500, without the share headers
    def broken():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "tree", broken)
    res = client.get("/api/pages")
    assert res.status_code == 500
    assert res.text == "Internal Server Error"
    for name in ("content-security-policy", "x-robots-tag", "referrer-policy"):
        assert name not in res.headers
    assert res.headers.get("cache-control") != "no-store"

    # HTTPException responses are not swallowed by the catch-all handler
    assert client.get("/api/pages/9999").status_code == 404


OLD_PAGES = """
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


def old_db(path):
    con = sqlite3.connect(path)
    con.executescript(OLD_PAGES)
    con.commit()
    con.close()
    return str(path)


def test_empty_old_schema_database_opens_and_shares(tmp_path):
    store = Store(old_db(tmp_path / "old.db"))
    page = store.create(title="New")
    assert store.share(page["id"])


class RacingConnection:
    """Thin proxy (sqlite3.Connection.execute is a C method, so it cannot be patched on the
    instance). It reports the column as missing the first time it is asked, and lets a
    rival process add the column before our own ALTER runs."""

    def __init__(self, real, path, connect, alter_error=None):
        self._real = real
        self._path = path
        self._connect = connect
        self._alter_error = alter_error
        self._seen = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._real, name, value)

    def execute(self, sql, *args):
        if sql.startswith("PRAGMA table_info(pages)") and not self._seen:
            self._seen = True
            rows = self._real.execute(sql, *args).fetchall()
            assert all(r[1] != "share_token" for r in rows)
            if self._alter_error is None:
                rival = self._connect(self._path)
                rival.execute("ALTER TABLE pages ADD COLUMN share_token TEXT")
                rival.commit()
                rival.close()
            return iter(rows)
        if sql.startswith("ALTER TABLE") and self._alter_error is not None:
            raise self._alter_error
        return self._real.execute(sql, *args)


def patch_connect(monkeypatch, path, alter_error=None):
    real_connect = sqlite3.connect

    def connect(*a, **kw):
        return RacingConnection(real_connect(*a, **kw), path, real_connect, alter_error)

    monkeypatch.setattr(app.store.sqlite3, "connect", connect)


def test_migration_survives_another_process_adding_the_column(tmp_path, monkeypatch):
    path = old_db(tmp_path / "race.db")
    patch_connect(monkeypatch, path)
    store = Store(path)
    page = store.create(title="Raced")
    token = store.share(page["id"])
    assert store.get_shared(token)["title"] == "Raced"


def test_migration_error_is_raised_when_the_column_is_still_missing(tmp_path, monkeypatch):
    path = old_db(tmp_path / "boom.db")
    patch_connect(monkeypatch, path, alter_error=sqlite3.OperationalError("boom"))
    with pytest.raises(sqlite3.OperationalError, match="boom"):
        Store(path)


def test_editor_page_has_the_share_controls(client):
    res = client.get("/")
    assert res.status_code == 200
    for el in ("share", "share-panel", "copy", "unshare"):
        assert f'id="{el}"' in res.text
